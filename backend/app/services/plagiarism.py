"""
Plagiarism Checker — two-layer detection.

Layer 1: MinHash internal deduplication (no API cost, instant)
Layer 2: Copyscape API check against the live web (only if internal check passes)

Stores a local hash index at .tmp/content_hashes.pkl using atomic writes.
Requires COPYSCAPE_USERNAME and COPYSCAPE_API_KEY in .env for web checks.
"""

import os
import re
import pickle
import hashlib
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional

from datasketch import MinHash
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

HASH_INDEX_PATH = ".tmp/content_hashes.pkl"
MINHASH_PERMUTATIONS = 128
SHINGLE_SIZE = 3
SIMILARITY_THRESHOLD = 0.3
COPYSCAPE_API_URL = "https://www.copyscape.com/api/"
COPYSCAPE_MAX_WORDS = 2000   # API soft limit; truncate before sending
COPYSCAPE_MAX_RESULTS = 10

COPYSCAPE_USERNAME = os.getenv("COPYSCAPE_USERNAME")
COPYSCAPE_API_KEY = os.getenv("COPYSCAPE_API_KEY")


# ─── MinHash helpers ──────────────────────────────────────────────────────────

def _get_shingles(text: str, k: int = SHINGLE_SIZE) -> set:
    """Return the set of k-character shingles from normalised text."""
    text = re.sub(r"\s+", " ", text.lower().strip())
    return {text[i:i + k] for i in range(len(text) - k + 1)}


def _compute_minhash(text: str) -> MinHash:
    """Compute a MinHash signature for a piece of text."""
    m = MinHash(num_perm=MINHASH_PERMUTATIONS)
    for shingle in _get_shingles(text):
        m.update(shingle.encode("utf8"))  # datasketch v1.6+ requires bytes
    return m


# ─── Index persistence (atomic writes) ───────────────────────────────────────

