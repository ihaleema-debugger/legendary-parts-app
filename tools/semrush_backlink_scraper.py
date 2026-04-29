#!/usr/bin/env python3
"""
Semrush Backlink Gap Scraper
=============================
Playwright-based browser automation for the Semrush Backlink Gap tool.

Handles:
  - Session persistence via semrush_session.json (shared with keyword gap scraper)
  - Full login with credential caching
  - URL-based navigation to the Backlink Gap tool
  - "Missing" tab click to show domains linking to competitor but NOT to my domain
  - Authority Score > 20 filter application
  - Export trigger and Playwright download event handling
  - CSV parsing → DataFrame with columns: Referring Domain, Authority Score
  - One retry (3-second wait) on selector failure; screenshot saved on final failure

Exports:
    run(my_domain, competitor_domain, headless) -> pd.DataFrame
    LoginError
    EmptyResultsError

Usage:
    from tools.semrush_backlink_scraper import run, LoginError, EmptyResultsError
    df = run("legendary-parts.com", "partseurope.eu", headless=True)
"""

import csv
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

load_dotenv()

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SESSION_FILE       = "semrush_session.json"
LOGIN_URL          = "https://www.semrush.com/login/"
# Correct Backlink Gap tool URL (discovered Apr 2026 via sidebar navigation).
# The old /analytics/backlinks/gap/ URL now redirects to a free backlink checker
# landing page. The actual gap tool lives at /analytics/gap/backlinks/.
BACKLINK_GAP_URL   = "https://www.semrush.com/analytics/gap/backlinks/?q={domain}&searchType=domain"
# Backlink Analytics overview for a domain — used as a fallback entry point.
BACKLINK_ANALYTICS_URL = "https://www.semrush.com/analytics/backlinks/overview/?q={domain}&searchType=domain"

PAGE_TIMEOUT    = 60_000    # ms — full page load
ELEMENT_TIMEOUT = 30_000    # ms — individual elements
NAV_TIMEOUT     = 120_000   # ms — Backlink Gap results can be slow

# Column aliases Semrush may use for referring domain and authority score
DOMAIN_ALIASES = [
    "Referring Domain", "referring domain", "Domain", "domain",
    "Root Domain", "root domain", "URL", "url",
]
AS_ALIASES = [
    "Authority Score", "authority score", "AS", "as",
    "Domain ascore", "domain ascore",  # observed Apr 2026 in Backlink Gap export
    "Domain Authority", "DA", "Page Authority", "PA",
]


# ── Custom Exceptions ──────────────────────────────────────────────────────────

class LoginError(Exception):
    """Raised when login fails or session expires and cannot be renewed."""


class EmptyResultsError(Exception):
    """Raised when no backlink gap results are returned for the given domains."""


# ── Session Management ─────────────────────────────────────────────────────────
# Identical to semrush_scraper.py — reuses the same semrush_session.json file.

def _save_session(context, session_file: str = SESSION_FILE) -> None:
    cookies = context.cookies()
    with open(session_file, "w") as fh:
        json.dump({"cookies": cookies}, fh, indent=2)
    log.info("Session saved → %s (%d cookies)", session_file, len(cookies))


def _load_session(context, session_file: str = SESSION_FILE) -> bool:
    if not Path(session_file).exists():
        log.info("No session file at %s — will perform full login.", session_file)
        return False
    with open(session_file) as fh:
        data = json.load(fh)
    context.add_cookies(data.get("cookies", []))
    log.info("Session loaded from %s (%d cookies)", session_file, len(data.get("cookies", [])))
    return True


# ── Authentication ─────────────────────────────────────────────────────────────

def _is_multilogin_page(page) -> bool:
    """Return True if the current page is the 'too many active sessions' interstitial."""
    if "multilogin" in page.url:
        return True
    try:
        return page.locator(':has-text("too many active sessions")').count() > 0
    except Exception:
        return False


def _click_multilogin_continue(page) -> None:
    """Click the Continue button on the multilogin interstitial (best effort)."""
    for sel in ['button:has-text("Continue")', 'a:has-text("Continue")', 'button[type="submit"]']:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click()
                log.info("Multilogin Continue clicked.")
                time.sleep(2)
                return
        except Exception:
            continue
    log.warning("Multilogin Continue button not found — proceeding anyway.")


