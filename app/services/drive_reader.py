"""Fetch and parse Google Doc content via the Drive API export endpoint."""
from __future__ import annotations

import re
from typing import Optional

from slugify import slugify as _slug_lib

from .drive_uploader import _get_service


def fetch_doc(doc_id: str) -> dict:
    """Export a Google Doc as HTML and return a structured dict.

    Title resolution order:
      1. Drive metadata filename (most reliable — always set by the user)
      2. HTML body parsing: <h1>, then <p class="title">, then <p class="subtitle">
      3. RuntimeError — never silently falls back to "Untitled"

    Returns:
        {
            "title": str,
            "slug": str,
            "meta_description": str | None,
            "body_html": str,
            "faq": list[{"question": str, "answer": str}],
            "raw_html": str,
        }

    Raises:
        RuntimeError: if the doc is not found, the service account lacks access,
                      or no title can be determined from any source.
    """
    service = _get_service()

    # Primary title source: Drive metadata filename
    try:
        file_metadata = service.files().get(
            fileId=doc_id,
            fields="name",
            supportsAllDrives=True,
        ).execute()
        drive_filename = file_metadata.get("name", "").strip()
    except Exception as e:
        raise RuntimeError(f"Could not fetch metadata for doc {doc_id!r}: {e}") from e

    # HTML export
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
    body_html = _extract_body(raw_html)

    # Secondary title source: HTML body parsing
    body_title = _extract_title_from_body(body_html)

    title = drive_filename or body_title
    if not title:
        raise RuntimeError(
            f"Could not extract title from doc {doc_id!r}. "
            "Drive filename was empty and no recognizable title element found in body HTML. "
            "Cannot proceed — translated doc filenames would be invalid."
        )

    meta = _extract_meta_description(raw_html)
    faq = _extract_faq(raw_html)

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

def _extract_title_from_body(html: str) -> Optional[str]:
    """Try to extract a title from the HTML body. Returns None if nothing found.

    Tries in order: <h1>, <p class="...title...">, <p class="...subtitle...">.
    """
    patterns = [
        r"<h1[^>]*>(.*?)</h1>",
        r'<p[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</p>',
        r'<p[^>]*class="[^"]*subtitle[^"]*"[^>]*>(.*?)</p>',
    ]
    for pattern in patterns:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            candidate = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if candidate:
                return candidate
    return None


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
    """Convert a title to a URL-safe slug.

    Apostrophes are stripped before slugifying so that "Buyer's" becomes
    "buyers" rather than "buyer-s". All other non-ASCII chars are
    transliterated. Consecutive hyphens are collapsed by python-slugify.
    """
    text = re.sub(r"'", "", text)
    return _slug_lib(text, max_length=80)
