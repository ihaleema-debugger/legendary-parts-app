"""Tests for translation_workflow orchestration and Trello update logic."""
from __future__ import annotations
import sys
import types
from unittest.mock import MagicMock, patch

import app.services.anthropic_client as ac_module


def test_claude_timeout_is_300():
    assert ac_module._CLAUDE_TIMEOUT == 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(lang: str, status: str = "success", error: str | None = None, doc_url: str = "https://docs.google.com/x", flags: list | None = None) -> dict:
    return {
        "lang": lang,
        "status": status,
        "doc_id": "abc" if status == "success" else None,
        "doc_url": doc_url if status == "success" else None,
        "flags": flags or [],
        "error": error,
    }


ALL_SUCCESS = [_make_result(l) for l in ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]]
PARTIAL_SUCCESS = [
    _make_result("fr"),
    _make_result("de"),
    _make_result("es", status="failed", error="claude -p timed out"),
    _make_result("it"),
    _make_result("nl"),
    _make_result("pl"),
    _make_result("sl"),
    _make_result("pt"),
]
ALL_FAILED = [_make_result(l, status="failed", error="connection refused") for l in ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]]


def _call_update_trello(results, *, card_id="card123", env_overrides=None):
    """Call _update_trello_on_completion with mocked Trello/state dependencies."""
    import translation_workflow as tw

    mock_state = MagicMock()
    mock_state.get_by_doc_id.return_value = {"card_id": card_id, "status": "handed_off"}
    mock_client = MagicMock()
    mock_client.resolve_list_ids.return_value = None
    captured_comment = {}
    moved_to = {}

    def capture_comment(cid, text):
        captured_comment["text"] = text

    def capture_move(cid, list_name):
        moved_to["list"] = list_name

    mock_client.add_comment.side_effect = capture_comment
    mock_client.move_card_to_list.side_effect = capture_move

    env = {"TRELLO_DONE_LIST_NAME": "Done", "TRELLO_TRANSLATING_LIST_NAME": "Doing"}
    if env_overrides:
        env.update(env_overrides)

    with patch("app.services.trello_state.TrelloState", return_value=mock_state), \
         patch("app.services.trello_client.TrelloClient", return_value=mock_client), \
         patch.dict("os.environ", env):
        tw._update_trello_on_completion("doc_abc", results)

    return captured_comment.get("text", ""), moved_to.get("list")


# ---------------------------------------------------------------------------
# Trello comment content tests
# ---------------------------------------------------------------------------

def test_trello_comment_all_success_shows_count():
    comment, _ = _call_update_trello(ALL_SUCCESS)
    assert "8/8 succeeded" in comment


def test_trello_comment_all_success_lists_languages():
    comment, _ = _call_update_trello(ALL_SUCCESS)
    for code in ["FR", "DE", "ES", "IT", "NL", "PL", "SL", "PT"]:
        assert code in comment


def test_trello_comment_all_success_no_failed_line():
    comment, _ = _call_update_trello(ALL_SUCCESS)
    assert "Failed:" not in comment
    assert "Re-run" not in comment


def test_trello_comment_partial_shows_correct_count():
    comment, _ = _call_update_trello(PARTIAL_SUCCESS)
    assert "7/8 succeeded" in comment


def test_trello_comment_partial_includes_failed_language():
    comment, _ = _call_update_trello(PARTIAL_SUCCESS)
    assert "Failed:" in comment
    assert "ES" in comment


def test_trello_comment_partial_includes_rerun_hint():
    comment, _ = _call_update_trello(PARTIAL_SUCCESS)
    assert "Re-run" in comment
    assert "doc_abc" in comment


def test_trello_comment_partial_truncates_long_error():
    long_error = "x" * 200
    results = [_make_result("fr")] * 7 + [_make_result("de", status="failed", error=long_error)]
    comment, _ = _call_update_trello(results)
    assert long_error not in comment
    assert "..." in comment


def test_trello_comment_all_failed_shows_catastrophic_note():
    comment, _ = _call_update_trello(ALL_FAILED)
    assert "0/8 succeeded" in comment
    assert "All translations failed" in comment


# ---------------------------------------------------------------------------
# Trello card movement tests
# ---------------------------------------------------------------------------

def test_trello_move_to_done_on_full_success():
    _, moved_to = _call_update_trello(ALL_SUCCESS)
    assert moved_to == "Done"


def test_trello_move_to_done_on_partial_success():
    _, moved_to = _call_update_trello(PARTIAL_SUCCESS)
    assert moved_to == "Done"


def test_trello_no_move_on_all_failed():
    _, moved_to = _call_update_trello(ALL_FAILED)
    assert moved_to is None
