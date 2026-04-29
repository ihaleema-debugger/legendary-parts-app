#!/usr/bin/env python3
"""
Semrush Keyword Gap Workflow Orchestrator
==========================================
WAT-framework root-level agent for the Keyword Gap scraping pipeline.

Prompts for competitor_domain and location, calls the Playwright scraper,
filters results (KD < 30, Volume > 100), and exports to .tmp/.

Usage:
    python agent_workflow.py
    python agent_workflow.py --competitor partseurope.eu --location France
    python agent_workflow.py --headful          # show browser for debugging
    python agent_workflow.py --no-xlsx          # CSV only
"""

import os
import sys
import argparse
import logging
import re
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from tools.semrush_scraper import run as scrape, LoginError, EmptyResultsError
from tools.exporter import export

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Filters ────────────────────────────────────────────────────────────────────

KD_MAX     = 30
VOLUME_MIN = 100

VALID_LOCATIONS = [
    "France",
    "United States",
    "United Kingdom",
    "Germany",
    "Spain",
    "Italy",
]


# ── Argument Parsing ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments. All are optional — interactive prompts fill missing ones.

    Flags:
        --competitor   Competitor domain (e.g. partseurope.eu)
        --location     Target market display name (e.g. France)
        --headful      Show browser window (disables headless for debugging)
        --no-xlsx      Skip Excel export, write CSV only
    """
    parser = argparse.ArgumentParser(
        description="Semrush Keyword Gap Analysis — legendary-parts.com vs. competitor"
    )
    parser.add_argument(
        "--competitor",
        metavar="DOMAIN",
        help="Competitor domain (e.g. partseurope.eu)",
    )
    parser.add_argument(
        "--location",
        metavar="LOCATION",
        help=f"Target market. One of: {', '.join(VALID_LOCATIONS)}",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show the browser window (useful for debugging login/CAPTCHA issues)",
    )
    parser.add_argument(
        "--no-xlsx",
        action="store_true",
        help="Skip Excel export and only write CSV",
    )
    return parser.parse_args()


# ── Interactive Prompts ────────────────────────────────────────────────────────

def prompt_competitor_domain() -> str:
    """
    Interactively prompt for competitor domain with basic validation.

    Validates: contains a dot, no spaces, no http prefix.
    Re-prompts up to 3 times before exiting.

    Returns:
        Cleaned domain string (lowercased, stripped).
    """
    domain_pattern = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}$')
    for attempt in range(3):
        raw = input("\nCompetitor domain (e.g. partseurope.eu): ").strip().lower()
        raw = raw.removeprefix("http://").removeprefix("https://").rstrip("/")
        if domain_pattern.match(raw):
            return raw
        print(f"  Invalid domain: '{raw}'. Enter a bare domain like 'autozone.com'.")
        if attempt == 2:
            print("Too many invalid attempts. Exiting.")
            sys.exit(1)
    return ""  # unreachable


def prompt_location() -> str:
    """
    Interactively prompt for target location from VALID_LOCATIONS.

    Displays a numbered menu. Accepts number or exact text (case-insensitive).
    Re-prompts on invalid selection.

    Returns:
        Selected location string (e.g. "France").
    """
    print("\nAvailable locations:")
    for i, loc in enumerate(VALID_LOCATIONS, 1):
        print(f"  {i}. {loc}")

    while True:
        raw = input("Select location (number or name): ").strip()
        # Try number
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(VALID_LOCATIONS):
                return VALID_LOCATIONS[idx]
        # Try text match
        for loc in VALID_LOCATIONS:
            if raw.lower() == loc.lower():
                return loc
        print(f"  '{raw}' is not a valid option. Enter a number (1-{len(VALID_LOCATIONS)}) or exact name.")


# ── Filtering ──────────────────────────────────────────────────────────────────

def apply_filters(df: pd.DataFrame) -> tuple:
    """
    Apply KD, Volume, and multi-word filters to the raw scraper DataFrame.

    Coerces KD and Volume to numeric before filtering to handle any
    non-numeric strings the scraper may have returned.

    Args:
        df: Raw DataFrame from tools/semrush_scraper.run().

    Returns:
        (filtered_df, stats_dict) where stats_dict contains:
            total_raw, after_kd_filter, after_volume_filter,
            after_multiword_filter, kept
    """
    total_raw = len(df)

    # Ensure numeric types (scraper already does this, but guard here too)
    df = df.copy()
    for col in ["Volume", "KD"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df_kd = df[df["KD"] < KD_MAX] if "KD" in df.columns else df
    after_kd = len(df_kd)

    df_vol = df_kd[df_kd["Volume"] > VOLUME_MIN] if "Volume" in df_kd.columns else df_kd
    after_vol = len(df_vol)

    # Filter out single-word keywords (must contain at least one space)
    df_multi = df_vol[df_vol["Keyword"].str.contains(" ", na=False)] if "Keyword" in df_vol.columns else df_vol
    after_multi = len(df_multi)

    stats = {
        "total_raw":              total_raw,
        "after_kd_filter":        after_kd,
        "after_volume_filter":    after_vol,
        "after_multiword_filter": after_multi,
        "kept":                   after_multi,
    }
    return df_multi.reset_index(drop=True), stats


# ── Summary Output ─────────────────────────────────────────────────────────────

def print_summary(
    competitors: list,
    location: str,
    all_stats: list,
    output_paths: dict,
) -> None:
    """
    Print a human-readable pipeline summary to stdout.

    Args:
        competitors: List of competitor domains analysed.
        location:   Target market.
        all_stats:  List of stats dicts (one per competitor) from apply_filters().
        output_paths: Dict from tools/exporter.export().
    """
    print("\n" + "=" * 65)
    print("  Semrush Keyword Gap Analysis — Results")
    print("=" * 65)
    print(f"  Root domain   : legendary-parts.com")
    print(f"  Competitors   : {', '.join(competitors)}")
    print(f"  Location      : {location}")
    print(f"  Filters       : KD < {KD_MAX}  |  Volume > {VOLUME_MIN}  |  Words ≥ 2")
    print("-" * 65)

    total_kept = 0
    for competitor, stats in zip(competitors, all_stats):
        dropped_kd     = stats["total_raw"] - stats["after_kd_filter"]
        dropped_vol    = stats["after_kd_filter"] - stats["after_volume_filter"]
        dropped_single = stats["after_volume_filter"] - stats["after_multiword_filter"]
        print(f"  [{competitor}]")
        print(f"    Raw scraped         : {stats['total_raw']:,}")
        print(f"    Dropped (KD ≥ {KD_MAX})  : {dropped_kd:,}")
        print(f"    Dropped (Vol ≤ {VOLUME_MIN}): {dropped_vol:,}")
        print(f"    Dropped (1 word)    : {dropped_single:,}")
        print(f"    Keywords kept       : {stats['kept']:,}")
        total_kept += stats["kept"]

    print("-" * 65)
    print(f"  Combined keywords    : {total_kept:,}")
    print("-" * 65)
    print("  Output files:")
    for fmt, path in output_paths.items():
        print(f"    [{fmt.upper()}] {path}")
    print("=" * 65)


# ── Main Pipeline ──────────────────────────────────────────────────────────────

def prompt_add_another() -> bool:
    """
    Ask the user whether to add a second/further competitor.

    Returns:
        True if the user wants to add another competitor, False otherwise.
    """
    while True:
        raw = input("\nAdd another competitor? (y/n): ").strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter 'y' or 'n'.")


def main() -> None:
    """
    Main pipeline:
        1. Parse args / prompt for location (shared across all competitors).
        2. Loop: prompt for competitor → scrape → filter → accumulate.
        3. After each competitor ask whether to add another.
        4. Combine all results, add Competitor column, export once.
        5. Print combined summary.

    Error handling:
        LoginError        → print credentials hint, exit 1
        EmptyResultsError → warn and continue loop (skip that competitor)
        KeyboardInterrupt → clean exit 0
        Unexpected        → log traceback, exit 1
    """
    args = parse_args()

    print("\n" + "=" * 65)
    print("  Semrush Keyword Gap Workflow")
    print("  legendary-parts.com vs. competitor(s)")
    print("=" * 65)

    # Location is shared across all competitor runs
    location = args.location or prompt_location()
    headless = not args.headful
    formats  = ["csv"] if args.no_xlsx else ["csv", "xlsx"]

    competitors: list[str]      = []
    all_dfs:     list           = []
    all_stats:   list[dict]     = []
    first_iteration = True

    try:
        while True:
            # Collect competitor domain
            if first_iteration and args.competitor:
                competitor_domain = args.competitor
            else:
                competitor_domain = prompt_competitor_domain()

            log.info(
                "Starting scrape: competitor=%s  location=%s  headless=%s",
                competitor_domain, location, headless,
            )

            try:
                # Scrape
                raw_df = scrape(competitor_domain, location, headless=headless)

                # Filter (KD, Volume, multi-word)
                filtered_df, stats = apply_filters(raw_df)

                if filtered_df.empty:
                    print(
                        f"\nNo keywords matched the filters for {competitor_domain} "
                        f"(KD < {KD_MAX}, Volume > {VOLUME_MIN}, words ≥ 2).\n"
                        f"Raw rows before filtering: {stats['total_raw']}\n"
                        "Skipping this competitor."
                    )
                else:
                    filtered_df = filtered_df.copy()
                    filtered_df["Competitor"] = competitor_domain
                    competitors.append(competitor_domain)
                    all_dfs.append(filtered_df)
                    all_stats.append(stats)
                    print(f"\n  {stats['kept']:,} keywords kept for {competitor_domain}.")

            except EmptyResultsError as exc:
                print(f"\n[NO RESULTS] {exc}")
                print(
                    "This usually means legendary-parts.com and the competitor share no\n"
                    "common keywords in the selected location. Skipping this competitor."
                )

            first_iteration = False

            # Ask whether to add another competitor
            if not prompt_add_another():
                break

        if not all_dfs:
            print("\nNo keywords collected for any competitor. Exiting.")
            sys.exit(0)

        # Combine all competitors into one DataFrame
        combined_df = pd.concat(all_dfs, ignore_index=True)

        # Re-sort combined: Volume DESC, KD ASC
        sort_cols = []
        if "Volume" in combined_df.columns:
            sort_cols.append(("Volume", False))
        if "KD" in combined_df.columns:
            sort_cols.append(("KD", True))
        if sort_cols:
            cols, ascending = zip(*sort_cols)
            combined_df = combined_df.sort_values(
                list(cols), ascending=list(ascending)
            ).reset_index(drop=True)

        # Export to Desktop
        date = datetime.now().strftime("%Y%m%d")
        output_paths = export(
            combined_df,
            competitor_domain=competitors,
            date=date,
            output_dir=os.path.expanduser("~/Desktop"),
            formats=formats,
        )

        # Report
        print_summary(competitors, location, all_stats, output_paths)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(0)

    except LoginError as exc:
        print(f"\n[SESSION EXPIRED] {exc}")
        print(
            "\nFix: delete semrush_session.json and re-run — a browser window will open "
            "for you to log in again.\n"
            "    rm semrush_session.json && python agent_workflow.py"
        )
        sys.exit(1)

    except Exception as exc:
        log.exception("Unexpected error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
