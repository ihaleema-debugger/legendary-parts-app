# tests/test_docs_client.py
"""Unit tests for docs_client — all Google API calls are mocked."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.docs_client import resolve_comment


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


if __name__ == "__main__":
    unittest.main()
