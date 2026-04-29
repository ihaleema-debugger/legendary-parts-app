"""Shopify Admin API client for localized product and blog URL lookup.

Queries the Shopify Admin GraphQL API (2024-01) + Shopify Markets to return
{lang_code: url} maps for products (by OEM number) and blog articles (by slug).

Requires in .env:
  SHOPIFY_ADMIN_API_TOKEN  — Admin API access token
  SHOPIFY_STORE_DOMAIN     — e.g. legendary-parts.myshopify.com (used for API calls)
  SHOPIFY_STORE_URL        — e.g. https://legendary-parts.com (used to construct localized URLs)
  SHOPIFY_OEM_METAFIELD    — metafield key storing OEM numbers, e.g. custom.oem_number
  SHOPIFY_BLOG_ID          — numeric ID of the blog containing articles (optional)
"""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

LANG_CODES = ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]
_API_VERSION = "2024-01"
_MAX_RETRIES = 3


class ShopifyConnectionError(RuntimeError):
    pass


class ProductNotFoundError(KeyError):
    pass


class BlogNotFoundError(KeyError):
    pass


class ShopifyMCPClient:
    """Thin client for Shopify Admin GraphQL API."""

    def __init__(self) -> None:
        token = os.environ.get("SHOPIFY_ADMIN_API_TOKEN", "")
        domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "")
        store_url = os.environ.get("SHOPIFY_STORE_URL", "")
        if not token:
            raise RuntimeError(
                "SHOPIFY_ADMIN_API_TOKEN is not set. "
                "Add it to .env (Shopify admin → Apps → [app name] → API credentials)."
            )
        if not domain:
            raise RuntimeError(
                "SHOPIFY_STORE_DOMAIN is not set. "
                "Add it to .env (e.g. legendary-parts.myshopify.com)."
            )
        if not store_url:
            raise RuntimeError(
                "SHOPIFY_STORE_URL is not set. "
                "Add it to .env (e.g. https://legendary-parts.com). "
                "Used to construct localized product/blog URLs."
            )
        self._token = token
        self._api_url = f"https://{domain}/admin/api/{_API_VERSION}/graphql.json"
        self._store_url = store_url.rstrip("/")
        self._oem_metafield = os.environ.get("SHOPIFY_OEM_METAFIELD", "custom.oem_number")
        self._blog_id = os.environ.get("SHOPIFY_BLOG_ID", "")

    # ── Public interface ──────────────────────────────────────────────────────

    def get_product_urls_by_oem(self, oem_number: str) -> dict[str, Optional[str]]:
        """Return {lang_code: localized_url} for all 8 languages.

        Raises ProductNotFoundError if OEM is not in the Shopify store.
        """
        ns, key = self._oem_metafield.split(".", 1)
        query = """
        query ProductByOEM($query: String!) {
          products(first: 1, query: $query) {
            nodes {
              id
              handle
            }
          }
        }
        """
        data = self._request(query, {"query": f"metafield:{ns}.{key}:{oem_number.lower()}"})
        nodes = data["data"]["products"]["nodes"]
        if not nodes:
            raise ProductNotFoundError(oem_number)
        handle = nodes[0]["handle"]
        return self._build_product_urls(handle)

    def get_blog_urls_by_slug(self, slug: str) -> dict[str, Optional[str]]:
        """Return {lang_code: localized_url} for all 8 languages.

        Raises BlogNotFoundError if slug is not found in the Shopify store.
        """
        blog_filter = f" AND blog_id:{self._blog_id}" if self._blog_id else ""
        query = """
        query ArticleByHandle($query: String!) {
          articles(first: 1, query: $query) {
            nodes {
              id
              handle
              blog {
                handle
              }
            }
          }
        }
        """
        data = self._request(query, {"query": f"handle:{slug}{blog_filter}"})
        nodes = data["data"]["articles"]["nodes"]
        if not nodes:
            raise BlogNotFoundError(slug)
        article = nodes[0]
        blog_handle = article["blog"]["handle"]
        article_handle = article["handle"]
        return self._build_blog_urls(blog_handle, article_handle)

    # ── URL construction (Shopify Markets subfolder pattern) ──────────────────

    def _build_product_urls(self, handle: str) -> dict[str, Optional[str]]:
        return {lang: f"{self._store_url}/{lang}/products/{handle}" for lang in LANG_CODES}

    def _build_blog_urls(self, blog_handle: str, article_handle: str) -> dict[str, Optional[str]]:
        return {
            lang: f"{self._store_url}/{lang}/blogs/{blog_handle}/{article_handle}"
            for lang in LANG_CODES
        }

    # ── HTTP transport with retry ─────────────────────────────────────────────

    def _request(self, query: str, variables: dict) -> dict:
        headers = {
            "X-Shopify-Access-Token": self._token,
            "Content-Type": "application/json",
        }
        payload = {"query": query, "variables": variables}
        last_exc: Exception = RuntimeError("no attempts made")

        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.post(self._api_url, json=payload, headers=headers, timeout=15)
                if resp.status_code == 401:
                    raise RuntimeError(
                        "Shopify Admin API token invalid or expired. "
                        "Regenerate the token in Shopify admin → Apps → [app name]."
                    )
                resp.raise_for_status()
                return resp.json()
            except RuntimeError:
                raise  # 401 — don't retry
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_exc = e
            except requests.exceptions.HTTPError as e:
                last_exc = e
                if e.response is not None and 400 <= e.response.status_code < 500:
                    raise  # non-401 client error — don't retry

            if attempt < _MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

        raise ShopifyConnectionError(
            "Shopify MCP unreachable. Check SHOPIFY_STORE_DOMAIN and network connection. "
            f"Last error: {last_exc}"
        )
