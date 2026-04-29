#!/usr/bin/env python3
"""
Semrush Keyword Gap Scraper
============================
Playwright-based browser automation for the Semrush Keyword Gap tool.

Handles:
  - Session persistence via semrush_session.json (skips login when valid)
  - Full login with credential caching
  - URL-based navigation to the Keyword Gap tool
  - Full pagination scraping across all result pages
  - Column normalisation for Semrush's varying header names
  - Retry logic with exponential backoff on flaky selectors

Exports:
    run(competitor_domain, location, headless) -> pd.DataFrame
    LoginError
    EmptyResultsError

Usage:
    from tools.semrush_scraper import run, LoginError, EmptyResultsError
    df = run("autozone.com", "United States", headless=True)
"""

import json
import logging
import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

load_dotenv()

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

SESSION_FILE = "semrush_session.json"
ROOT_DOMAIN  = "legendary-parts.com"
LOGIN_URL    = "https://www.semrush.com/login/"
GAP_BASE_URL = "https://www.semrush.com/analytics/keywordgap/"

# Semrush database codes per market
LOCATION_TO_DB: dict[str, str] = {
    "United States": "us",
    "United Kingdom": "uk",
    "France":         "fr",
    "Germany":        "de",
    "Spain":          "es",
    "Italy":          "it",
}

PAGE_TIMEOUT    = 60_000   # ms — full page load
ELEMENT_TIMEOUT = 30_000   # ms — waiting for individual elements
NAV_TIMEOUT     = 90_000   # ms — Keyword Gap results can be slow


# ── Custom Exceptions ──────────────────────────────────────────────────────────

class LoginError(Exception):
    """Raised when login fails or session expires and cannot be renewed."""


class EmptyResultsError(Exception):
    """Raised when no keyword gap results are returned for the given domains."""


# ── Retry Helper ───────────────────────────────────────────────────────────────

