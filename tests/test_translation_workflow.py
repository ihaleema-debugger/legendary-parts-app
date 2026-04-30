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


# ---------------------------------------------------------------------------
# Sequential orchestration + retry tests
# ---------------------------------------------------------------------------
import translation_workflow as tw


def _make_mock_run_task(results_by_lang: dict):
    """
    Factory: returns a _run_language_task replacement.
    results_by_lang maps lang_code -> list of dicts to return on successive calls.
    """
    call_counts: dict[str, int] = {}

    def mock_run(*, lang_code, lang_name, blog, guidelines, shopify_client,
                 source_doc_id, original_slug, folder_id, model, dry_run):
        call_counts[lang_code] = call_counts.get(lang_code, 0) + 1
        responses = results_by_lang.get(lang_code, [])
        call_idx = call_counts[lang_code] - 1
        if call_idx < len(responses):
            return responses[call_idx]
        return _make_result(lang_code)  # default success if not specified

    mock_run.call_counts = call_counts
    return mock_run


def _orchestrate_with_mock(mock_run_task, langs=None, doc_id="doc_abc"):
    """
    Call orchestrate() with all external dependencies mocked out.
    Returns the result_objects list that was passed to notifier.send_summary.
    """
    if langs is None:
        langs = tw.LANGUAGES

    fake_blog = {"title": "T", "meta_description": "M", "body_html": "<p>B</p>", "slug": "t", "faq": []}
    notifier_calls = []

    with patch("translation_workflow.drive_reader.fetch_doc", return_value=fake_blog), \
         patch("translation_workflow.translator_mod.load_guidelines", return_value="guidelines"), \
         patch("translation_workflow.ShopifyMCPClient", return_value=None), \
         patch("translation_workflow.get_doc_parent_folder", return_value="folder123"), \
         patch("translation_workflow._run_language_task", side_effect=mock_run_task), \
         patch("translation_workflow.notifier.send_summary", side_effect=lambda slug, did, res: notifier_calls.append(res)), \
         patch("translation_workflow._update_trello_on_completion"), \
         patch.dict("os.environ", {"TRANSLATION_MODEL": "claude-sonnet-4-6", "NOTIFY_EMAIL": "x@x.com"}):
        tw.orchestrate(doc_id, dry_run=False)

    return notifier_calls[0] if notifier_calls else []


def test_sequential_all_succeed_produces_8_results():
    """All 8 languages succeed — result_objects has 8 success entries."""
    mock = _make_mock_run_task({lang: [_make_result(lang)] for lang in tw.LANGUAGES})
    results = _orchestrate_with_mock(mock)
    assert len(results) == 8
    assert all(r["status"] == "success" for r in results)


def test_sequential_order_is_fr_de_es_it_nl_pl_sl_pt():
    """Languages are processed in the canonical order."""
    call_order = []

    def recording_run(*, lang_code, **kwargs):
        call_order.append(lang_code)
        return _make_result(lang_code)

    with patch("translation_workflow.drive_reader.fetch_doc", return_value={"title": "T", "meta_description": "M", "body_html": "", "slug": "t", "faq": []}), \
         patch("translation_workflow.translator_mod.load_guidelines", return_value="g"), \
         patch("translation_workflow.ShopifyMCPClient", return_value=None), \
         patch("translation_workflow.get_doc_parent_folder", return_value="f"), \
         patch("translation_workflow._run_language_task", side_effect=recording_run), \
         patch("translation_workflow.notifier.send_summary"), \
         patch("translation_workflow._update_trello_on_completion"), \
         patch.dict("os.environ", {"TRANSLATION_MODEL": "m", "NOTIFY_EMAIL": "x"}):
        tw.orchestrate("doc_abc", dry_run=False)

    assert call_order == ["fr", "de", "es", "it", "nl", "pl", "sl", "pt"]


def test_retry_language_that_failed_first_pass():
    """A language that fails first pass but succeeds on retry ends up in succeeded."""
    mock = _make_mock_run_task({
        "fr": [_make_result("fr")],
        "de": [_make_result("de")],
        "es": [
            _make_result("es", status="failed", error="timeout"),
            _make_result("es"),  # retry succeeds
        ],
        "it": [_make_result("it")],
        "nl": [_make_result("nl")],
        "pl": [_make_result("pl")],
        "sl": [_make_result("sl")],
        "pt": [_make_result("pt")],
    })
    results = _orchestrate_with_mock(mock)
    succeeded_langs = [r["lang"] for r in results if r["status"] == "success"]
    assert "es" in succeeded_langs
    assert len(succeeded_langs) == 8


def test_retry_uses_second_error_message_on_double_failure():
    """A language that fails both attempts keeps the second error message."""
    mock = _make_mock_run_task({
        **{lang: [_make_result(lang)] for lang in tw.LANGUAGES if lang != "it"},
        "it": [
            _make_result("it", status="failed", error="first error"),
            _make_result("it", status="failed", error="second error"),
        ],
    })
    results = _orchestrate_with_mock(mock)
    it_result = next(r for r in results if r["lang"] == "it")
    assert it_result["status"] == "failed"
    assert it_result["error"] == "second error"


def test_retry_called_only_once_per_failed_language():
    """Each failed language is retried exactly once — no third attempt."""
    mock = _make_mock_run_task({
        **{lang: [_make_result(lang)] for lang in tw.LANGUAGES if lang != "nl"},
        "nl": [
            _make_result("nl", status="failed", error="err1"),
            _make_result("nl", status="failed", error="err2"),
        ],
    })
    _orchestrate_with_mock(mock)
    assert mock.call_counts.get("nl", 0) == 2  # first pass + one retry


def test_single_language_failure_does_not_stop_run():
    """A failure in one language does not prevent subsequent languages from running."""
    called = []

    def run(*, lang_code, **kwargs):
        called.append(lang_code)
        if lang_code == "de":
            return _make_result("de", status="failed", error="boom")
        return _make_result(lang_code)

    with patch("translation_workflow.drive_reader.fetch_doc", return_value={"title": "T", "meta_description": "M", "body_html": "", "slug": "t", "faq": []}), \
         patch("translation_workflow.translator_mod.load_guidelines", return_value="g"), \
         patch("translation_workflow.ShopifyMCPClient", return_value=None), \
         patch("translation_workflow.get_doc_parent_folder", return_value="f"), \
         patch("translation_workflow._run_language_task", side_effect=run), \
         patch("translation_workflow.notifier.send_summary"), \
         patch("translation_workflow._update_trello_on_completion"), \
         patch.dict("os.environ", {"TRANSLATION_MODEL": "m", "NOTIFY_EMAIL": "x"}):
        tw.orchestrate("doc_abc", dry_run=False)

    # All 8 languages ran in first pass + DE retry
    assert set(called) == set(tw.LANGUAGES)
    assert "es" in called  # languages after DE still ran
