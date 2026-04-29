# tests/test_comment_resolution.py
"""Integration tests for comment_resolution — all I/O is mocked."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.comment_resolution import (
    resolve_all_comments,
    format_stage9_summary,
    DRIVE_RESOLVE_FAILURE_NOTE,
)


def _comment(cid="C1", quoted="Twin Cam engine", body="fix this", anchor="",
             para="The V-Rod is powered by the Twin Cam engine."):
    return {"id": cid, "quoted_text": quoted, "body": body, "anchor": anchor,
            "paragraph_context": para}


def _resolution(action="replace", anchor_text="Twin Cam engine",
                replacement_text="Revolution engine", confidence="high",
                rationale="Factual correction."):
    return {"action": action, "anchor_text": anchor_text,
            "replacement_text": replacement_text, "confidence": confidence,
            "rationale": rationale}


class TestNoComments(unittest.TestCase):
    @patch("app.services.comment_resolution.get_unresolved_comments", return_value=[])
    def test_empty_returns_empty_summary(self, _):
        result = resolve_all_comments("DOC1")
        self.assertEqual(result, {"applied": [], "flagged_low_confidence": [], "failed": []})

    @patch("app.services.comment_resolution.get_unresolved_comments", return_value=[])
    def test_empty_does_not_call_resolver(self, _):
        with patch("app.services.comment_resolution.claude_code_resolver.resolve_comment") as m:
            resolve_all_comments("DOC1")
            m.assert_not_called()


class TestHighConfidence(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_high_confidence_goes_to_applied(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(confidence="high")
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(result["applied"][0]["comment_id"], "C1")
        self.assertEqual(len(result["flagged_low_confidence"]), 0)
        self.assertEqual(len(result["failed"]), 0)

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_medium_confidence_goes_to_applied(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(confidence="medium")
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["flagged_low_confidence"]), 0)

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_apply_called_with_correct_args(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment(anchor="anchor-json")]
        mock_cr.return_value = _resolution(anchor_text="Twin Cam engine",
                                            replacement_text="Revolution engine")
        resolve_all_comments("DOC1")
        mock_apply.assert_called_once_with(
            "DOC1", "Twin Cam engine", "Revolution engine", "anchor-json"
        )

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_resolve_doc_comment_called(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution()
        resolve_all_comments("DOC1")
        mock_rd.assert_called_once_with("DOC1", "C1")


class TestLowConfidence(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_low_confidence_goes_to_flagged(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(confidence="low")
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["flagged_low_confidence"]), 1)
        self.assertEqual(len(result["applied"]), 0)

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_low_confidence_edit_still_applied(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(confidence="low")
        resolve_all_comments("DOC1")
        mock_apply.assert_called_once()
        mock_rd.assert_called_once_with("DOC1", "C1")

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_low_confidence_note_contains_low_confidence(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(confidence="low", rationale="Uncertain.")
        result = resolve_all_comments("DOC1")
        self.assertIn("low confidence", result["flagged_low_confidence"][0]["note"].lower())


class TestResolverNone(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement")
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment",
           return_value=None)
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_resolver_none_goes_to_failed(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["failed"]), 1)
        mock_apply.assert_not_called()
        mock_rd.assert_not_called()

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_first_fails_loop_continues_to_second(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment("C1", "text one"), _comment("C2", "text two")]
        mock_cr.side_effect = [None, _resolution(anchor_text="text two",
                                                  replacement_text="improved")]
        result = resolve_all_comments("DOC1")
        self.assertEqual(result["failed"][0]["comment_id"], "C1")
        self.assertEqual(result["applied"][0]["comment_id"], "C2")


class TestNoopAction(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement")
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_noop_resolves_comment_silently_no_list_entry(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution(action="noop")
        result = resolve_all_comments("DOC1")
        mock_apply.assert_not_called()
        mock_rd.assert_called_once_with("DOC1", "C1")
        self.assertEqual(result, {"applied": [], "flagged_low_confidence": [], "failed": []})


class TestApplyFails(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=False)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_apply_false_goes_to_failed_comment_not_resolved(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution()
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["failed"]), 1)
        mock_rd.assert_not_called()

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement")
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_apply_false_loop_continues(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment("C1"), _comment("C2")]
        mock_cr.return_value = _resolution()
        mock_apply.side_effect = [False, True]
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(len(result["applied"]), 1)


class TestInsertAction(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_insert_passes_combined_string_to_apply(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment(anchor="anchor-json")]
        mock_cr.return_value = _resolution(
            action="insert",
            anchor_text="the Twin Cam engine",
            replacement_text=" (which is actually Revolution)",
            confidence="high",
        )
        resolve_all_comments("DOC1")
        mock_apply.assert_called_once_with(
            "DOC1",
            "the Twin Cam engine",
            "the Twin Cam engine (which is actually Revolution)",
            "anchor-json",
        )


class TestDriveResolveFails(unittest.TestCase):
    @patch("app.services.comment_resolution.resolve_doc_comment",
           side_effect=Exception("Drive API error"))
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_drive_resolve_exception_routes_to_failed(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution()
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["failed"]), 1)
        self.assertIn("could not resolve in Drive", result["failed"][0]["note"])

    @patch("app.services.comment_resolution.resolve_doc_comment",
           side_effect=Exception("Drive API error"))
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_drive_resolve_exception_does_not_add_to_applied(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment()]
        mock_cr.return_value = _resolution()
        result = resolve_all_comments("DOC1")
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["flagged_low_confidence"]), 0)

    @patch("app.services.comment_resolution.resolve_doc_comment")
    @patch("app.services.comment_resolution.apply_text_replacement", return_value=True)
    @patch("app.services.comment_resolution.claude_code_resolver.resolve_comment")
    @patch("app.services.comment_resolution.get_unresolved_comments")
    def test_loop_continues_after_drive_resolve_failure(self, mock_get, mock_cr, mock_apply, mock_rd):
        mock_get.return_value = [_comment("C1"), _comment("C2")]
        mock_cr.return_value = _resolution()
        mock_rd.side_effect = [Exception("Drive error"), None]
        result = resolve_all_comments("DOC1")
        self.assertEqual(result["failed"][0]["comment_id"], "C1")
        self.assertEqual(result["applied"][0]["comment_id"], "C2")

    def test_drive_resolve_failure_note_constant_exists(self):
        self.assertIn("could not resolve in Drive", DRIVE_RESOLVE_FAILURE_NOTE)


class TestFormatStage9Summary(unittest.TestCase):
    def test_header_always_present(self):
        s = format_stage9_summary({"applied": [], "flagged_low_confidence": [], "failed": []})
        self.assertIn("Stage 9", s)
        self.assertIn("Comment Resolution complete", s)

    def test_translation_triggered_by_default(self):
        s = format_stage9_summary({"applied": [], "flagged_low_confidence": [], "failed": []})
        self.assertIn("Translation triggered", s)

    def test_translation_paused_when_flagged(self):
        s = format_stage9_summary(
            {"applied": [], "flagged_low_confidence": [], "failed": []},
            translation_triggered=False,
        )
        self.assertNotIn("Translation triggered", s)
        self.assertIn("Translation paused", s)

    def test_empty_sections_omitted(self):
        s = format_stage9_summary({"applied": [], "flagged_low_confidence": [], "failed": []})
        self.assertNotIn("Applied (", s)
        self.assertNotIn("Flagged for review (", s)
        self.assertNotIn("Failed (", s)

    def test_applied_section_shown_when_nonempty(self):
        summary = {"applied": [{"comment_id": "C1", "anchor_preview": "old text", "note": "fix"}],
                   "flagged_low_confidence": [], "failed": []}
        s = format_stage9_summary(summary)
        self.assertIn("Applied (1)", s)
        self.assertIn("old text", s)
        self.assertIn("→", s)

    def test_flagged_section_shown_when_nonempty(self):
        summary = {"applied": [],
                   "flagged_low_confidence": [{"comment_id": "C2", "anchor_preview": "phrase",
                                               "note": "vague (low confidence)"}],
                   "failed": []}
        s = format_stage9_summary(summary)
        self.assertIn("Flagged for review (1)", s)

    def test_failed_section_shown_when_nonempty(self):
        summary = {"applied": [], "flagged_low_confidence": [],
                   "failed": [{"comment_id": "C3", "anchor_preview": "text", "note": "timeout"}]}
        s = format_stage9_summary(summary)
        self.assertIn("Failed (1)", s)
        self.assertIn("timeout", s)


if __name__ == "__main__":
    unittest.main()
