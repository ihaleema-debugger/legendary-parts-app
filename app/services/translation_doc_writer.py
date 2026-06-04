"""Create a formatted Google Doc for a translated blog post.

Flow:
  1. Build an HTML representation of the translated content
  2. Upload to Drive as text/html (Google converts it to a Google Doc server-side)
  3. Use the Google Docs API to apply yellow background highlighting to [REVIEW:...] spans

The Google Docs API requires the 'documents' OAuth scope in addition to 'drive'.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaInMemoryUpload
from google.oauth2 import service_account

_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


def _get_drive_service():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=_DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_docs_service():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=_DRIVE_SCOPES)
    return build("docs", "v1", credentials=creds)


def save_translated_doc(
    translated: dict,
    validation_flags: list,
    inline_flags: list,
    source_doc_id: str,
    lang_code: str,
    original_slug: str,
    folder_id: str,
    model: str,
) -> dict:
    """Create a Google Doc for the translated blog and apply yellow highlights to flags.

    Returns:
        {"id": str, "name": str, "webViewLink": str}
    """
    doc_name = f"{original_slug}--{lang_code}"
    all_flags = list(validation_flags) + list(inline_flags)

    html_content = _build_html(translated, all_flags, source_doc_id, lang_code, model)

    drive = _get_drive_service()
    file_metadata: dict = {
        "name": doc_name,
        "mimeType": "application/vnd.google-apps.document",
    }
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaInMemoryUpload(
        html_content.encode("utf-8"),
        mimetype="text/html",
        resumable=False,
    )

    try:
        file = (
            drive.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(f"Drive upload failed for {doc_name!r}: {e}") from e

    doc_id = file["id"]

    # Apply yellow highlighting to [REVIEW:...] spans via Docs API batchUpdate
    try:
        _highlight_review_spans(doc_id)
    except Exception as e:
        # Non-fatal: doc is already created; just warn
        print(f"  Warning: could not apply yellow highlights to {doc_name}: {e}")

    return file


def _build_html(translated: dict, flags: list, source_doc_id: str, lang_code: str, model: str) -> str:
    """Build the full HTML document for the translated blog."""
    title = _esc(translated.get("title", ""))
    meta = _esc(translated.get("meta_description", ""))
    body_md = translated.get("body_markdown", "")
    body_md = strip_locale_annotations(body_md)
    faq = translated.get("faq", [])

    body_html = _markdown_to_html(body_md)

    faq_html = ""
    if faq:
        faq_items = "\n".join(
            f"<h4>{_esc(item.get('question', ''))}</h4>\n<p>{_esc(item.get('answer', ''))}</p>"
            for item in faq
        )
        faq_html = f"<h2>FAQ</h2>\n{faq_items}"

    flags_html = _build_flags_section(flags)

    errors = sum(1 for f in flags if f.get("severity") == "error")
    warnings = sum(1 for f in flags if f.get("severity") == "warning")
    infos = sum(1 for f in flags if f.get("severity") == "info")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    footer_html = (
        f"<hr>"
        f"<p><small>"
        f"Source doc: {_esc(source_doc_id)} | "
        f"Language: {lang_code.upper()} | "
        f"Model: {_esc(model)} | "
        f"Generated: {timestamp} | "
        f"Flags: {errors} error(s), {warnings} warning(s), {infos} info(s)"
        f"</small></p>"
    )

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<blockquote><p>{meta}</p></blockquote>
{body_html}
{faq_html}
{flags_html}
{footer_html}
</body>
</html>"""


def _build_flags_section(flags: list) -> str:
    if not flags:
        return ""

    by_severity: dict[str, list] = {"error": [], "warning": [], "info": []}
    for f in flags:
        sev = f.get("severity", "info")
        by_severity.setdefault(sev, []).append(f)

    sections = []
    for sev in ("error", "warning", "info"):
        items = by_severity.get(sev, [])
        if not items:
            continue
        label = sev.upper()
        li_items = "\n".join(
            f"<li><strong>[{label}]</strong> {_esc(f.get('message', ''))} "
            f"<em>({_esc(f.get('location', ''))})</em></li>"
            for f in items
        )
        sections.append(f"<ul>\n{li_items}\n</ul>")

    if not sections:
        return ""

    return "<hr>\n<h2>Review Flags</h2>\n" + "\n".join(sections)


