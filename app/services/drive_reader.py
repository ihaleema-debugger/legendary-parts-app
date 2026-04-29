"""Fetch and parse Google Doc content via the Drive API export endpoint."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional

from .drive_uploader import _get_service


def fetch_doc(doc_id: str) -> dict:
    """Export a Google Doc as HTML and return a structured dict.

    Returns:
        {
            "title": str,
            "slug": str,
            "meta_description": "str | None",
            "body_html": str,
            "faq": list[{"question": str, "answer": str}],
            "raw_html": str,
        }

    Raises:
        RuntimeError: if the doc is not found or the service account lacks access.
    """
    service = _get_service()
    try:
        raw_bytes = (
            service.files()
            .export(fileId=doc_id, mimeType="text/html")
            .execute()
        )
    except Exception as e:
        raise RuntimeError(
            f"Could not export doc {doc_id!r} from Drive. "
            f"Check that the service account has at least viewer access. Error: {e}"
        ) from e

    raw_html: str = raw_bytes.decode("utf-8") if isinstance(raw_bytes, bytes) else raw_bytes

    title = _extract_title_from_html(raw_html)
    meta = _extract_meta_description(raw_html)
    faq = _extract_faq(raw_html)
    body_html = _extract_body(raw_html)

    return {
        "title": title,
        "slug": _slugify(title),
        "meta_description": meta,
        "body_html": body_html,
        "faq": faq,
        "raw_html": raw_html,
    }


def get_doc_title(doc_id: str) -> str:
    """Return only the document title (Drive metadata, no export needed)."""
    service = _get_service()
    try:
        meta = service.files().get(fileId=doc_id, fields="name", supportsAllDrives=True).execute()
    except Exception as e:
        raise RuntimeError(f"Could not fetch metadata for doc {doc_id!r}: {e}") from e
    return meta.get("name", "")


def get_doc_parent_folder(doc_id: str) -> Optional[str]:
    """Return the Drive folder ID of the doc's first parent, or None."""
    service = _get_service()
    try:
        meta = (
            service.files()
            .get(fileId=doc_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
    except Exception as e:
        raise RuntimeError(f"Could not fetch parents for doc {doc_id!r}: {e}") from e
    parents = meta.get("parents", [])
    return parents[0] if parents else None


# ── HTML parsing helpers ──────────────────────────────────────────────────────

def _extract_title_from_html(html: str) -> str:
    """Extract the first <h1> text, falling back to <title> tag."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return _strip_tags(m.group(1)).strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return _strip_tags(m.group(1)).strip()
    return "Untitled"


def _extract_meta_description(html: str) -> Optional[str]:
    """Extract the meta description line.

    Convention: a paragraph whose text content starts with 'Meta:' or
    'Meta Description:' (case-insensitive), as written by the seo-blog-writer skill.
    """
    pattern = re.compile(
        r"<p[^>]*>\s*(?:meta\s*description\s*:?\s*|meta\s*:?\s*)(.*?)</p>",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(html)
    if m:
        return _strip_tags(m.group(1)).strip()
    return None


def _extract_faq(html: str) -> list:
    """Extract FAQ items from an <h2>FAQ</h2> section if present."""
    faq_section = re.search(
        r"<h2[^>]*>.*?faq.*?</h2>(.*?)(?:<h2|</body|$)",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not faq_section:
        return []
    section_html = faq_section.group(1)
    questions = re.findall(r"<h3[^>]*>(.*?)</h3>", section_html, re.DOTALL | re.IGNORECASE)
    answers = re.findall(r"<p[^>]*>(.*?)</p>", section_html, re.DOTALL | re.IGNORECASE)
    faq = []
    for i, q in enumerate(questions):
        answer = answers[i] if i < len(answers) else ""
        faq.append(
            {"question": _strip_tags(q).strip(), "answer": _strip_tags(answer).strip()}
        )
    return faq


def _extract_body(html: str) -> str:
    """Return the <body> inner HTML, or full HTML if no body tag found."""
    m = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return html


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80].rstrip("-") or "untitled"
