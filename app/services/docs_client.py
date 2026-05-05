"""Google Docs/Drive API wrapper for comment resolution (Stage 9).

Provides:
  - get_unresolved_comments()    — Drive v3 comments.list
  - apply_text_replacement()     — Docs v1 batchUpdate (deleteContentRange + insertText)
  - replace_body()               — Docs v1 batchUpdate (atomic delete-all + insertText)
  - resolve_comment()            — Drive v3 comments.update resolved=True
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from googleapiclient.discovery import build
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]


def _get_drive_service():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=_SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_docs_service():
    key_path = os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"]
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=_SCOPES)
    return build("docs", "v1", credentials=creds)


def get_unresolved_comments(doc_id: str) -> list:
    """Fetch all unresolved comments from a Google Doc.

    Returns a list of dicts:
        {id, quoted_text, body, anchor, paragraph_context}
    """
    drive = _get_drive_service()
    docs = _get_docs_service()

    result = drive.comments().list(
        fileId=doc_id,
        includeDeleted=False,
        fields="comments(id,content,quotedFileContent,anchor,resolved)",
    ).execute()

    all_comments = result.get("comments", [])
    unresolved = [c for c in all_comments if not c.get("resolved", False)]

    if not unresolved:
        return []

    doc = docs.documents().get(documentId=doc_id).execute()
    doc_content = doc.get("body", {}).get("content", [])

    comments = []
    for c in unresolved:
        quoted_text = c.get("quotedFileContent", {}).get("value", "")
        body = c.get("content", "")
        anchor = c.get("anchor", "")
        paragraph_context = _find_paragraph_context(doc_content, quoted_text)
        comments.append({
            "id": c["id"],
            "quoted_text": quoted_text,
            "body": body,
            "anchor": anchor,
            "paragraph_context": paragraph_context,
        })

    return comments


def apply_text_replacement(
    doc_id: str,
    original_text: str,
    revised_text: str,
    anchor_str: str = "",
) -> bool:
    """Apply a targeted text replacement at the comment's anchor position.

    Finds all occurrences of original_text in the document.  When there are
    multiple occurrences, parses the Drive comment anchor to pick the closest
    one; falls back to the first occurrence with a warning if anchor is opaque.

    Returns True if the replacement was applied, False if original_text was not
    found in the document.
    """
    docs = _get_docs_service()

    doc = docs.documents().get(documentId=doc_id).execute()
    doc_content = doc.get("body", {}).get("content", [])

    occurrences = _find_text_occurrences(doc_content, original_text)
    if not occurrences:
        flat_text, offset_map = _build_flat_text(doc_content)
        flat_idx = flat_text.find(original_text)
        if flat_idx == -1:
            # Layer 1: normalize whitespace/quotes/dashes and retry on flat text
            from app.services import anchor_matcher
            span = anchor_matcher.find_span(flat_text, original_text)
            if span is None:
                logger.warning("Text not found in document: %r", original_text[:80])
                return False
            flat_idx, flat_end_idx = span
            start_idx = offset_map[flat_idx]
            end_idx = offset_map[flat_end_idx - 1] + 1
        else:
            start_idx = offset_map[flat_idx]
            end_idx = offset_map[flat_idx + len(original_text) - 1] + 1
    elif len(occurrences) == 1:
        start_idx, end_idx = occurrences[0]
    else:
        anchor_start = _parse_anchor_start(anchor_str)
        if anchor_start is not None:
            start_idx, end_idx = min(occurrences, key=lambda o: abs(o[0] - anchor_start))
            logger.info(
                "Multiple occurrences of quoted text; selected index %d (closest to anchor %d)",
                start_idx, anchor_start,
            )
        else:
            start_idx, end_idx = occurrences[0]
            logger.warning(
                "Multiple occurrences of %r and anchor unparseable; using first occurrence",
                original_text[:40],
            )

    batch_requests = [
        {"deleteContentRange": {"range": {"startIndex": start_idx, "endIndex": end_idx}}},
        {"insertText": {"location": {"index": start_idx}, "text": revised_text}},
    ]
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": batch_requests},
    ).execute()
    logger.info(
        "Replaced %r → %r at index %d in doc %r",
        original_text[:40], revised_text[:40], start_idx, doc_id,
    )
    return True


def replace_body(doc_id: str, new_text: str) -> int:
    """Replace the entire body of a Google Doc with new_text.

    Fetches the current body to determine the end index, then issues a single
    atomic batchUpdate: deleteContentRange(1, end-1) + insertText(1, new_text).
    Returns the end index that was deleted (useful for logging).
    """
    docs = _get_docs_service()

    doc = docs.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    end_index = content[-1].get("endIndex", 2) if content else 2

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}},
            {"insertText": {"location": {"index": 1}, "text": new_text}},
        ]},
    ).execute()
    logger.info("Replaced body of doc %r (deleted up to index %d)", doc_id, end_index - 1)
    return end_index - 1


_STYLE_MAP = {
    "title": "TITLE",
    "h1": "HEADING_1",
    "h2": "HEADING_2",
    "h3": "HEADING_3",
    "h4": "HEADING_4",
    "p": "NORMAL_TEXT",
}


def write_structured_doc(doc_id: str, blocks: list) -> None:
    """Write structured content to a Google Doc, applying heading and paragraph styles.

    blocks is a list of dicts with required key ``level`` ("title", "h1"–"h4", "p")
    and ``text`` (str). Optional key ``links`` is a list of
    {anchor: str, url: str} dicts for inline hyperlinks.

    Issues a single atomic batchUpdate:
      1. deleteContentRange clearing existing body
      2. insertText for each non-empty block (tracks running index)
      3. updateParagraphStyle for each heading/title block
      4. updateTextStyle for each link whose anchor is found in its block

    Raises ValueError if blocks is empty.
    Skips blocks with empty text silently.
    Logs a warning (does not raise) if a link anchor is not found in its block.
    """
    if not blocks:
        raise ValueError("blocks must not be empty")

    docs = _get_docs_service()

    doc = docs.documents().get(documentId=doc_id).execute()
    content = doc.get("body", {}).get("content", [])
    end_index = content[-1].get("endIndex", 2) if content else 2

    requests: list = []

    # Step 1 — clear existing content (skip if doc is already empty)
    if end_index > 2:
        requests.append({
            "deleteContentRange": {
                "range": {"startIndex": 1, "endIndex": end_index - 1},
            }
        })

    # Step 2 — insert all blocks, tracking indices
    running_index = 1
    block_data: list = []  # (start, para_end, level, text, links)

    for block in blocks:
        level = block.get("level", "p")
        text = block.get("text", "")
        links = block.get("links", [])

        if not text:
            continue

        text_with_newline = text + "\n"
        start = running_index
        para_end = running_index + len(text_with_newline)

        requests.append({
            "insertText": {
                "location": {"index": running_index},
                "text": text_with_newline,
            }
        })

        block_data.append((start, para_end, level, text, links))
        running_index = para_end

    # Step 3 — apply paragraph styles (heading/title blocks only)
    for start, para_end, level, _text, _links in block_data:
        if level == "p":
            continue
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": para_end},
                "paragraphStyle": {
                    "namedStyleType": _STYLE_MAP.get(level, "NORMAL_TEXT"),
                },
                "fields": "namedStyleType",
            }
        })

    # Step 4 — apply link styles
    for start, _para_end, _level, text, links in block_data:
        for link_dict in links:
            anchor = link_dict.get("anchor", "")
            url = link_dict.get("url", "")
            if not anchor or not url:
                continue
            idx = text.find(anchor)
            if idx == -1:
                logger.warning(
                    "Link anchor %r not found in block text, skipping", anchor[:40]
                )
                continue
            requests.append({
                "updateTextStyle": {
                    "range": {
                        "startIndex": start + idx,
                        "endIndex": start + idx + len(anchor),
                    },
                    "textStyle": {"link": {"url": url}},
                    "fields": "link",
                }
            })

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()
    logger.info("Wrote %d blocks to doc %r", len(block_data), doc_id)


def resolve_comment(doc_id: str, comment_id: str) -> None:
    """Mark a Google Doc comment as resolved via Drive API.

    The Drive v3 comments.update endpoint requires the existing comment
    content to be included in the PATCH body alongside resolved=True;
    omitting it yields HttpError 400 "Comment content is required".
    """
    drive = _get_drive_service()
    existing = drive.comments().get(
        fileId=doc_id,
        commentId=comment_id,
        fields="content",
    ).execute()
    drive.comments().update(
        fileId=doc_id,
        commentId=comment_id,
        fields="id,resolved",
        body={"resolved": True, "content": existing["content"]},
    ).execute()
    logger.info("Resolved comment %r on doc %r", comment_id, doc_id)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_paragraph_context(doc_content: list, quoted_text: str) -> str:
    """Return the full text of the paragraph that contains quoted_text."""
    for element in doc_content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        para_text = "".join(
            elem.get("textRun", {}).get("content", "")
            for elem in paragraph.get("elements", [])
        )
        if quoted_text in para_text:
            return para_text.strip()
    return ""


def _find_text_occurrences(doc_content: list, text: str) -> list:
    """Find all (start_index, end_index) character positions of text in the document."""
    occurrences = []
    for element in doc_content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if not text_run:
                continue
            run_text = text_run.get("content", "")
            run_start = elem.get("startIndex", 0)
            search_from = 0
            while True:
                idx = run_text.find(text, search_from)
                if idx == -1:
                    break
                occurrences.append((run_start + idx, run_start + idx + len(text)))
                search_from = idx + 1
    return occurrences


def _build_flat_text(doc_content: list) -> tuple:
    """Reconstruct document as a flat string with Docs API index mapping.

    Returns (flat_text, offset_map) where offset_map[i] is the Docs API
    startIndex for flat_text[i]. Enables cross-run and cross-paragraph matching.
    """
    parts: list = []
    offset_map: list = []
    for element in doc_content:
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for elem in paragraph.get("elements", []):
            text_run = elem.get("textRun")
            if not text_run:
                continue
            content = text_run.get("content", "")
            run_start = elem.get("startIndex", 0)
            parts.append(content)
            for i in range(len(content)):
                offset_map.append(run_start + i)
    return "".join(parts), offset_map


def _parse_anchor_start(anchor_str: str) -> Optional[int]:
    """Try to extract the start character index from a Drive comment anchor JSON string.

    The anchor field is an opaque JSON string whose schema is not publicly
    documented.  This parses the most common format observed in practice:
      {"r": "head", "a": [{"v": {"op": {"e": [{"si": N}]}, ...}}]}
    where "si" is the absolute character offset.  Returns None if parsing fails.
    """
    if not anchor_str:
        return None
    try:
        anchor = json.loads(anchor_str)
        a_list = anchor.get("a", [])
        if not a_list:
            return None
        v = a_list[0].get("v", {})
        e_list = v.get("op", {}).get("e", [])
        if not e_list:
            return None
        si = e_list[0].get("si")
        return int(si) if si is not None else None
    except (json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError):
        return None
