"""Unit tests for app/services/url_localizer.py"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from app.services.url_localizer import localize_urls, _extract_oem, _extract_blog_slug
from app.services.shopify_mcp import ProductNotFoundError, BlogNotFoundError

LANG_CODES = ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]


# ── OEM extraction unit tests ─────────────────────────────────────────────────

class TestExtractOem:
    def test_explicit_oem_prefix(self):
        url = "https://www.legendary-parts.com/en/products/engine-mount-oem-41699-04"
        assert _extract_oem(url) == "41699-04"

    def test_oem_at_end_of_slug(self):
        url = "https://www.legendary-parts.com/en/products/belt-guard-60367-04a"
        result = _extract_oem(url)
        assert result == "60367-04a"

    def test_not_a_product_url(self):
        url = "https://www.legendary-parts.com/en/blogs/conseils/harley-batteries"
        assert _extract_oem(url) is None

    def test_external_url_returns_none(self):
        url = "https://www.harley-davidson.com/en/products/some-part"
        assert _extract_oem(url) is None


class TestExtractBlogSlug:
    def test_standard_blog_url(self):
        url = "https://www.legendary-parts.com/en/blogs/conseils/harley-davidson-batteries"
        assert _extract_blog_slug(url) == "harley-davidson-batteries"

    def test_not_a_blog_url(self):
        url = "https://www.legendary-parts.com/en/products/some-part-oem-123"
        assert _extract_blog_slug(url) is None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client(product_map=None, blog_map=None, product_exc=None, blog_exc=None):
    """Build a ShopifyMCPClient mock."""
    client = MagicMock()
    if product_exc:
        client.get_product_urls_by_oem.side_effect = product_exc
    elif product_map is not None:
        client.get_product_urls_by_oem.return_value = product_map
    if blog_exc:
        client.get_blog_urls_by_slug.side_effect = blog_exc
    elif blog_map is not None:
        client.get_blog_urls_by_slug.return_value = blog_map
    return client


def _all_lang_urls(base_url: str) -> dict:
    return {lang: f"{base_url}/{lang}" for lang in LANG_CODES}


# ── Three-branch localization tests ──────────────────────────────────────────

class TestProductLinkFound:
    """Branch 1: product found in Shopify AND target-lang URL present."""

    def test_replaces_link_and_appends_en_anchor(self):
        client = _make_client(
            product_map=_all_lang_urls("https://www.legendary-parts.com/products/belt-guard-60367-04a")
        )
        body = "[Belt Guard](https://www.legendary-parts.com/en/products/belt-guard-60367-04a)"
        result, flags = localize_urls(body, "fr", client)

        assert "legendary-parts.com/products/belt-guard-60367-04a/fr" in result
        assert "[EN: Belt Guard]" in result
        assert not flags

    def test_all_eight_langs_resolve(self):
        for lang in LANG_CODES:
            client = _make_client(
                product_map=_all_lang_urls("https://www.legendary-parts.com/products/p")
            )
            body = "[p](https://www.legendary-parts.com/en/products/p-60367-04a)"
            result, flags = localize_urls(body, lang, client)
            assert f"/products/p/{lang}" in result
            assert not flags


class TestProductLinkUrlEmpty:
    """Branch 2: product found but target-lang URL is None."""

    def test_removes_hyperlink_keeps_anchor_and_review_flag(self):
        null_map = {lang: None for lang in LANG_CODES}
        client = _make_client(product_map=null_map)
        body = "[Belt Guard](https://www.legendary-parts.com/en/products/belt-guard-60367-04a)"
        result, flags = localize_urls(body, "de", client)

        assert "Belt Guard" in result
        assert "[REVIEW:" in result
        assert len(flags) == 1
        assert flags[0]["severity"] == "warning"


class TestProductLinkNotInShopify:
    """Branch 3: OEM not found in Shopify at all."""

    def test_removes_hyperlink_and_flags_not_in_shopify(self):
        client = _make_client(product_exc=ProductNotFoundError("60367-04a"))
        body = "[Belt Guard](https://www.legendary-parts.com/en/products/belt-guard-60367-04a)"
        result, flags = localize_urls(body, "fr", client)

        assert "not found in Shopify" in result
        assert "[REVIEW:" in result
        assert len(flags) == 1

    def test_no_hyperlink_in_output(self):
        client = _make_client(product_exc=ProductNotFoundError("oem"))
        body = "[Belt Guard](https://www.legendary-parts.com/en/products/belt-guard-60367-04a)"
        result, _ = localize_urls(body, "fr", client)
        assert "](http" not in result


class TestBlogLinkFound:
    """Branch 1 for blog links."""

    def test_replaces_blog_link_and_appends_en_anchor(self):
        client = _make_client(
            blog_map=_all_lang_urls("https://www.legendary-parts.com/blogs/guide/harley-batteries")
        )
        body = "[Battery Guide](https://www.legendary-parts.com/en/blogs/guide/harley-batteries)"
        result, flags = localize_urls(body, "fr", client)

        assert "legendary-parts.com/blogs/guide/harley-batteries/fr" in result
        assert "[EN: Battery Guide]" in result
        assert not flags


class TestBlogLinkUrlEmpty:
    """Branch 2 for blog links: found but target-lang URL is None."""

    def test_removes_blog_hyperlink_and_flags(self):
        null_map = {lang: None for lang in LANG_CODES}
        client = _make_client(blog_map=null_map)
        body = "[Guide](https://www.legendary-parts.com/en/blogs/guide/harley-batteries)"
        result, flags = localize_urls(body, "de", client)

        assert "[REVIEW:" in result
        assert "Guide" in result
        assert len(flags) == 1


class TestBlogLinkNotInShopify:
    """Branch 3 for blog links: slug not found in Shopify."""

    def test_removes_blog_hyperlink_and_flags_not_in_shopify(self):
        client = _make_client(blog_exc=BlogNotFoundError("harley-batteries"))
        body = "[Guide](https://www.legendary-parts.com/en/blogs/guide/harley-batteries)"
        result, flags = localize_urls(body, "de", client)

        assert "[REVIEW:" in result
        assert "harley-batteries" in result
        assert len(flags) == 1


class TestExternalLinkPassthrough:
    """External (non-legendary-parts.com) links pass through unchanged."""

    def test_external_link_unchanged(self):
        client = MagicMock()
        body = "[Harley site](https://www.harley-davidson.com/en/bikes)"
        result, flags = localize_urls(body, "fr", client)

        assert result == body
        assert not flags
        client.get_product_urls_by_oem.assert_not_called()
        client.get_blog_urls_by_slug.assert_not_called()

    def test_mixed_internal_external(self):
        client = _make_client(
            product_map=_all_lang_urls("https://www.legendary-parts.com/products/x-60367-04a")
        )
        body = (
            "[External](https://www.harley-davidson.com) and "
            "[Belt Guard](https://www.legendary-parts.com/en/products/belt-guard-60367-04a)"
        )
        result, flags = localize_urls(body, "fr", client)

        assert "harley-davidson.com" in result
        assert "legendary-parts.com/products/x-60367-04a/fr" in result
        assert not flags