def _is_logged_in(page) -> bool:
    # Multilogin interstitial = user IS logged in, just has too many sessions
    if _is_multilogin_page(page):
        log.info("Multilogin interstitial — session is valid.")
        return True

    current_url = page.url
    if "login" in current_url or "signin" in current_url:
        log.info("Session invalid — on login page: %s", current_url)
        return False

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    if _is_multilogin_page(page):
        log.info("Multilogin interstitial after load — session is valid.")
        return True

    current_url = page.url
    if "login" in current_url or "signin" in current_url:
        log.info("Session invalid — redirected to login after load: %s", current_url)
        return False

    LOGGED_IN_SELECTORS = [
        "[data-test='user-menu']",
        "[data-test='header-user-menu']",
        ".sem-avatar",
        "[class*='userMenu']",
        "[class*='UserMenu']",
        "[aria-label*='account']",
        "[aria-label*='Account']",
        "a[href*='/profile']",
        "a[href*='/account']",
    ]
    deadline = time.time() + 15
    while time.time() < deadline:
        for sel in LOGGED_IN_SELECTORS:
            if page.query_selector(sel):
                log.debug("Logged-in indicator found: %s", sel)
                return True
        time.sleep(2)

    log.info("Not on login page and page loaded — assuming valid session.")
    return True


