#!/usr/bin/env python3
"""
find_stolen_oem.py  --  OEM-based DMCA match. Replaces image hashing entirely.

Output: two-column spreadsheet
  A = infringing product URL on piecesharleyfrance.com
  B = matching legendary-parts.com product URL (matched on Harley OEM number)

NO image downloads, NO perceptual hashing, NO their_hashes.json.
Their side is a SET keyed by product URL, so it cannot collapse to 59 like the
old image-keyed cache did. The OEM is read straight out of the URL slug.

Modes:
  python find_stolen_oem.py --test            # scrape page 1 only, print what it found, write nothing
  python find_stolen_oem.py --scrape-only     # scrape all pages -> their_products.json, no matching
  python find_stolen_oem.py                    # full run -> stolen_images.xlsx
  optional: --pages N   --threads N

Run --test FIRST. Confirm it reports ~36 distinct products on page 1 before any full run.
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
THEIR_HOST = "https://www.piecesharleyfrance.com"
# Scrape the Harley-Davidson CATEGORY, not the site root (the root is a mixed-brand showcase).
THEIR_BASE = f"{THEIR_HOST}/product-category/harley-davidson/"
TOTAL_PAGES = 264                            # verified live: 36 products/page, 97% carry an OEM
DEFAULT_THREADS = 8                          # handoff: timeouts are THEIR throttling, not bandwidth. Lower if they recur.
PAGE_RETRIES = 3
PAGE_TIMEOUT = 30                            # seconds
RETRY_BACKOFF = 4                            # seconds, multiplied by attempt number

# Column B URL. Storefront also exposes /en/ paths -- VERIFY one resolves before trusting output.
STOREFRONT_BASE = "https://www.legendary-parts.com/products/"

# Where shopify_auth.py lives, relative to project root. Confirm this matches your tree.
PUBLISHERS_DIR = "workflows/Publishers"

OUT_XLSX = "stolen_images.xlsx"
THEIR_JSON = "their_products.json"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

# ----------------------------------------------------------------------------
# OEM extraction  (same logic applied to THEIR slugs and YOUR handles)
# ----------------------------------------------------------------------------
# One OEM token: 4-9 digits, optionally -<2 digits><optional letter>.
#   68329-03  60506-82b  52000148  11287
# Multi-OEM slugs (e.g. 60506-82b-60543-86a) yield BOTH tokens via findall.
OEM_TOKEN_RE = re.compile(r"\d{4,9}(?:-\d{2}[a-z]{0,2})?")
PRODUCT_HREF_RE = re.compile(r'href="([^"]*?/product/[^"]+?)"', re.IGNORECASE)


def extract_oems(url_or_slug: str) -> frozenset:
    """Return the set of normalized OEM tokens found after the 'oem' or 'ref' marker.

    Empty set => no OEM in this URL/handle (those are unmatchable, by design).
    Set form makes multi-OEM order-independent.
    """
    s = url_or_slug.lower().strip().rstrip("/")
    slug = s.rsplit("/", 1)[-1]              # last path segment
    for marker, width in (("oem-", 4), ("ref-", 4)):
        idx = slug.find(marker)
        if idx != -1:
            return frozenset(OEM_TOKEN_RE.findall(slug[idx + width:]))
    idx = slug.find("oem")                   # fallback: 'oem' with no dash (flagged: looser)
    if idx == -1:
        return frozenset()
    return frozenset(OEM_TOKEN_RE.findall(slug[idx + 3:]))
    # TUNING LEVER: if recall is low, switch to a "compact" form (strip dashes)
    # on BOTH sides -> {t.replace('-', '') for t in ...}. Slightly looser, more matches.


# ----------------------------------------------------------------------------
# Their side: harvest /product/ URLs per page into a global set
# ----------------------------------------------------------------------------
def fetch_html(url: str) -> str:
    last_err = None
    for attempt in range(1, PAGE_RETRIES + 1):
        try:
            r = requests.get(url, headers=UA, timeout=PAGE_TIMEOUT)
            if r.status_code == 200:
                return r.text
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        if attempt < PAGE_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError(f"{url} failed after {PAGE_RETRIES} tries: {last_err}")


def page_url(n: int) -> str:
    return THEIR_BASE if n == 1 else f"{THEIR_BASE}page/{n}/"


def scrape_page(n: int) -> set:
    """Return the set of product URLs found on page n (deduped)."""
    html = fetch_html(page_url(n))
    found = set()
    for href in PRODUCT_HREF_RE.findall(html):
        if href.startswith("/"):
            href = THEIR_HOST + href
        href = href.split("?")[0].split("#")[0].rstrip("/") + "/"
        if "/product/" in href:
            found.add(href)
    return found


def scrape_all(pages: int, threads: int) -> set:
    products = set()
    failed = []
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = {ex.submit(scrape_page, n): n for n in range(1, pages + 1)}
        done = 0
        for fut in as_completed(futures):
            n = futures[fut]
            done += 1
            try:
                products |= fut.result()
            except Exception as e:          # LOUD: a failed page is lost products
                failed.append(n)
                print(f"  [PAGE {n}] FAILED: {e}", file=sys.stderr)
            if done % 20 == 0 or done == pages:
                print(f"  scraped {done}/{pages} pages | {len(products)} distinct products so far")
    if failed:
        print(f"\n  !! {len(failed)} pages failed (lost products): {sorted(failed)}", file=sys.stderr)
        print("     Re-run, or lower --threads, before trusting the count.", file=sys.stderr)
    return products


# ----------------------------------------------------------------------------
# Your side: pull catalogue handles from Shopify Admin API, index by OEM
# ----------------------------------------------------------------------------
def load_shopify():
    sys.path.insert(0, os.path.abspath(PUBLISHERS_DIR))
    try:
        from shopify_auth import get_access_token  # noqa
    except ImportError as e:
        raise RuntimeError(
            f"Could not import shopify_auth from '{PUBLISHERS_DIR}'. "
            f"Run from project root, or fix PUBLISHERS_DIR. Original: {e}")
    store = os.environ.get("SHOPIFY_STORE")
    version = os.environ.get("SHOPIFY_API_VERSION")
    if not store or not version:
        raise RuntimeError("SHOPIFY_STORE / SHOPIFY_API_VERSION missing from environment (.env).")
    return get_access_token(), store, version


def fetch_catalogue_handles() -> list:
    token, store, version = load_shopify()
    base = f"https://{store}/admin/api/{version}/products.json"
    headers = {"X-Shopify-Access-Token": token}
    handles, url, params = [], base, {"limit": 250, "fields": "handle"}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=PAGE_TIMEOUT)
        r.raise_for_status()
        handles.extend(p["handle"] for p in r.json().get("products", []))
        # cursor pagination via Link header
        link = r.headers.get("Link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url, params = (m.group(1), None) if m else (None, None)
        print(f"  pulled {len(handles)} handles...", end="\r")
    print(f"  pulled {len(handles)} handles total      ")
    return handles


def build_oem_index(handles: list) -> dict:
    """oem_token -> handle. First handle wins on collision; collisions counted."""
    index, collisions = {}, 0
    for h in handles:
        for tok in extract_oems(h):
            if tok in index:
                collisions += 1
            else:
                index[tok] = h
    have_oem = sum(1 for h in handles if extract_oems(h))
    print(f"  {have_oem}/{len(handles)} handles carry an OEM | {len(index)} unique OEMs indexed "
          f"| {collisions} collisions")
    return index


# ----------------------------------------------------------------------------
# Match + write
# ----------------------------------------------------------------------------
def match(their_urls: set, oem_index: dict) -> list:
    rows, multi = [], 0
    for url in sorted(their_urls):
        hits = {oem_index[t] for t in extract_oems(url) if t in oem_index}
        if not hits:
            continue
        if len(hits) > 1:
            multi += 1
        handle = sorted(hits)[0]
        rows.append((url, STOREFRONT_BASE + handle))
    if multi:
        print(f"  note: {multi} infringing URLs matched >1 of your products (took first).")
    return rows


def write_xlsx(rows: list, path: str):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "DMCA matches"
    ws.append(["Infringing URL (piecesharleyfrance.com)", "Original URL (legendary-parts.com)"])
    for a, b in rows:
        ws.append([a, b])
    wb.save(path)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="scrape page 1 only, print, write nothing")
    ap.add_argument("--scrape-only", action="store_true", help="scrape all pages -> their_products.json")
    ap.add_argument("--pages", type=int, default=TOTAL_PAGES)
    ap.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    args = ap.parse_args()

    if args.test:
        print("TEST: scraping page 1 only...")
        prods = scrape_page(1)
        with_oem = [p for p in prods if extract_oems(p)]
        print(f"\n  distinct products on page 1 : {len(prods)}   (expect ~36)")
        print(f"  of those, carry an OEM      : {len(with_oem)}")
        print("\n  sample:")
        for p in sorted(prods)[:5]:
            print(f"    {sorted(extract_oems(p)) or '(no OEM)'}  <-  {p}")
        return

    print(f"Scraping {args.pages} pages with {args.threads} threads...")
    their = scrape_all(args.pages, args.threads)
    print(f"\nTotal distinct infringing products: {len(their)}\n")

    if args.scrape_only:
        with open(THEIR_JSON, "w") as f:
            json.dump({u: sorted(extract_oems(u)) for u in sorted(their)}, f, indent=2)
        print(f"Saved -> {THEIR_JSON}")
        return

    print("Pulling your catalogue from Shopify...")
    handles = fetch_catalogue_handles()
    oem_index = build_oem_index(handles)

    print("\nMatching on OEM...")
    rows = match(their, oem_index)
    write_xlsx(rows, OUT_XLSX)
    print(f"\nMatched {len(rows)} / {len(their)} infringing products -> {OUT_XLSX}")
    print("VERIFY one Column-B link resolves (watch for /en/ paths) before submitting.")


if __name__ == "__main__":
    main()
