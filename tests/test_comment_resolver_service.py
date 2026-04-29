"""Unit tests for comment_resolver_service — all external calls are mocked."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.comment_resolver_service import (
    _classify_comment,
    _generate_direct_edit,
    build_trello_summary,
    resolve_comments,
)
from app.services.trello_state import TrelloState


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _state():
    """Return a TrelloState backed by a fresh temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return TrelloState(db_path=tmp.name)


def _make_comment(
    comment_id="C1",
    quoted_text="Twin Cam engine",
    body="V-Rod uses Revolution engine, not Twin Cam",
    anchor="",
    paragraph_context="The V-Rod is powered by the Twin Cam engine.",
):
    return {
        "id": comment_id,
        "quoted_text": quoted_text,
        "body": body,
        "anchor": anchor,
        "paragraph_context": paragraph_context,
    }


# ── Classification ────────────────────────────────────────────────────────────

class TestClassifyComment(unittest.TestCase):
    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.anthropic_client.extract_json")
    def test_classifies_direct(self, mock_extract, mock_call):
        mock_call.return_value = '{"category": "direct", "reasoning": "explicit replacement"}'
        mock_extract.return_value = {"category": "direct", "reasoning": "explicit replacement"}

        category, reasoning = _classify_comment(
            "Change X to Y", "X", "paragraph with X", "claude-sonnet-4-5"
        )

        self.assertEqual(category, "direct")
        self.assertEqual(reasoning, "explicit replacement")

    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.anthropic_client.extract_json")
    def test_classifies_interpretive(self, mock_extract, mock_call):
        mock_call.return_value = '{"category": "interpretive", "reasoning": "vague flag"}'
        mock_extract.return_value = {"category": "interpretive", "reasoning": "vague flag"}

        category, _ = _classify_comment(
            "this sounds awkward", "some text", "paragraph", "claude-sonnet-4-5"
        )

        self.assertEqual(category, "interpretive")

    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.anthropic_client.extract_json")
    def test_unknown_category_defaults_to_interpretive(self, mock_extract, mock_call):
        mock_call.return_value = '{"category": "unknown", "reasoning": "?"}'
        mock_extract.return_value = {"category": "unknown", "reasoning": "?"}

        category, _ = _classify_comment("comment", "text", "ctx", "claude-sonnet-4-5")

        self.assertEqual(category, "interpretive")


# ── Direct edit application ───────────────────────────────────────────────────

class TestApplyDirectEdit(unittest.TestCase):
    @patch("app.services.comment_resolver_service.resolve_doc_comment")
    @patch("app.services.comment_resolver_service.apply_text_replacement")
    @patch("app.services.comment_resolver_service.anthropic_client.extract_json")
    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.get_unresolved_comments")
    def test_direct_comment_applies_replacement_and_resolves(
        self, mock_get, mock_call, mock_extract, mock_apply, mock_resolve
    ):
        mock_get.return_value = [_make_comment()]
        # First call = classify, second call = generate replacement
        mock_call.side_effect = [
            '{"category": "direct", "reasoning": "explicit"}',
            "Revolution engine",
        ]
        mock_extract.return_value = {"category": "direct", "reasoning": "explicit"}
        mock_apply.return_value = True

        state = _state()
        direct, interpretive, skipped = resolve_comments("DOC1", state, "claude-sonnet-4-5")

        self.assertEqual(len(direct), 1)
        self.assertEqual(len(interpretive), 0)
        self.assertEqual(len(skipped), 0)
        mock_apply.assert_called_once_with("DOC1", "Twin Cam engine", "Revolution engine", "")
        mock_resolve.assert_called_once_with("DOC1", "C1")

    @patch("app.services.comment_resolver_service.resolve_doc_comment")
    @patch("app.services.comment_resolver_service.apply_text_replacement")
    @patch("app.services.comment_resolver_service.anthropic_client.extract_json")
    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.get_unresolved_comments")
    def test_text_not_found_skips_comment(
        self, mock_get, mock_call, mock_extract, mock_apply, mock_resolve
    ):
        mock_get.return_value = [_make_comment()]
        mock_call.side_effect = [
            '{"category": "direct", "reasoning": "explicit"}',
            "Revolution engine",
        ]
        mock_extract.return_value = {"category": "direct", "reasoning": "explicit"}
        mock_apply.return_value = False  # text not found

        state = _state()
        direct, interpretive, skipped = resolve_comments("DOC1", state, "claude-sonnet-4-5")

        self.assertEqual(len(direct), 0)
        self.assertEqual(len(skipped), 1)
        mock_resolve.assert_not_called()


