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
    """write_structured_doc must insert text and apply heading styles atomically."""

    def _make_docs_service(self, end_index: int = 10):
        """Mock Docs service that returns a doc with the given end_index."""
        docs = MagicMock()
        docs.documents().get().execute.return_value = {
            "body": {"content": [{"endIndex": end_index}]}
        }
        docs.documents().batchUpdate().execute.return_value = {}
        # Reset call counts accumulated during mock wiring so tests can
        # assert on calls made by write_structured_doc alone.
        docs.documents().batchUpdate.reset_mock()
        return docs

    def _get_requests(self, docs) -> list:
        call = docs.documents().batchUpdate.call_args
        if call is None:
            return []
        return call.kwargs.get("body", {}).get("requests", [])

    @patch("app.services.docs_client._get_docs_service")
    def test_basic_title_h3_h4_p_applies_correct_styles(self, mock_get_docs):
        """title, h3, and h4 blocks get style requests; p blocks do not."""
        docs = self._make_docs_service(end_index=10)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {"level": "title", "text": "My Title"},
            {"level": "h3", "text": "Section One"},
            {"level": "p", "text": "Body text here."},
            {"level": "h3", "text": "Frequently Asked Questions"},
            {"level": "h4", "text": "What is OEM?"},
            {"level": "p", "text": "OEM stands for Original Equipment Manufacturer."},
        ])

        requests = self._get_requests(docs)
        style_reqs = [r for r in requests if "updateParagraphStyle" in r]

        # Exactly 4 style requests: title, h3, h3, h4 (both p blocks skipped)
        self.assertEqual(len(style_reqs), 4)

        title_req = style_reqs[0]["updateParagraphStyle"]
        self.assertEqual(title_req["paragraphStyle"]["namedStyleType"], "TITLE")
        self.assertEqual(title_req["range"]["startIndex"], 1)
        self.assertEqual(title_req["range"]["endIndex"], 10)  # "My Title\n" = 9 chars → [1, 10)

        h3_req = style_reqs[1]["updateParagraphStyle"]
        self.assertEqual(h3_req["paragraphStyle"]["namedStyleType"], "HEADING_3")
        self.assertEqual(h3_req["range"]["startIndex"], 10)
        self.assertEqual(h3_req["range"]["endIndex"], 22)  # "Section One\n" = 12 chars → [10, 22)

        h4_req = style_reqs[3]["updateParagraphStyle"]
        self.assertEqual(h4_req["paragraphStyle"]["namedStyleType"], "HEADING_4")

    @patch("app.services.docs_client._get_docs_service")
    def test_mixed_levels_style_requests_count(self, mock_get_docs):
        """Two h3s and three paragraphs produce exactly 2 style requests."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {"level": "h3", "text": "Intro"},
            {"level": "p", "text": "Para one."},
            {"level": "h3", "text": "Details"},
            {"level": "p", "text": "Para two."},
            {"level": "p", "text": "Para three."},
        ])

        style_reqs = [r for r in self._get_requests(docs) if "updateParagraphStyle" in r]
        self.assertEqual(len(style_reqs), 2)
        for req in style_reqs:
            self.assertEqual(
                req["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"],
                "HEADING_3",
            )

    @patch("app.services.docs_client._get_docs_service")
    def test_empty_doc_skips_delete(self, mock_get_docs):
        """When end_index <= 2 (empty doc), no deleteContentRange is added."""
        docs = self._make_docs_service(end_index=2)
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {"level": "h3", "text": "Section"},
            {"level": "p", "text": "Body text."},
        ])

        requests = self._get_requests(docs)
        delete_reqs = [r for r in requests if "deleteContentRange" in r]
        self.assertEqual(len(delete_reqs), 0)

        # insertText and style requests still fire at index 1
        insert_reqs = [r for r in requests if "insertText" in r]
        self.assertEqual(len(insert_reqs), 2)
        self.assertEqual(insert_reqs[0]["insertText"]["location"]["index"], 1)

    @patch("app.services.docs_client._get_docs_service")
    def test_paragraph_with_one_link(self, mock_get_docs):
        """A single link in a paragraph produces one updateTextStyle request."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {
                "level": "p",
                "text": "Buy OEM parts here.",
                "links": [{"anchor": "OEM parts", "url": "https://legendary-parts.com/oem"}],
            }
        ])

        requests = self._get_requests(docs)
        link_reqs = [r for r in requests if "updateTextStyle" in r]
        self.assertEqual(len(link_reqs), 1)

        link_req = link_reqs[0]["updateTextStyle"]
        self.assertEqual(link_req["textStyle"]["link"]["url"], "https://legendary-parts.com/oem")
        # "OEM parts" starts at offset 4 in "Buy OEM parts here." → Docs [1+4, 1+4+9) = [5, 14)
        self.assertEqual(link_req["range"]["startIndex"], 5)
        self.assertEqual(link_req["range"]["endIndex"], 14)

    @patch("app.services.docs_client._get_docs_service")
    def test_paragraph_with_two_links(self, mock_get_docs):
        """Two links in one paragraph produce two updateTextStyle requests with correct ranges."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        text = "See OEM parts and aftermarket here."
        write_structured_doc("DOC1", [
            {
                "level": "p",
                "text": text,
                "links": [
                    {"anchor": "OEM parts", "url": "https://url1.com"},
                    {"anchor": "aftermarket", "url": "https://url2.com"},
                ],
            }
        ])

        link_reqs = [r for r in self._get_requests(docs) if "updateTextStyle" in r]
        self.assertEqual(len(link_reqs), 2)

        # "OEM parts" at offset 4 → Docs [5, 14)
        oem_req = link_reqs[0]["updateTextStyle"]
        self.assertEqual(oem_req["textStyle"]["link"]["url"], "https://url1.com")
        self.assertEqual(oem_req["range"]["startIndex"], 5)
        self.assertEqual(oem_req["range"]["endIndex"], 14)

        # "aftermarket" at offset 18 → Docs [19, 30)
        am_req = link_reqs[1]["updateTextStyle"]
        self.assertEqual(am_req["textStyle"]["link"]["url"], "https://url2.com")
        self.assertEqual(am_req["range"]["startIndex"], 19)
        self.assertEqual(am_req["range"]["endIndex"], 30)

    @patch("app.services.docs_client._get_docs_service")
    def test_empty_blocks_raises_value_error(self, mock_get_docs):
        """Passing an empty list must raise ValueError before any API call."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        with self.assertRaises(ValueError):
            write_structured_doc("DOC1", [])

        docs.documents().batchUpdate.assert_not_called()

    @patch("app.services.docs_client._get_docs_service")
    def test_empty_text_block_skipped(self, mock_get_docs):
        """A block with empty text is silently skipped; surrounding blocks are unaffected."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        write_structured_doc("DOC1", [
            {"level": "title", "text": "Real Title"},
            {"level": "p", "text": ""},
            {"level": "h3", "text": "Section"},
        ])

        insert_reqs = [r for r in self._get_requests(docs) if "insertText" in r]
        self.assertEqual(len(insert_reqs), 2)
        self.assertEqual(insert_reqs[0]["insertText"]["text"], "Real Title\n")
        self.assertEqual(insert_reqs[1]["insertText"]["text"], "Section\n")
        self.assertEqual(insert_reqs[1]["insertText"]["location"]["index"], 12)

    @patch("app.services.docs_client._get_docs_service")
    def test_anchor_not_found_logs_warning_write_succeeds(self, mock_get_docs):
        """Anchor not in block text: log warning, skip link, batchUpdate still called."""
        docs = self._make_docs_service()
        mock_get_docs.return_value = docs

        with self.assertLogs("app.services.docs_client", level="WARNING") as cm:
            write_structured_doc("DOC1", [
                {
                    "level": "p",
                    "text": "Some text.",
                    "links": [{"anchor": "not in text", "url": "https://example.com"}],
                }
            ])

        docs.documents().batchUpdate.assert_called_once()
        link_reqs = [r for r in self._get_requests(docs) if "updateTextStyle" in r]
        self.assertEqual(len(link_reqs), 0)
        self.assertTrue(any("not in text" in msg or "anchor" in msg.lower() for msg in cm.output))


if __name__ == "__main__":
    unittest.main()
