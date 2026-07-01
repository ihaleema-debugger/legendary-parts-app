#!/usr/bin/env python3
"""
check_distances.py  —  READ ONLY. Downloads nothing. Touches nothing.

Reads the two existing caches:
  their_hashes.json  {their_img_url: [phash, their_product_url]}
  hash_cache.json    {my_img_url:   [phash, my_product_url]}

For each of THEIR images, finds the nearest match in YOUR catalogue and
records that smallest distance. Then prints how many of their images would
match at each cutoff, and a few example pairs at distances just above the
current cutoff of 5 so you can eyeball whether they're real copies.
"""

import json
import imagehash

THEIR_CACHE = "their_hashes.json"
MINE_CACHE  = "hash_cache.json"

theirs = json.load(open(THEIR_CACHE))
mine   = json.load(open(MINE_CACHE))

print(f"their images cached: {len(theirs)}")
print(f"your  images cached: {len(mine)}")

# Pre-convert your side once.
mine_items = [(imagehash.hex_to_hash(h), purl) for h, (purl_h, purl) in
              [(v[0], v) for v in mine.values()]]
# (above keeps purl = v[1])
mine_items = [(imagehash.hex_to_hash(v[0]), v[1]) for v in mine.values()]

# For each of their images, find nearest distance + the matched product pair.
results = []  # (distance, their_product_url, your_product_url)
n = 0
for iurl, (h, their_url) in theirs.items():
    hh = imagehash.hex_to_hash(h)
    best_d, best_purl = 999, None
    for mh, purl in mine_items:
        d = hh - mh
        if d < best_d:
            best_d, best_purl = d, purl
            if d == 0:
                break
    results.append((best_d, their_url, best_purl))
    n += 1
    if n % 1000 == 0:
        print(f"  ...compared {n}/{len(theirs)}")

# Histogram of nearest-distance counts at each cutoff.
print("\n--- how many of THEIR images match at each cutoff ---")
for cutoff in [3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 20, 25]:
    c = sum(1 for d, _, _ in results if d <= cutoff)
    print(f"  distance <= {cutoff:>2}:  {c:>6} matches")

# Show example pairs in the 6-10 band (just above current cutoff) to eyeball.
print("\n--- example pairs at distance 6-10 (eyeball these: real copies?) ---")
shown = 0
for d, turl, purl in sorted(results):
    if 6 <= d <= 10 and purl:
        print(f"  dist {d}:")
        print(f"    them: {turl}")
        print(f"    you : {purl}")
        shown += 1
        if shown >= 8:
            break
if shown == 0:
    print("  (none in this band)")
