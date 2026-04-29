#!/usr/bin/env python3
"""
Email Scraper — Contact Email Finder
======================================
Visits each domain's contact/about pages and extracts email addresses
using regex over raw HTML. Sequential, polite (1.5s delay between domains).

Used by backlink_gap_workflow.py after the Semrush scrape to enrich the
output with contact emails for outreach. Domains where no email is found
are returned as "TODO" so they can be manually followed up.

Pages checked per domain (in order, stops at first hit):
    /contact → /contact-us → /about → /about-us → / (homepage)

Protocol: HTTPS first, HTTP fallback if HTTPS fails.

Anti-blocking:
    - 4 rotating User-Agent strings
    - 1.5s delay between domains (configurable)
    - 10s request timeout
    - Skips SSL errors gracefully

Dependencies: requests (already in requirements.txt)

Usage:
    from tools.email_scraper import find_emails_for_domains

    emails = find_emails_for_domains(["example.com", "rival.com"])
    # → ["info@example.com", "TODO"]
"""

import re
import time
import itertools
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

TODO_MARKER = "TODO"

PAGE_PATHS = ["/contact", "/contact-us", "/about", "/about-us", "/"]

REQUEST_TIMEOUT = 10  # seconds per request

# Addresses starting with these prefixes are not useful for outreach
BLOCKED_PREFIXES = ("noreply@", "no-reply@", "donotreply@", "do-not-reply@")

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

USER_AGENTS = itertools.cycle([
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
])


# ── Internal helpers ───────────────────────────────────────────────────────────

def _fetch(url: str) -> Optional[str]:
    """Fetch URL and return response text, or None on any error."""
    headers = {"User-Agent": next(USER_AGENTS)}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                            allow_redirects=True, verify=True)
        if resp.status_code == 200:
            return resp.text
    except requests.exceptions.SSLError:
        # Retry without SSL verification (some sites have bad certs)
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT,
                                allow_redirects=True, verify=False)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
    except Exception:
        pass
    return None


def _extract_email(html: str) -> Optional[str]:
    """Return the first useful email address found in raw HTML, or None."""
    matches = EMAIL_REGEX.findall(html)
    for email in matches:
        email_lower = email.lower()
        # Skip image filenames that look like emails (e.g. image@2x.png)
        if email_lower.endswith((".png", ".jpg", ".gif", ".svg", ".webp")):
            continue
        if any(email_lower.startswith(prefix) for prefix in BLOCKED_PREFIXES):
            continue
        return email
    return None


def _find_email(domain: str) -> Optional[str]:
    """
    Visit up to 5 pages on a domain and return the first contact email found.

    Tries HTTPS on each path first, then HTTP as a fallback for the homepage
    if all HTTPS attempts fail.

    Args:
        domain: Root domain without protocol (e.g. "example.com").

    Returns:
        Email address string, or None if not found.
    """
    for path in PAGE_PATHS:
        for protocol in ("https", "http"):
            url = f"{protocol}://{domain}{path}"
            html = _fetch(url)
            if html:
                email = _extract_email(html)
                if email:
                    return email
                break  # Got a valid response, no email on this page — try next path
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def find_emails_for_domains(
    domains: list[str],
    delay: float = 1.5,
) -> list[str]:
    """
    Find contact emails for a list of domains by scraping their pages.

    Visits each domain sequentially with a polite delay. Prints per-domain
    progress to stdout. Returns "TODO" for any domain where no email is found.

    Args:
        domains: List of root domains (e.g. ["example.com", "rival.com"]).
        delay:   Seconds to wait between domains. Default 1.5s.

    Returns:
        List of email strings or "TODO", parallel-indexed to input list.
        Example: ["info@example.com", "TODO", "hello@other.com"]
    """
    total = len(domains)
    results = []

    for i, domain in enumerate(domains, start=1):
        email = _find_email(domain)
        if email:
            print(f"  [{i:>{len(str(total))}}/{total}] {domain} → found: {email}")
            results.append(email)
        else:
            print(f"  [{i:>{len(str(total))}}/{total}] {domain} → TODO")
            results.append(TODO_MARKER)

        if i < total:
            time.sleep(delay)

    return results
