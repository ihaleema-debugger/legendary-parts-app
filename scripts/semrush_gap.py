#!/usr/bin/env python3
"""
CLI entry point for the Semrush Keyword Gap scraper.

Usage:
    python scripts/semrush_gap.py <competitor_domain> <location> <output_csv_path>

Example:
    python scripts/semrush_gap.py autozone.com "United States" ~/Desktop/seo-forge/run_id/01_raw_keywords.csv

Exit codes:
    0 — success, CSV written
    1 — login failure, empty results, or unexpected error
"""

import sys
import os
from pathlib import Path

# Allow importing from tools/ regardless of working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.semrush_scraper import run, LoginError, EmptyResultsError


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python scripts/semrush_gap.py <competitor_domain> <location> <output_csv_path>",
            file=sys.stderr,
        )
        sys.exit(1)

    competitor_domain = sys.argv[1]
    location = sys.argv[2]
    output_path = Path(sys.argv[3]).expanduser().resolve()

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        print(f"Scraping Semrush Keyword Gap: legendary-parts.com vs {competitor_domain} ({location})")
        df = run(competitor_domain, location, headless=True)
        df.to_csv(output_path, index=False)
        print(f"Done. {len(df)} keywords saved to {output_path}")
    except LoginError as e:
        print(f"ERROR: Semrush login failed — {e}", file=sys.stderr)
        sys.exit(1)
    except EmptyResultsError as e:
        print(f"ERROR: No results returned from Semrush — {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected failure — {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
