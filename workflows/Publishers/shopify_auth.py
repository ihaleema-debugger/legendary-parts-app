"""
Shopify OAuth token manager for the seo-forge translation pipeline.

Provides a single function, `get_access_token()`, that returns a currently-valid
Shopify Admin API access token. If the cached token is within the safety buffer
of its expiry, this module automatically exchanges the OAuth app's client_id
and client_secret for a fresh access token via Shopify's token endpoint
(client credentials grant), persists the new value to disk and to .env, and
returns it.

Usage in publisher scripts:

    from shopify_auth import get_access_token

    token = get_access_token()
    headers = {"X-Shopify-Access-Token": token, ...}

Environment variables (read from project-root .env):
    SHOPIFY_STORE              e.g. spcmotors.myshopify.com
    SHOPIFY_CLIENT_ID          OAuth app client id (stable)
    SHOPIFY_CLIENT_SECRET      OAuth app client secret (stable)
    SHOPIFY_ACCESS_TOKEN       Current access token (auto-updated; visible for debugging)

Cache file (auto-managed, gitignored):
    workflows/Publishers/.token_cache.json
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Module-level configuration
# ---------------------------------------------------------------------------

# Refresh the access token if it expires within this many seconds. 5 minutes
# gives plenty of headroom for a long-running publisher script to finish.
EXPIRY_SAFETY_BUFFER_SECONDS = 300

# Path resolution. This file lives at workflows/Publishers/shopify_auth.py,
# so the project root is two parents up.
_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
CACHE_PATH = _THIS_FILE.parent / ".token_cache.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_access_token(force_refresh: bool = False) -> str:
    """
    Return a currently-valid Shopify Admin API access token.

    If the cached token is still valid (more than EXPIRY_SAFETY_BUFFER_SECONDS
    remaining before expiry), return it as-is. Otherwise, exchange client_id
    and client_secret for a fresh access token, persist it, and return the
    new value.

    Set `force_refresh=True` to bypass the cache and refresh unconditionally.
    Useful when a Shopify API call returned 401 and you want to retry with a
    guaranteed-fresh token.
    """
    load_dotenv(ENV_PATH)

    if not force_refresh:
        cached = _read_cache()
        if cached and _is_still_valid(cached):
            return cached["access_token"]

    fresh = _fetch_new_access_token()
    _write_cache(fresh)
    _update_env_access_token(fresh["access_token"])
    return fresh["access_token"]


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def _read_cache() -> Optional[dict]:
    if not CACHE_PATH.exists():
        return None
    try:
        with CACHE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(token_data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": token_data["access_token"],
        "expires_at": token_data["expires_at"],
        "scope": token_data.get("scope", ""),
    }
    # Owner-only (0o600): token cache must not be world-readable
    fd = os.open(CACHE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _is_still_valid(cached: dict) -> bool:
    expires_at = cached.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        return False
    return (expires_at - time.time()) > EXPIRY_SAFETY_BUFFER_SECONDS


# ---------------------------------------------------------------------------
# Shopify client credentials grant
# ---------------------------------------------------------------------------

def _fetch_new_access_token() -> dict:
    """
    Call Shopify's OAuth token endpoint with grant_type=client_credentials.

    Per Shopify docs:
        POST https://{shop}.myshopify.com/admin/oauth/access_token
        Content-Type: application/x-www-form-urlencoded

    Returns a dict with `access_token`, `expires_at` (absolute unix timestamp),
    and `scope`. Raises RuntimeError with a useful message on failure.
    """
    store = os.getenv("SHOPIFY_STORE")
    client_id = os.getenv("SHOPIFY_CLIENT_ID")
    client_secret = os.getenv("SHOPIFY_CLIENT_SECRET")

    missing = [
        name for name, val in [
            ("SHOPIFY_STORE", store),
            ("SHOPIFY_CLIENT_ID", client_id),
            ("SHOPIFY_CLIENT_SECRET", client_secret),
        ] if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing required env vars for token refresh: {', '.join(missing)}. "
            f"Check {ENV_PATH}."
        )

    url = f"https://{store}/admin/oauth/access_token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }

    response = requests.post(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Shopify token request failed: HTTP {response.status_code}\n"
            f"Response body: {response.text}\n"
            f"This usually means the client_id/client_secret are wrong, the app "
            f"was uninstalled from the store, or the store domain is incorrect."
        )

    payload = response.json()
    if "access_token" not in payload or "expires_in" not in payload:
        raise RuntimeError(
            f"Shopify token response missing expected fields: {payload}"
        )

    return {
        "access_token": payload["access_token"],
        "expires_at": time.time() + payload["expires_in"],
        "scope": payload.get("scope", ""),
    }


# ---------------------------------------------------------------------------
# .env update (keep current access token visible for debugging)
# ---------------------------------------------------------------------------

def _update_env_access_token(new_token: str) -> None:
    """
    Rewrite the SHOPIFY_ACCESS_TOKEN line in .env so the current value is
    visible alongside the other config. The cache file remains the source
    of truth for the refresh logic; this is purely for human inspection.
    """
    if not ENV_PATH.exists():
        return

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        if line.startswith("SHOPIFY_ACCESS_TOKEN="):
            ending = "\n" if line.endswith("\n") else ""
            lines[i] = f"SHOPIFY_ACCESS_TOKEN={new_token}{ending}"
            found = True
            break

    if not found:
        # Append it if it wasn't there at all.
        if lines and not lines[-1].endswith("\n"):
            lines[-1] = lines[-1] + "\n"
        lines.append(f"SHOPIFY_ACCESS_TOKEN={new_token}\n")

    # Preserve owner-only permissions when rewriting .env
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(lines))


# ---------------------------------------------------------------------------
# CLI for manual testing: `python shopify_auth.py [--force]`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    try:
        token = get_access_token(force_refresh=force)
        cached = _read_cache() or {}
        expires_at = cached.get("expires_at", 0)
        remaining = int(expires_at - time.time()) if expires_at else 0
        print(f"✓ Access token: {token[:12]}...")
        print(f"  Scope: {cached.get('scope', '<unknown>')}")
        print(f"  Expires in: {remaining}s (~{remaining // 60} min)")
        print(f"  Cache file: {CACHE_PATH}")
    except RuntimeError as e:
        print(f"✗ Token request failed:\n{e}", file=sys.stderr)
        sys.exit(1)
