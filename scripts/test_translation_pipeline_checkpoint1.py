"""Checkpoint 1 smoke test: fetch all V-Rod blog files and parse them.

Usage:
    cd "/Users/mac/Documents/SEO Agent Workflow"
    keyword_forge/.venv/bin/python scripts/test_translation_pipeline_checkpoint1.py
"""
import os
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add Publishers dir so we can import drive_fetcher and gdoc_reader directly
PUBLISHERS_DIR = PROJECT_ROOT / "workflows" / "Publishers"
if str(PUBLISHERS_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHERS_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from drive_fetcher import fetch_blog_files
from gdoc_reader import read_blog_gdoc

BLOG_STEM = "harley-davidson-vrsc-v-rod-complete-buyers-and-owners-guide"
FOLDER_PATH = "12. Claude Blogs / Approved Blogs"
SHARED_DRIVE = "shared drive with Claude"


def main():
    print(f"Fetching files for: {BLOG_STEM!r}")
    print(f"Folder: {SHARED_DRIVE!r} / {FOLDER_PATH!r}\n")

    files = fetch_blog_files(BLOG_STEM, FOLDER_PATH, SHARED_DRIVE)
    print(f"Found {len(files)} locale file(s): {[f['locale'] for f in files]}\n")

    results = []
    for f in files:
        print(f"  [{f['locale']}] reading...", end=" ", flush=True)
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                data = read_blog_gdoc(f["file_id"])
            # Filter out ResourceWarning noise from the Google API client (Python 3.9)
            warn_msgs = [
                str(w.message) for w in caught
                if not issubclass(w.category, ResourceWarning)
            ]
            if warn_msgs:
                print(f"WARN ({'; '.join(warn_msgs)})")
            else:
                print("OK")
            results.append(data)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"locale": f["locale"], "_error": str(e)})

    # Summary table
    print("\n" + "=" * 96)
    header = f"{'locale':<8} {'title':<46} {'words':>6} {'tags':>5} {'meta?':>6} {'handle':<30}"
    print(header)
    print("-" * 96)
    for r in sorted(results, key=lambda x: x.get("locale", "")):
        locale = r.get("locale", "?")
        if "_error" in r:
            print(f"{locale:<8} ERROR: {r['_error']}")
            continue
        title = (r.get("title") or "")[:44]
        # word count from body_html (rough: split on whitespace after stripping tags)
        import re
        body_text = re.sub(r"<[^>]+>", " ", r.get("body_html", ""))
        word_count = len(body_text.split())
        tags_count = len(r.get("tags", []))
        has_meta = "yes" if r.get("meta_description") else "NO"
        handle = (r.get("handle") or "")[:28]
        print(f"{locale:<8} {title:<46} {word_count:>6} {tags_count:>5} {has_meta:>6} {handle:<30}")
    print("=" * 96)

    errors = [r for r in results if "_error" in r]
    if errors:
        print(f"\n{len(errors)} locale(s) failed. See above.")
        sys.exit(1)

    print(f"\nAll {len(results)} locales parsed successfully.")


if __name__ == "__main__":
    main()
