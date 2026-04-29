# tests/test_trello_gate_stage9.py
"""Test poll_once() Drive-resolve failure handling: untick checkboxes, block translation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.comment_resolution import DRIVE_RESOLVE_FAILURE_NOTE


def _make_validated_row():
    return {"doc_id": "DOC1", "card_id": "CARD1", "blog_title": "Test Blog"}


def _make_validated_checklist():
    return {"Validated by Haleema": True, "Validated by Jeremy": True}


def _run_poll(summary):
    from trello_gate import poll_once

    mock_state = MagicMock()
    mock_state.get_pending.return_value = [_make_validated_row()]

    mock_client = MagicMock()
    mock_client.get_card_checklist_state.return_value = _make_validated_checklist()

    with patch("trello_gate.resolve_all_comments", return_value=summary), \
         patch("trello_gate.format_stage9_summary", return_value="summary text"), \
         patch("trello_gate._run_translation") as mock_translation, \
         patch.dict("os.environ", {
             "TRELLO_TRANSLATING_LIST_NAME": "Doing",
             "TRELLO_CHECKLIST_ITEM_1": "Validated by Haleema",
             "TRELLO_CHECKLIST_ITEM_2": "Validated by Jeremy",
         }):
        poll_once(state=mock_state, client=mock_client)

    return mock_state, mock_client, mock_translation


class TestDriveResolveFailureInPollOnce(unittest.TestCase):
    def _drive_resolve_summary(self):
        return {
            "applied": [],
            "flagged_low_confidence": [],
            "failed": [{"comment_id": "C1", "anchor_preview": "text",
                         "note": DRIVE_RESOLVE_FAILURE_NOTE}],
        }

    def test_drive_resolve_failure_resets_db_to_pending(self):
        mock_state, _, mock_translation = _run_poll(self._drive_resolve_summary())
        mock_state.reset_to_pending.assert_called_once_with("DOC1")

    def test_drive_resolve_failure_blocks_translation(self):
        _, _, mock_translation = _run_poll(self._drive_resolve_summary())
        mock_translation.assert_not_called()

    def test_drive_resolve_failure_unticks_checklist(self):
        _, mock_client, _ = _run_poll(self._drive_resolve_summary())
        mock_client.uncheck_all_checklist_items.assert_called_once_with("CARD1")

    def test_normal_failure_does_not_block_translation(self):
        summary = {
            "applied": [{"comment_id": "C2", "anchor_preview": "t2", "note": "fixed"}],
            "flagged_low_confidence": [],
            "failed": [{"comment_id": "C1", "anchor_preview": "t1",
                         "note": "resolver failed (timeout, non-zero exit, or malformed JSON)"}],
        }
        mock_state, mock_client, mock_translation = _run_poll(summary)
        mock_state.reset_to_pending.assert_not_called()
        mock_client.uncheck_all_checklist_items.assert_not_called()
        mock_translation.assert_called_once_with("DOC1")

    def test_no_failures_triggers_translation(self):
        summary = {
            "applied": [{"comment_id": "C1", "anchor_preview": "text", "note": "fix"}],
            "flagged_low_confidence": [],
            "failed": [],
        }
        mock_state, mock_client, mock_translation = _run_poll(summary)
        mock_state.reset_to_pending.assert_not_called()
        mock_client.uncheck_all_checklist_items.assert_not_called()
        mock_translation.assert_called_once_with("DOC1")


if __name__ == "__main__":
    unittest.main()
