#!/usr/bin/env python3
"""
oem_match_check.py — READ ONLY. Reads the two existing caches, extracts OEM-style
part numbers from the product URLs on each side, and reports coverage + match count.
Downloads nothing. Touches nothing.

Goal: decide whether matching on OEM number (from the URL) is viable, BEFORE building it.
"""
import json, re, os

THEIR_CACHE = "their_hashes.json"
MINE_CACHE  = "hash_cache.json"

def load(p):
    return json.load(open(p)) if os.path.exists(p) else {}

theirs = load(THEIR_CACHE)   # {img_url: [phash, their_product_url]}
mine   = load(MINE_CACHE)    # {img_url: [phash, my_product_url]}

# Their product URLs and your product URLs
their_urls = sorted({v[1] for v in theirs.values()})
my_urls    = sorted({v[1] for v in mine.values()})

print(f"their unique product URLs: {len(their_urls)}")
print(f"your  unique product URLs: {len(my_urls)}")
print()

# OEM extraction: Harley OEM refs are messy — digits, sometimes with a trailing
# letter-suffix or a hyphenated segment (e.g. 52000148, 45998-73, 16800-84B,
# 52000148DEMO). Strategy: grab the LAST run of digits (optionally with a
# trailing -XX or letters) that looks like an OEM ref, normalized.
def extract_oem(url):
    slug = url.rstrip("/").split("/")[-1].lower()
    # find an 'oem' marker and take what follows, else look for long digit runs
    m = re.search(r'oem[-_]?([a-z0-9\-]+)', slug)
    cand = None
    if m:
        cand = m.group(1)
    else:
        # fallback: longest digit(-ish) token in the slug
        toks = re.findall(r'[0-9]{4,}[a-z0-9\-]*', slug)
        cand = max(toks, key=len) if toks else None
    if not cand:
        return None
    # normalize: strip non-alphanumerics, drop common noise suffix 'demo'
    norm = re.sub(r'[^a-z0-9]', '', cand)
    norm = re.sub(r'demo$', '', norm)
    return norm or None

their_oem = {}
for u in their_urls:
    o = extract_oem(u)
    if o:
        their_oem.setdefault(o, u)

my_oem = {}
for u in my_urls:
    o = extract_oem(u)
    if o:
        my_oem.setdefault(o, u)

print(f"their URLs with an OEM-like ref: {len(their_oem)} / {len(their_urls)}  ({100*len(their_oem)//max(len(their_urls),1)}%)")
print(f"your  URLs with an OEM-like ref: {len(my_oem)} / {len(my_urls)}  ({100*len(my_oem)//max(len(my_urls),1)}%)")
print()

# How many of THEIR OEMs match one of YOURS?
matches = [(o, their_oem[o], my_oem[o]) for o in their_oem if o in my_oem]
print(f"=> exact OEM matches (their product <-> your product): {len(matches)}")
print()
print("--- 10 example matches ---")
for o, turl, murl in matches[:10]:
    print(f"  OEM {o}")
    print(f"    them: {turl}")
    print(f"    you : {murl}")
print()
print("--- 5 of THEIR OEMs with NO match on your side (sanity check) ---")
nomatch = [(o, their_oem[o]) for o in their_oem if o not in my_oem]
for o, turl in nomatch[:5]:
    print(f"  OEM {o}  ->  {turl}")
