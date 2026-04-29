#!/usr/bin/env python3
"""
Backlink Gap Workflow — Orchestrator
======================================
WAT framework entry point for the Semrush Backlink Gap automation.

Workflow steps:
  1. Ensure .env is gitignored (safety guard runs before anything else)
  2. Validate SEMRUSH_EMAIL and SEMRUSH_PASSWORD exist in .env
  3. Prompt (or accept via CLI args) MY_DOMAIN and COMPETITOR_DOMAIN
  4. Run Playwright scraper (tools/semrush_backlink_scraper.py)
  5. Find contact emails by scraping each referring domain (tools/email_scraper.py)
  6. Export filtered results + emails to ~/Desktop as .xlsx
  7. Print summary

Usage:
    # Interactive mode (prompts for both domains):
    python backlink_gap_workflow.py

    # CLI mode (skip prompts):
    python backlink_gap_workflow.py --my-domain legendary-parts.com --competitor partseurope.eu

    # Debug (browser visible):
    python backlink_gap_workflow.py --headful

    # Skip prompts + headful:
    python backlink_gap_workflow.py --my-domain example.com --competitor rival.com --headful
"""

import argparse
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

DOMAIN_PATTERN = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)
MIN_AUTHORITY_SCORE = 20


# ── Gitignore Guard ────────────────────────────────────────────────────────────

def ensure_gitignore() -> None:
    """
    Guarantee .env is listed in .gitignore and untracked from git (if applicable).

    Actions taken:
      1. Create .gitignore if it doesn't exist.
      2. Append '.env' if not already listed.
      3. If inside a git repo, run 'git rm --cached .env' silently to untrack
         the file (safe no-op if the file was never tracked).
    """
    gitignore = Path(".gitignore")

    # Step 1: Create if missing
    if not gitignore.exists():
        gitignore.write_text("# Secrets\n.env\n")
        log.info(".gitignore created with .env entry.")
        _untrack_env_from_git()
        print("\u2705 .env is now in .gitignore and will not be pushed to GitHub.")
        return

    # Step 2: Check if .env is already listed
    content = gitignore.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    if ".env" not in lines:
        with gitignore.open("a", encoding="utf-8") as fh:
            if not content.endswith("\n"):
                fh.write("\n")
            fh.write(".env\n")
        log.info(".env appended to .gitignore.")
    else:
        log.info(".env already in .gitignore.")

    # Step 3: Untrack from git
    _untrack_env_from_git()

    print("\u2705 .env is now in .gitignore and will not be pushed to GitHub.")


def _untrack_env_from_git() -> None:
    """
    Run 'git rm --cached .env' if inside a git repo.
    Suppresses all output — safe if .env was never tracked.
    """
    # Check if we're in a git repo
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return  # Not a git repo — nothing to do

    # Untrack .env (safe no-op if not tracked)
    subprocess.run(
        ["git", "rm", "--cached", ".env"],
        capture_output=True, text=True,
    )
    log.debug("'git rm --cached .env' executed (no-op if file was never tracked).")


# ── Credential Validation ──────────────────────────────────────────────────────

def load_and_validate_credentials() -> tuple[str, str]:
    """
    Load .env and return (SEMRUSH_EMAIL, SEMRUSH_PASSWORD).

    Raises:
        SystemExit: If either credential is missing or blank.
    """
    load_dotenv()
    email    = os.getenv("SEMRUSH_EMAIL", "").strip()
    password = os.getenv("SEMRUSH_PASSWORD", "").strip()

    missing = []
    if not email:
        missing.append("SEMRUSH_EMAIL")
    if not password:
        missing.append("SEMRUSH_PASSWORD")

    if missing:
        print(f"\u274c Missing credentials in .env: {', '.join(missing)}")
        print("Add them to .env:\n  SEMRUSH_EMAIL=your@email.com\n  SEMRUSH_PASSWORD=yourpassword")
        sys.exit(1)

    return email, password


# ── Domain Prompts ─────────────────────────────────────────────────────────────

def _is_valid_domain(domain: str) -> bool:
    return bool(DOMAIN_PATTERN.match(domain.strip()))


def prompt_domain(label: str, max_retries: int = 3) -> str:
    """
    Prompt the user for a domain and validate it.

    Args:
        label:      Human-readable name shown in the prompt (e.g. "My domain").
        max_retries: Maximum number of attempts before exiting.

    Returns:
        Validated domain string.
    """
    for attempt in range(max_retries):
        raw = input(f"\n{label} (e.g. example.com): ").strip().lower()
        # Strip protocol if pasted
        raw = re.sub(r"^https?://", "", raw).rstrip("/")
        if _is_valid_domain(raw):
            return raw
        remaining = max_retries - attempt - 1
        if remaining > 0:
            print(f"  \u26a0\ufe0f  Invalid domain format. {remaining} attempt(s) left.")
        else:
            print("  \u274c  Too many invalid attempts. Exiting.")
            sys.exit(1)

    sys.exit(1)  # unreachable but satisfies type checkers


# ── Export ─────────────────────────────────────────────────────────────────────

