"""
TDD: Fast failure detection for Stage 10 translation.

A crashed --resume run must move its Trello card to "Failed translation" and
write failed_error to the DB within the same process, without waiting for the
14-day staleness timeout.

Run with:
  keyword_forge/.venv/bin/python -m pytest tests/test_stage10_failure_routing.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

DOC_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
CARD_ID = "CARD456abc"
FAILED_LIST = "Failed translation"


def _make_row():
    return {
        "doc_id": DOC_ID,
        "card_id": CARD_ID,
        "status": "handed_off",
        "blog_title": "Test Blog",
    }


def _run_main_resume(
    orchestrate_side_effect=None,
    orchestrate_return_value=0,
    extra_client_setup=None,
):
    """
    Call translation_workflow.main() with --resume DOC_ID.
    Returns (mock_state, mock_client, raised_exception_or_None).
    extra_client_setup(mock_client) is called before main() to configure side-effects.
    """
    mock_state = MagicMock()
    mock_client = MagicMock()
    mock_state.get_by_doc_id.return_value = _make_row()
    if extra_client_setup:
        extra_client_setup(mock_client)

    raised = None
    with patch.object(sys, "argv", ["translation_workflow.py", "--resume", DOC_ID]), \
         patch("translation_workflow.validate_doc"), \
         patch("translation_workflow.orchestrate",
               side_effect=orchestrate_side_effect,
               return_value=orchestrate_return_value), \
         patch("app.services.trello_state.TrelloState", return_value=mock_state), \
         patch("app.services.trello_client.TrelloClient", return_value=mock_client):
        try:
            import translation_workflow
            translation_workflow.main()
        except BaseException as exc:
            raised = exc

    return mock_state, mock_client, raised


class TestStage10CrashPath(unittest.TestCase):
    """orchestrate() raises an exception — must route to Trello failure list immediately."""

    def test_crash_moves_card_to_failed_list(self):
        _, mock_client, _ = _run_main_resume(
            orchestrate_side_effect=RuntimeError("openai timeout")
        )
        mock_client.move_card_to_list.assert_called_once_with(CARD_ID, FAILED_LIST)

    def test_crash_writes_failed_error_to_db(self):
        mock_state, _, _ = _run_main_resume(
            orchestrate_side_effect=RuntimeError("openai timeout")
        )
        mock_state.mark_failed_error.assert_called_once()
        assert mock_state.mark_failed_error.call_args[0][0] == DOC_ID

    def test_crash_reraises_original_exception(self):
        _, _, raised = _run_main_resume(
            orchestrate_side_effect=RuntimeError("openai timeout")
        )
        self.assertIsNotNone(raised)
        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("openai timeout", str(raised))

    def test_crash_posts_comment_to_trello(self):
        _, mock_client, _ = _run_main_resume(
            orchestrate_side_effect=RuntimeError("openai timeout")
        )
        mock_client.add_comment.assert_called()
        card_arg, text_arg = mock_client.add_comment.call_args[0]
        self.assertEqual(card_arg, CARD_ID)
        self.assertIn("Translation", text_arg)

    def test_crash_looks_up_card_by_doc_id(self):
        mock_state, _, _ = _run_main_resume(
            orchestrate_side_effect=RuntimeError("openai timeout")
        )
        mock_state.get_by_doc_id.assert_called_once_with(DOC_ID)


class TestStage10NFailedPath(unittest.TestCase):
    """orchestrate() returns n_failed > 0 — also routes to Trello failure list."""

    def test_n_failed_moves_card_to_failed_list(self):
        _, mock_client, _ = _run_main_resume(orchestrate_return_value=3)
        mock_client.move_card_to_list.assert_called_once_with(CARD_ID, FAILED_LIST)

    def test_n_failed_writes_failed_error_to_db(self):
        mock_state, _, _ = _run_main_resume(orchestrate_return_value=3)
        mock_state.mark_failed_error.assert_called_once()
        assert mock_state.mark_failed_error.call_args[0][0] == DOC_ID

    def test_n_failed_exits_nonzero(self):
        _, _, raised = _run_main_resume(orchestrate_return_value=3)
        self.assertIsNotNone(raised, "n_failed > 0 must exit non-zero")


class TestStage10SuccessPath(unittest.TestCase):
    """orchestrate() returns 0 — must NOT touch the failure path at all."""

    def test_success_does_not_move_card_to_failed_list(self):
        _, mock_client, raised = _run_main_resume(orchestrate_return_value=0)
        self.assertIsNone(raised)
        mock_client.move_card_to_list.assert_not_called()

    def test_success_does_not_write_failed_error(self):
        mock_state, _, raised = _run_main_resume(orchestrate_return_value=0)
        self.assertIsNone(raised)
        mock_state.mark_failed_error.assert_not_called()


class TestStage10HandlerSafety(unittest.TestCase):
    """The failure handler must never mask the original exception."""

    def test_trello_move_failure_still_writes_db_and_reraises(self):
        """If move_card_to_list throws, mark_failed_error is still called and original raises."""
        def _client_setup(mock_client):
            mock_client.move_card_to_list.side_effect = RuntimeError("Trello API down")

        mock_state, _, raised = _run_main_resume(
            orchestrate_side_effect=RuntimeError("original crash"),
            extra_client_setup=_client_setup,
        )
        # DB write must still happen despite Trello failure
        mock_state.mark_failed_error.assert_called_once()
        # Original error must surface, not the Trello error
        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("original crash", str(raised))

    def test_db_write_failure_does_not_mask_original_error(self):
        """If mark_failed_error throws, the original exception still propagates."""
        mock_state = MagicMock()
        mock_client = MagicMock()
        mock_state.get_by_doc_id.return_value = _make_row()
        mock_state.mark_failed_error.side_effect = RuntimeError("DB locked")

        raised = None
        with patch.object(sys, "argv", ["translation_workflow.py", "--resume", DOC_ID]), \
             patch("translation_workflow.validate_doc"), \
             patch("translation_workflow.orchestrate",
                   side_effect=RuntimeError("original crash")), \
             patch("app.services.trello_state.TrelloState", return_value=mock_state), \
             patch("app.services.trello_client.TrelloClient", return_value=mock_client):
            try:
                import translation_workflow
                translation_workflow.main()
            except BaseException as exc:
                raised = exc

        self.assertIsInstance(raised, RuntimeError)
        self.assertIn("original crash", str(raised))


if __name__ == "__main__":
    unittest.main()
