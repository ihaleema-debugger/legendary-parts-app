"""Unit tests for TrelloState — uses a temporary SQLite file per test."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.trello_state import TrelloState


def _state():
    """Return a TrelloState backed by a fresh temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return TrelloState(db_path=tmp.name)


class TestInsertAndGetPending(unittest.TestCase):
    def test_insert_appears_in_pending(self):
        s = _state()
        s.insert("DOC1", "CARD1", "My Blog", "https://docs.google.com/d/DOC1/edit")
        pending = s.get_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["doc_id"], "DOC1")
        self.assertEqual(pending[0]["card_id"], "CARD1")
        self.assertEqual(pending[0]["status"], "pending")

    def test_multiple_pending_rows(self):
        s = _state()
        s.insert("DOC1", "CARD1", "Blog 1", "https://url1")
        s.insert("DOC2", "CARD2", "Blog 2", "https://url2")
        self.assertEqual(len(s.get_pending()), 2)

    def test_handed_off_not_in_pending(self):
        s = _state()
        s.insert("DOC1", "CARD1", "Blog 1", "https://url1")
        s.mark_handed_off("DOC1")
        self.assertEqual(len(s.get_pending()), 0)


class TestGetByDocId(unittest.TestCase):
    def test_returns_row_for_existing_doc(self):
        s = _state()
        s.insert("DOC1", "CARD1", "Blog", "https://url")
        row = s.get_by_doc_id("DOC1")
        self.assertIsNotNone(row)
        self.assertEqual(row["card_id"], "CARD1")

    def test_returns_none_for_unknown_doc(self):
        s = _state()
        self.assertIsNone(s.get_by_doc_id("NONEXISTENT"))


class TestStatusTransitions(unittest.TestCase):
    def setUp(self):
        self.s = _state()
        self.s.insert("DOC1", "CARD1", "Blog", "https://url")

    def test_mark_handed_off(self):
        self.s.mark_handed_off("DOC1")
        row = self.s.get_by_doc_id("DOC1")
        self.assertEqual(row["status"], "handed_off")
        self.assertIsNotNone(row["handed_off_at"])

    def test_mark_completed(self):
        self.s.mark_completed("DOC1")
        row = self.s.get_by_doc_id("DOC1")
        self.assertEqual(row["status"], "completed")
        self.assertIsNotNone(row["completed_at"])

    def test_mark_failed_stores_reason(self):
        self.s.mark_failed("DOC1", "card deleted from Trello")
        row = self.s.get_by_doc_id("DOC1")
        self.assertEqual(row["status"], "failed")
        self.assertIn("card deleted", row["failure_reason"])

    def test_reset_to_pending(self):
        self.s.mark_failed("DOC1", "some error")
        self.s.reset_to_pending("DOC1")
        row = self.s.get_by_doc_id("DOC1")
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["failure_reason"])

    def test_failed_cards_not_in_pending(self):
        self.s.mark_failed("DOC1", "gone")
        self.assertEqual(len(self.s.get_pending()), 0)


class TestGetAll(unittest.TestCase):
    def test_returns_all_rows_in_descending_order(self):
        s = _state()
        s.insert("DOC1", "CARD1", "Blog 1", "https://url1")
        s.insert("DOC2", "CARD2", "Blog 2", "https://url2")
        rows = s.get_all()
        self.assertEqual(len(rows), 2)

    def test_empty_state_returns_empty_list(self):
        s = _state()
        self.assertEqual(s.get_all(), [])


if __name__ == "__main__":
    unittest.main()