def export_to_desktop(df, competitor_domain: str) -> str:
    """
    Export the backlink gap DataFrame to ~/Desktop as a styled .xlsx file.

    Args:
        df:                DataFrame with columns: Referring Domain, Authority Score, Email
        competitor_domain: Used in the output filename.

    Returns:
        Absolute path to the saved file.
    """
    from tools.exporter import build_backlink_filename, export_xlsx

    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    filename = build_backlink_filename(competitor_domain)
    filepath = str(desktop / filename)

    export_xlsx(df, filepath, sheet_name="Backlink Gap")
    return filepath


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary(
    my_domain: str,
    competitor_domain: str,
    prospect_count: int,
    emails_found: int,
    output_path: str,
) -> None:
    todo_count = prospect_count - emails_found
    width = 60
    print("\n" + "=" * width)
    print("  BACKLINK GAP ANALYSIS — COMPLETE")
    print("=" * width)
    print(f"  My domain:        {my_domain}")
    print(f"  Competitor:       {competitor_domain}")
    print(f"  Prospects found:  {prospect_count}")
    print(f"  Authority Score:  > {MIN_AUTHORITY_SCORE} (filtered)")
    print(f"  Emails found:     {emails_found} / {prospect_count}")
    print(f"  TODO (manual):    {todo_count}")
    print(f"  Saved to:         {output_path}")
    print(f"  .env gitignored:  \u2705")
    print("=" * width + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Semrush Backlink Gap — automated scraper & exporter"
    )
    parser.add_argument(
        "--my-domain",
        metavar="DOMAIN",
        help="Your root domain (e.g. legendary-parts.com). Skips interactive prompt.",
    )
    parser.add_argument(
        "--competitor",
        metavar="DOMAIN",
        help="Competitor domain (e.g. partseurope.eu). Skips interactive prompt.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        default=False,
        help="Run browser in visible (non-headless) mode for debugging.",
    )
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    print("\n\U0001f517 Semrush Backlink Gap — Automated Workflow")
    print("─" * 48)

    # Step 1: Security guard — .gitignore before anything else
    ensure_gitignore()

    # Step 2: Validate credentials
    load_and_validate_credentials()
    log.info("Credentials validated.")

    # Step 3: Gather domain inputs
    if args.my_domain:
        my_domain = args.my_domain.strip().lower()
        my_domain = re.sub(r"^https?://", "", my_domain).rstrip("/")
        if not _is_valid_domain(my_domain):
            print(f"\u274c Invalid domain format: {args.my_domain}")
            sys.exit(1)
        log.info("My domain (CLI): %s", my_domain)
    else:
        my_domain = prompt_domain("My domain")

    if args.competitor:
        competitor_domain = args.competitor.strip().lower()
        competitor_domain = re.sub(r"^https?://", "", competitor_domain).rstrip("/")
        if not _is_valid_domain(competitor_domain):
            print(f"\u274c Invalid domain format: {args.competitor}")
            sys.exit(1)
        log.info("Competitor domain (CLI): %s", competitor_domain)
    else:
        competitor_domain = prompt_domain("Competitor's domain")

    print(f"\n  My domain:   {my_domain}")
    print(f"  Competitor:  {competitor_domain}")
    print(f"  Browser:     {'headful (visible)' if args.headful else 'headless'}")
    print()

    # Step 4: Run scraper
    from tools.semrush_backlink_scraper import (
        EmptyResultsError,
        LoginError,
        run as scraper_run,
    )

    try:
        log.info("Starting Playwright scraper...")
        df = scraper_run(
            my_domain=my_domain,
            competitor_domain=competitor_domain,
            headless=not args.headful,
            min_authority_score=MIN_AUTHORITY_SCORE,
        )
    except LoginError as e:
        print(f"\n\u274c Login failed: {e}")
        print("Tips:")
        print("  - Check SEMRUSH_EMAIL and SEMRUSH_PASSWORD in .env")
        print("  - If 2FA is enabled on your Semrush account, disable it temporarily")
        print("  - Delete semrush_session.json and retry to force a fresh login")
        sys.exit(1)
    except EmptyResultsError as e:
        print(f"\n\u26a0\ufe0f  No prospects found: {e}")
        print("Tips:")
        print("  - Try a different competitor domain")
        print("  - Lower the Authority Score threshold (edit MIN_AUTHORITY_SCORE in this file)")
        print("  - Check .tmp/debug_backlink_*.png screenshots for what happened")
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\u26a0\ufe0f  Interrupted by user.")
        sys.exit(0)
    except Exception as e:
        log.exception("Unexpected error during scrape.")
        print(f"\n\u274c Unexpected error: {e}")
        print("Check .tmp/debug_backlink_*.png for browser state at time of failure.")
        sys.exit(1)

    # Step 5: Find contact emails for each referring domain
    from tools.email_scraper import find_emails_for_domains

    print(f"\n\U0001f4e7 Finding contact emails for {len(df)} domains...\n")
    emails = find_emails_for_domains(df["Referring Domain"].tolist())
    df["Email"] = emails
    emails_found = sum(1 for e in emails if e != "TODO")

    # Step 6: Export to Desktop
    try:
        output_path = export_to_desktop(df, competitor_domain)
    except Exception as e:
        log.exception("Export failed.")
        print(f"\n\u274c Export error: {e}")
        sys.exit(1)

    # Step 7: Summary
    print_summary(
        my_domain=my_domain,
        competitor_domain=competitor_domain,
        prospect_count=len(df),
        emails_found=emails_found,
        output_path=output_path,
    )


if __name__ == "__main__":
    main()
