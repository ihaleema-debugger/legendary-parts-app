"""Register Shopify translations for locale variants of a published blog article.

Uses the Shopify Translations API (GraphQL Admin API) to attach translated
content to an existing source article without creating new articles.

Fields registered per locale:
    title, meta_title, body_html, summary_html, meta_description, handle
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PUBLISHERS_DIR = Path(__file__).resolve().parent
if str(PUBLISHERS_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHERS_DIR))

load_dotenv(PROJECT_ROOT / ".env")

from drive_fetcher import fetch_blog_files_by_id  # noqa: E402
from gdoc_reader import read_blog_gdoc      # noqa: E402
from shopify_auth import get_access_token   # noqa: E402

STORE   = os.getenv("SHOPIFY_STORE")
VERSION = os.getenv("SHOPIFY_API_VERSION", "2026-04")

_GQL_URL = f"https://{STORE}/admin/api/{VERSION}/graphql.json"

SOURCE_LOCALE = "fr"

# Drive filename suffix → Shopify shop locale code.
# Only locales that don't match 1:1 need an entry here.
LOCALE_OVERRIDES = {
    "pt": "pt-PT",
}


# ── GraphQL helpers ────────────────────────────────────────────────────────────

def _gql(query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    headers = {
        "X-Shopify-Access-Token": get_access_token(),
        "Content-Type": "application/json",
    }
    r = requests.post(_GQL_URL, headers=headers, json=payload)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data


def _fetch_digests(article_gid: str) -> dict[str, str]:
    """Return {key: digest} for every translatable field on the article."""
    query = """
    query getDigests($resourceId: ID!) {
      translatableResource(resourceId: $resourceId) {
        translatableContent { key digest }
      }
    }
    """
    data = _gql(query, {"resourceId": article_gid})
    resource = data["data"].get("translatableResource")
    if not resource:
        raise RuntimeError(
            f"No translatableResource found for {article_gid}. "
            "Verify the article ID and that the token has read_translations scope."
        )
    return {item["key"]: item["digest"] for item in resource["translatableContent"]}


# ── Per-locale registration ────────────────────────────────────────────────────

def _build_translations(locale: str, doc: dict, digests: dict[str, str]) -> list[dict]:
    """Map parsed doc fields to Shopify TranslationInput objects."""
    shop_locale = LOCALE_OVERRIDES.get(locale, locale)
    meta_title = doc.get("meta_title") or doc["title"]

    # Shopify key → value from gdoc_reader output
    field_map = [
        ("title",            doc["title"]),
        ("meta_title",       meta_title),
        ("body_html",        doc["body_html"]),
        ("summary_html",     doc["summary"]),
        ("meta_description", doc["meta_description"]),
        ("handle",           doc["handle"]),
    ]

    translations = []
    for key, value in field_map:
        if not value:
            continue
        if key not in digests:
            continue
        translations.append({
            "locale": shop_locale,
            "key": key,
            "value": value,
            "translatableContentDigest": digests[key],
        })
    return translations


def _register_locale(
    article_gid: str,
    locale: str,
    doc: dict,
    digests: dict[str, str],
) -> dict:
    """Submit translationsRegister for one locale. Returns a result dict."""
    shop_locale = LOCALE_OVERRIDES.get(locale, locale)
    print(f"    locale: {locale!r} → shop locale: {shop_locale!r}")
    translations = _build_translations(locale, doc, digests)

    if not translations:
        return {
            "status": "skipped",
            "reason": "no translatable fields with values",
            "fields_registered": [],
            "errors": [],
        }

    mutation = """
    mutation registerTranslations($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        userErrors { field message code }
        translations { key }
      }
    }
    """
    data = _gql(mutation, {"resourceId": article_gid, "translations": translations})
    result = data["data"]["translationsRegister"]

    if result["userErrors"]:
        return {
            "status": "failed",
            "fields_registered": [],
            "errors": [
                f"{e.get('field', '?')}: {e['message']}" for e in result["userErrors"]
            ],
        }

    return {
        "status": "ok",
        "fields_registered": [t["key"] for t in result["translations"]],
        "errors": [],
    }


# ── Prose word count ───────────────────────────────────────────────────────────

def prose_word_count(body_html: str) -> int:
    """Strip HTML tags and count whitespace-separated tokens."""
    text = re.sub(r"<[^>]+>", " ", body_html)
    return len(text.split())


# ── Public entry point ─────────────────────────────────────────────────────────

def publish_translations(
    source_article_id: str | int,
    blog_stem: str,
    target_locales: list[str] | None = None,
) -> dict:
    """Register Shopify translations for all locale variants of a blog post.

    Args:
        source_article_id: Shopify numeric article ID of the source (FR) article.
        blog_stem: Drive filename prefix, e.g.
            "harley-davidson-vrsc-v-rod-complete-buyers-and-owners-guide"
        target_locales: If provided, only process these locales (never 'fr').

    Returns:
        Dict keyed by locale:
            {locale: {status, fields_registered, errors, word_count}}
    """
    folder_id = os.getenv("TRANSLATIONS_FOLDER_ID", "")
    if not folder_id:
        raise RuntimeError(
            "TRANSLATIONS_FOLDER_ID is not set. Add it to .env to specify "
            "the Drive folder containing translated docs."
        )

    article_gid = f"gid://shopify/Article/{source_article_id}"

    print(f"→ Fetching translatable digests for article {source_article_id}...")
    digests = _fetch_digests(article_gid)
    print(f"  Translatable keys: {sorted(digests)}")

    print(f"\n→ Listing Drive files for {blog_stem!r} in folder {folder_id!r}...")
    all_files = fetch_blog_files_by_id(blog_stem, folder_id)
    print(f"  Found {len(all_files)} file(s): {[f['locale'] for f in all_files]}")

    to_process = [
        f for f in all_files
        if f["locale"] != SOURCE_LOCALE
        and (target_locales is None or f["locale"] in target_locales)
    ]
    print(f"  Processing {len(to_process)} translation locale(s): "
          f"{[f['locale'] for f in to_process]}\n")

    results: dict[str, dict] = {}

    for f in to_process:
        locale = f["locale"]
        print(f"  [{locale}] reading {f['name']!r}...", end=" ", flush=True)
        try:
            doc = read_blog_gdoc(f["file_id"])
            wc = prose_word_count(doc["body_html"])
            print(f"{wc} words | {doc['title'][:55]!r}")

            result = _register_locale(article_gid, locale, doc, digests)
            result["word_count"] = wc

            if result["status"] == "ok":
                print(f"    ✓ registered: {result['fields_registered']}")
            else:
                print(f"    ✗ {result['status']}: "
                      f"{result.get('reason') or '; '.join(result.get('errors', []))}")

        except Exception as exc:
            print("ERROR")
            results[locale] = {
                "status": "error",
                "fields_registered": [],
                "errors": [str(exc)],
                "word_count": 0,
            }
            continue

        results[locale] = result

    return results