def _perform_login(page, email: str, password: str) -> None:
    log.info("Navigating to login page: %s", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeout:
        log.warning("Login page did not reach networkidle — proceeding.")

    os.makedirs(".tmp", exist_ok=True)
    page.screenshot(path=".tmp/debug_backlink_login.png")
    log.info("Login screenshot → .tmp/debug_backlink_login.png")

    for email_sel in ['input[name="email"]', 'input[type="email"]', '#email',
                      'input[autocomplete="email"]', 'input[autocomplete="username"]']:
        try:
            page.wait_for_selector(email_sel, timeout=15_000)
            page.fill(email_sel, email)
            log.debug("Email filled via: %s", email_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError(
            "Email input not found on Semrush login page. "
            "See .tmp/debug_backlink_login.png"
        )

    for pwd_sel in ['input[name="password"]', 'input[type="password"]', '#password',
                    'input[autocomplete="current-password"]']:
        try:
            page.wait_for_selector(pwd_sel, timeout=10_000)
            page.fill(pwd_sel, password)
            log.debug("Password filled via: %s", pwd_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError("Password input not found on Semrush login page.")

    for submit_sel in ['button[type="submit"]', '[data-test="login-button"]',
                       'button:has-text("Log in")', 'button:has-text("Sign in")',
                       'button:has-text("Log In")', 'button:has-text("Continue")']:
        try:
            page.wait_for_selector(submit_sel, timeout=5_000)
            page.click(submit_sel)
            log.debug("Submitted via: %s", submit_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError("Submit button not found on Semrush login page.")

    try:
        page.wait_for_url(
            lambda url: "login" not in url and "signin" not in url,
            timeout=30_000,
        )
    except PlaywrightTimeout:
        error_text = page.locator('[class*="error"], [class*="Error"], [role="alert"]').all_inner_texts()
        hint = " | ".join(error_text) if error_text else "No error message found."
        raise LoginError(
            f"Login failed — still on login page after submit. "
            f"Check SEMRUSH_EMAIL / SEMRUSH_PASSWORD in .env. Hint: {hint}"
        )

    log.info("Login successful — redirected to: %s", page.url)


def _ensure_authenticated(page, context, email: str, password: str) -> None:
    session_loaded = _load_session(context)
    if session_loaded:
        log.info("Verifying cached session...")
        page.goto("https://www.semrush.com/", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        if _is_logged_in(page):
            log.info("Cached session valid — skipping login.")
            return
        log.info("Cached session expired — performing fresh login.")

    _perform_login(page, email, password)
    _save_session(context)


# ── Backlink Gap Navigation ────────────────────────────────────────────────────

def _screenshot(page, name: str) -> None:
    """Save a debug screenshot to .tmp/."""
    os.makedirs(".tmp", exist_ok=True)
    path = f".tmp/debug_backlink_{name}.png"
    try:
        page.screenshot(path=path, full_page=False)
        log.info("Screenshot → %s", path)
    except Exception as e:
        log.debug("Screenshot failed (%s): %s", name, e)


def _click_with_retry(page, selectors: list, label: str, wait: float = 3.0) -> bool:
    """
    Try each selector once. On first pass failure, wait `wait` seconds and retry.
    Saves a screenshot and returns False if both passes fail.

    Args:
        page:      Playwright Page object.
        selectors: List of CSS/text selectors to try in order.
        label:     Human-readable name for logging/screenshot.
        wait:      Seconds to wait between first and second pass.

    Returns:
        True if click succeeded; False otherwise.
    """
    for attempt in range(2):
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible():
                    el.click()
                    log.info("[%s] Clicked via: %s", label, sel)
                    return True
            except Exception:
                continue
        if attempt == 0:
            log.warning("[%s] Not found on first pass — waiting %.0fs then retrying.", label, wait)
            _screenshot(page, f"{label.lower().replace(' ', '_')}_retry")
            time.sleep(wait)

    _screenshot(page, f"{label.lower().replace(' ', '_')}_failed")
    log.error("[%s] Could not click after retry. Screenshot saved.", label)
    return False


def _fill_single_input(page, value: str, label: str) -> bool:
    """
    Fill the first visible non-search-bar text input on the page with `value`.
    Used on the Backlink Analytics landing page which has exactly one domain input.

    Returns True if the input was filled.
    """
    all_inputs = page.locator('input[type="text"], input[type="search"], input:not([type])')
    for i in range(all_inputs.count()):
        try:
            inp = all_inputs.nth(i)
            if not inp.is_visible():
                continue
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            if placeholder == "search":
                continue
            box = inp.bounding_box()
            if box and box["y"] < 80:
                continue  # global top nav bar
            inp.click()
            inp.fill(value)
            log.info("[%s] Filled via positional index %d (placeholder=%r)", label, i, placeholder)
            time.sleep(0.5)
            return True
        except Exception:
            continue
    log.error("[%s] Could not find a suitable input to fill.", label)
    return False


def _fill_competitor_input(page, competitor_domain: str) -> bool:
    """
    Fill the 'Add domain' competitor input on the Backlink Gap tool page.

    The Backlink Gap form (at /analytics/gap/backlinks/) has:
      - "You" row: a chip-style input pre-filled with my domain (contains "Add" in placeholder)
      - "Add domain" row: an empty input for the competitor domain (also contains "Add")

    Key insight: BOTH inputs contain "Add" in their placeholder. The "You" input is
    pre-filled (has a value); the competitor "Add domain" input is empty.
    Strategy: skip inputs that already have a value, target only empty ones.
    Fallback: use nth(1) to get the second "Add*" input.

    Returns True if the competitor input was filled.
    """
    # Strategy 1: Find an empty visible input with "Add" in placeholder.
    # The "You" field is pre-filled (has a chip value) so we skip non-empty inputs.
    all_add_inputs = page.locator('input[placeholder*="Add"], input[placeholder*="domain"]')
    for i in range(all_add_inputs.count()):
        try:
            inp = all_add_inputs.nth(i)
            if not inp.is_visible():
                continue
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            if placeholder == "search":
                continue
            # Skip inputs that are already filled (the "You" chip field)
            current_value = inp.input_value()
            if current_value and current_value.strip():
                log.debug("Skipping pre-filled input at index %d (value=%r)", i, current_value)
                continue
            box = inp.bounding_box()
            if box and box["y"] < 80:
                continue
            inp.click()
            inp.fill(competitor_domain)
            log.info("Competitor domain filled (empty input, placeholder=%r, index=%d)", placeholder, i)
            time.sleep(0.5)
            return True
        except Exception as e:
            log.debug("Competitor input attempt %d failed: %s", i, e)
            continue

    # Strategy 2: nth(1) — second visible "Add*" input (first is "You", second is competitor)
    log.info("Empty-input strategy failed — trying nth(1) of 'Add*' inputs.")
    visible_add = page.locator('input[placeholder*="Add"]')
    if visible_add.count() >= 2:
        try:
            inp = visible_add.nth(1)
            inp.click()
            inp.fill(competitor_domain)
            log.info("Competitor domain filled via nth(1) of Add* inputs.")
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning("nth(1) fill failed: %s", e)

    # Strategy 3: positional — second visible non-search-bar, non-filled input
    log.info("Falling back to full positional scan.")
    all_inputs = page.locator('input[type="text"], input[type="search"], input:not([type])')
    gap_inputs = []
    for i in range(all_inputs.count()):
        try:
            inp = all_inputs.nth(i)
            if not inp.is_visible():
                continue
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            if placeholder == "search":
                continue
            box = inp.bounding_box()
            if box and box["y"] < 80:
                continue
            gap_inputs.append(i)
        except Exception:
            continue

    if len(gap_inputs) >= 2:
        try:
            all_inputs.nth(gap_inputs[1]).click()
            all_inputs.nth(gap_inputs[1]).fill(competitor_domain)
            log.info("Competitor domain filled positionally (filtered index %d)", gap_inputs[1])
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning("Positional fill (competitor) failed: %s", e)

    log.error("Could not fill competitor domain input.")
    return False


# Keep old name as alias so external callers still work
def _fill_gap_form_inputs(page, my_domain: str, competitor_domain: str) -> bool:
    filled_comp = _fill_competitor_input(page, competitor_domain)
    return filled_comp  # "You" is pre-filled by this point in the flow


_fill_domain_inputs = _fill_gap_form_inputs


def _click_find_prospects(page) -> bool:
    """Click the 'Find prospects' / submit button."""
    return _click_with_retry(
        page,
        selectors=[
            'button:has-text("Find prospects")',
            'button:has-text("Find Prospects")',
            'button:has-text("Compare")',
            'button:has-text("Analyze")',
            'button:has-text("Search")',
            'button[type="submit"]',
            '[data-test*="submit"]',
            '[data-test*="compare"]',
        ],
        label="Find prospects",
    )


def _poll_for_rows(page, total_wait: int = 120) -> bool:
    """
    Poll every 2s until any data rows appear in the results table.
    Dismisses multilogin interstitials if they appear mid-poll.
    Returns True if rows found; False if budget expires.
    """
    deadline = time.time() + total_wait
    while time.time() < deadline:
        # Dismiss multilogin interstitial if it reappears during polling
        if _is_multilogin_page(page):
            log.info("Multilogin interstitial appeared mid-poll — clicking Continue.")
            _click_multilogin_continue(page)
            time.sleep(3)
            continue

        try:
            row_count = page.evaluate("""
                () => {
                    const tableRows = document.querySelectorAll('tbody tr td');
                    if (tableRows.length > 0) return tableRows.length;

                    const ariaRows = document.querySelectorAll('[role="row"]');
                    if (ariaRows.length > 1) return ariaRows.length - 1;

                    const dataRows = document.querySelectorAll(
                        '[data-test*="row"], [class*="tableRow"], [class*="TableRow"]'
                    );
                    if (dataRows.length > 0) return dataRows.length;

                    return 0;
                }
            """)
            if row_count and row_count > 0:
                log.info("Data rows detected: %d", row_count)
                return True
        except Exception as e:
            log.debug("Row poll error: %s", e)

        remaining = int(deadline - time.time())
        log.info("Waiting for data rows... (%ds remaining)", remaining)
        time.sleep(2)

    return False


def _click_missing_tab(page) -> bool:
    """
    Click the tab that shows domains linking to competitor but NOT my domain.

    Semrush has renamed tabs over time:
      Old UI (pre-2025): "Missing" tab
      New UI (Apr 2026):  "Best" tab = highest-authority domains unique to competitor
                          "Unique" tab = all domains unique to competitor (not linking to you)

    We try all known names in priority order.
    """
    return _click_with_retry(
        page,
        selectors=[
            # New UI tab names (Apr 2026)
            'button:has-text("Best")',
            'a:has-text("Best")',
            '[role="tab"]:has-text("Best")',
            'button:has-text("Unique")',
            'a:has-text("Unique")',
            '[role="tab"]:has-text("Unique")',
            # Old UI tab name
            'button:has-text("Missing")',
            'a:has-text("Missing")',
            '[role="tab"]:has-text("Missing")',
            ':has-text("Missing")',
            '[class*="tab"]:has-text("Missing")',
        ],
        label="Missing/Best tab",
    )


def _apply_authority_score_filter(page, min_score: int = 20) -> bool:
    """
    Apply the Authority Score > min_score filter in the Backlink Gap filter UI.

    Semrush uses a filter bar with dropdowns or inline inputs. This function
    tries several approaches to set AS > 20.

    Returns True if the filter was applied; False otherwise (not fatal — results
    are still returned, just unfiltered; the orchestrator re-filters in Python).
    """
    log.info("Applying Authority Score > %d filter...", min_score)

    # Try to open a filter panel if one exists
    filter_opener_selectors = [
        'button:has-text("Filters")',
        'button:has-text("Filter")',
        '[data-test*="filter"]',
        '[aria-label*="filter"]',
        '[aria-label*="Filter"]',
        'button:has-text("Add filter")',
    ]
    for sel in filter_opener_selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click()
                log.info("Filter panel opened via: %s", sel)
                time.sleep(1)
                break
        except Exception:
            continue

    # Try to find an Authority Score filter input
    AS_FILTER_SELECTORS = [
        'input[placeholder*="Authority"]',
        'input[aria-label*="Authority"]',
        'input[aria-label*="authority"]',
        'input[placeholder*="AS"]',
        'input[name*="authority"]',
        'input[name*="Authority"]',
    ]
    for sel in AS_FILTER_SELECTORS:
        try:
            inp = page.locator(sel).first
            if inp.count() > 0:
                inp.click()
                inp.fill(str(min_score))
                inp.press("Enter")
                log.info("Authority Score filter set to %d via: %s", min_score, sel)
                time.sleep(2)
                return True
        except Exception:
            continue

    # Try dropdown-based filter (Authority Score > X)
    AS_DROPDOWN_SELECTORS = [
        '[data-test*="authority"]',
        '[data-test*="Authority"]',
        'select[name*="authority"]',
        ':has-text("Authority Score")',
    ]
    for sel in AS_DROPDOWN_SELECTORS:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click()
                time.sleep(0.5)
                # Try to type the value in any subsequent input
                inp = page.locator('input[type="number"], input[type="text"]').last
                if inp.count() > 0:
                    inp.fill(str(min_score))
                    inp.press("Enter")
                    log.info("Authority Score filter set via dropdown approach")
                    time.sleep(2)
                    return True
        except Exception:
            continue

    log.warning(
        "Could not apply Authority Score filter via UI — "
        "results will be filtered in Python (AS > %d) after export.", min_score
    )
    return False


def _trigger_export_and_download(page, download_dir: str) -> Optional[str]:
    """
    Click the Export button and capture the downloaded file via Playwright's
    download event handler.

    Args:
        page:         Playwright Page on the Backlink Gap results page.
        download_dir: Directory where the downloaded file will be saved.

    Returns:
        Absolute path to the downloaded file, or None on failure.
    """
    os.makedirs(download_dir, exist_ok=True)
    log.info("Triggering export download...")

    EXPORT_SELECTORS = [
        'button:has-text("Export")',
        'a:has-text("Export")',
        '[data-test*="export"]',
        '[aria-label*="export"]',
        '[aria-label*="Export"]',
        'button:has-text("Download")',
        'a:has-text("Download")',
    ]

    # Start watching for download before clicking
    try:
        with page.expect_download(timeout=60_000) as download_info:
            clicked = False
            for sel in EXPORT_SELECTORS:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        log.info("Export button clicked via: %s", sel)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                log.warning("Export button not found — cannot trigger download.")
                return None

            # If a format chooser appears (CSV / Excel dropdown), click CSV.
            # Semrush uses various element types for dropdown items (li, span, div, a).
            time.sleep(1.5)
            for fmt_sel in [
                'li:has-text("CSV")',
                'span:has-text("CSV")',
                'div:has-text("CSV")',
                '[role="menuitem"]:has-text("CSV")',
                '[role="option"]:has-text("CSV")',
                'a:has-text("CSV")',
                'button:has-text("CSV")',
                '[data-test*="csv"]',
                # Fall back to Excel if CSV not found
                'li:has-text("Excel")',
                'span:has-text("Excel")',
                'div:has-text("Excel")',
                '[role="menuitem"]:has-text("Excel")',
                'a:has-text("Excel")',
                'button:has-text("Excel")',
                'a:has-text(".csv")',
                'a:has-text(".xlsx")',
            ]:
                try:
                    fmt_el = page.locator(fmt_sel).first
                    if fmt_el.count() > 0 and fmt_el.is_visible():
                        fmt_el.click()
                        log.info("Format selected via: %s", fmt_sel)
                        break
                except Exception:
                    continue

        download = download_info.value
        suggested_name = download.suggested_filename or "backlink_gap_export.csv"
        dest = os.path.join(download_dir, suggested_name)
        download.save_as(dest)
        log.info("Download saved → %s", dest)
        return dest

    except PlaywrightTimeout:
        log.error("Download timed out — export may not have triggered.")
        _screenshot(page, "export_timeout")
        return None
    except Exception as e:
        log.error("Download failed: %s", e)
        _screenshot(page, "export_failed")
        return None


# ── CSV Parsing ────────────────────────────────────────────────────────────────

def _parse_export_file(filepath: str) -> pd.DataFrame:
    """
    Parse the downloaded export file (CSV or XLSX) into a normalised DataFrame.

    Normalises column names to 'Referring Domain' and 'Authority Score'
    regardless of the exact header names Semrush used.

    Args:
        filepath: Path to the downloaded export file.

    Returns:
        DataFrame with at minimum a 'Referring Domain' column.
        'Authority Score' column included if present in the source.

    Raises:
        ValueError: If no recognisable domain column is found.
    """
    ext = Path(filepath).suffix.lower()
    if ext in (".xlsx", ".xls"):
        raw = pd.read_excel(filepath)
    else:
        # Try common delimiters
        for delimiter in [",", ";", "\t"]:
            try:
                raw = pd.read_csv(filepath, sep=delimiter, encoding="utf-8")
                if len(raw.columns) > 1:
                    break
            except Exception:
                continue
        else:
            raw = pd.read_csv(filepath, encoding="utf-8")

    log.info("Raw export columns: %s", list(raw.columns))

    # Normalise column names (strip whitespace)
    raw.columns = [str(c).strip() for c in raw.columns]

    # Find domain column
    domain_col = None
    for alias in DOMAIN_ALIASES:
        if alias in raw.columns:
            domain_col = alias
            break
    if domain_col is None:
        # Case-insensitive fallback
        for col in raw.columns:
            if any(alias.lower() in col.lower() for alias in ["domain", "url", "referring"]):
                domain_col = col
                break
    if domain_col is None:
        raise ValueError(
            f"Could not find a referring domain column in export. "
            f"Columns found: {list(raw.columns)}"
        )

    # Find authority score column
    as_col = None
    for alias in AS_ALIASES:
        if alias in raw.columns:
            as_col = alias
            break
    if as_col is None:
        for col in raw.columns:
            if any(alias.lower() in col.lower() for alias in ["authority", " as", "score", " da", " pa"]):
                as_col = col
                break

    # Build output DataFrame
    cols_to_keep = [domain_col]
    rename_map = {domain_col: "Referring Domain"}
    if as_col:
        cols_to_keep.append(as_col)
        rename_map[as_col] = "Authority Score"

    df = raw[cols_to_keep].rename(columns=rename_map).copy()
    df = df.dropna(subset=["Referring Domain"])
    df = df[df["Referring Domain"].astype(str).str.strip() != ""]
    df = df.reset_index(drop=True)

    if "Authority Score" in df.columns:
        df["Authority Score"] = pd.to_numeric(df["Authority Score"], errors="coerce")

    log.info("Parsed %d referring domains from export.", len(df))
    return df


# ── Public Entry Point ─────────────────────────────────────────────────────────

def run(
    my_domain: str,
    competitor_domain: str,
    headless: bool = True,
    min_authority_score: int = 20,
) -> pd.DataFrame:
    """
    Execute the full Backlink Gap scrape: login → navigate → fill form →
    Missing tab → AS filter → export → parse → return DataFrame.

    Args:
        my_domain:            Your root domain (e.g. "legendary-parts.com").
        competitor_domain:    Competitor's domain (e.g. "partseurope.eu").
        headless:             Run browser without visible window (default True).
        min_authority_score:  Minimum AS to retain (applied in Python after export).

    Returns:
        DataFrame with columns: Referring Domain, Authority Score (where available).
        Rows where AS < min_authority_score are removed.

    Raises:
        LoginError:       If authentication fails.
        EmptyResultsError: If no prospects remain after filtering.
    """
    email    = os.getenv("SEMRUSH_EMAIL", "").strip()
    password = os.getenv("SEMRUSH_PASSWORD", "").strip()

    if not email:
        raise LoginError("SEMRUSH_EMAIL is not set in .env")
    if not password:
        raise LoginError("SEMRUSH_PASSWORD is not set in .env")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # ── Step 1: Authenticate ────────────────────────────────────────
            _ensure_authenticated(page, context, email, password)

            # ── Step 2: Navigate directly to the Backlink Gap tool ──────────
            # Discovered Apr 2026: the actual Backlink Gap tool (Missing/All/Weak tabs)
            # lives at /analytics/gap/backlinks/ — NOT /analytics/backlinks/gap/.
            # Passing ?q=my_domain&searchType=domain pre-fills "You" with my domain.
            # No sidebar click needed.

            gap_url = BACKLINK_GAP_URL.format(domain=my_domain)
            log.info("Navigating directly to Backlink Gap tool: %s", gap_url)
            page.goto(gap_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
            time.sleep(3)

            # Dismiss multilogin interstitial — up to 3 attempts.
            # After clicking Continue, Semrush uses its redirect_to parameter to
            # send us to the target page automatically. We must NOT navigate directly
            # right away or we'll trigger another multilogin challenge. Instead, wait
            # for Semrush to complete the redirect, then navigate only if it stalls.
            for _ml_attempt in range(3):
                if not _is_multilogin_page(page):
                    break
                log.info("Multilogin interstitial — clicking Continue (attempt %d/3).", _ml_attempt + 1)
                _click_multilogin_continue(page)
                try:
                    page.wait_for_url(
                        lambda url: "multilogin" not in url,
                        timeout=15_000,
                    )
                    log.info("Redirected away from multilogin → %s", page.url)
                    break
                except PlaywrightTimeout:
                    log.warning("Still on multilogin after Continue — navigating to gap URL directly.")
                    page.goto(gap_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                    time.sleep(3)

            log.info("After gap navigation — URL: %s", page.url)

            try:
                page.wait_for_load_state("networkidle", timeout=25_000)
            except PlaywrightTimeout:
                log.warning("networkidle timeout on gap page — proceeding.")

            # Dismiss any modal popups
            for popup_sel in [
                'button:has-text("Got it")', 'button:has-text("Skip")',
                'button:has-text("Dismiss")', '[aria-label="Close"]',
                '[data-test*="close"]', 'button:has-text("×")',
            ]:
                try:
                    el = page.locator(popup_sel).first
                    if el.count() > 0 and el.is_visible():
                        el.click()
                        log.info("Closed popup via: %s", popup_sel)
                        time.sleep(0.5)
                except Exception:
                    continue

            _screenshot(page, "01_gap_form")

            # ── Step 3: Fill competitor domain ──────────────────────────────
            # "You" is pre-filled with my domain from the URL parameter.
            # We only need to fill the empty "Add domain" competitor input.
            log.info("Filling competitor domain: %s", competitor_domain)
            filled_comp = _fill_competitor_input(page, competitor_domain)
            if not filled_comp:
                _screenshot(page, "02_competitor_fill_failed")
                log.warning("Could not fill competitor domain.")

            _screenshot(page, "02_after_fill")
            time.sleep(0.5)

            # ── Step 4: Click Find Prospects ────────────────────────────────
            clicked = _click_with_retry(
                page,
                selectors=[
                    'button:has-text("Find prospects")',
                    'button:has-text("Find Prospects")',
                    'button:has-text("Compare")',
                    'button[type="submit"]',
                    '[data-test*="submit"]',
                    '[data-test*="compare"]',
                ],
                label="Find prospects",
            )
            if not clicked:
                _screenshot(page, "03_find_prospects_failed")
                raise EmptyResultsError(
                    "Could not click 'Find prospects' — check .tmp/debug_backlink_03_find_prospects_failed.png"
                )

            # ── Step 5: Wait for results ────────────────────────────────────
            log.info("Waiting for Backlink Gap results to load...")

            # Semrush may show the multilogin interstitial again right after Find prospects.
            # Wait for redirect_to to resolve, then re-fill + re-submit.
            time.sleep(2)
            if _is_multilogin_page(page):
                log.info("Multilogin interstitial after Find prospects — clicking Continue.")
                _click_multilogin_continue(page)
                try:
                    page.wait_for_url(
                        lambda url: "multilogin" not in url,
                        timeout=15_000,
                    )
                    log.info("Redirected away from multilogin (post Find-prospects) → %s", page.url)
                except PlaywrightTimeout:
                    log.warning("Still on multilogin — navigating to gap URL directly.")
                    page.goto(gap_url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                    time.sleep(3)
                _fill_competitor_input(page, competitor_domain)
                time.sleep(0.5)
                _click_with_retry(
                    page,
                    selectors=['button:has-text("Find prospects")', 'button:has-text("Compare")'],
                    label="Find prospects (multilogin retry)",
                )
                time.sleep(2)

            try:
                page.wait_for_load_state("networkidle", timeout=60_000)
            except PlaywrightTimeout:
                log.warning("networkidle timeout waiting for results.")

            rows_found = _poll_for_rows(page, total_wait=120)
            _screenshot(page, "03_results_loaded")

            if not rows_found:
                log.warning("No rows detected in results table — may be empty for these domains.")

            # ── Step 6: Click 'Missing' tab ─────────────────────────────────
            tab_clicked = _click_missing_tab(page)
            if tab_clicked:
                time.sleep(3)  # Allow tab switch + data re-fetch
                _screenshot(page, "04_missing_tab")

            # ── Step 7: Apply Authority Score filter ────────────────────────
            _apply_authority_score_filter(page, min_score=min_authority_score)
            time.sleep(2)
            # Close any open filter panel (press Escape) so it doesn't block Export.
            try:
                page.keyboard.press("Escape")
                time.sleep(1)
                log.info("Pressed Escape to close any open filter panel.")
            except Exception:
                pass
            _screenshot(page, "05_after_filter")

            # ── Step 8: Export ──────────────────────────────────────────────
            download_path = _trigger_export_and_download(page, download_dir=".tmp")
            _screenshot(page, "06_after_export")

        finally:
            browser.close()

    # ── Step 9: Parse ───────────────────────────────────────────────────────
    if download_path is None:
        raise EmptyResultsError(
            "Export download failed — no file received. "
            "Check screenshots in .tmp/ for what happened in the browser."
        )

    df = _parse_export_file(download_path)

    # Belt-and-suspenders: filter AS > min_authority_score in Python
    if "Authority Score" in df.columns:
        before = len(df)
        df = df[df["Authority Score"] > min_authority_score].reset_index(drop=True)
        log.info("AS filter: %d → %d rows (AS > %d)", before, len(df), min_authority_score)

    if df.empty:
        raise EmptyResultsError(
            f"No referring domains found after filtering (AS > {min_authority_score}). "
            f"Try a lower threshold or a different competitor."
        )

    # Sort by Authority Score descending
    if "Authority Score" in df.columns:
        df = df.sort_values("Authority Score", ascending=False).reset_index(drop=True)

    log.info(
        "Backlink gap scrape complete: %d prospects for %s vs %s",
        len(df), my_domain, competitor_domain,
    )
    return df
