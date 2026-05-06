# app/services/word_count_validator.py
"""Word count validation and trimming for blog blocks before Drive publish."""
from __future__ import annotations

import json
import logging

from app.services import anthropic_client

logger = logging.getLogger(__name__)

TARGET_WORDS = 850
HARD_CEILING = 1000
ACCEPTABLE_RANGE_PCT = 0.15
MAX_TRIM_ATTEMPTS = 1

_TRIM_SYSTEM = """You are a precise blog editor. You will be given a blog post as a JSON array
of blocks and a target word count. Return a trimmed version of the same JSON array that hits
the target word count.

Mandatory preservation rules — never violate these:
1. Keep ALL h3 section headings (do not merge or delete sections)
2. Keep the "Frequently Asked Questions" h3 and ALL h4 question headings
3. Keep ALL factual numbers (years, displacements, prices, OEM part numbers)
4. Keep ALL internal links (anchor + url pairs in paragraph blocks)
5. Keep ALL CTA blocks (paragraphs containing a direct call to action)
6. Do NOT introduce any h1 or h2 blocks
7. Do NOT add new sections not present in input

Trimming strategy: shorten paragraph body text, cut redundant sentences,
tighten FAQ answers. Never cut headings.

Return ONLY the JSON array of blocks. No prose, no markdown fences."""


class WordCountExceededException(Exception):
    """Raised when a blog exceeds HARD_CEILING after all trim attempts."""


def count_words(blocks: list) -> int:
    """Count total words across all blocks (title, headings, paragraphs, FAQ)."""
    total = 0
    for block in blocks:
        text = block.get("text", "")
        if text:
            total += len(text.split())
    return total


def trim_blocks(blocks: list, target: int) -> list:
    """Ask Claude to trim blocks to target word count.

    Returns a new list of blocks in the same schema.
    Raises RuntimeError if the Claude response cannot be parsed as a JSON array.
    """
    user_prompt = (
        f"Target word count: {target} words (±50 is fine).\n\n"
        f"Current blocks:\n{json.dumps(blocks, ensure_ascii=False, indent=2)}"
    )
    response = anthropic_client.call(
        system=_TRIM_SYSTEM,
        user=user_prompt,
        model="claude-sonnet-4-6",
        max_tokens=8000,
    )
    trimmed = anthropic_client.extract_json(response)
    if not isinstance(trimmed, list):
        raise RuntimeError(
            f"trim_blocks: expected JSON array from Claude, got {type(trimmed).__name__}"
        )
    return trimmed


def validate_word_count(blocks: list) -> list:
    """Validate word count and trim if over HARD_CEILING.

    Returns (possibly trimmed) blocks.
    Raises WordCountExceededException if count still exceeds HARD_CEILING
    after MAX_TRIM_ATTEMPTS.
    Does not raise if count is below TARGET_WORDS (short drafts pass through).
    """
    count = count_words(blocks)
    lower = int(TARGET_WORDS * (1 - ACCEPTABLE_RANGE_PCT))
    upper = int(TARGET_WORDS * (1 + ACCEPTABLE_RANGE_PCT))

    logger.info(
        "Word count: %d (target: %d, acceptable: %d–%d, ceiling: %d)",
        count, TARGET_WORDS, lower, upper, HARD_CEILING,
    )

    if count <= HARD_CEILING:
        if count < lower:
            logger.warning("Word count %d is below target range (%d–%d)", count, lower, upper)
        return blocks

    original_count = count
    logger.warning(
        "Word count %d exceeds ceiling %d, triggering trim", count, HARD_CEILING
    )

    for attempt in range(MAX_TRIM_ATTEMPTS):
        trimmed_blocks = trim_blocks(blocks, TARGET_WORDS)
        trimmed_count = count_words(trimmed_blocks)
        logger.info(
            "Trim attempt %d/%d: %d → %d words",
            attempt + 1, MAX_TRIM_ATTEMPTS, count, trimmed_count,
        )
        if trimmed_count <= HARD_CEILING:
            return trimmed_blocks
        blocks = trimmed_blocks
        count = trimmed_count

    raise WordCountExceededException(
        f"Word count {count} still exceeds ceiling {HARD_CEILING} after "
        f"{MAX_TRIM_ATTEMPTS} trim attempt(s). Original: {original_count} words. "
        f"Blog NOT written to Drive."
    )
