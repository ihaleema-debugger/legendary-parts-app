"""One-shot script: publish the Legendary Parts press kit HTML to Shopify."""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── paths ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# Make shopify_auth importable without touching shopify_publisher.py
sys.path.insert(0, str(PROJECT_ROOT / "workflows" / "Publishers"))
from shopify_auth import get_access_token  # noqa: E402

# ── config ────────────────────────────────────────────────────────────────────

PRESS_HTML_PATH = "/Users/mac/Documents/SEO Agent Workflow/press_kit/legendary-parts-press_kit.html"

BLOG_ID     = 98568634712
API_VERSION = "2026-04"
STORE       = os.environ["SHOPIFY_STORE"]   # fail fast if missing
BASE        = f"https://{STORE}/admin/api/{API_VERSION}"


# ── helpers ───────────────────────────────────────────────────────────────────

def _headers():
    return {
        "X-Shopify-Access-Token": get_access_token(),
        "Content-Type": "application/json",
    }


def _check(response: requests.Response) -> None:
    if response.status_code >= 300:
        print(f"ERROR {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Read HTML — fail loud if missing or empty
    html_path = Path(PRESS_HTML_PATH)
    if not html_path.exists():
        print(f"ERROR: file not found: {html_path}", file=sys.stderr)
        sys.exit(1)
    body_html = html_path.read_text(encoding="utf-8").strip()
    if not body_html:
        print(f"ERROR: file is empty: {html_path}", file=sys.stderr)
        sys.exit(1)
    print(f"Read {len(body_html):,} bytes from {html_path.name}")

    # 2. Create article
    url = f"{BASE}/blogs/{BLOG_ID}/articles.json"
    payload = {
        "article": {
            "title": "Legendary Parts — Press & Media Kit",
            "author": "Haleema",
            "body_html": body_html,
            "published": True,
        }
    }
    print(f"POSTing to {url} ...")
    r = requests.post(url, headers=_headers(), json=payload, timeout=30)
    _check(r)

    article = r.json()["article"]
    article_id     = article["id"]
    article_handle = article["handle"]
    print(f"Article created — id={article_id}  handle={article_handle!r}")

    # 3. Fetch blog handle
    r2 = requests.get(f"{BASE}/blogs/{BLOG_ID}.json", headers=_headers(), timeout=30)
    _check(r2)
    blog_handle = r2.json()["blog"]["handle"]

    # 4. Print URLs
    public_url = f"https://{STORE}/blogs/{blog_handle}/{article_handle}"
    admin_url  = f"https://{STORE}/admin/articles/{article_id}"

    print()
    print(f"Public URL : {public_url}")
    print(f"Admin URL  : {admin_url}")
    print(f"Article ID : {article_id}")


if __name__ == "__main__":
    main()
