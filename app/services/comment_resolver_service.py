"""Core logic for Stage 9 — Comment Resolution.

Flow for each unresolved Google Doc comment:
  1. Classify: direct (explicit instruction) vs interpretive (open-ended flag)
  2. Generate revised text via Claude (+ web search for interpretive comments)
  3. Apply edit to the Google Doc at the exact anchor position
  4. Resolve the comment in the Doc
  5. Log to comment_resolutions table

resolve_comments() returns (direct_results, interpretive_results, skipped_ids).
Trello summary posting and exit-code logic live in comment_resolver.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.services import anthropic_client
from app.services.docs_client import (
    get_unresolved_comments,
    apply_text_replacement,
    resolve_comment as resolve_doc_comment,
)

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = (
    "You are a document editor assistant. Classify a Google Doc comment as either:\n"
    "- \"direct\": the reviewer gave an explicit instruction with a clear replacement "
    "(e.g. \"change X to Y\", \"remove this sentence\", factual correction with a "
    "specific replacement such as \"V-Rod uses Revolution engine, not Twin Cam\")\n"
    "- \"interpretive\": the reviewer flagged something without a specific fix "
    "(e.g. \"this sounds awkward\", \"French riders won't relate\", \"rephrase\")\n\n"
    "Respond with JSON only, no prose: "
    "{\"category\": \"direct\" | \"interpretive\", \"reasoning\": \"one sentence\"}"
)

_DIRECT_EDIT_SYSTEM = (
    "You are a document editor. Given highlighted text from a Google Doc, a reviewer "
    "comment, and surrounding paragraph context, generate the exact replacement text.\n"
    "Return ONLY the replacement text — no explanation, no surrounding quotes, no prefix. "
    "The replacement must integrate naturally into the paragraph."
)

_INTERPRETIVE_SYSTEM = (
    "You are a document editor with web search access. Given highlighted text from a "
    "Google Doc, a reviewer's concern, and surrounding paragraph context, research how "
    "this concept is authentically expressed by the target audience, then propose a "
    "revised version of the highlighted text.\n"
    "Return ONLY the revised text — no explanation, no surrounding quotes, no prefix. "
    "The replacement must integrate naturally into the paragraph."
)


def resolve_comments(doc_id: str, state, model: str) -> tuple:
    """Resolve all unresolved comments on the Google Doc.

    For each comment: classify → generate edit → apply to doc → resolve → log.
    Failures per comment are logged and skipped; the loop always continues.

    Returns:
        (direct_results, interpretive_results, skipped_ids)
        where each result list contains dicts:
            {comment_id, original, revised, reasoning}
        and skipped_ids is a list of comment ID strings.

    Raises RuntimeError only if the initial comment fetch itself fails.
    """
    comments = get_unresolved_comments(doc_id)

    if not comments:
        logger.info("No unresolved comments for doc_id=%r — nothing to do", doc_id)
        return ([], [], [])

    logger.info("Found %d unresolved comment(s) for doc_id=%r", len(comments), doc_id)

    direct_results: list = []
    interpretive_results: list = []
    skipped_ids: list = []

    for comment in comments:
        comment_id = comment["id"]
        quoted_text = comment["quoted_text"]
        body = comment["body"]
        anchor = comment["anchor"]
        paragraph_context = comment["paragraph_context"]

        try:
            category, reasoning = _classify_comment(body, quoted_text, paragraph_context, model)
            logger.info("Comment %r classified as %r", comment_id, category)

            if category == "direct":
                revised = _generate_direct_edit(quoted_text, body, paragraph_context, model)
            else:
                revised = _generate_interpretive_edit(quoted_text, body, paragraph_context, model)

            applied = apply_text_replacement(doc_id, quoted_text, revised, anchor)
            if not applied:
                logger.warning(
                    "Comment %r: quoted text not found in doc — skipping", comment_id
                )
                skipped_ids.append(comment_id)
                continue

            resolve_doc_comment(doc_id, comment_id)

            _log_resolution(state, doc_id, comment_id, category, quoted_text, revised, reasoning)

            result = {
                "comment_id": comment_id,
                "original": quoted_text,
                "revised": revised,
                "reasoning": reasoning,
            }
            if category == "direct":
                direct_results.append(result)
            else:
                interpretive_results.append(result)

        except Exception as e:
            logger.warning("Failed to process comment %r: %s — skipping", comment_id, e)
            skipped_ids.append(comment_id)
            continue

    return (direct_results, interpretive_results, skipped_ids)


def build_trello_summary(
    direct: list,
    interpretive: list,
    n_skipped: int,
) -> str:
    """Format the ✅ summary string posted to the Trello card."""
    lines = [
        "✅ Comment resolution complete.",
        f"- {len(direct)} direct edit(s) applied",
        f"- {len(interpretive)} interpretive revision(s) applied (with research)",
    ]
    if n_skipped:
        lines.append(f"- {n_skipped} comment(s) skipped (API error or text not found in doc)")

    if direct:
        lines.append("\nDirect edits:")
        for r in direct:
            orig = _truncate(r["original"], 60)
            rev = _truncate(r["revised"], 60)
            lines.append(f"• {orig} → {rev}")

    if interpretive:
        lines.append("\nInterpretive revisions:")
        for r in interpretive:
            orig = _truncate(r["original"], 60)
            rev = _truncate(r["revised"], 60)
            lines.append(f"• {orig} → {rev}")
            if r.get("reasoning"):
                lines.append(f"  Reasoning: {r['reasoning']}")

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _classify_comment(body: str, quoted_text: str, paragraph_context: str, model: str) -> tuple:
    """Returns (category, reasoning). Raises on Anthropic API failure."""
    user_prompt = (
        f"Comment: {body}\n"
        f"Highlighted text: {quoted_text}\n"
        f"Paragraph context: {paragraph_context}"
    )
    raw = anthropic_client.call(
        _CLASSIFY_SYSTEM, user_prompt, model=model, max_tokens=256
    )
    parsed = anthropic_client.extract_json(raw)
    category = parsed.get("category", "interpretive")
    reasoning = parsed.get("reasoning", "")
    if category not in ("direct", "interpretive"):
        category = "interpretive"
    return category, reasoning


def _generate_direct_edit(
    quoted_text: str, body: str, paragraph_context: str, model: str
) -> str:
    """Call Claude to produce replacement text for a direct comment."""
    user_prompt = (
        f"Highlighted text: {quoted_text}\n"
        f"Reviewer comment: {body}\n"
        f"Paragraph context: {paragraph_context}\n\n"
        "Provide the exact replacement text for the highlighted text only."
    )
    return anthropic_client.call(
        _DIRECT_EDIT_SYSTEM, user_prompt, model=model, max_tokens=512
    ).strip()


def _generate_interpretive_edit(
    quoted_text: str, body: str, paragraph_context: str, model: str
) -> str:
    """Call Claude with web search to produce a researched revision."""
    user_prompt = (
        f"Highlighted text: {quoted_text}\n"
        f"Reviewer concern: {body}\n"
        f"Paragraph context: {paragraph_context}\n\n"
        "Research how this concept is authentically expressed by the target audience, "
        "then provide the exact replacement text for the highlighted text only."
    )
    return anthropic_client.call_with_web_search(
        _INTERPRETIVE_SYSTEM,
        user_prompt,
        model=model,
        max_tokens=1024,
        max_searches=3,
    ).strip()


def _log_resolution(
    state,
    doc_id: str,
    comment_id: str,
    category: str,
    original_text: str,
    revised_text: str,
    reasoning: str,
) -> None:
    try:
        state.log_comment_resolution(
            doc_id, comment_id, category, original_text, revised_text, reasoning
        )
    except Exception as e:
        logger.warning("Could not log comment resolution to DB: %s", e)


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len] + "…" if len(text) > max_len else text
