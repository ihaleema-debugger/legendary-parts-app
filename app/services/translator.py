"""Translate a structured English blog into a target language via Anthropic Claude."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import anthropic_client

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_GUIDELINES_PATH = _PROJECT_ROOT / "config" / "translation_guidelines.md"

_LANG_INSTRUCTIONS = {
    "fr": "Translate into French. Target variant: FR (France). Use formal 'vous' unless the source uses informal tone throughout.",
    "de": "Translate into German. Target variant: DE (Germany). Use formal 'Sie' register.",
    "es": "Translate into Spanish. Target variant: ES (Spain). Use 'vosotros' for plural second person where appropriate.",
    "it": "Translate into Italian. Target variant: IT (Italy).",
    "nl": "Translate into Dutch. Target variant: NL (Netherlands).",
    "pl": "Translate into Polish. Target variant: PL (Poland).",
    "sl": "Translate into Slovenian. Target variant: SL (Slovenia).",
    "pt": "Translate into Portuguese. Target variant: PT (Portugal). Use European Portuguese, not Brazilian.",
}


def load_guidelines() -> str:
    """Load translation_guidelines.md. Raises RuntimeError if missing or empty."""
    if not _GUIDELINES_PATH.exists():
        raise RuntimeError(
            f"Translation guidelines file not found: {_GUIDELINES_PATH}\n"
            "Create config/translation_guidelines.md before running translations."
        )
    content = _GUIDELINES_PATH.read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError(
            f"Translation guidelines file is empty: {_GUIDELINES_PATH}\n"
            "Add content to config/translation_guidelines.md before running translations."
        )
    return content


def translate_blog(
    blog: dict,
    lang_code: str,
    lang_name: str,
    guidelines: str,
    model: str,
) -> dict:
    """Translate a structured English blog into a target language.

    Args:
        blog: {"title", "meta_description", "body_html", "faq": [{"question", "answer"}]}
        lang_code: e.g. "fr"
        lang_name: e.g. "French (France)"
        guidelines: full content of translation_guidelines.md
        model: Anthropic model ID

    Returns:
        {
            "title": str,
            "meta_description": str,
            "body_markdown": str,
            "faq": [{"question": str, "answer": str}],
            "flags": [{"type": str, "severity": str, "message": str, "location": str}],
        }

    Raises:
        RuntimeError: if the LLM response cannot be parsed as valid JSON.
    """
    lang_instruction = _LANG_INSTRUCTIONS.get(
        lang_code,
        f"Translate into {lang_name}.",
    )

    system_prompt = f"""{guidelines}

---

## Current Translation Task

{lang_instruction}

You MUST return a single JSON object with exactly these fields:
- title (string): translated H1 title
- meta_description (string): translated meta description, max 155 characters
- body_markdown (string): translated body as Markdown, preserving all heading levels, links, and lists
- faq (array of objects with "question" and "answer" string fields): translated FAQ items, empty array if none
- flags (array of objects with "type", "severity", "message", "location" string fields): any translation review flags you want to raise (e.g. untranslatable puns, culturally specific references, ambiguous source phrases)

Severity values: "info", "warning", "error"

Rules:
1. Preserve all URLs exactly — do not translate or modify any hyperlink href values
2. Preserve all markdown syntax (##, **, *, [], (), etc.)
3. Protected tokens from Section 3 of the guidelines must appear verbatim
4. Do NOT add commentary or explanation outside the JSON
5. Return ONLY the JSON object, no code fences
"""

    user_prompt = json.dumps(
        {
            "title": blog.get("title", ""),
            "meta_description": blog.get("meta_description", ""),
            "body": blog.get("body_html", ""),
            "faq": blog.get("faq", []),
        },
        ensure_ascii=False,
        indent=2,
    )

    raw = anthropic_client.call(
        system_prompt,
        user_prompt,
        model=model,
        max_tokens=8000,
        max_retries=2,
    )

    try:
        result = anthropic_client.extract_json(raw)
    except ValueError as e:
        raise RuntimeError(
            f"Translator returned non-JSON response for {lang_code}. "
            f"Raw preview: {raw[:300]!r}. Error: {e}"
        ) from e

    return {
        "title": str(result.get("title", "")),
        "meta_description": str(result.get("meta_description", "")),
        "body_markdown": str(result.get("body_markdown", "")),
        "faq": result.get("faq", []),
        "flags": result.get("flags", []),
    }