_LOCALE_ANNOTATION = re.compile(r'[ \t]*\[[A-Z]{2}:\s*.*?\]')


def strip_locale_annotations(text: str) -> str:
    """Drop trailing [XX: ...] cross-reference markers from url_localizer.
    Each duplicates the anchor of the link right before it, so remove the
    whole annotation plus its leading space."""
    return _LOCALE_ANNOTATION.sub('', text)


def _markdown_to_html(md: str) -> str:
    """Convert Markdown to basic HTML.

    Handles: headings (H1–H6), bold, italic, inline code, links, unordered lists,
    ordered lists, horizontal rules, and paragraphs. Not a full Markdown parser —
    covers the subset generated by the blog writer.
    """
    lines = md.split("\n")
    html_lines: list[str] = []
    in_ul = False
    in_ol = False

    for line in lines:
        stripped = line.strip()

        # Close open lists if line is not a list item
        if in_ul and not stripped.startswith("- ") and not stripped.startswith("* "):
            html_lines.append("</ul>")
            in_ul = False
        if in_ol and not re.match(r"^\d+\.", stripped):
            html_lines.append("</ol>")
            in_ol = False

        if not stripped:
            html_lines.append("")
            continue

        # Headings
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            content = _inline_md(heading_match.group(2))
            html_lines.append(f"<h{level}>{content}</h{level}>")
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            html_lines.append("<hr>")
            continue

        # Unordered list item
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            content = _inline_md(stripped[2:])
            html_lines.append(f"<li>{content}</li>")
            continue

        # Ordered list item
        ol_match = re.match(r"^\d+\.\s+(.*)", stripped)
        if ol_match:
            if not in_ol:
                html_lines.append("<ol>")
                in_ol = True
            content = _inline_md(ol_match.group(1))
            html_lines.append(f"<li>{content}</li>")
            continue

        # Regular paragraph
        html_lines.append(f"<p>{_inline_md(stripped)}</p>")

    # Close any open lists
    if in_ul:
        html_lines.append("</ul>")
    if in_ol:
        html_lines.append("</ol>")

    return "\n".join(html_lines)


def _inline_md(text: str) -> str:
    """Apply inline Markdown transforms: bold, italic, code, links."""
    # Links: [anchor](url)
    text = re.sub(
        r"\[([^\]]*)\]\((https?://[^\)]+)\)",
        lambda m: f'<a href="{_esc(m.group(2))}">{_esc(m.group(1))}</a>',
        text,
    )
    # Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    # Italic *text* or _text_
    text = re.sub(r"\*(.+?)\*|_(.+?)_", lambda m: f"<em>{m.group(1) or m.group(2)}</em>", text)
    # Inline code
    text = re.sub(r"`(.+?)`", lambda m: f"<code>{_esc(m.group(1))}</code>", text)
    return text


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _highlight_review_spans(doc_id: str) -> None:
    """Use the Docs API to apply yellow background to text matching '[REVIEW:...]' patterns."""
    docs = _get_docs_service()

    doc = docs.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])

    requests = []
    for element in content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if not text_run:
                continue
            text = text_run.get("content", "")
            start = elem.get("startIndex", 0)

            for m in re.finditer(r"\[REVIEW:[^\]]*\]", text):
                match_start = start + m.start()
                match_end = start + m.end()
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": match_start, "endIndex": match_end},
                        "textStyle": {
                            "backgroundColor": {
                                "color": {
                                    "rgbColor": {"red": 1.0, "green": 1.0, "blue": 0.0}
                                }
                            }
                        },
                        "fields": "backgroundColor",
                    }
                })

    if requests:
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests},
        ).execute()