# ── Zero-comments case ────────────────────────────────────────────────────────

class TestZeroComments(unittest.TestCase):
    @patch("app.services.comment_resolver_service.get_unresolved_comments")
    def test_zero_comments_returns_empty_tuples_without_calling_claude(self, mock_get):
        mock_get.return_value = []

        state = _state()
        with patch("app.services.comment_resolver_service.anthropic_client.call") as mock_call:
            direct, interpretive, skipped = resolve_comments("DOC1", state, "claude-sonnet-4-5")
            mock_call.assert_not_called()

        self.assertEqual(direct, [])
        self.assertEqual(interpretive, [])
        self.assertEqual(skipped, [])


# ── Anthropic API failure graceful handling ───────────────────────────────────

class TestAnthropicFailure(unittest.TestCase):
    @patch("app.services.comment_resolver_service.resolve_doc_comment")
    @patch("app.services.comment_resolver_service.apply_text_replacement")
    @patch("app.services.comment_resolver_service.anthropic_client.call")
    @patch("app.services.comment_resolver_service.get_unresolved_comments")
    def test_anthropic_failure_on_first_comment_skips_it_continues_to_second(
        self, mock_get, mock_call, mock_apply, mock_resolve
    ):
        comment_1 = _make_comment("C1", "text one", "comment one")
        comment_2 = _make_comment("C2", "text two", "comment two", paragraph_context="paragraph with text two")
        mock_get.return_value = [comment_1, comment_2]

        # C1 classify call raises; C2 classify + generate succeed
        mock_call.side_effect = [
            RuntimeError("API timeout"),                            # C1 classify fails
            '{"category": "direct", "reasoning": "ok"}',          # C2 classify
            "revised two",                                         # C2 generate
        ]

        with patch(
            "app.services.comment_resolver_service.anthropic_client.extract_json",
            return_value={"category": "direct", "reasoning": "ok"},
        ):
            mock_apply.return_value = True
            state = _state()
            direct, interpretive, skipped = resolve_comments("DOC1", state, "claude-sonnet-4-5")

        self.assertEqual(len(skipped), 1)
        self.assertIn("C1", skipped)
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]["comment_id"], "C2")

    @patch("app.services.comment_resolver_service.get_unresolved_comments")
    def test_all_comments_fail_returns_all_skipped(self, mock_get):
        mock_get.return_value = [_make_comment("C1"), _make_comment("C2")]

        with patch(
            "app.services.comment_resolver_service.anthropic_client.call",
            side_effect=RuntimeError("network error"),
        ):
            state = _state()
            direct, interpretive, skipped = resolve_comments("DOC1", state, "claude-sonnet-4-5")

        self.assertEqual(len(skipped), 2)
        self.assertEqual(len(direct), 0)
        self.assertEqual(len(interpretive), 0)


# ── Trello summary formatting ─────────────────────────────────────────────────

class TestBuildTrelloSummary(unittest.TestCase):
    def _direct(self, original="old text", revised="new text", reasoning="factual fix"):
        return {"comment_id": "C1", "original": original, "revised": revised, "reasoning": reasoning}

    def _interpretive(self, original="awkward phrase", revised="better phrase", reasoning="research done"):
        return {"comment_id": "C2", "original": original, "revised": revised, "reasoning": reasoning}

    def test_success_header_present(self):
        summary = build_trello_summary([self._direct()], [], 0)
        self.assertIn("✅ Comment resolution complete.", summary)
        self.assertIn("1 direct edit(s) applied", summary)
        self.assertIn("0 interpretive revision(s)", summary)

    def test_direct_edit_arrow_format(self):
        summary = build_trello_summary([self._direct("old text", "new text")], [], 0)
        self.assertIn("old text → new text", summary)

    def test_interpretive_includes_reasoning(self):
        summary = build_trello_summary([], [self._interpretive(reasoning="used web search")], 0)
        self.assertIn("better phrase", summary)
        self.assertIn("Reasoning: used web search", summary)

    def test_skipped_count_shown(self):
        summary = build_trello_summary([], [], 3)
        self.assertIn("3 comment(s) skipped", summary)

    def test_long_text_truncated(self):
        long_text = "a" * 80
        summary = build_trello_summary([self._direct(original=long_text, revised="short")], [], 0)
        # Should contain the truncated version (60 chars + ellipsis)
        self.assertIn("a" * 60 + "…", summary)

    def test_no_comments_at_all_still_shows_zeros(self):
        summary = build_trello_summary([], [], 0)
        self.assertIn("0 direct edit(s)", summary)
        self.assertIn("0 interpretive revision(s)", summary)


if __name__ == "__main__":
    unittest.main()
