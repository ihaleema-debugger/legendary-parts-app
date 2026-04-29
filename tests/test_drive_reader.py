# tests/test_drive_reader.py
"""Unit tests for drive_reader — all Drive API calls are mocked."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.drive_reader import fetch_doc, _slugify


def _make_service(filename: str = "", body_html: str = "<html><body></body></html>") -> MagicMock:
    """Build a mock Drive service with configurable filename and HTML export."""
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {"name": filename}
    service.files.return_value.export.return_value.execute.return_value = body_html.encode("utf-8")
    return service


class TestFetchDocTitleResolution(unittest.TestCase):

    @patch("app.services.drive_reader._get_service")
    def test_title_from_drive_filename(self, mock_get_service):
        """Drive metadata filename is the primary title source."""
        mock_get_service.return_value = _make_service(
            filename="My Blog Post",
            body_html="<html><body><p>content</p></body></html>",
        )
        result = fetch_doc("DOC1")
        self.assertEqual(result["title"], "My Blog Post")

    @patch("app.services.drive_reader._get_service")
    def test_title_from_body_h1_when_filename_empty(self, mock_get_service):
        """Falls back to <h1> when Drive filename is empty."""
        mock_get_service.return_value = _make_service(
            filename="",
            body_html="<html><body><h1>H1 Title From Body</h1><p>content</p></body></html>",
        )
        result = fetch_doc("DOC1")
        self.assertEqual(result["title"], "H1 Title From Body")

    @patch("app.services.drive_reader._get_service")
    def test_title_from_body_p_title_when_no_h1(self, mock_get_service):
        """Falls back to <p class='title'> when filename is empty and no <h1> present."""
        mock_get_service.return_value = _make_service(
            filename="",
            body_html='<html><body><p class="title">P Class Title</p><p>content</p></body></html>',
        )
        result = fetch_doc("DOC1")
        self.assertEqual(result["title"], "P Class Title")

    @patch("app.services.drive_reader._get_service")
    def test_raises_when_no_title_found(self, mock_get_service):
        """RuntimeError is raised — not silent 'Untitled' — when all title sources fail."""
        mock_get_service.return_value = _make_service(
            filename="",
            body_html="<html><body><p>just plain content, no title element</p></body></html>",
        )
        with self.assertRaises(RuntimeError) as ctx:
            fetch_doc("DOC1")
        self.assertIn("Could not extract title", str(ctx.exception))
        self.assertIn("DOC1", str(ctx.exception))

    @patch("app.services.drive_reader._get_service")
    def test_drive_filename_takes_priority_over_h1(self, mock_get_service):
        """Drive filename wins even when an <h1> is present in the body."""
        mock_get_service.return_value = _make_service(
            filename="Drive Name Wins",
            body_html="<html><body><h1>H1 Should Lose</h1></body></html>",
        )
        result = fetch_doc("DOC1")
        self.assertEqual(result["title"], "Drive Name Wins")


class TestSlugify(unittest.TestCase):

    def test_apostrophe_in_slug(self):
        """Apostrophe is stripped cleanly — 'Buyer's' → 'buyers', not 'buyer-s'."""
        self.assertEqual(_slugify("V-Rod Buyer's Guide"), "v-rod-buyers-guide")

    def test_full_title_apostrophes(self):
        """Full V-Rod title slugifies correctly."""
        result = _slugify("Harley-Davidson VRSC V-Rod: Complete Buyer's and Owner's Guide")
        self.assertEqual(result, "harley-davidson-vrsc-v-rod-complete-buyers-and-owners-guide")

    def test_consecutive_hyphens_collapsed(self):
        """Ampersand and extra spaces do not produce double hyphens."""
        result = _slugify("Parts & Accessories - Harley  -  Davidson")
        self.assertNotIn("--", result)
        self.assertIn("parts", result)
        self.assertIn("accessories", result)
        self.assertIn("harley", result)

    def test_non_ascii_transliterated(self):
        """Non-ASCII characters are transliterated to ASCII equivalents."""
        result = _slugify("Über die Lenkerklemme")
        self.assertFalse(any(ord(c) > 127 for c in result))
        self.assertIn("uber", result)

    def test_lowercase(self):
        self.assertEqual(_slugify("UPPERCASE TITLE"), "uppercase-title")

    def test_max_length(self):
        long_title = "word " * 30
        self.assertLessEqual(len(_slugify(long_title)), 80)


if __name__ == "__main__":
    unittest.main()
