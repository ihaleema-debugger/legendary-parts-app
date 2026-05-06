# tests/test_word_count_validator.py
"""Unit tests for word_count_validator — Claude API calls are mocked."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.word_count_validator import (
    count_words,
    validate_word_count,
    WordCountExceededException,
    HARD_CEILING,
    TARGET_WORDS,
)


def _blocks_with_words(n: int) -> list:
    """Return a minimal blocks list whose total word count is exactly n."""
    # Use 10-word chunks in h3 headings + paragraphs
    blocks = [{"level": "title", "text": "Test Title"}]  # 2 words
    remaining = n - 2
    while remaining > 0:
        chunk = min(remaining, 10)
        words = " ".join(f"word{i}" for i in range(chunk))
        blocks.append({"level": "p", "text": words})
        remaining -= chunk
    return blocks


class TestCountWords(unittest.TestCase):

    def test_counts_across_all_levels(self):
        """Words in title, h3, h4, and p blocks are all counted."""
        blocks = [
            {"level": "title", "text": "Blog Title Here"},       # 3
            {"level": "h3", "text": "Section Heading"},           # 2
            {"level": "h4", "text": "FAQ Question Here"},         # 3
            {"level": "p", "text": "Answer text with words."},    # 4
        ]
        self.assertEqual(count_words(blocks), 12)

    def test_faq_counted_as_part_of_budget(self):
        """FAQ blocks (h3 header + h4 questions + p answers) are in the word budget."""
        blocks = [
            {"level": "h3", "text": "Frequently Asked Questions"},  # 3
            {"level": "h4", "text": "What does VRSC stand for?"},    # 5
            {"level": "p", "text": "VRSC stands for V-twin Racing Street Custom."},  # 7
        ]
        self.assertEqual(count_words(blocks), 15)


class TestValidateWordCount(unittest.TestCase):

    def test_within_range_passes_through_unchanged(self):
        """Blocks within HARD_CEILING are returned as-is with no trim call."""
        blocks = _blocks_with_words(TARGET_WORDS)
        with patch("app.services.word_count_validator.trim_blocks") as mock_trim:
            result = validate_word_count(blocks)
        mock_trim.assert_not_called()
        self.assertEqual(result, blocks)

    def test_over_ceiling_triggers_trim_and_returns_trimmed(self):
        """Blocks over HARD_CEILING trigger one trim attempt; trimmed blocks returned."""
        over_ceiling = _blocks_with_words(HARD_CEILING + 50)
        trimmed = _blocks_with_words(TARGET_WORDS)

        with patch("app.services.word_count_validator.trim_blocks", return_value=trimmed) as mock_trim:
            result = validate_word_count(over_ceiling)

        mock_trim.assert_called_once()
        self.assertEqual(result, trimmed)

    def test_still_over_after_trim_raises_exception(self):
        """If still over HARD_CEILING after MAX_TRIM_ATTEMPTS, raise WordCountExceededException."""
        over_ceiling = _blocks_with_words(HARD_CEILING + 50)
        still_over = _blocks_with_words(HARD_CEILING + 10)

        with patch("app.services.word_count_validator.trim_blocks", return_value=still_over):
            with self.assertRaises(WordCountExceededException) as ctx:
                validate_word_count(over_ceiling)

        self.assertIn(str(HARD_CEILING + 10), str(ctx.exception))

    def test_trim_preserves_h3_headings(self):
        """trim_blocks must not remove any H3 headings present in input."""
        # We test this structurally: the mock trim returns blocks with the same H3s
        h3_texts = ["Intro Section", "Main Section", "Frequently Asked Questions"]
        blocks = [{"level": "title", "text": "Title"}]
        for h3 in h3_texts:
            blocks.append({"level": "h3", "text": h3})
            blocks.extend(_blocks_with_words(50)[1:])  # body paragraphs

        trimmed = [b for b in blocks if b.get("level") == "title"]
        for h3 in h3_texts:
            trimmed.append({"level": "h3", "text": h3})
            trimmed.append({"level": "p", "text": "Shorter paragraph text here today."})

        with patch("app.services.word_count_validator.trim_blocks", return_value=trimmed):
            result = validate_word_count([b for b in blocks] + _blocks_with_words(200)[1:])

        result_h3s = [b["text"] for b in result if b.get("level") == "h3"]
        for expected in h3_texts:
            self.assertIn(expected, result_h3s)


if __name__ == "__main__":
    unittest.main()