def _retry(fn, max_attempts: int = 3, base_delay: float = 2.0):
    """
    Call fn() with exponential backoff on PlaywrightTimeout.

    Args:
        fn:           Zero-argument callable to attempt.
        max_attempts: Maximum number of tries before re-raising.
        base_delay:   Seconds for first retry wait; doubles each attempt.

    Returns:
        The return value of fn() on success.

    Raises:
        PlaywrightTimeout: If all attempts fail.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except PlaywrightTimeout:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            log.warning("Attempt %d/%d failed — retrying in %.1fs", attempt + 1, max_attempts, delay)
            time.sleep(delay)


# ── Session Management ─────────────────────────────────────────────────────────

def _save_session(context, session_file: str = SESSION_FILE) -> None:
    """
    Persist browser cookies to a JSON file for reuse on future runs.

    Args:
        context:      Playwright BrowserContext with active session cookies.
        session_file: Path to the JSON file where cookies will be written.
    """
    cookies = context.cookies()
    with open(session_file, "w") as fh:
        json.dump({"cookies": cookies}, fh, indent=2)
    log.info("Session saved → %s (%d cookies)", session_file, len(cookies))


def _load_session(context, session_file: str = SESSION_FILE) -> bool:
    """
    Load cookies from a previously saved session file into the browser context.

    Args:
        context:      Playwright BrowserContext to inject cookies into.
        session_file: Path to the JSON session file.

    Returns:
        True if the file exists and cookies were loaded; False otherwise.
    """
    if not Path(session_file).exists():
        log.info("No session file found at %s — will perform full login.", session_file)
        return False
    with open(session_file) as fh:
        data = json.load(fh)
    context.add_cookies(data.get("cookies", []))
    log.info("Session loaded from %s (%d cookies)", session_file, len(data.get("cookies", [])))
    return True


# ── Authentication ─────────────────────────────────────────────────────────────

def _is_logged_in(page) -> bool:
    """
    Check whether the current browser page reflects a logged-in Semrush session.

    Primary check: if the current URL contains 'login' or 'signin', the session
    has expired and we've been redirected to the auth wall.

    Secondary check: polls for known logged-in UI elements (user menu / avatar).
    These selectors are less reliable across Semrush UI updates, so we give them
    only 15 seconds total via a fast poll loop.

    Args:
        page: Playwright Page object (after navigating to a Semrush page).

    Returns:
        True if the session appears valid; False if redirected to login.
    """
    # URL-based check — most reliable signal
    current_url = page.url
    if "login" in current_url or "signin" in current_url:
        log.info("Session invalid — redirected to login page: %s", current_url)
        return False

    # Wait briefly for the page to settle, then check for any login redirect
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    # Re-check URL after networkidle (SPA may redirect after JS executes)
    current_url = page.url
    if "login" in current_url or "signin" in current_url:
        log.info("Session invalid — redirected to login after page load: %s", current_url)
        return False

    LOGGED_IN_SELECTORS = [
        "[data-test='user-menu']",
        "[data-test='header-user-menu']",
        ".sem-avatar",
        "[class*='userMenu']",
        "[class*='UserMenu']",
        "[aria-label*='account']",
        "[aria-label*='Account']",
        # Generic: any element containing the user's email domain or profile link
        "a[href*='/profile']",
        "a[href*='/account']",
    ]
    # Fast poll: scan all selectors every 2s for up to 15s
    deadline = time.time() + 15
    while time.time() < deadline:
        for sel in LOGGED_IN_SELECTORS:
            if page.query_selector(sel):
                log.debug("Logged-in indicator found: %s", sel)
                return True
        time.sleep(2)

    # If we didn't get redirected to login and the page loaded, assume valid
    log.info("No explicit logged-in indicator found, but not on login page — assuming valid session.")
    return True


def _perform_login(page, email: str, password: str) -> None:
    """
    Navigate to the Semrush login page and authenticate with credentials.

    Fills the email and password fields, submits the form, and waits for the
    URL to change away from the login page — indicating a successful redirect.

    Args:
        page:     Playwright Page object.
        email:    Semrush account email (from SEMRUSH_EMAIL in .env).
        password: Semrush account password (from SEMRUSH_PASSWORD in .env).

    Raises:
        LoginError: If the browser is still on the login page after submit,
                    indicating credential rejection or an unexpected redirect.
    """
    log.info("Navigating to login page: %s", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    # Wait for JS to render the login form
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except PlaywrightTimeout:
        log.warning("Login page did not reach networkidle — proceeding anyway.")

    # Debug screenshot to capture what the login page looks like
    os.makedirs(".tmp", exist_ok=True)
    page.screenshot(path=".tmp/debug_login_page.png")
    log.info("Login page screenshot → .tmp/debug_login_page.png  (title: %s)", page.title())

    # Email — wait up to 15s for the JS-rendered input
    for email_sel in ['input[name="email"]', 'input[type="email"]', '#email',
                      'input[autocomplete="email"]', 'input[autocomplete="username"]']:
        try:
            page.wait_for_selector(email_sel, timeout=15_000)
            page.fill(email_sel, email)
            log.debug("Email filled via selector: %s", email_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError(
            "Could not find email input field on Semrush login page. "
            "Check .tmp/debug_login_page.png to see what loaded."
        )

    # Password — 10s wait (should be present once email field loaded)
    for pwd_sel in ['input[name="password"]', 'input[type="password"]', '#password',
                    'input[autocomplete="current-password"]']:
        try:
            page.wait_for_selector(pwd_sel, timeout=10_000)
            page.fill(pwd_sel, password)
            log.debug("Password filled via selector: %s", pwd_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError("Could not find password input field on Semrush login page.")

    # Submit
    for submit_sel in ['button[type="submit"]', '[data-test="login-button"]',
                       'button:has-text("Log in")', 'button:has-text("Sign in")',
                       'button:has-text("Log In")', 'button:has-text("Continue")']:
        try:
            page.wait_for_selector(submit_sel, timeout=5_000)
            page.click(submit_sel)
            log.debug("Submitted via selector: %s", submit_sel)
            break
        except PlaywrightTimeout:
            continue
    else:
        raise LoginError("Could not find login submit button on Semrush login page.")

    # Wait for redirect away from login URL
    try:
        page.wait_for_url(
            lambda url: "login" not in url and "signin" not in url,
            timeout=30_000,
        )
    except PlaywrightTimeout:
        # Check if there's an error message on the page
        error_text = page.locator('[class*="error"], [class*="Error"], [role="alert"]').all_inner_texts()
        hint = " | ".join(error_text) if error_text else "No error message found on page."
        raise LoginError(
            f"Login failed — still on login page after submit. "
            f"Check SEMRUSH_EMAIL and SEMRUSH_PASSWORD in .env. Page hint: {hint}"
        )

    log.info("Login successful — redirected to: %s", page.url)


def _ensure_authenticated(
    page,
    context,
    email: str,
    password: str,
    session_file: str = SESSION_FILE,
) -> None:
    """
    Ensure the browser has a valid authenticated Semrush session.

    Strategy:
        1. Attempt to load a cached session from session_file.
        2. If loaded, navigate to semrush.com and verify the session is still active.
        3. If the session is expired or missing, perform a full login and save the
           new session to session_file for future reuse.

    Args:
        page:         Playwright Page object.
        context:      Playwright BrowserContext (used for cookie management).
        email:        Semrush account email.
        password:     Semrush account password.
        session_file: Path to the session cache JSON file.

    Raises:
        LoginError: Propagated from _perform_login() on credential failure.
    """
    session_loaded = _load_session(context, session_file)

    if session_loaded:
        log.info("Verifying cached session...")
        page.goto("https://www.semrush.com/", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        if _is_logged_in(page):
            log.info("Cached session is valid — skipping login.")
            return
        log.info("Cached session has expired — performing fresh login.")

    _perform_login(page, email, password)
    _save_session(context, session_file)


# ── Keyword Gap Navigation ─────────────────────────────────────────────────────

def _poll_for_rows(page, total_wait: int = 90) -> bool:
    """
    Poll every 2 seconds until data rows appear in the Keyword Gap table.

    Uses page.evaluate() to run JavaScript directly — more reliable than CSS
    selectors for Semrush's React/div-based virtual table which may not use
    standard <table> HTML elements.

    Returns True as soon as at least one keyword data row is detected.
    Returns False if the budget expires with no rows found.

    Args:
        page:       Playwright Page object.
        total_wait: Total seconds to wait.

    Returns:
        True if rows were found; False if budget expired.
    """
    deadline = time.time() + total_wait
    while time.time() < deadline:
        try:
            row_count = page.evaluate("""
                () => {
                    // Standard HTML table rows
                    const tableRows = document.querySelectorAll('tbody tr td');
                    if (tableRows.length > 0) return tableRows.length;

                    // ARIA-based rows (React virtual tables)
                    const ariaRows = document.querySelectorAll('[role="row"]');
                    if (ariaRows.length > 1) return ariaRows.length - 1; // exclude header

                    // Semrush-specific: rows with data attributes
                    const dataRows = document.querySelectorAll('[data-test*="row"], [class*="tableRow"], [class*="TableRow"]');
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
    Click the 'Missing' tab on the Keyword Gap results page.

    The 'Missing' tab shows keywords the competitor ranks for that legendary-parts.com
    does not — the core of a keyword gap analysis. Clicking it changes the results
    from the default 'Shared' or 'All' view to the gap view.

    Args:
        page: Playwright Page object on a loaded Keyword Gap results page.

    Returns:
        True if the tab was found and clicked; False if not found.
    """
    MISSING_SELECTORS = [
        ':has-text("Missing")',
        'button:has-text("Missing")',
        'a:has-text("Missing")',
        '[role="tab"]:has-text("Missing")',
        '[class*="tab"]:has-text("Missing")',
    ]
    for sel in MISSING_SELECTORS:
        try:
            tab = page.locator(sel).first
            if tab.count() > 0:
                tab.click()
                log.info("'Missing' tab clicked via: %s", sel)
                time.sleep(2)  # Let the tab switch + data re-fetch
                return True
        except Exception:
            continue
    log.warning("'Missing' tab not found — proceeding with current view.")
    return False


def _click_compare(page) -> bool:
    """
    Find and click the Compare button on the Keyword Gap form.

    Args:
        page: Playwright Page object.

    Returns:
        True if the button was found and clicked; False otherwise.
    """
    COMPARE_SELECTORS = [
        'button:has-text("Compare")',
        'button:has-text("Analyze")',
        'button:has-text("Find keywords")',
        'button:has-text("compare")',
        '[data-test*="compare"]',
        '[data-test*="submit"]',
        'button[type="submit"]',
    ]
    for sel in COMPARE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_enabled():
                btn.click()
                log.info("Compare button clicked via: %s", sel)
                return True
        except Exception:
            continue
    return False


def _fill_gap_form(page, competitor_domain: str, db_code: str) -> None:
    """
    Fill the Keyword Gap UI form and click Compare to trigger the analysis.

    Semrush's Keyword Gap tool does not auto-run when navigated via URL params —
    it requires explicit form interaction. This function fills domain inputs and
    clicks Compare.

    Args:
        page:              Playwright Page object on the Keyword Gap base page.
        competitor_domain: Competitor domain string (e.g. "partseurope.eu").
        db_code:           Semrush database code (e.g. "fr") — used to verify or
                           change the country selection if needed.
    """
    log.info("Filling Keyword Gap form via UI...")

    # Use Playwright locator API (supports fill, which clears + types)
    INPUT_SELECTORS = [
        "input[placeholder*='domain']",
        "input[placeholder*='Domain']",
        "input[placeholder*='Enter']",
        "input[placeholder*='root']",
        "input[type='text']",
        "input[type='search']",
    ]

    inputs_found = None
    for sel in INPUT_SELECTORS:
        locs = page.locator(sel)
        count = locs.count()
        if count >= 1:
            log.debug("Found %d input(s) via selector: %s", count, sel)
            inputs_found = (locs, count)
            break

    if inputs_found:
        locs, count = inputs_found
        # Fill root domain in first input
        try:
            locs.nth(0).click()
            locs.nth(0).fill(ROOT_DOMAIN)
            log.info("Root domain filled: %s", ROOT_DOMAIN)
            time.sleep(0.5)
        except Exception as e:
            log.warning("Could not fill root domain: %s", e)

        # Fill competitor in second input (or first 'Add domain' slot)
        if count >= 2:
            try:
                locs.nth(1).click()
                locs.nth(1).fill(competitor_domain)
                log.info("Competitor domain filled: %s", competitor_domain)
                time.sleep(0.5)
            except Exception as e:
                log.warning("Could not fill competitor domain: %s", e)
        else:
            # Try clicking an "Add domain" button first
            for add_sel in ['button:has-text("Add domain")', 'a:has-text("Add domain")',
                            '[data-test*="add-domain"]', ':has-text("Add domain")']:
                try:
                    add_btn = page.locator(add_sel).first
                    if add_btn.count() > 0:
                        add_btn.click()
                        time.sleep(1)
                        # Re-query inputs
                        new_locs = page.locator(INPUT_SELECTORS[0])
                        if new_locs.count() >= 2:
                            new_locs.nth(1).fill(competitor_domain)
                            log.info("Competitor domain filled after Add domain click: %s", competitor_domain)
                        break
                except Exception:
                    continue
    else:
        log.warning("No domain input fields found on Keyword Gap page.")

    # Brief pause before clicking Compare
    time.sleep(1)

    if _click_compare(page):
        log.info("Compare clicked — waiting for results to load...")
    else:
        log.warning("Compare button not found — results may not load.")


def _navigate_to_gap_tool(page, competitor_domain: str, db_code: str) -> None:
    """
    Navigate to the Semrush Keyword Gap tool, fill the form, and wait for results.

    Strategy:
        1. Navigate to the Keyword Gap base URL with db param for country pre-selection.
        2. Wait for networkidle so the React form renders.
        3. Save a debug screenshot.
        4. Fill in domain inputs and click Compare via UI interaction.
        5. Wait for networkidle again (analysis fetch).
        6. Save a post-Compare screenshot.
        7. Poll for any table-like element (120s budget, 2s intervals).

    Args:
        page:              Playwright Page object (must be authenticated).
        competitor_domain: Competitor domain to analyse (e.g. "autozone.com").
        db_code:           Semrush database code for the target market (e.g. "fr").

    Raises:
        PlaywrightTimeout: If no table element is found within the polling budget.
    """
    # Navigate to base URL — db param may pre-select the country dropdown
    url = f"{GAP_BASE_URL}?db={db_code}"
    log.info("Navigating to Keyword Gap tool: %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)

    # Wait for React form to render
    log.info("Waiting for form to render...")
    try:
        page.wait_for_load_state("networkidle", timeout=25_000)
    except PlaywrightTimeout:
        log.warning("Network not fully idle after 25s — proceeding.")

    # Debug screenshot — before form fill
    os.makedirs(".tmp", exist_ok=True)
    page.screenshot(path=".tmp/debug_gap_form.png", full_page=False)
    log.info("Form screenshot → .tmp/debug_gap_form.png  (title: %s)", page.title())

    # Fill form and click Compare
    _fill_gap_form(page, competitor_domain, db_code)

    # Wait for the analysis API call to complete
    log.info("Waiting for analysis results to load...")
    try:
        page.wait_for_load_state("networkidle", timeout=45_000)
    except PlaywrightTimeout:
        log.warning("Network not idle after 45s — results may still be loading.")

    # Debug screenshot — after Compare click
    page.screenshot(path=".tmp/debug_gap_results.png", full_page=False)
    log.info("Results screenshot → .tmp/debug_gap_results.png  (url: %s)", page.url)

    # Click 'Missing' tab to get gap keywords (competitor ranks, we don't)
    _click_missing_tab(page)

    # Wait for data rows to appear — 120s total budget
    if _poll_for_rows(page, total_wait=120):
        page.screenshot(path=".tmp/debug_gap_data.png", full_page=False)
        log.info("Data loaded screenshot → .tmp/debug_gap_data.png")
        return

    raise PlaywrightTimeout(
        "No data rows appeared after form fill, Compare click, and Missing tab selection. "
        "Run with --headful to inspect the browser. "
        "Check .tmp/debug_gap_results.png and .tmp/debug_gap_data.png for clues."
    )


# ── Data Extraction ────────────────────────────────────────────────────────────

def _extract_table_page(page) -> list[dict]:
    """
    Extract visible data rows from the main Keyword Gap data table.

    Semrush renders multiple [role="grid"] components on the Keyword Gap page:
    - A compact "Top Opportunities" grid with only 2 columns (Keyword + Volume)
    - The main keyword details grid with 6-8 columns (Keyword, Volume, KD, CPC,
      domain positions, Intent)

    This function targets the main grid by selecting the one with the most
    column headers. Column names are read from the `name` attribute on
    [role="columnheader"] elements — more reliable than innerText which includes
    sort icons and other decorators.

    Note: Semrush uses virtual scrolling (only visible rows are in the DOM).
    Call this function repeatedly while scrolling to capture all rows — see
    _scrape_all_pages() for the full scroll loop.

    Args:
        page: Playwright Page object positioned on a loaded results page.

    Returns:
        List of dicts mapping column name → cell text for each visible data row.
        Empty list if no data rows are found.
    """
    try:
        result = page.evaluate("""
            () => {
                const out = { headers: [], rows: [], debug: {} };

                // Find all grid containers
                const grids = document.querySelectorAll('[role="grid"]');
                out.debug.gridCount = grids.length;

                // Pick the grid with the most column headers (= main data table)
                let mainGrid = null;
                let maxHeaderCount = 0;
                grids.forEach((grid, idx) => {
                    const hdrs = grid.querySelectorAll('[role="columnheader"]');
                    out.debug['grid' + idx + '_cols'] = hdrs.length;
                    if (hdrs.length > maxHeaderCount) {
                        maxHeaderCount = hdrs.length;
                        mainGrid = grid;
                    }
                });

                if (!mainGrid) return out;

                // Extract header names — prefer 'name' attribute over innerText
                const headerEls = mainGrid.querySelectorAll('[role="columnheader"]');
                out.headers = Array.from(headerEls).map(h => {
                    const name = h.getAttribute('name');
                    if (name) return name;
                    // Fall back to first line of innerText (strips sort icons)
                    return h.innerText.trim().split('\\n')[0].trim();
                });

                // Extract data rows (Body.Row elements only — skip header row)
                const bodyRows = mainGrid.querySelectorAll(
                    '[data-ui-name="Body.Row"], [role="row"]:not([aria-rowindex="1"])'
                );
                bodyRows.forEach(row => {
                    // Skip header-containing rows
                    if (row.querySelector('[role="columnheader"]')) return;

                    const cells = row.querySelectorAll('[role="gridcell"]');
                    if (cells.length === 0) return;

                    const cellTexts = Array.from(cells).map(c => {
                        // Use 'name' attr to help map if available, else innerText
                        return c.innerText.trim();
                    });

                    // Skip rows that appear completely empty
                    if (cellTexts.every(t => t === '')) return;

                    out.rows.push(cellTexts);
                });

                return out;
            }
        """)

        headers = result.get("headers", [])
        raw_rows = result.get("rows", [])
        debug = result.get("debug", {})

        log.debug("Grid debug: %s", debug)
        log.debug("Headers extracted: %s", headers)

        if not raw_rows:
            log.debug("No rows from main grid extraction.")
            return []

        # Normalise headers — fill blanks with positional fallbacks
        headers = [h if h else f"Col{i}" for i, h in enumerate(headers)]

        rows = []
        for row_vals in raw_rows:
            if any(v for v in row_vals):
                row_dict = {
                    headers[i]: row_vals[i]
                    for i in range(min(len(headers), len(row_vals)))
                }
                rows.append(row_dict)

        log.debug("Extracted %d rows from main grid.", len(rows))
        return rows

    except Exception as exc:
        log.warning("JS table extraction failed: %s", exc)
        return []


def _has_next_page(page) -> bool:
    """
    Determine whether a next-page pagination button exists and is enabled.

    Tries multiple selector patterns to accommodate Semrush's varying pagination
    markup across different tool pages.

    Args:
        page: Playwright Page object.

    Returns:
        True if a clickable next-page button is found and not disabled.
    """
    NEXT_SELECTORS = [
        "[data-test='pagination-next']",
        "button[aria-label*='Next']",
        "button[aria-label*='next']",
        "a[aria-label*='Next']",
        "[class*='pagination'] [class*='next']",
        "[class*='Pagination'] [class*='Next']",
        "button:has-text('›')",
        "button:has-text('>')",
    ]
    for sel in NEXT_SELECTORS:
        el = page.query_selector(sel)
        if el and el.is_enabled():
            return True
    return False


def _click_next_page(page) -> None:
    """
    Click the next-page pagination button and wait for new rows to load.

    Args:
        page: Playwright Page object.

    Raises:
        PlaywrightTimeout: If the next button cannot be clicked within ELEMENT_TIMEOUT.
    """
    NEXT_SELECTORS = [
        "[data-test='pagination-next']",
        "button[aria-label*='Next']",
        "button[aria-label*='next']",
        "a[aria-label*='Next']",
        "[class*='pagination'] [class*='next']",
        "[class*='Pagination'] [class*='Next']",
        "button:has-text('›')",
        "button:has-text('>')",
    ]
    for sel in NEXT_SELECTORS:
        el = page.query_selector(sel)
        if el and el.is_enabled():
            el.click()
            log.debug("Next page clicked via: %s", sel)
            # Brief pause to let table re-render
            time.sleep(1.5)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeout:
                pass  # networkidle can be slow on SPAs — table content is usually fine
            return
    raise PlaywrightTimeout("Could not find or click the next-page button.")


def _set_rows_per_page(page, target: int = 100) -> None:
    """
    Attempt to change the Keyword Gap table's rows-per-page to the maximum
    available, reducing the number of scroll/page cycles needed.

    Semrush typically offers 10 / 50 / 100 rows per page. Silently skips if the
    control isn't found or the target value isn't an option.

    Args:
        page:   Playwright Page object on the results page.
        target: Preferred row count per page (default 100).
    """
    try:
        for sel in [
            f'[aria-label*="rows"] option[value="{target}"]',
            f'select option[value="{target}"]',
        ]:
            el = page.query_selector(sel)
            if el:
                el.click()
                log.info("Rows per page set to %d", target)
                time.sleep(1.5)
                return
    except Exception:
        pass
    log.debug("Rows-per-page control not found — using default page size.")


def _scrape_all_pages(page) -> list[dict]:
    """
    Collect all keyword rows from the Keyword Gap results, handling both
    traditional pagination and virtual (infinite) scroll.

    Strategy:
        1. Attempt to set 100 rows per page to minimise page cycles.
        2. Extract visible rows from the current viewport.
        3. Check for a traditional next-page button; click it if found.
        4. If no button, scroll the page to trigger virtual-scroll row loading.
        5. Stop when no new unique rows are found after a scroll/page advance.

    De-duplication: rows are keyed by their Keyword cell value so duplicate
    entries from overlapping scroll windows are discarded.

    Args:
        page: Playwright Page object positioned on the loaded results page.

    Returns:
        Accumulated list of unique row dicts from all pages / scroll positions.
    """
    _set_rows_per_page(page, target=100)

    seen_keywords: set = set()
    all_rows: list[dict] = []
    scroll_attempt = 0
    MAX_SCROLL_ATTEMPTS = 30
    last_height = 0

    while scroll_attempt <= MAX_SCROLL_ATTEMPTS:
        log.info("Scraping scroll position %d...", scroll_attempt + 1)
        rows = _extract_table_page(page)

        new_count = 0
        for row in rows:
            key = row.get("keyword") or row.get("Keyword") or str(list(row.values())[:1])
            if key not in seen_keywords:
                seen_keywords.add(key)
                all_rows.append(row)
                new_count += 1

        log.info("  Position %d: %d visible rows, %d new (total unique: %d)",
                 scroll_attempt + 1, len(rows), new_count, len(all_rows))

        # Try traditional next-page button first
        if _has_next_page(page):
            try:
                _retry(lambda: _click_next_page(page), max_attempts=2, base_delay=2.0)
                scroll_attempt += 1
                continue
            except PlaywrightTimeout:
                log.info("Next-page click failed — switching to scroll mode.")

        # Virtual scroll: scroll down and check if the page grew
        current_height = page.evaluate("() => document.body.scrollHeight")
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        new_height = page.evaluate("() => document.body.scrollHeight")

        if new_height == last_height and new_count == 0:
            log.info("No new content after scroll — extraction complete.")
            break

        last_height = new_height
        scroll_attempt += 1

    if scroll_attempt >= MAX_SCROLL_ATTEMPTS:
        log.warning("Hit safety cap of %d scroll attempts.", MAX_SCROLL_ATTEMPTS)

    return all_rows


# ── Column Normalisation ───────────────────────────────────────────────────────

# Maps lowercase Semrush header variants → canonical column names.
# Includes both `name` attribute values (e.g. "kd_index", "traffic_volume") and
# display text variants (e.g. "Keyword Difficulty", "KD%").
COLUMN_ALIASES: dict[str, str] = {
    # Keyword — name attr and display text variants
    "keyword":                  "Keyword",
    "keywords":                 "Keyword",
    "search term":              "Keyword",
    # Volume — name attr variants Semrush uses
    "volume":                   "Volume",
    "traffic_volume":           "Volume",
    "search volume":            "Volume",
    "avg. monthly searches":    "Volume",
    "avg. searches":            "Volume",
    "monthly searches":         "Volume",
    # KD — name attr: "kd_index", "kd", "keyworddifficulty"; display: "KD%"
    "kd":                       "KD",
    "kd_index":                 "KD",
    "keyworddifficulty":        "KD",
    "kd%":                      "KD",
    "kd %":                     "KD",
    "keyword difficulty":       "KD",
    "keyword diff.":            "KD",
    "difficulty":               "KD",
    # CPC — name attr: "cpc"; display: "CPC (USD)", "CPC (EUR)"
    "cpc":                      "CPC",
    "cpc (usd)":                "CPC",
    "cpc (eur)":                "CPC",
    "cost per click":           "CPC",
    # Competitive Density
    "com.":                     "Com.",
    "competitive density":      "Com.",
    "com. density":             "Com.",
    "competition":              "Com.",
    # Intent — name attr: "intents" or "intent"; display: "Intent", "SI"
    "intent":                   "Intent",
    "intents":                  "Intent",
    "search intent":            "Intent",
    "si":                       "Intent",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename DataFrame columns from Semrush's raw header text to canonical names.

    Uses COLUMN_ALIASES for matching (case-insensitive, stripped). Unrecognised
    columns are left unchanged so no data is silently discarded.

    Args:
        df: Raw DataFrame as returned by pd.DataFrame(all_rows).

    Returns:
        DataFrame with canonical column names where aliases were matched.
    """
    rename_map = {}
    for col in df.columns:
        canonical = COLUMN_ALIASES.get(col.lower().strip())
        if canonical:
            rename_map[col] = canonical
    if rename_map:
        log.debug("Column rename map: %s", rename_map)
    return df.rename(columns=rename_map)


def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert Volume, KD, CPC, and Com. columns to numeric dtype.

    Strips commas (thousands separators), percent signs, currency symbols,
    and whitespace before conversion. Non-parseable values become NaN.

    Args:
        df: DataFrame with canonical column names.

    Returns:
        DataFrame with numeric columns coerced.
    """
    for col in ["Volume", "KD", "CPC", "Com."]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.replace("$", "", regex=False)
                .str.replace("€", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ── Main Entry Point ───────────────────────────────────────────────────────────

def run(competitor_domain: str, location: str, headless: bool = True) -> pd.DataFrame:
    """
    Execute the full Semrush Keyword Gap scrape pipeline.

    Steps:
        1. Load credentials from environment (SEMRUSH_EMAIL, SEMRUSH_PASSWORD).
        2. Launch Playwright Chromium browser.
        3. Restore cached session or perform full login.
        4. Navigate to the Keyword Gap tool with URL parameters.
        5. Scrape all paginated result pages.
        6. Normalise column names and coerce numeric types.
        7. Return clean DataFrame.

    Args:
        competitor_domain: Domain to compare against (e.g. "autozone.com").
        location:          Target market name — must be a key in LOCATION_TO_DB.
                           Valid values: United States, United Kingdom, France,
                           Germany, Spain, Italy.
        headless:          If False, shows the browser window. Useful for
                           debugging login issues or inspecting selectors.

    Returns:
        DataFrame with columns: Keyword, Volume, KD, and optionally CPC, Com., Intent.
        Sorted by Volume descending. All numeric columns are float/int dtype.

    Raises:
        LoginError:        If SEMRUSH_EMAIL/PASSWORD are missing, login fails,
                           or the session cannot be established.
        EmptyResultsError: If the Keyword Gap tool returns zero rows — typically
                           because the domains share no common keywords in the
                           selected location, or the table failed to load.
        ValueError:        If location is not a recognised market name.
    """
    email    = os.getenv("SEMRUSH_EMAIL", "").strip()
    password = os.getenv("SEMRUSH_PASSWORD", "").strip()

    if not email or not password:
        raise LoginError(
            "SEMRUSH_EMAIL and SEMRUSH_PASSWORD must be set in .env. "
            "Copy .env.example to .env and fill in your credentials."
        )

    db_code = LOCATION_TO_DB.get(location)
    if not db_code:
        raise ValueError(
            f"Unknown location '{location}'. "
            f"Valid options: {', '.join(LOCATION_TO_DB.keys())}"
        )

    log.info(
        "Starting Keyword Gap scrape: root=%s  competitor=%s  location=%s  db=%s  headless=%s",
        ROOT_DOMAIN, competitor_domain, location, db_code, headless,
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            _ensure_authenticated(page, context, email, password)
            _navigate_to_gap_tool(page, competitor_domain, db_code)
            raw_rows = _scrape_all_pages(page)
        except LoginError:
            raise
        except Exception as exc:
            log.exception("Error during scrape: %s", exc)
            raise
        finally:
            context.close()
            browser.close()

    if not raw_rows:
        raise EmptyResultsError(
            f"No keywords found for {ROOT_DOMAIN} vs {competitor_domain} in {location}. "
            "The domains may share no common keywords, the table may have failed to load, "
            "or the selectors may need updating. Re-run with --headful to inspect the browser."
        )

    df = pd.DataFrame(raw_rows)
    df = _normalize_columns(df)
    df = _coerce_numeric(df)

    # Drop rows with missing or blank keyword
    if "Keyword" in df.columns:
        df = df[df["Keyword"].notna() & (df["Keyword"].str.strip() != "")]

    log.info("Scrape complete: %d total keywords extracted.", len(df))
    return df.reset_index(drop=True)
