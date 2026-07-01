"""Checkpoint 2 smoke test: publish translations for the V-Rod blog.

Registers translations for all 8 non-FR locales against the existing
French V-Rod draft article in Shopify, then prints a per-locale result table
including prose word counts so outliers (truncated translations, export
failures) are easy to spot.

Usage:
    cd "/Users/mac/Documents/SEO Agent Workflow"
    keyword_forge/.venv/bin/python scripts/test_translation_pipeline_checkpoint2.py
"""
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PUBLISHERS_DIR = PROJECT_ROOT / "workflows" / "Publishers"
if str(PUBLISHERS_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHERS_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from translation_publisher import publish_translations, prose_word_count
from drive_fetcher import fetch_blog_files
from gdoc_reader import read_blog_gdoc

# ── Constants — confirm these match Shopify admin before running ───────────────
SOURCE_ARTICLE_ID = "1002085548376"   # V-Rod French draft article ID
BLOG_STEM         = "harley-davidson-vrsc-v-rod-complete-buyers-and-owners-guide"
FOLDER_PATH       = "12. Claude Blogs / Approved Blogs"
SHARED_DRIVE      = "shared drive with Claude"


def _get_fr_word_count() -> int:
    """Fetch the French source doc and return its prose word count."""
    files = fetch_blog_files(BLOG_STEM, FOLDER_PATH, SHARED_DRIVE)
    fr_file = next((f for f in files if f["locale"] == "fr"), None)
    if not fr_file:
        return 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = read_blog_gdoc(fr_file["file_id"])
    return prose_word_count(doc["body_html"])


def main():
    print("=" * 70)
    print("Checkpoint 2 — Shopify translation publisher smoke test")
    print(f"Article ID : {SOURCE_ARTICLE_ID}")
    print(f"Blog stem  : {BLOG_STEM}")
    print("=" * 70)

    # Fetch French baseline word count for comparison
    print("\n→ Fetching French source word count for baseline...")
    fr_wc = _get_fr_word_count()
    print(f"  French source: {fr_wc} words\n")

    # Run translations
    results = publish_translations(
        source_article_id=SOURCE_ARTICLE_ID,
        blog_stem=BLOG_STEM,
        folder_path=FOLDER_PATH,
        drive_name=SHARED_DRIVE,
    )

    # ── Result table ──────────────────────────────────────────────────────────
    col_w = {"locale": 8, "status": 8, "words": 7, "pct": 7, "fields": 6, "errors": 55}
    divider = "-" * (sum(col_w.values()) + len(col_w) * 3)

    print("\n" + "=" * len(divider))
    print(
        f"{'locale':<{col_w['locale']}}  "
        f"{'status':<{col_w['status']}}  "
        f"{'words':>{col_w['words']}}  "
        f"{'%vs_fr':>{col_w['pct']}}  "
        f"{'fields':>{col_w['fields']}}  "
        f"{'errors':<{col_w['errors']}}"
    )
    print(divider)

    # French baseline row
    if fr_wc:
        print(
            f"{'fr':<{col_w['locale']}}  "
            f"{'source':<{col_w['status']}}  "
            f"{fr_wc:>{col_w['words']}}  "
            f"{'100%':>{col_w['pct']}}  "
            f"{'—':>{col_w['fields']}}  "
            f"{'(source — not registered)':<{col_w['errors']}}"
        )
        print(divider)

    ok_count = fail_count = skip_count = 0
    for locale in sorted(results):
        r = results[locale]
        status     = r.get("status", "?")
        wc         = r.get("word_count", 0)
        n_fields   = len(r.get("fields_registered") or [])
        errors_raw = "; ".join(r.get("errors") or [])
        pct        = f"{100 * wc / fr_wc:.1f}%" if fr_wc and wc else "—"

        # Flag locales whose body is ≥20% shorter than French
        flag = ""
        if fr_wc and wc and (wc / fr_wc) < 0.80:
            flag = " ⚠ SHORT"

        fields_cell = str(n_fields) if n_fields else "—"
        errors_cell = (errors_raw + flag)[:col_w["errors"]]

        print(
            f"{locale:<{col_w['locale']}}  "
            f"{status:<{col_w['status']}}  "
            f"{wc:>{col_w['words']}}  "
            f"{pct:>{col_w['pct']}}  "
            f"{fields_cell:>{col_w['fields']}}  "
            f"{errors_cell:<{col_w['errors']}}"
        )

        if status == "ok":
            ok_count += 1
        elif status in ("failed", "error"):
            fail_count += 1
        else:
            skip_count += 1

    print("=" * len(divider))
    print(f"\n{ok_count} registered  |  {fail_count} failed  |  {skip_count} skipped")

    if fail_count:
        print("\n✗ Some locales failed — see errors column above.")
        sys.exit(1)

    print("\n✓ All locales processed successfully.")
    print("\nTo verify in Shopify admin:")
    print("  1. Go to Apps → Translate & Adapt")
    print("  2. Select the V-Rod article")
    print("  3. Use the language switcher to confirm each locale shows translated content")
    print("  (Alternatively: Admin → Online Store → Blog posts → V-Rod article")
    print("   → Translate content button in the top-right)")


if __name__ == "__main__":
    main()
