#!/usr/bin/env python3
"""
match_probe.py  —  Phase 1 diagnostic (run on your machine, not in chat).

Goal: prove ONE thing before building the full scraper.
Are the infringing site's image filenames (e.g. 8874885513560_535128.webp)
the same numeric IDs Shopify assigns to your product images?

If YES  -> matching is a cheap exact-ID lookup, no image downloads needed.
If NO   -> we fall back to perceptual hashing in Phase 2.

This script downloads NOTHING heavy. It pulls 5 of your products from the
Admin API and reads page 1 of the infringing category, then prints both sets
of image filenames side by side so YOU can see whether the IDs line up.

Needs: requests   ->   pip install requests
"""

import os
import re
import sys
import requests

# ----------------------------- CONFIG -------------------------------------
# Point this at the folder holding shopify_auth.py so we can import it.
# From your project root that's workflows/Publishers.
PUBLISHERS_DIR = os.path.join(os.path.dirname(__file__), "workflows", "Publishers")
INFRINGING     = "https://www.piecesharleyfrance.com/product-category/harley-davidson/"
# --------------------------------------------------------------------------

# Load .env (SHOPIFY_STORE / SHOPIFY_API_VERSION) the same way seo-forge does.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Use your real auth module instead of a hardcoded token.
sys.path.insert(0, PUBLISHERS_DIR)
from shopify_auth import get_access_token  # noqa: E402

_tok = get_access_token()
token = _tok if isinstance(_tok, str) else _tok.get("access_token")  # handle str or dict
if not token:
    sys.exit("get_access_token() returned nothing usable.")

SHOP        = os.environ["SHOPIFY_STORE"]                  # also the Admin API domain
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-04")

UA = {"User-Agent": "Mozilla/5.0 (compatible; LP-match-probe/1.0)"}


def shopify_sample(n=5):
    """Grab n products from the Admin API and surface their image IDs/filenames."""
    url = f"https://{SHOP}/admin/api/{API_VERSION}/products.json?limit={n}"
    r = requests.get(url, headers={"X-Shopify-Access-Token": token}, timeout=30)
    r.raise_for_status()
    rows = []
    for p in r.json().get("products", []):
        for img in p.get("images", []):
            src = img.get("src", "")
            rows.append({
                "handle": p.get("handle"),
                "image_id": str(img.get("id")),          # Shopify's numeric image id
                "filename": src.split("/")[-1].split("?")[0],  # e.g. 8874885513560_535128.webp
                "src": src,
            })
    return rows


def infringing_sample():
    """Read page 1 of the infringing category, pull product links + image filenames."""
    r = requests.get(INFRINGING, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text
    products = re.findall(r'href="(https://www\.piecesharleyfrance\.com/product/[^"]+/)"', html)
    images   = re.findall(r'src="(https://www\.piecesharleyfrance\.com/wp-content/uploads/[^"]+\.webp)"', html)
    files = [u.split("/")[-1] for u in images]
    return sorted(set(products)), files


def main():
    print("=== YOUR SHOPIFY IMAGES (sample of 5 products) ===")
    mine = shopify_sample(5)
    for row in mine:
        print(f"  id={row['image_id']:>16}  file={row['filename']:<32} handle={row['handle']}")

    print("\n=== INFRINGING SITE IMAGES (page 1) ===")
    prod, files = infringing_sample()
    print(f"  {len(prod)} product URLs found on page 1")
    for f in files[:15]:
        print(f"  file={f}")

    print("\n=== MATCH TEST: do infringing filenames contain your image IDs? ===")
    my_ids = {row["image_id"] for row in mine}
    my_files = {row["filename"] for row in mine}
    hits = 0
    for f in files:
        tokens = re.findall(r"\d+", f)              # split 8874885513560_535128 -> two numbers
        id_hit = any(t in my_ids for t in tokens)
        file_hit = f in my_files
        if id_hit or file_hit:
            hits += 1
            print(f"  MATCH  {f}  (id_hit={id_hit}, file_hit={file_hit})")
    print(f"\n  {hits} of {len(files)} page-1 images matched the 5-product sample.")
    print("  (A sample of 5 products vs their full catalog will rarely overlap —")
    print("   what matters is whether the NUMBER FORMAT looks like your image IDs above.)")


if __name__ == "__main__":
    main()
