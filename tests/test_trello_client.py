"""Unit tests for TrelloClient — all HTTP calls are mocked via unittest.mock."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.trello_client import TrelloClient


def _make_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


class TestResolveListIds(unittest.TestCase):
    def _client(self):
        c = TrelloClient()
        c.board_id = "BOARD1"
        c.pending_list_name = "To Do"
        c.translating_list_name = "Doing"
        c.done_list_name = "Done"
        return c

    def test_success_builds_list_id_dict(self):
        c = self._client()
        lists = [
            {"name": "To Do", "id": "list1"},
            {"name": "Doing", "id": "list2"},
            {"name": "Done", "id": "list3"},
        ]
        with patch.object(c._session, "request", return_value=_make_response(200, lists)):
            result = c.resolve_list_ids()

        self.assertEqual(result, {"To Do": "list1", "Doing": "list2", "Done": "list3"})
        self.assertEqual(c._list_ids, result)

    def test_missing_list_raises_runtime_error(self):
        c = self._client()
        lists = [{"name": "To Do", "id": "list1"}]  # Doing and Done missing
        with patch.object(c._session, "request", return_value=_make_response(200, lists)):
            with self.assertRaises(RuntimeError) as ctx:
                c.resolve_list_ids()

        msg = str(ctx.exception)
        self.assertIn("Doing", msg)
        self.assertIn("Done", msg)

    def test_api_error_raises(self):
        c = self._client()
        with patch.object(
            c._session, "request", return_value=_make_response(500, text="internal error")
        ):
            with self.assertRaises(RuntimeError):
                c.resolve_list_ids()


class TestCreateValidationCard(unittest.TestCase):
    def _client_with_lists(self):
        c = TrelloClient()
        c._list_ids = {"To Do": "list-pending", "Doing": "list-doing", "Done": "list-done"}
        c.pending_list_name = "To Do"
        c.checklist_name = "Validations"
        c.checklist_item_1 = "Validated by Haleema"
        c.checklist_item_2 = "Validated by Jeremy"
        return c

    def test_creates_card_checklist_and_items(self):
        c = self._client_with_lists()
        card_resp = _make_response(200, {"id": "CARD1"})
        checklist_resp = _make_response(200, {"id": "CL1"})
        item_resp = _make_response(200, {"id": "ITEM1"})

        responses = [card_resp, checklist_resp, item_resp, item_resp]
        with patch.object(c._session, "request", side_effect=responses):
            card_id = c.create_validation_card("My Blog", "https://docs.google.com/d/DOC1/edit")

        self.assertEqual(card_id, "CARD1")

    def test_raises_key_error_if_list_ids_not_resolved(self):
        c = TrelloClient()
        c.pending_list_name = "To Do"
        with self.assertRaises(KeyError):
            c.create_validation_card("title", "https://url")


class TestGetCardChecklistState(unittest.TestCase):
    def _client(self):
        c = TrelloClient()
        c.checklist_name = "Validations"
        c.checklist_item_1 = "Validated by Haleema"
        c.checklist_item_2 = "Validated by Jeremy"
        return c

    def test_both_complete(self):
        c = self._client()
        checklists = [
            {
                "name": "Validations",
                "checkItems": [
                    {"name": "Validated by Haleema", "state": "complete"},
                    {"name": "Validated by Jeremy", "state": "complete"},
                ],
            }
        ]
        with patch.object(c._session, "request", return_value=_make_response(200, checklists)):
            result = c.get_card_checklist_state("CARD1")

        self.assertTrue(result["Validated by Haleema"])
        self.assertTrue(result["Validated by Jeremy"])

    def test_mixed_state(self):
        c = self._client()
        checklists = [
            {
                "name": "Validations",
                "checkItems": [
                    {"name": "Validated by Haleema", "state": "complete"},
                    {"name": "Validated by Jeremy", "state": "incomplete"},
                ],
            }
        ]
        with patch.object(c._session, "request", return_value=_make_response(200, checklists)):
            result = c.get_card_checklist_state("CARD1")

        self.assertTrue(result["Validated by Haleema"])
        self.assertFalse(result["Validated by Jeremy"])

    def test_returns_none_on_404(self):
        c = self._client()
        with patch.object(c._session, "request", return_value=_make_response(404)):
            result = c.get_card_checklist_state("DELETED_CARD")

        self.assertIsNone(result)

    def test_returns_empty_dict_when_checklist_not_found(self):
        c = self._client()
        checklists = [{"name": "Other Checklist", "checkItems": []}]
        with patch.object(c._session, "request", return_value=_make_response(200, checklists)):
            result = c.get_card_checklist_state("CARD1")

        self.assertEqual(result, {})


class TestMoveCardToList(unittest.TestCase):
    def test_happy_path(self):
        c = TrelloClient()
        c._list_ids = {"Doing": "list-doing"}
        with patch.object(c._session, "request", return_value=_make_response(200, {})):
            c.move_card_to_list("CARD1", "Doing")  # should not raise


class TestAddComment(unittest.TestCase):
    def test_happy_path(self):
        c = TrelloClient()
        with patch.object(c._session, "request", return_value=_make_response(200, {})):
            c.add_comment("CARD1", "All done!")  # should not raise


class TestRetryLogic(unittest.TestCase):
    def _client(self):
        c = TrelloClient()
        c.board_id = "BOARD1"
        c.pending_list_name = "To Do"
        c.translating_list_name = "Doing"
        c.done_list_name = "Done"
        return c

    def test_429_is_retried_up_to_three_times(self):
        c = self._client()
        rate_limited = _make_response(429, text="rate limit")

        with patch.object(c._session, "request", return_value=rate_limited):
            with patch("time.sleep"):  # don't actually sleep in tests
                with self.assertRaises(RuntimeError) as ctx:
                    c.resolve_list_ids()

        self.assertIn("429", str(ctx.exception))

    def test_non_429_error_is_not_retried(self):
        c = self._client()
        c._list_ids = {"To Do": "l1", "Doing": "l2", "Done": "l3"}

        error_resp = _make_response(404, text="not found")

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return error_resp

        with patch.object(c._session, "request", side_effect=side_effect):
            result = c.get_card_checklist_state("GONE_CARD")

        # 404 on get_card_checklist_state should return None after exactly 1 attempt (no retry)
        self.assertIsNone(result)
        self.assertEqual(call_count["n"], 1)


if __name__ == "__main__":
    unittest.main()
