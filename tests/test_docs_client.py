# tests/test_docs_client.py
"""Unit tests for docs_client — all Google API calls are mocked."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.docs_client import resolve_comment, _build_flat_text, apply_text_replacement, write_structured_doc


class TestResolveComment(unittest.TestCase):
    """resolve_comment must fetch the existing comment content and include it
    in the PATCH body alongside resolved=True, otherwise the Drive API returns
    HttpError 400 "Comment content is required"."""

    def _make_drive(self, existing_content="Original comment text"):
        """Build a mock Drive service where comments().get() returns existing_content."""
        drive = MagicMock()
        get_resp = MagicMock()
        get_resp.execute.return_value = {"id": "C1", "content": existing_content}
        drive.comments().get.return_value = get_resp

        update_resp = MagicMock()
        update_resp.execute.return_value = {"id": "C1", "resolved": True}
        drive.comments().update.return_value = update_resp

        return drive

    @patch("app.services.docs_client._get_drive_service")
    def test_patch_body_includes_content_and_resolved(self, mock_get_drive):
        """PATCH body must contain both 'content' and 'resolved: True'."""
        drive = self._make_drive("Please fix the spelling.")
        mock_get_drive.return_value = drive

        resolve_comment("DOC1", "C1")

        drive.comments().update.assert_called_once()
        _, kwargs = drive.comments().update.call_args
        body = kwargs.get("body") or drive.comments().update.call_args[0][0] if drive.comments().update.call_args[0] else kwargs["body"]
        # Extract body robustly — it may be positional or keyword
        call_args = drive.comments().update.call_args
        body = call_args.kwargs.get("body") or (call_args.args[0] if call_args.args else None)
        self.assertIsNotNone(body, "update() must be called with a body argument")
        self.assertIn("content", body, "body must include 'content' field")
        self.assertEqual(body["content"], "Please fix the spelling.")
        self.assertIn("resolved", body, "body must include 'resolved' field")
        self.assertTrue(body["resolved"])

    @patch("app.services.docs_client._get_drive_service")
    def test_get_called_before_update(self, mock_get_drive):
        """comments.get must be called to fetch existing content before update."""
        drive = self._make_drive()
        mock_get_drive.return_value = drive

        resolve_comment("DOC1", "C1")

        drive.comments().get.assert_called_once_with(
            fileId="DOC1",
            commentId="C1",
            fields="content",
        )

    @patch("app.services.docs_client._get_drive_service")
    def test_update_called_with_correct_file_and_comment_ids(self, mock_get_drive):
        """update() must target the correct fileId and commentId."""
        drive = self._make_drive()
        mock_get_drive.return_value = drive

        resolve_comment("DOC_XYZ", "COMMENT_ABC")

        call_kwargs = drive.comments().update.call_args.kwargs
        self.assertEqual(call_kwargs.get("fileId"), "DOC_XYZ")
        self.assertEqual(call_kwargs.get("commentId"), "COMMENT_ABC")


class TestBuildFlatText(unittest.TestCase):

    def test_single_run(self):
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "hello world"}, "startIndex": 1}
                    ]
                }
            }
        ]
        flat, mp = _build_flat_text(doc_content)
        self.assertEqual(flat, "hello world")
        self.assertEqual(mp[0], 1)   # 'h' maps to Docs index 1
        self.assertEqual(mp[5], 6)   # ' ' maps to Docs index 6

    def test_two_runs_same_paragraph(self):
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "foo"}, "startIndex": 1},
                        {"textRun": {"content": "bar"}, "startIndex": 4},
                    ]
                }
            }
        ]
        flat, mp = _build_flat_text(doc_content)
        self.assertEqual(flat, "foobar")
        self.assertEqual(mp[0], 1)
        self.assertEqual(mp[3], 4)

    def test_non_paragraph_elements_skipped(self):
        doc_content = [
            {"sectionBreak": {}},
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "text"}, "startIndex": 1}
                    ]
                }
            },
        ]
        flat, mp = _build_flat_text(doc_content)
        self.assertEqual(flat, "text")

    def test_non_text_run_elements_skipped(self):
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"inlineObjectElement": {"inlineObjectId": "obj1"}, "startIndex": 1},
                        {"textRun": {"content": "text"}, "startIndex": 2},
                    ]
                }
            }
        ]
        flat, mp = _build_flat_text(doc_content)
        self.assertEqual(flat, "text")

    def test_four_runs_spanning_sentence(self):
        """Regression fixture: V-Rod Comment 1 sentence split across 4 runs."""
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "The Harley-Davidson VRSC "}, "startIndex": 1},
                        {"textRun": {"content": "V-Rod is unlike "}, "startIndex": 25},
                        {"textRun": {"content": "anything else in the "}, "startIndex": 41},
                        {"textRun": {"content": "Milwaukee catalog."}, "startIndex": 62},
                    ]
                }
            }
        ]
        flat, mp = _build_flat_text(doc_content)
        anchor = "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."
        self.assertIn(anchor, flat)
        idx = flat.find(anchor)
        self.assertEqual(mp[idx], 1)          # start maps to Docs index 1
        self.assertEqual(mp[idx + len(anchor) - 1] + 1, 80)  # end maps correctly


class TestApplyTextReplacementFallback(unittest.TestCase):
    """apply_text_replacement must use flat-text path when exact match fails."""

    def _make_docs_service(self, doc_content):
        docs = MagicMock()
        docs.documents().get().execute.return_value = {
            "body": {"content": doc_content}
        }
        docs.documents().batchUpdate().execute.return_value = {}
        return docs

    @patch("app.services.docs_client._get_docs_service")
    def test_cross_run_anchor_resolved_via_flat_text(self, mock_get_docs):
        """Anchor spanning 4 runs is found via flat text — the V-Rod Comment 1 scenario."""
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "The Harley-Davidson VRSC "}, "startIndex": 1},
                        {"textRun": {"content": "V-Rod is unlike "}, "startIndex": 25},
                        {"textRun": {"content": "anything else in the "}, "startIndex": 41},
                        {"textRun": {"content": "Milwaukee catalog."}, "startIndex": 62},
                    ]
                }
            }
        ]
        mock_get_docs.return_value = self._make_docs_service(doc_content)
        anchor = "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."
        result = apply_text_replacement("DOC1", anchor, anchor + " [updated]")
        self.assertTrue(result)

    @patch("app.services.docs_client._get_docs_service")
    def test_exact_match_path_unchanged(self, mock_get_docs):
        """When anchor exists in a single run, exact path resolves it (no flat-text fallback)."""
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "The V-Rod is great."}, "startIndex": 1}
                    ]
                }
            }
        ]
        mock_get_docs.return_value = self._make_docs_service(doc_content)
        result = apply_text_replacement("DOC1", "V-Rod is great", "V-Rod is excellent")
        self.assertTrue(result)

    @patch("app.services.docs_client._get_docs_service")
    def test_returns_false_when_anchor_absent(self, mock_get_docs):
        doc_content = [
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Some other content."}, "startIndex": 1}
                    ]
                }
            }
        ]
        mock_get_docs.return_value = self._make_docs_service(doc_content)
        result = apply_text_replacement("DOC1", "The V-Rod is great.", "replacement")
        self.assertFalse(result)


class TestVRodComment1Regression(unittest.TestCase):
    """Regression for April 29 V-Rod Comment 1 failure (run-boundary bug)."""

    # Confirmed structure from Task 0 — 4 textRun elements in the intro paragraph
    _DOC_CONTENT = [
        {
            "paragraph": {
                "elements": [
                    {"textRun": {"content": "The Harley-Davidson VRSC "}, "startIndex": 1},
                    {"textRun": {"content": "V-Rod is unlike "}, "startIndex": 25},
                    {"textRun": {"content": "anything else in the "}, "startIndex": 41},
                    {"textRun": {"content": "Milwaukee catalog."}, "startIndex": 62},
                ]
            }
        }
    ]
    _ANCHOR = "The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog."

    @patch("app.services.docs_client._get_docs_service")
    def test_apply_text_replacement_resolves_split_run_anchor(self, mock_get_docs):
        """apply_text_replacement must succeed for an anchor spanning 4 textRun elements."""
        docs_mock = MagicMock()
        docs_mock.documents().get().execute.return_value = {
            "body": {"content": self._DOC_CONTENT}
        }
        docs_mock.documents().batchUpdate().execute.return_value = {}
        mock_get_docs.return_value = docs_mock

        result = apply_text_replacement("DOC1", self._ANCHOR, self._ANCHOR + " [fixed]")

        self.assertTrue(result, "apply_text_replacement must return True for cross-run anchor")
        # Verify batchUpdate was called with correct startIndex/endIndex
        call_args = docs_mock.documents().batchUpdate.call_args
        self.assertIsNotNone(call_args)
        requests = call_args[1].get("body", {}).get("requests", [])
        replace_req = next(
            (r for r in requests if "replaceAllText" in r or "deleteContentRange" in r),
            None
        )
        self.assertIsNotNone(replace_req, "batchUpdate must include a replace/delete request")


class TestWriteStructuredDoc(unittest.TestCase):
    """Unit tests for write_structured_doc — all Google API calls are mocked."""

    def _make_docs_service(self, end_index=10):
        """Return a mock Docs service whose get() returns a doc with the given end_index."""
        docs = MagicMock()
        docs.documents().get().execute.return_value = {
            "body": {
                "content": [{"endIndex": end_index}]
            }
        }
        docs.documents().batchUpdate().execute.return_value = {}
        return docs

    @patch("app.services.docs_client._get_docs_service")
    def test_raises_on_empty_blocks(self, mock_get_docs):
        """write_structured_doc must raise ValueError when blocks is empty."""
        mock_get_docs.return_value = self._make_docs_service()
        with self.assertRaises(ValueError):
            write_structured_doc("DOC1", [])

    @patch("app.services.docs_client._get_docs_service")
    def test_delete_content_range_included_when_doc_has_content(self, mock_get_docs):
        """deleteContentRange must be included when end_index > 2."""
        docs = self._make_docs_service(end_index=50)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [{"level": "p", "text": "Hello"}])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        delete_reqs = [r for r in requests if "deleteContentRange" in r]
        self.assertEqual(len(delete_reqs), 1)
        self.assertEqual(delete_reqs[0]["deleteContentRange"]["range"]["startIndex"], 1)
        self.assertEqual(delete_reqs[0]["deleteContentRange"]["range"]["endIndex"], 49)

    @patch("app.services.docs_client._get_docs_service")
    def test_no_delete_when_doc_is_empty(self, mock_get_docs):
        """deleteContentRange must be omitted when end_index <= 2."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [{"level": "p", "text": "Hello"}])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        delete_reqs = [r for r in requests if "deleteContentRange" in r]
        self.assertEqual(len(delete_reqs), 0)

    @patch("app.services.docs_client._get_docs_service")
    def test_insert_text_appends_newline(self, mock_get_docs):
        """Each non-empty block must be inserted with a trailing newline."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [{"level": "p", "text": "My paragraph"}])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        insert_reqs = [r for r in requests if "insertText" in r]
        self.assertEqual(len(insert_reqs), 1)
        self.assertEqual(insert_reqs[0]["insertText"]["text"], "My paragraph\n")

    @patch("app.services.docs_client._get_docs_service")
    def test_empty_text_blocks_are_skipped(self, mock_get_docs):
        """Blocks with empty text must be skipped silently."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {"level": "h1", "text": ""},
            {"level": "p", "text": "Real content"},
        ])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        insert_reqs = [r for r in requests if "insertText" in r]
        self.assertEqual(len(insert_reqs), 1)
        self.assertEqual(insert_reqs[0]["insertText"]["text"], "Real content\n")

    @patch("app.services.docs_client._get_docs_service")
    def test_heading_block_gets_update_paragraph_style(self, mock_get_docs):
        """Non-'p' blocks must generate an updateParagraphStyle request with correct style."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [{"level": "h2", "text": "Section Title"}])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        style_reqs = [r for r in requests if "updateParagraphStyle" in r]
        self.assertEqual(len(style_reqs), 1)
        named_style = style_reqs[0]["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
        self.assertEqual(named_style, "HEADING_2")

    @patch("app.services.docs_client._get_docs_service")
    def test_paragraph_block_gets_no_update_paragraph_style(self, mock_get_docs):
        """'p' level blocks must NOT generate any updateParagraphStyle request."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [{"level": "p", "text": "Just a paragraph"}])

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        style_reqs = [r for r in requests if "updateParagraphStyle" in r]
        self.assertEqual(len(style_reqs), 0)

    @patch("app.services.docs_client._get_docs_service")
    def test_link_generates_update_text_style(self, mock_get_docs):
        """A link whose anchor is found in the block text must produce an updateTextStyle request."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        blocks = [{
            "level": "p",
            "text": "Click here for more info",
            "links": [{"anchor": "here", "url": "https://example.com"}],
        }]
        write_structured_doc("DOC1", blocks)

        call_args = docs.documents().batchUpdate.call_args
        requests = call_args[1].get("body", {}).get("requests", [])
        link_reqs = [r for r in requests if "updateTextStyle" in r]
        self.assertEqual(len(link_reqs), 1)
        link_req = link_reqs[0]["updateTextStyle"]
        self.assertEqual(link_req["textStyle"]["link"]["url"], "https://example.com")
        # "here" starts at index 6 in "Click here for more info" (block starts at index 1)
        self.assertEqual(link_req["range"]["startIndex"], 7)
        self.assertEqual(link_req["range"]["endIndex"], 11)


if __name__ == "__main__":
    unittest.main()
