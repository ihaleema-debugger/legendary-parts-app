"""Tests for anchor_matcher — Layer 1 normalization fallback."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.anchor_matcher import _normalize_with_map, _layer1, find_span


class TestNormalizeWithMap(unittest.TestCase):

    def test_plain_text_unchanged(self):
        norm, mp = _normalize_with_map("hello world")
        self.assertEqual(norm, "hello world")
        self.assertEqual(mp, list(range(11)))

    def test_collapses_double_space(self):
        norm, mp = _normalize_with_map("foo  bar")
        self.assertEqual(norm, "foo bar")
        self.assertEqual(mp, [0, 1, 2, 3, 5, 6, 7])

    def test_collapses_nbsp(self):
        norm, mp = _normalize_with_map("V\xa0Rod")
        self.assertEqual(norm, "V Rod")
        # NBSP is a single char at index 1; 'R' follows at index 2
        self.assertEqual(mp, [0, 1, 2, 3, 4])

    def test_collapses_tab(self):
        norm, mp = _normalize_with_map("a\tb")
        self.assertEqual(norm, "a b")
        self.assertEqual(mp, [0, 1, 2])

    def test_curly_single_quotes_to_straight(self):
        norm, mp = _normalize_with_map("‘hello’")
        self.assertEqual(norm, "'hello'")
        self.assertEqual(mp, list(range(7)))

    def test_curly_double_quotes_to_straight(self):
        norm, _ = _normalize_with_map("“hello”")
        self.assertEqual(norm, '"hello"')

    def test_em_dash_to_hyphen(self):
        norm, _ = _normalize_with_map("foo—bar")
        self.assertEqual(norm, "foo-bar")

    def test_en_dash_to_hyphen(self):
        norm, _ = _normalize_with_map("foo–bar")
        self.assertEqual(norm, "foo-bar")

    def test_nfc_normalization(self):
        import unicodedata
        decomposed = "é"  # NFD: e + combining acute
        norm, _ = _normalize_with_map(decomposed)
        self.assertEqual(norm, unicodedata.normalize("NFC", decomposed))

    def test_mixed_whitespace_run(self):
        norm, mp = _normalize_with_map("a \t\xa0b")
        self.assertEqual(norm, "a b")
        self.assertEqual(mp, [0, 1, 4])


class TestLayer1(unittest.TestCase):

    # Regression: Comment 1 failure from April 29 run (V-Rod card).
    # Root cause confirmed 2026-05-04: NOT a character divergence.
    # Anchor and doc text were character-for-character identical.
    # Real bug: sentence spanned 4 textRun elements; _find_text_occurrences
    # searched run-by-run so no single run contained the full string.
    # The structural fix (_build_flat_text in Task 1) resolves the actual bug.
    # Layer 1 resolves it on the assembled flat text (exact match, no normalization needed).
    _REGRESSION_ANCHOR = (
        "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."
    )
    _REGRESSION_DOC = (
        "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."
    )

    def test_regression_comment1_split_textrun(self):
        """Layer 1 finds exact match on flat text (identical strings, run-boundary was the real bug)."""
        span = _layer1(self._REGRESSION_DOC, self._REGRESSION_ANCHOR)
        self.assertIsNotNone(span)
        start, end = span
        self.assertIn("V-Rod", self._REGRESSION_DOC[start:end])
        self.assertIn("Milwaukee catalog", self._REGRESSION_DOC[start:end])

    def test_exact_match_still_works(self):
        doc = "The engine produces 115 hp."
        span = _layer1(doc, "engine produces 115 hp")
        self.assertIsNotNone(span)
        start, end = span
        self.assertIn("engine produces 115 hp", doc[start:end])

    def test_double_space_in_doc(self):
        span = _layer1("V-Rod   specifications are generous.", "V-Rod specifications are generous.")
        self.assertIsNotNone(span)

    def test_nbsp_in_doc(self):
        span = _layer1("fits\xa0Softail models.", "fits Softail models.")
        self.assertIsNotNone(span)

    def test_curly_quote_in_doc(self):
        span = _layer1("Harley’s V-Rod engine", "Harley's V-Rod engine")
        self.assertIsNotNone(span)

    def test_em_dash_in_doc(self):
        span = _layer1("high-output—115 hp", "high-output-115 hp")
        self.assertIsNotNone(span)

    def test_returns_correct_span_bounds(self):
        doc = "prefix. Target sentence here. suffix."
        span = _layer1(doc, "Target sentence here.")
        self.assertIsNotNone(span)
        start, end = span
        self.assertEqual(doc[start:end], "Target sentence here.")

    def test_no_match_returns_none(self):
        span = _layer1("completely unrelated content", "The Harley-Davidson V-Rod")
        self.assertIsNone(span)


class TestFindSpan(unittest.TestCase):

    def test_exact_match(self):
        doc = "The engine produces 115 hp at 8,250 rpm."
        span = find_span(doc, "engine produces 115 hp at 8,250 rpm")
        self.assertIsNotNone(span)

    def test_nbsp_via_layer1(self):
        doc = "The Harley-Davidson VRSC\xa0V-Rod is unlike anything else in the Milwaukee catalog."
        anchor = "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."
        span = find_span(doc, anchor)
        self.assertIsNotNone(span)
        start, end = span
        self.assertIn("Milwaukee catalog", doc[start:end])

    def test_no_match_returns_none(self):
        span = find_span("The Softail lineup has many variants.", "The Dyna lineup is discontinued.")
        self.assertIsNone(span)


if __name__ == "__main__":
    unittest.main()
