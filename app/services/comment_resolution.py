# app/services/comment_resolution.py
"""Stage 9 — orchestrate all unresolved Google Doc comment resolutions via claude -p.

Public API:
    resolve_all_comments(doc_id: str) -> dict
    format_stage9_summary(summary: dict, translation_triggered: bool = True) -> str
    DRIVE_RESOLVE_FAILURE_NOTE: str  — sentinel used by trello_gate to detect hazardous failures

resolve_all_comments returns:
    {
        "applied": [{"comment_id", "anchor_preview", "note"}, ...],
        "flagged_low_confidence": [...],   # edit applied but needs human review
        "failed": [...],                   # edit not applied OR Drive resolve failed
    }

Routing logic per comment:
    resolver returns None              → failed (no doc edit, comment not resolved)
    action == "noop"                   → resolve comment silently, no list entry
    apply_text_replacement False       → failed (comment NOT resolved)
    resolve_doc_comment raises         → failed with DRIVE_RESOLVE_FAILURE_NOTE
                                         (edit WAS applied — caller must block re-execution
                                          to prevent double-apply on next poller cycle)
    confidence == "low"                → flagged_low_confidence (edit applied, comment resolved)
    confidence == "high"/"medium"      → applied

apply_text_replacement contract (verified in planning):
    Uses deleteContentRange + insertText (range-based, NOT replaceAllText).
    Disambiguates multiple occurrences via Drive comment anchor JSON offset.
    insert action: pass anchor_text + replacement_text as revised_text (appends after anchor).
"""
from __future__ import annotations

import logging

from app.services import claude_code_resolver
from app.services.docs_client import (
    get_unresolved_comments,
    apply_text_replacement,
    resolve_comment as resolve_doc_comment,
)

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 50

DRIVE_RESOLVE_FAILURE_NOTE = (
    "edit applied but could not resolve in Drive — manual cleanup required"
)


def resolve_all_comments(doc_id: str) -> dict:
    """Fetch, resolve, and apply all unresolved comments for a Google Doc.

    Per-comment failures are caught and logged; the loop never halts.
    If Drive resolve fails after an edit is applied, the entry goes to failed
    with DRIVE_RESOLVE_FAILURE_NOTE so the caller can block re-execution.

    Raises RuntimeError only if the initial comment fetch fails.
    """
    comments = get_unresolved_comments(doc_id)

    applied: list = []
    flagged: list = []
    failed: list = []

    if not comments:
        logger.info("No unresolved comments for doc_id=%r", doc_id)
        return {"applied": applied, "flagged_low_confidence": flagged, "failed": failed}

    logger.info("Found %d unresolved comment(s) for doc_id=%r", len(comments), doc_id)

    for comment in comments:
        comment_id = comment["id"]
        anchor_preview = _truncate(comment.get("quoted_text", ""), _PREVIEW_LEN)

        try:
            response = claude_code_resolver.resolve_comment(
                doc_text=comment.get("paragraph_context", ""),
                comment=comment,
            )

            if response is None:
                logger.warning("Resolver returned None for comment %r", comment_id)
                failed.append({
                    "comment_id": comment_id,
                    "anchor_preview": anchor_preview,
                    "note": "resolver failed (timeout, non-zero exit, or malformed JSON)",
                })
                continue

            action = response["action"]

            if action == "noop":
                logger.info("Comment %r is noop — resolving silently", comment_id)
                try:
                    resolve_doc_comment(doc_id, comment_id)
                except Exception as e:
                    logger.warning("Could not resolve noop comment %r in Drive: %s", comment_id, e)
                continue

            anchor_text = response["anchor_text"]
            replacement_text = response["replacement_text"]
            confidence = response["confidence"]
            rationale = response.get("rationale", "")

            # Map action to revised_text for apply_text_replacement
            if action == "replace":
                new_text = replacement_text
            elif action == "delete":
                new_text = ""
            elif action == "insert":
                # deleteContentRange(anchor_text) + insertText(anchor_text + replacement_text)
                # = anchor_text stays in place, replacement_text appended immediately after
                new_text = anchor_text + replacement_text
            else:
                new_text = replacement_text  # unreachable after schema validation

            ok = apply_text_replacement(
                doc_id, anchor_text, new_text, comment.get("anchor", "")
            )

            if not ok:
                logger.warning(
                    "apply_text_replacement returned False for comment %r", comment_id
                )
                failed.append({
                    "comment_id": comment_id,
                    "anchor_preview": anchor_preview,
                    "note": "text not found in document",
                })
                continue

            # Edit is in the doc — now resolve the Drive comment.
            # If this fails, the comment stays open and would be re-processed on the next
            # poll cycle, applying the same edit twice. Treat this as a hard failure.
            try:
                resolve_doc_comment(doc_id, comment_id)
            except Exception as e:
                logger.error(
                    "Edit applied for comment %r but Drive resolve failed: %s", comment_id, e
                )
                failed.append({
                    "comment_id": comment_id,
                    "anchor_preview": anchor_preview,
                    "note": DRIVE_RESOLVE_FAILURE_NOTE,
                })
                continue

            entry = {"comment_id": comment_id, "anchor_preview": anchor_preview,
                     "note": rationale}
            if confidence == "low":
                entry["note"] = f"{rationale} (low confidence)"
                flagged.append(entry)
                logger.info("Comment %r applied and flagged (low confidence)", comment_id)
            else:
                applied.append(entry)
                logger.info("Comment %r applied (confidence=%r)", comment_id, confidence)

        except Exception as e:
            logger.warning("Unexpected error on comment %r: %s — skipping", comment_id, e)
            failed.append({
                "comment_id": comment_id,
                "anchor_preview": anchor_preview,
                "note": f"unexpected error: {type(e).__name__}",
            })

    return {"applied": applied, "flagged_low_confidence": flagged, "failed": failed}


def format_stage9_summary(summary: dict, translation_triggered: bool = True) -> str:
    """Format a resolve_all_comments result dict as a Trello comment string.

    Applied (N):
    - "<anchor_preview>" → <note>

    Flagged for review (N):
    - "<anchor_preview>" → <note>

    Failed (N):
    - "<anchor_preview>" → <note>

    Translation triggered.   ← or "Translation paused..." when translation_triggered=False

    Empty sections are omitted.
    """
    applied = summary.get("applied", [])
    flagged = summary.get("flagged_low_confidence", [])
    failed = summary.get("failed", [])

    lines = ["Stage 9 — Comment Resolution complete"]

    if applied:
        lines.append(f"\nApplied ({len(applied)}):")
        for item in applied:
            lines.append(f'- "{item["anchor_preview"]}" → {item["note"]}')

    if flagged:
        lines.append(f"\nFlagged for review ({len(flagged)}):")
        for item in flagged:
            lines.append(f'- "{item["anchor_preview"]}" → {item["note"]}')

    if failed:
        lines.append(f"\nFailed ({len(failed)}):")
        for item in failed:
            lines.append(f'- "{item["anchor_preview"]}" → {item["note"]}')

    lines.append("")
    if translation_triggered:
        lines.append("Translation triggered.")
    else:
        lines.append(
            "Translation paused — manual cleanup required before translation can proceed."
        )

    return "\n".join(lines)


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text
