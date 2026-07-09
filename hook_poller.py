#!/usr/bin/env python3
"""Background daemon that watches the outreach sheet for hand-written Hooks
and, once every Outreach row has one, runs the sheet-import chain and pushes
survivors to Gmail as drafts.

Usage:
  python3 hook_poller.py            # uses HOOK_POLLING_INTERVAL_MINUTES from .env (default 10)
  python3 hook_poller.py --interval 2   # override interval in minutes
  python3 hook_poller.py --once         # run a single cycle and exit (testing)

Nothing here sends email — outreach.run_outreach.run() only ever creates
Gmail drafts. A human presses Send.

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent

# Variables that must only ever be satisfied by the real process environment
# (shell export, launchd EnvironmentVariables, or inline in a wrapper script
# like run_poller.sh) — never by .env. load_dotenv() defaults to
# override=False, so a var already present in the real environment before
# this call is untouched by it; a var that only exists in .env gets injected
# here for the first time. Snapshotting "was it already set?" before the
# call, then stripping anything that newly appeared, mechanically closes
# .env as a route to satisfying these — not just a comment relying on
# someone reading it. See outreach/gmail_client.py's LIVE_GATE_VAR for why
# this specific one matters: this file's own --test runs would otherwise
# inherit a .env-set value, since load_dotenv() runs before the --test
# check below.
_ENV_ONLY_VARS = {"OUTREACH_ALLOW_LIVE_GMAIL"}
_pre_dotenv_present = {name: (name in os.environ) for name in _ENV_ONLY_VARS}

load_dotenv(_ROOT / ".env")

for _name, _was_present in _pre_dotenv_present.items():
    if not _was_present:
        os.environ.pop(_name, None)

sys.path.insert(0, str(_ROOT))

from outreach.stages.s_sheet_read import read_sheet
from outreach.stages.s_sheet_autofill import _is_real_hook, EXPECTED_HEADERS
from outreach.stages.s_sheet_commit import commit_records
from outreach.run_outreach import run as run_outreach_chain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_STATE_PATH = _ROOT / "outreach" / "state" / "active_sheet.json"


def _load_active_sheet_state(state_path: Path = _STATE_PATH):
    """Return {"sheet_id": ..., "tab": ...} or None if missing/unreadable."""
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("active_sheet.json is not valid JSON — skipping cycle")
        return None
    if "sheet_id" not in data:
        logger.warning("active_sheet.json missing 'sheet_id' — skipping cycle")
        return None
    return data


def check_hook_gate(sheet_id: str, tab: str = None, read_fn=None) -> dict:
    """All-or-nothing: every Decision=='Outreach' row must have a real Hook.

    Returns {"passed": bool, "total_outreach": int, "blocked_domains": [...]}.
    read_fn is injectable for tests (mirrors s3_enrich.run_enrich's fetch_fn=None DI pattern).
    """
    fn = read_fn or read_sheet
    rows = fn(sheet_id, tab)
    header_row, *data_rows = rows
    col = {name: idx for idx, name in enumerate(header_row)}

    missing = [h for h in EXPECTED_HEADERS if h not in col]
    if missing:
        raise RuntimeError(
            f"Sheet header is missing expected columns: {missing}\n"
            f"Actual header: {header_row}"
        )

    decision_idx = col["Decision"]
    hook_idx = col["Hook"]
    domain_idx = col["Referring Domain"]
    n_cols = len(header_row)

    total_outreach = 0
    blocked_domains = []

    for raw_row in data_rows:
        row = list(raw_row) + [""] * (n_cols - len(raw_row))
        if row[decision_idx].strip().lower() != "outreach":
            continue
        total_outreach += 1
        if not _is_real_hook(row[hook_idx]):
            blocked_domains.append(row[domain_idx].strip() or "(blank domain)")

    return {
        "passed": len(blocked_domains) == 0,
        "total_outreach": total_outreach,
        "blocked_domains": blocked_domains,
    }


def run_cycle(sheet_id_override: str = None, tab_override: str = None,
              chain_fn=None, gmail_fn=None, read_fn=None,
              state_path: Path = _STATE_PATH) -> dict:
    """One cycle: resolve sheet/tab -> gate check -> run chain + gmail, or skip.

    Never raises — callers wrap this the same way trello_poller.py's run()
    wraps poll_once, but run_cycle itself stays exception-clean so it can be
    unit-tested directly.
    """
    chain_fn = chain_fn or commit_records
    gmail_fn = gmail_fn or run_outreach_chain

    if sheet_id_override:
        sheet_id, tab = sheet_id_override, tab_override
    else:
        state = _load_active_sheet_state(state_path)
        if state is None:
            logger.info("No active_sheet.json found — nothing to watch this cycle.")
            return {"status": "no-state"}
        sheet_id, tab = state["sheet_id"], state.get("tab")

    gate = check_hook_gate(sheet_id, tab, read_fn=read_fn)

    if not gate["passed"]:
        logger.info(
            "Hook gate BLOCKED — %d of %d Outreach row(s) still need a Hook: %s",
            len(gate["blocked_domains"]), gate["total_outreach"], gate["blocked_domains"],
        )
        return {"status": "blocked", **gate}

    logger.info(
        "Hook gate PASSED (%d Outreach row(s)) — running sheet chain + Gmail push.",
        gate["total_outreach"],
    )
    commit_summary = chain_fn(sheet_id=sheet_id, tab=tab)
    gmail_summary = gmail_fn()

    logger.info("Cycle complete: commit=%s gmail=%s", commit_summary, gmail_summary)
    return {"status": "ran", "gate": gate, "commit": commit_summary, "gmail": gmail_summary}


def run(interval_minutes: int, sheet_id_override: str = None,
        tab_override: str = None, once: bool = False):
    print(f"Hook gate poller started — checking every {interval_minutes} minute(s). Press Ctrl+C to stop.")
    logger.info("Poller started with interval=%dm", interval_minutes)

    while True:
        try:
            run_cycle(sheet_id_override=sheet_id_override, tab_override=tab_override)
        except Exception as e:
            logger.warning("run_cycle raised an unexpected error: %s", e)

        if once:
            break
        time.sleep(interval_minutes * 60)


# ── self-tests (no live network / Sheets / Gmail calls) ────────────────────

def _run_tests() -> None:
    import tempfile
    from unittest.mock import MagicMock

    print("Running hook_poller tests...")

    header = EXPECTED_HEADERS

    # T1 — all Hooks filled -> gate passes
    rows_all_filled = [
        header,
        ["a.com", "10", "a@a.com", "Outreach", "High", "real hook one", "REL-EDITORIAL", ""],
        ["b.com", "10", "b@b.com", "Outreach", "Med", "real hook two", "REL-DIRECTORY", ""],
        ["c.com", "10", "", "Review", "", "", "UNKNOWN", ""],
    ]
    gate = check_hook_gate("sid", "tab", read_fn=lambda s, t: rows_all_filled)
    assert gate == {"passed": True, "total_outreach": 2, "blocked_domains": []}, gate
    print("  PASS  [T1]  all Hooks filled -> gate passes")

    # T2 — one blank Hook -> gate blocked, that domain named
    rows_one_blank = [
        header,
        ["a.com", "10", "a@a.com", "Outreach", "High", "real hook one", "REL-EDITORIAL", ""],
        ["b.com", "10", "b@b.com", "Outreach", "Med", "", "REL-DIRECTORY", ""],
    ]
    gate = check_hook_gate("sid", "tab", read_fn=lambda s, t: rows_one_blank)
    assert gate["passed"] is False
    assert gate["blocked_domains"] == ["b.com"], gate
    print("  PASS  [T2]  one blank Hook -> gate blocked, domain named")

    # T3 — one "TODO" Hook (any case) -> gate blocked
    rows_todo = [
        header,
        ["a.com", "10", "a@a.com", "Outreach", "High", "todo", "REL-EDITORIAL", ""],
    ]
    gate = check_hook_gate("sid", "tab", read_fn=lambda s, t: rows_todo)
    assert gate["passed"] is False
    assert gate["blocked_domains"] == ["a.com"], gate
    print("  PASS  [T3]  'TODO' Hook (any case) -> gate blocked")

    # T4 — zero Outreach rows -> vacuously passes
    rows_none = [
        header,
        ["a.com", "10", "", "Review", "", "", "UNKNOWN", ""],
        ["b.com", "10", "", "Skip", "", "", "MARKETPLACE", ""],
    ]
    gate = check_hook_gate("sid", "tab", read_fn=lambda s, t: rows_none)
    assert gate == {"passed": True, "total_outreach": 0, "blocked_domains": []}, gate
    print("  PASS  [T4]  zero Outreach rows -> gate vacuously passes")

    # T5 — run_cycle: gate passes -> chain_fn and gmail_fn each called once
    mock_chain = MagicMock(return_value={"added": 1})
    mock_gmail = MagicMock(return_value={"gmail_created": 1})
    result = run_cycle(
        sheet_id_override="sid123", tab_override="tabX",
        chain_fn=mock_chain, gmail_fn=mock_gmail,
        read_fn=lambda s, t: rows_all_filled,
    )
    assert result["status"] == "ran", result
    mock_chain.assert_called_once_with(sheet_id="sid123", tab="tabX")
    mock_gmail.assert_called_once_with()
    print("  PASS  [T5]  run_cycle: gate passed -> chain_fn + gmail_fn each called once")

    # T5b — run_cycle: gate blocked -> neither chain_fn nor gmail_fn called
    mock_chain2 = MagicMock()
    mock_gmail2 = MagicMock()
    result = run_cycle(
        sheet_id_override="sid123", tab_override="tabX",
        chain_fn=mock_chain2, gmail_fn=mock_gmail2,
        read_fn=lambda s, t: rows_one_blank,
    )
    assert result["status"] == "blocked", result
    mock_chain2.assert_not_called()
    mock_gmail2.assert_not_called()
    print("  PASS  [T5b] run_cycle: gate blocked -> chain_fn + gmail_fn not called")

    # T6 — missing active_sheet.json -> run_cycle short-circuits, gate never checked
    with tempfile.TemporaryDirectory() as tmp:
        missing_state_path = Path(tmp) / "active_sheet.json"
        assert not missing_state_path.exists()

        def _should_not_be_called(*a, **k):
            raise AssertionError("check_hook_gate's read_fn should not be called when state is missing")

        result = run_cycle(state_path=missing_state_path, read_fn=_should_not_be_called)
        assert result == {"status": "no-state"}, result
    print("  PASS  [T6]  missing active_sheet.json -> run_cycle returns no-state, gate skipped")

    print("\nAll hook_poller tests passed.")


def main():
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Hook gate poller — watches active_sheet.json and runs the outreach "
                     "chain once every Outreach row has a real Hook."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Polling interval in minutes (overrides HOOK_POLLING_INTERVAL_MINUTES)",
    )
    parser.add_argument(
        "--sheet-id",
        default=None,
        help="Override: bypass active_sheet.json, use this sheet ID directly (testing)",
    )
    parser.add_argument(
        "--tab",
        default=None,
        help="Override: tab to use with --sheet-id",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (testing)",
    )
    args = parser.parse_args()

    interval = args.interval or int(os.environ.get("HOOK_POLLING_INTERVAL_MINUTES", "10"))
    run(interval, sheet_id_override=args.sheet_id, tab_override=args.tab, once=args.once)


if __name__ == "__main__":
    main()
