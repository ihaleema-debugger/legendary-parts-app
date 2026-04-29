# app/services/claude_code_resolver.py
"""Claude Code headless subprocess wrapper: resolve one Google Doc comment per invocation.

Public API:
    resolve_comment(doc_text, comment) -> dict | None

Returns None on: TimeoutExpired, non-zero exit, malformed JSON, schema mismatch.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = {"action", "anchor_text", "replacement_text", "confidence", "rationale"}
_VALID_ACTIONS = {"replace", "insert", "delete", "noop"}
_VALID_CONFIDENCE = {"high", "medium", "low"}

_PROMPT_TEMPLATE = """\
You are a precise document editor. A Google Doc reviewer left a comment that must be resolved.

Paragraph context (the paragraph containing the highlighted text):
{paragraph_context}

Highlighted text (the exact quoted text of the comment):
{quoted_text}

Reviewer comment:
{comment_body}

Return ONLY a JSON object with exactly these fields — no markdown fences, no prose:
{{
  "action": "replace" | "insert" | "delete" | "noop",
  "anchor_text": "<verbatim substring from the paragraph to act on>",
  "replacement_text": "<new text; empty string for delete; ignored for noop>",
  "confidence": "high" | "medium" | "low",
  "rationale": "<one sentence explaining the edit>"
}}

Rules:
- "replace": substitute anchor_text with replacement_text
- "insert": insert replacement_text immediately after anchor_text
- "delete": remove anchor_text entirely (replacement_text must be "")
- "noop": comment is a question or observation needing no doc edit
- Use "low" confidence whenever the comment is interpretive rather than directive
- anchor_text MUST be a verbatim substring of the paragraph context above
"""


def resolve_comment(doc_text: str, comment: dict) -> Optional[dict]:
    """Invoke `claude -p` to resolve a single Google Doc comment.

    Args:
        doc_text: The paragraph text containing the comment anchor (passed as context).
        comment: Dict with keys: id, quoted_text, body, anchor, paragraph_context.

    Returns:
        Validated dict matching the schema, or None on any failure.
    """
    prompt = _PROMPT_TEMPLATE.format(
        paragraph_context=comment.get("paragraph_context", doc_text),
        quoted_text=comment.get("quoted_text", ""),
        comment_body=comment.get("body", ""),
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.warning("claude -p timed out for comment %r", comment.get("id", "?"))
        return None

    if result.returncode != 0:
        logger.warning(
            "claude -p exited %d for comment %r. stderr: %s",
            result.returncode,
            comment.get("id", "?"),
            (result.stderr or "")[:200],
        )
        return None

    return _parse_and_validate(result.stdout, comment.get("id", "?"))


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*([\[{].*?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text.strip()


def _parse_and_validate(raw: str, comment_id: str) -> Optional[dict]:
    text = _strip_fences(raw)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(
            "Could not parse JSON from claude for comment %r: %s. Preview: %r",
            comment_id, e, raw[:200],
        )
        return None

    if not isinstance(data, dict):
        logger.warning("claude output for comment %r is not a JSON object", comment_id)
        return None

    missing = _REQUIRED_FIELDS - data.keys()
    if missing:
        logger.warning("claude response for comment %r missing fields: %s", comment_id, missing)
        return None

    if data["action"] not in _VALID_ACTIONS:
        logger.warning(
            "claude response for comment %r has invalid action: %r", comment_id, data["action"]
        )
        return None

    if data["confidence"] not in _VALID_CONFIDENCE:
        logger.warning(
            "claude response for comment %r has invalid confidence: %r",
            comment_id, data["confidence"],
        )
        return None

    return data
