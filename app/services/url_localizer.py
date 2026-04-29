"""Post-translation URL localization using Shopify Admin API queries.

Three-branch logic per internal legendary-parts.com link:
  Branch 1 — product/blog found AND target-lang URL is present → replace + [EN: anchor]
  Branch 2 — product/blog found BUT target-lang URL is None    → plain text + [REVIEW: ...]
  Branch 3 — product/blog not found in Shopify at all          → plain text + [REVIEW: ...]

External links pass through unchanged.
"""
from __future__ import annotations

import re
from typing import Optional

# Regex to find Markdown links: [anchor text](url)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\)]+)\)")

_LEGENDARY_HOST = "legendary-parts.com"


def localize_urls(
    body_markdown: str,
    lang_code: str,
    shopify_client,  # ShopifyMCPClient — not type-annotated to avoid circular import
) -> tuple[str, list[dict]]:
    """Localize internal legendary-parts.com links in Markdown body.

    Returns:
        (localized_body_markdown, inline_flags)

    inline_flags is a list of {type, severity, message, location} dicts for
    links that could not be fully resolved.
    """
    inline_flags: list[dict] = []
    result = _MD_LINK_RE.sub(
        lambda m: _process_link(m, lang_code, shopify_client, inline_flags),
        body_markdown,
    )
    return result, inline_flags


def _process_link(
    match: re.Match,
    lang_code: str,
    shopify_client,
    inline_flags: list,
) -> str:
    anchor = match.group(1)
    url = match.group(2)

    if _LEGENDARY_HOST not in url:
        return match.group(0)  # external — pass through

    oem = _extract_oem(url)
    if oem:
        return _resolve_product(url, anchor, oem, lang_code, shopify_client, inline_flags)

    slug = _extract_blog_slug(url)
    if slug:
        return _resolve_blog(url, anchor, slug, lang_code, shopify_client, inline_flags)

    # Internal link that's neither a product nor a blog — preserve as-is
    return match.group(0)


def _resolve_product(
    url: str,
    anchor: str,
    oem: str,
    lang_code: str,
    shopify_client,
    inline_flags: list,
) -> str:
    from .shopify_mcp import ProductNotFoundError
    try:
        lang_urls = shopify_client.get_product_urls_by_oem(oem)
    except ProductNotFoundError:
        msg = f"OEM {oem} not found in Shopify"
        inline_flags.append(_flag("link_unresolved", "warning", msg, f"[{anchor}]({url})"))
        return f"{anchor} [REVIEW: OEM {oem} not found in Shopify]"

    localized_url = lang_urls.get(lang_code)
    if localized_url:
        return f"[{anchor}]({localized_url}) [EN: {anchor}]"
    else:
        msg = f"OEM {oem} — no {lang_code.upper()} URL available; add manually if desired"
        inline_flags.append(_flag("link_unresolved", "warning", msg, f"[{anchor}]({url})"))
        return f"{anchor} [REVIEW: OEM {oem} — no {lang_code.upper()} URL available; add manually if desired]"


def _resolve_blog(
    url: str,
    anchor: str,
    slug: str,
    lang_code: str,
    shopify_client,
    inline_flags: list,
) -> str:
    from .shopify_mcp import BlogNotFoundError
    try:
        lang_urls = shopify_client.get_blog_urls_by_slug(slug)
    except BlogNotFoundError:
        msg = f"Blog slug '{slug}' not found in Shopify"
        inline_flags.append(_flag("link_unresolved", "warning", msg, f"[{anchor}]({url})"))
        return f"{anchor} [REVIEW: Blog slug '{slug}' not found in Shopify]"

    localized_url = lang_urls.get(lang_code)
    if localized_url:
        return f"[{anchor}]({localized_url}) [EN: {anchor}]"
    else:
        msg = f"Blog '{slug}' — no {lang_code.upper()} URL available; add manually if desired"
        inline_flags.append(_flag("link_unresolved", "warning", msg, f"[{anchor}]({url})"))
        return f"{anchor} [REVIEW: Blog '{slug}' — no {lang_code.upper()} URL available; add manually if desired]"


def _extract_oem(url: str) -> Optional[str]:
    """Extract OEM code from a legendary-parts.com product URL.

    Handles two patterns:
      /products/{desc}-oem-{code}   → returns code after 'oem-'
      /products/{desc}-{code}        → returns last dash-separated segment
    """
    if "/products/" not in url:
        return None
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    # Remove query string or fragment
    slug = re.split(r"[?#]", slug)[0]

    oem_prefix_match = re.search(r"-oem-([a-z0-9]+(?:-[a-z0-9]+)*)", slug)
    if oem_prefix_match:
        return oem_prefix_match.group(1)

    # Fall back: HD OEM numbers at end of slug follow pattern {digits}-{digits}{optional letter}
    # e.g. belt-guard-60367-04a → 60367-04a
    hd_pattern = re.search(r"(\d{3,}-\d{2,}[a-z]*)$", slug)
    if hd_pattern:
        return hd_pattern.group(1)

    # Last resort: all-digit trailing segment (e.g. foot-rest-support-50500289)
    parts = slug.split("-")
    if parts and re.match(r"^\d+$", parts[-1]):
        return parts[-1]

    return None


def _extract_blog_slug(url: str) -> Optional[str]:
    """Extract the blog article slug from a legendary-parts.com blog URL.

    Pattern: /blogs/{category}/{slug}  → returns {slug}
    """
    m = re.search(r"/blogs/[^/]+/([^/?#]+)", url)
    if m:
        return m.group(1).lower()
    return None


def _flag(flag_type: str, severity: str, message: str, location: str) -> dict:
    return {"type": flag_type, "severity": severity, "message": message, "location": location}
