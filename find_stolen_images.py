#!/usr/bin/env python3
"""
find_stolen_images.py  —  scrape THEIR side first, then match against your catalogue.

Order (the efficient way):
1. Scrape all 264 infringing pages -> their product URL + thumbnail. Hash each thumb.
2. Pull your catalogue, hash MAIN image only, one per product.
3. Match their thumbs against your mains. Write rows: their URL | your URL.

Both sides ~10k images, not 100k. Everything cached + resumable.
Output: stolen_images.xlsx
"""

import os, re, sys, json, time, requests
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import imagehash
import openpyxl

# ----------------------------- CONFIG -------------------------------------
PUBLISHERS_DIR  = os.path.join(os.path.dirname(__file__), "workflows", "Publishers")
INFRINGING_BASE = "https://www.piecesharleyfrance.com/product-category/harley-davidson"
LAST_PAGE       = 264
STOREFRONT_BASE = "https://www.legendary-parts.com/products/"
MATCH_DISTANCE  = 5          # hamming cutoff; raise to catch more, lower to cut false hits
THREADS         = 12
THEIR_CACHE     = "their_hashes.json"   # {their_img_url: [phash, their_product_url]}
MINE_CACHE      = "hash_cache.json"     # {my_img_url:   [phash, my_product_url]}
OUT_FILE        = "stolen_images.xlsx"
# --------------------------------------------------------------------------

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

sys.path.insert(0, PUBLISHERS_DIR)
from shopify_auth import get_access_token
_tok = get_access_token()
TOKEN = _tok if isinstance(_tok, str) else _tok.get("access_token")
if not TOKEN:
    sys.exit("get_access_token() returned nothing usable.")

SHOP        = os.environ["SHOPIFY_STORE"]
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-04")
UA = {"User-Agent": "Mozilla/5.0 (compatible; LP-image-audit/1.0)"}


def load_cache(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

def save_cache(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def hash_image(url):
    try:
        r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
        return str(imagehash.phash(Image.open(BytesIO(r.content)).convert("RGB")))
    except Exception:
        return None

def thumb(url, size=400):
    url = url.split("?")[0]
    stem, dot, ext = url.rpartition(".")
    return f"{stem}_{size}x{size}{dot}{ext}" if dot else url


# ---------------- STEP 1: their side, scraped + hashed --------------------
def scrape_their_images():
    """Return list of (their_product_url, their_image_url) across all pages."""
    found = []
    for n in range(1, LAST_PAGE + 1):
        page = INFRINGING_BASE + ("/" if n == 1 else f"/page/{n}/")
        try:
            html = requests.get(page, headers=UA, timeout=30).text
        except Exception as e:
            print(f"  page {n} failed: {e}"); continue
        cards = html.split('woocommerce-LoopProduct-link')
        for card in cards[1:]:
            hm = re.search(r'href="(https://www\.piecesharleyfrance\.com/product/[^"]+/)"', card)
            im = re.search(r'<img[^>]+src="([^"]+\.webp)"', card)
            if hm and im:
                found.append((hm.group(1), im.group(1)))
        if n % 20 == 0:
            print(f"  scraped page {n}/{LAST_PAGE}, {len(found)} pairs so far")
        time.sleep(0.2)
    seen, out = set(), []
    for purl, iurl in found:
        if iurl not in seen:
            seen.add(iurl); out.append((purl, iurl))
    return out


def build_their_index():
    cache = load_cache(THEIR_CACHE)
    pairs = scrape_their_images()
    todo = [(p, i) for p, i in pairs if i not in cache]
    print(f"Their side: {len(pairs)} images, {len(todo)} to hash.")
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(hash_image, i): (p, i) for p, i in todo}
        for fut in as_completed(futs):
            purl, iurl = futs[fut]; h = fut.result()
            if h: cache[iurl] = [h, purl]
            done += 1
            if done % 200 == 0:
                save_cache(THEIR_CACHE, cache); print(f"  their hashed {done}/{len(todo)}")
    save_cache(THEIR_CACHE, cache)
    return cache  # {img_url: [phash, their_product_url]}


# ---------------- STEP 2: your catalogue, MAIN image only -----------------
def fetch_my_mains():
    """Yield (my_product_url, main_image_src) — first image only, one per product."""
    base = f"https://{SHOP}/admin/api/{API_VERSION}/products.json"
    url, params = base, {"limit": 250}
    while url:
        r = requests.get(url, headers={"X-Shopify-Access-Token": TOKEN},
                         params=params if url == base else None, timeout=60)
        r.raise_for_status()
        for p in r.json().get("products", []):
            imgs = p.get("images", [])
            if imgs and imgs[0].get("src"):
                yield STOREFRONT_BASE + p.get("handle", ""), imgs[0]["src"]
        m = re.search(r'<([^>]+)>;\s*rel="next"', r.headers.get("Link", ""))
        url = m.group(1) if m else None
        time.sleep(0.3)

def build_my_index():
    cache = load_cache(MINE_CACHE)
    pairs = list(fetch_my_mains())
    todo = [(p, i) for p, i in pairs if i not in cache]
    print(f"Your side: {len(pairs)} main images, {len(todo)} to hash.")
    done = 0
    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(hash_image, thumb(i)): (p, i) for p, i in todo}
        for fut in as_completed(futs):
            purl, iurl = futs[fut]; h = fut.result()
            if h: cache[iurl] = [h, purl]
            done += 1
            if done % 200 == 0:
                save_cache(MINE_CACHE, cache); print(f"  your hashed {done}/{len(todo)}")
    save_cache(MINE_CACHE, cache)
    index = {}
    for _u, (h, purl) in cache.items():
        index.setdefault(h, purl)
    return index  # {phash: my_product_url}


# ---------------- STEP 3: match + write -----------------------------------
def main():
    print("STEP 1/3  scraping + hashing their site...")
    theirs = build_their_index()
    print("STEP 2/3  hashing your catalogue (main image only)...")
    mine = build_my_index()
    mine_items = [(imagehash.hex_to_hash(h), purl) for h, purl in mine.items()]

    print("STEP 3/3  matching...")
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Copied images"
    ws.append(["Infringing URL (piecesharleyfrance.com)", "Your URL (legendary-parts.com)"])
    seen, rows = set(), 0
    for _iurl, (h, their_url) in theirs.items():
        hh = imagehash.hex_to_hash(h)
        if not mine_items: break
        best = min(mine_items, key=lambda it: hh - it[0])
        if (hh - best[0]) <= MATCH_DISTANCE:
            pair = (their_url, best[1])
            if pair not in seen:
                seen.add(pair); ws.append([their_url, best[1]]); rows += 1
    wb.save(OUT_FILE)
    print(f"\nDone. {rows} matches written to {OUT_FILE}")

if __name__ == "__main__":
    main()
