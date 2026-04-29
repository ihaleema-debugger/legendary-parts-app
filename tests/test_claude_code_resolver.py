# tests/test_claude_code_resolver.py
"""Unit tests for claude_code_resolver — subprocess.run is mocked."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.claude_code_resolver import resolve_comment


def _make_proc(stdout: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = ""
    return proc


_VALID_RESPONSE = json.dumps({
    "action": "replace",
    "anchor_text": "Twin Cam engine",
    "replacement_text": "Revolution engine",
    "confidence": "high",
    "rationale": "V-Rod uses the Revolution engine, not Twin Cam.",
})

_COMMENT = {
    "id": "C1",
    "quoted_text": "Twin Cam engine",
    "body": "V-Rod uses Revolution engine, not Twin Cam",
    "anchor": "",
    "paragraph_context": "The V-Rod is powered by the Twin Cam engine.",
}


class TestValidJson(unittest.TestCase):
    """(a) Valid JSON → returns parsed dict."""

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_valid_json_returns_parsed_dict(self, mock_run):
        mock_run.return_value = _make_proc(stdout=_VALID_RESPONSE)
        result = resolve_comment("The V-Rod is powered by the Twin Cam engine.", _COMMENT)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "replace")
        self.assertEqual(result["anchor_text"], "Twin Cam engine")
        self.assertEqual(result["replacement_text"], "Revolution engine")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("rationale", result)

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_valid_json_inside_markdown_fences_is_parsed(self, mock_run):
        fenced = f"```json\n{_VALID_RESPONSE}\n```"
        mock_run.return_value = _make_proc(stdout=fenced)
        result = resolve_comment("context", _COMMENT)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "replace")


class TestMalformedJson(unittest.TestCase):
    """(b) Malformed JSON → returns None."""

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_malformed_json_returns_none(self, mock_run):
        mock_run.return_value = _make_proc(stdout="not valid json { broken")
        result = resolve_comment("context", _COMMENT)
        self.assertIsNone(result)


class TestTimeout(unittest.TestCase):
    """(c) TimeoutExpired → returns None."""

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=120)
        result = resolve_comment("context", _COMMENT)
        self.assertIsNone(result)


class TestNonZeroExit(unittest.TestCase):
    """(d) returncode != 0 → returns None."""

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_nonzero_returncode_returns_none(self, mock_run):
        mock_run.return_value = _make_proc(stdout='{"error": "fail"}', returncode=1)
        result = resolve_comment("context", _COMMENT)
        self.assertIsNone(result)


class TestSchemaMismatch(unittest.TestCase):
    """Schema mismatch → returns None."""

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_missing_action_field_returns_none(self, mock_run):
        partial = json.dumps({
            "anchor_text": "Twin Cam engine",
            "replacement_text": "Revolution engine",
            "confidence": "high",
            "rationale": "missing action",
        })
        mock_run.return_value = _make_proc(stdout=partial)
        result = resolve_comment("context", _COMMENT)
        self.assertIsNone(result)

    @patch("app.services.claude_code_resolver.subprocess.run")
    def test_invalid_action_value_returns_none(self, mock_run):
        bad = json.dumps({
            "action": "unknown_verb",
            "anchor_text": "text",
            "replacement_text": "new text",
            "confidence": "high",
            "rationale": "bad action",
        })
        mock_run.return_value = _make_proc(stdout=bad)
        result = resolve_comment("context", _COMMENT)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
