"""Parse a Google Doc blog post into structured data for Shopify publishing.

Reuses the service-account auth from app.services.drive_uploader._get_service.
"""
from __future__ import annotations

import html as _html_stdlib
import re
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.drive_uploader import _get_service  # noqa: E402


def read_blog_gdoc(file_id: str) -> dict:
    """Export a Google Doc and parse it into blog publishing fields.

    Returns:
        {
            "locale": str,           # from Drive filename suffix, e.g. "fr"
            "title": str,            # first H1 or H2 after META DESCRIPTION
            "body_html": str,        # cleaned HTML in justified wrapper div
            "summary": str,          # first non-empty paragraph after title
            "meta_description": str, # text from META DESCRIPTION: paragraph
            "handle": str,           # {filename-stem}-{locale} (single dashes)
            "tags": list[str],       # ["lang:{locale}"]
        }

    Warns (does not raise) when meta_description or title is absent.
    """
    service = _get_service()

    # Filename is the authoritative source for locale and handle
    try:
        meta = service.files().get(
            fileId=file_id,
            fields="name",
            supportsAllDrives=True,
        ).execute()
    except Exception as e:
        raise RuntimeError(
            f"Could not fetch Drive metadata for {file_id!r}: {e}"
        ) from e

    filename = meta.get("name", "").strip()
    locale = _extract_locale(filename)
    handle = _derive_handle(filename)

    # Export as HTML
    try:
        raw_bytes = service.files().export(
            fileId=file_id,
            mimeType="text/html",
        ).execute()
    except Exception as e:
        raise RuntimeError(
            f"Could not export doc {file_id!r} ({filename!r}): {e}"
        ) from e

    raw_html = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else raw_bytes

    body_match = re.search(r"<body[^>]*>(.*?)</body>", raw_html, re.DOTALL | re.IGNORECASE)
    inner = body_match.group(1).strip() if body_match else raw_html

    # Strip internal workflow metadata
    inner = _strip_review_flags(inner)

    # Extract fields and remove their source elements from body
    meta_description, inner = _extract_meta_description(inner)
    meta_title, inner = _extract_meta_title(inner)
    title, inner = _extract_title(inner)
    summary = _extract_summary(inner)

    # Clean Google's cosmetic inline styles, then wrap
    clean_body = _clean_html(inner)
    body_html = (
        '<div style="text-align: justify;" class="content">\n'
        + clean_body.strip()
        + "\n</div>"
    )

    if not title:
        title = filename.rsplit("--", 1)[0].strip() if "--" in filename else filename.strip()
        warnings.warn(
            f"[gdoc_reader] No H1/H2 title found in {filename!r} ({file_id}); "
            f"falling back to Drive filename: {title!r}"
        )
    if not meta_description:
        warnings.warn(
            f"[gdoc_reader] No META DESCRIPTION found in {filename!r} ({file_id})"
        )

    return {
        "locale": locale,
        "title": title,
        "meta_title": meta_title,  # "" if absent; caller defaults to title
        "body_html": body_html,
        "summary": summary,
        "meta_description": meta_description,
        "handle": handle,
        "tags": [f"lang:{locale}"] if locale else [],
    }


# ── private helpers ───────────────────────────────────────────────────────────

def _extract_locale(filename: str) -> str:
    """'blog-name--fr' → 'fr'"""
    if "--" not in filename:
        return ""
    return filename.rsplit("--", 1)[-1].strip().lower()


def _derive_handle(filename: str) -> str:
    """'blog-name--fr' → 'blog-name-fr'  (double dash → single dash)"""
    if "--" not in filename:
        return filename.lower()
    stem, locale = filename.rsplit("--", 1)
    return f"{stem}-{locale.strip().lower()}"


