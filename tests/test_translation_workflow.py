"""Tests for translation_workflow orchestration and Trello update logic."""
from __future__ import annotations
import app.services.anthropic_client as ac_module


def test_claude_timeout_is_300():
    assert ac_module._CLAUDE_TIMEOUT == 300