def _load_index() -> dict:
    """Load the hash index from disk. Returns empty dict on missing/corrupt file."""
    os.makedirs(".tmp", exist_ok=True)
    if not os.path.exists(HASH_INDEX_PATH):
        return {}
    try:
        with open(HASH_INDEX_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        # Treat any corruption as an empty index rather than crashing
        return {}


def _save_index(index: dict) -> None:
    """Atomically write the index to disk (write-then-rename)."""
    os.makedirs(".tmp", exist_ok=True)
    tmp_path = HASH_INDEX_PATH + ".tmp"
    with open(tmp_path, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.rename(tmp_path, HASH_INDEX_PATH)  # atomic on POSIX


# ─── Internal MinHash layer ───────────────────────────────────────────────────

def _check_internal(content: str, content_id: Optional[str]) -> dict:
    """
    Compare content against the local MinHash index.
    Stores the new content's signature regardless of match result.
    """
    index = _load_index()
    new_hash = _compute_minhash(content)

    matches = []
    max_similarity = 0.0

    for cid, data in index.items():
        if cid == content_id:
            continue  # skip self-comparison on re-checks
        stored_hash = data["minhash"]
        similarity = new_hash.jaccard(stored_hash)
        if similarity > max_similarity:
            max_similarity = similarity
        if similarity > SIMILARITY_THRESHOLD:
            matches.append({
                "content_id": cid,
                "similarity": round(similarity, 3),
                "preview": data.get("content_preview", ""),
            })

    # Store the new entry in the index
    effective_id = content_id or hashlib.md5(content[:200].encode()).hexdigest()[:12]
    index[effective_id] = {
        "minhash": new_hash,
        "content_preview": content[:100].strip(),
        "timestamp": datetime.utcnow().isoformat(),
    }
    _save_index(index)

    return {
        "is_duplicate": len(matches) > 0,
        "max_similarity": round(max_similarity, 3),
        "matches": sorted(matches, key=lambda x: x["similarity"], reverse=True),
    }


# ─── Copyscape API layer ──────────────────────────────────────────────────────

def _truncate_to_words(text: str, max_words: int) -> str:
    """Return at most max_words words of text."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _check_copyscape(content: str) -> dict:
    """
    Send content to the Copyscape API and return match results.
    Returns checked=False (with error) when credentials are missing or request fails.
    """
    if not COPYSCAPE_USERNAME or not COPYSCAPE_API_KEY:
        return {
            "checked": False,
            "error": "Copyscape credentials not configured (COPYSCAPE_USERNAME / COPYSCAPE_API_KEY)",
            "results": [],
        }

    truncated = _truncate_to_words(content, COPYSCAPE_MAX_WORDS)

    try:
        response = requests.post(
            COPYSCAPE_API_URL,
            data={
                "u": COPYSCAPE_USERNAME,
                "k": COPYSCAPE_API_KEY,
                "o": "csearch",
                "e": "UTF-8",
                "c": str(COPYSCAPE_MAX_RESULTS),
                "t": truncated,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"checked": False, "error": str(exc), "results": []}

    # Parse XML response
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        return {"checked": False, "error": f"XML parse error: {exc}", "results": []}

    # API-level error
    error_tag = root.find("error")
    if error_tag is not None:
        return {"checked": False, "error": error_tag.text, "results": []}

    # count == 0 means clean; result elements may be absent
    results = []
    for result in root.findall("result"):
        results.append({
            "url": result.findtext("url", ""),
            "title": result.findtext("title", ""),
            "percent_copied": int(result.findtext("percentmatched", "0") or 0),
            "words_copied": int(result.findtext("minwordsmatched", "0") or 0),
        })

    return {"checked": True, "error": None, "results": results}


# ─── Risk scoring ─────────────────────────────────────────────────────────────

def _compute_risk_score(internal: dict, cs: dict) -> int:
    """
    Combine internal similarity and Copyscape results into a 0–100 risk score.
    Up to 60 pts from internal similarity; up to 40 pts from Copyscape.
    """
    score = min(int(internal["max_similarity"] * 60), 60)
    if cs.get("checked") and cs.get("results"):
        max_pct = max(r["percent_copied"] for r in cs["results"])
        score += min(int(max_pct * 0.4), 40)
    return min(score, 100)


# ─── Public API ───────────────────────────────────────────────────────────────

def check(
    content: str,
    content_id: Optional[str] = None,
    skip_copyscape: bool = False,
) -> dict:
    """
    Run the two-layer plagiarism check.

    Layer 1 (always): MinHash internal deduplication against stored index.
    Layer 2 (optional): Copyscape API check — skipped if internal detects a duplicate
                        or if skip_copyscape=True.

    Args:
        content:         Plain-text content to check
        content_id:      Stable ID for this content (used to avoid self-comparison on re-checks)
        skip_copyscape:  Force-skip the Copyscape API call

    Returns:
        Result dict with is_duplicate_internal, internal_similarity, copyscape_results,
        overall_status (clean / warning / duplicate), and risk_score.
    """
    # Layer 1: internal MinHash
    internal = _check_internal(content, content_id)

    # Layer 2: Copyscape — only when internal passes and not explicitly skipped
    cs_result: dict = {"checked": False, "results": [], "error": None}
    if not internal["is_duplicate"] and not skip_copyscape:
        cs_result = _check_copyscape(content)

    risk_score = _compute_risk_score(internal, cs_result)

    # Determine overall status
    cs_results = cs_result.get("results", [])
    if internal["is_duplicate"] or any(r["percent_copied"] > 30 for r in cs_results):
        overall_status = "duplicate"
    elif internal["max_similarity"] > 0.2 or any(r["percent_copied"] > 10 for r in cs_results):
        overall_status = "warning"
    else:
        overall_status = "clean"

    return {
        "is_duplicate_internal": internal["is_duplicate"],
        "internal_similarity": internal["max_similarity"],
        "internal_matches": internal["matches"],
        "copyscape_checked": cs_result["checked"],
        "copyscape_error": cs_result.get("error"),
        "copyscape_results": cs_results,
        "overall_status": overall_status,
        "risk_score": risk_score,
    }


def index_size() -> int:
    """Return the number of entries currently in the local hash index."""
    return len(_load_index())


def clear_index() -> None:
    """Delete the local hash index. Use with caution."""
    if os.path.exists(HASH_INDEX_PATH):
        os.remove(HASH_INDEX_PATH)


# ─── CLI test block ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    content_a = """
    Harley Davidson parts are the backbone of any quality motorcycle build.
    Whether you're replacing worn brake pads or upgrading your exhaust system,
    using genuine Harley Davidson parts ensures reliability and performance.
    Our store carries thousands of OEM and aftermarket Harley Davidson parts
    for every model year from 1990 to present day.
    """

    content_b = """
    When it comes to motorcycle maintenance, Harley Davidson parts are essential.
    Genuine brake pads, exhaust upgrades, and OEM components keep your bike
    running at peak performance. Our inventory includes thousands of Harley Davidson
    parts for every model from 1990 onwards.
    """

    content_c = """
    Electric vehicles are transforming urban mobility. The shift away from internal
    combustion engines toward battery-powered transport represents one of the largest
    industrial transitions of the 21st century, driven by climate policy and
    falling battery costs.
    """

    print("=== Plagiarism Checker CLI Test ===\n")
    print(f"Index size before: {index_size()} entries")

    print("\n[1] Checking Content A (first submission)...")
    result_a = check(content_a, content_id="content_a", skip_copyscape=True)
    print(f"  Status: {result_a['overall_status']}  Risk: {result_a['risk_score']}")
    print(f"  Internal duplicate: {result_a['is_duplicate_internal']}  Similarity: {result_a['internal_similarity']}")

    print("\n[2] Checking Content B (similar to A — should flag warning/duplicate)...")
    result_b = check(content_b, content_id="content_b", skip_copyscape=True)
    print(f"  Status: {result_b['overall_status']}  Risk: {result_b['risk_score']}")
    print(f"  Internal duplicate: {result_b['is_duplicate_internal']}  Similarity: {result_b['internal_similarity']}")
    if result_b["internal_matches"]:
        print(f"  Matched: {result_b['internal_matches'][0]['content_id']} "
              f"(Jaccard: {result_b['internal_matches'][0]['similarity']})")

    print("\n[3] Checking Content C (unrelated — should be clean)...")
    result_c = check(content_c, content_id="content_c", skip_copyscape=True)
    print(f"  Status: {result_c['overall_status']}  Risk: {result_c['risk_score']}")
    print(f"  Internal duplicate: {result_c['is_duplicate_internal']}  Similarity: {result_c['internal_similarity']}")

    print(f"\nIndex size after: {index_size()} entries")
    print("\nFull result for Content B:")
    print(json.dumps(result_b, indent=2))