def _strip_review_flags(html: str) -> str:
    """Remove the 'Review Flags' section and everything that follows it.

    Tolerates any block-level tag (h1-h6, p, div) and styled spans inside
    that tag. Falls back to scanning for trailing [ERROR]/[WARNING]/[INFO]
    bullets if the heading itself can't be located.
    """
    # Primary pass: find "Review Flags" inside any block element,
    # then walk back to that block's opening tag and cut from there.
    flag_text = re.search(
        r"review\s*flags",
        html,
        re.IGNORECASE,
    )
    if flag_text:
        block_open = None
        for m in re.finditer(
            r"<(h[1-6]|p|div)\b[^>]*>",
            html[: flag_text.start()],
            re.IGNORECASE,
        ):
            block_open = m  # keep the last match before flag_text
        if block_open:
            return html[: block_open.start()].strip()
        return html[: flag_text.start()].strip()

    # Fallback pass: no "Review Flags" header, but stray flag bullets
    # may still be present. Cut from the first one.
    stray = re.search(
        r"<(li|p|div)\b[^>]*>[\s\S]{0,200}?\[\s*(ERROR|WARNING|INFO)\s*\]",
        html,
        re.IGNORECASE,
    )
    if stray:
        anchor = None
        for m in re.finditer(
            r"<(ul|ol|h[1-6]|p|div)\b[^>]*>",
            html[: stray.start()],
            re.IGNORECASE,
        ):
            anchor = m
        if anchor:
            return html[: anchor.start()].strip()
        return html[: stray.start()].strip()

    return html


def _extract_meta_description(html: str) -> tuple[str, str]:
    """Extract META DESCRIPTION text and remove its paragraph from html."""
    pattern = re.compile(
        r"<p[^>]*>.*?META\s*DESCRIPTION\s*:?\s*(.*?)</p>",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        return "", html
    raw = m.group(1)
    text = _html_stdlib.unescape(
        re.sub(r"<[^>]+>", "", raw)
    ).replace("\xa0", " ").strip()
    html_out = html[: m.start()] + html[m.end() :]
    return text, html_out.strip()


def _extract_meta_title(html: str) -> tuple[str, str]:
    """Extract META TITLE text and remove its paragraph from html."""
    pattern = re.compile(
        r"<p[^>]*>.*?META\s*TITLE\s*:?\s*(.*?)</p>",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        return "", html
    raw = m.group(1)
    text = _html_stdlib.unescape(
        re.sub(r"<[^>]+>", "", raw)
    ).replace("\xa0", " ").strip()
    html_out = html[: m.start()] + html[m.end() :]
    return text, html_out.strip()


def _extract_title(html: str) -> tuple[str, str]:
    """Extract first H1 or H2 as title and remove it from html."""
    pattern = re.compile(
        r"<(h[12])[^>]*>(.*?)</\1>",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        return "", html
    raw = m.group(2)
    title = _html_stdlib.unescape(
        re.sub(r"<[^>]+>", "", raw)
    ).replace("\xa0", " ").strip()
    html_out = html[: m.start()] + html[m.end() :]
    return title, html_out.strip()


def _extract_summary(html: str) -> str:
    """First non-empty paragraph text (plain text, entities decoded)."""
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE):
        text = _html_stdlib.unescape(
            re.sub(r"<[^>]+>", "", m.group(1))
        ).replace("\xa0", " ").strip()
        if text:
            return text
    return ""


def _clean_html(html: str) -> str:
    """Strip Google's cosmetic inline styling while preserving semantics.

    Order matters: convert bold/italic spans to strong/em BEFORE stripping
    all style attributes, otherwise the formatting information is lost.
    """
    # Promote bold spans to <strong>
    html = re.sub(
        r'<span[^>]*style="[^"]*font-weight\s*:\s*700[^"]*"[^>]*>(.*?)</span>',
        r"<strong>\1</strong>",
        html,
        flags=re.DOTALL,
    )
    # Promote italic spans to <em>
    html = re.sub(
        r'<span[^>]*style="[^"]*font-style\s*:\s*italic[^"]*"[^>]*>(.*?)</span>',
        r"<em>\1</em>",
        html,
        flags=re.DOTALL,
    )
    # Strip all inline style and Google anchor id attributes
    html = re.sub(r'\s+style="[^"]*"', "", html)
    html = re.sub(r'\s+id="[^"]*"', "", html)
    # Unwrap bare <span> elements (no remaining attributes)
    for _ in range(3):
        html = re.sub(r"<span>(.*?)</span>", r"\1", html, flags=re.DOTALL)
    # Remove empty paragraphs left behind by stripped elements
    html = re.sub(r"<p>\s*</p>", "", html)
    # Collapse runs of blank lines
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html
