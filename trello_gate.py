#!/usr/bin/env python3
"""Trello validation gate CLI.

Commands:
  register <doc_id> <blog_title>   Create a Trello card for a newly uploaded blog
  poll                             Check all pending cards; trigger translation if both validated
  retry <doc_id>                   Re-create a failed card or force-check a pending one
  status                           Show all tracked cards and their current state
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

import sys
sys.path.insert(0, str(_ROOT))

from app.services.trello_client import TrelloClient
from app.services.trello_state import TrelloState
from app.services.comment_resolution import (
    resolve_all_comments,
    format_stage9_summary,
    DRIVE_RESOLVE_FAILURE_NOTE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

TRELLO_STALE_DAYS = int(os.environ.get("TRELLO_STALE_DAYS", "14"))
TRELLO_FAILED_LIST_NAME = os.environ.get("TRELLO_FAILED_LIST_NAME", "Failed translation")


def _make_drive_url(doc_id):
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def cmd_register(doc_id, blog_title):
    """Create a Trello card for the blog and record it in the local DB."""
    drive_url = _make_drive_url(doc_id)
    state = TrelloState()

    existing = state.get_by_doc_id(doc_id)
    if existing and existing["status"] not in ("failed",):
        print(
            f"Warning: doc_id {doc_id!r} is already tracked "
            f"(status={existing['status']!r}, card={existing['card_id']!r})."
        )
        print("Use 'retry' to re-create a failed card or force a handoff.")
        return

    try:
        client = TrelloClient()
        client.resolve_list_ids()
        card_id = client.create_validation_card(blog_title, drive_url)
    except Exception as e:
        print(
            f"Warning: Trello card creation failed for doc_id={doc_id!r} — {e}\n"
            f"The blog is safely saved to Drive. Run 'python3 trello_gate.py retry {doc_id}' later."
        )
        logger.warning("Trello card creation failed for doc_id=%r: %s", doc_id, e)
        return

    if existing and existing["status"] == "failed":
        state.update_card_id(doc_id, card_id)
        state.reset_to_pending(doc_id)
    else:
        state.insert(doc_id, card_id, blog_title, drive_url)

    print(f"Trello card created: {card_id}")
    print(f"Doc: {drive_url}")
    _ensure_poller_running()


def _ensure_poller_running():
    """Start trello_poller.py in the background if it isn't already running."""
    try:
        check = subprocess.run(["pgrep", "-f", "trello_poller.py"], capture_output=True)
        if check.returncode == 0:
            print("  (Poller already running — not starting a second instance.)")
            logger.info("trello_poller.py already running; skipping auto-start")
            return
    except FileNotFoundError:
        pass  # pgrep unavailable; proceed to start

    poller = str(_ROOT / "trello_poller.py")
    try:
        _poller_log = _ROOT / "logs" / "poller.log"
        _poller_log.parent.mkdir(exist_ok=True)
        _poller_fh = open(_poller_log, "a")
        subprocess.Popen(
            [sys.executable, poller],
            cwd=str(_ROOT),
            start_new_session=True,   # detach from parent session so it survives terminal close
            stdout=_poller_fh,
            stderr=_poller_fh,
        )
        print(f"  ✓ Trello poller started in the background (log: {_poller_log}).")
        logger.info("Started trello_poller.py as background process (log: %s)", _poller_log)
    except Exception as e:
        print(f"  Warning: could not start poller automatically — {e}")
        print(f"  Start it manually: python3 trello_poller.py")
        logger.warning("Could not auto-start trello_poller.py: %s", e)


def poll_once(state=None, client=None, card_id=None):
    """Check pending cards; trigger translation for any with both validations done.

    If card_id is given, only that specific card is checked.
    """
    if state is None:
        state = TrelloState()
    if client is None:
        client = TrelloClient()
        client.resolve_list_ids()

    if card_id:
        row = state.get_by_card_id(card_id)
        pending = [row] if row and row["status"] == "pending" else []
    else:
        pending = state.get_pending()

    if not pending:
        logger.info("poll_once: 0 pending cards")
        return

    logger.info("poll_once: %d pending card(s)", len(pending))

    translating_list = os.environ.get("TRELLO_TRANSLATING_LIST_NAME", "Doing")
    item_1 = os.environ.get("TRELLO_CHECKLIST_ITEM_1", "Validated by Haleema")
    item_2 = os.environ.get("TRELLO_CHECKLIST_ITEM_2", "Validated by Jeremy")

    for row in pending:
        doc_id = row["doc_id"]
        card_id = row["card_id"]
        logger.info("Checking card %r (doc_id=%r)", card_id, doc_id)

        try:
            checklist_state = client.get_card_checklist_state(card_id)
        except Exception as e:
            logger.warning("Could not check card %r: %s — skipping", card_id, e)
            continue

        if checklist_state is None:
            # Card was deleted from Trello
            logger.warning("Card %r not found (deleted?); marking failed", card_id)
            state.mark_failed(doc_id, "card deleted from Trello")
            continue

        validated_1 = checklist_state.get(item_1, False)
        validated_2 = checklist_state.get(item_2, False)

        # Staleness check: move to "Failed translation" if pending > 14 days without both validations
        try:
            created_at_dt = datetime.fromisoformat(row["created_at"])
            if created_at_dt.tzinfo is None:
                created_at_dt = created_at_dt.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - created_at_dt
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Could not parse created_at for doc_id=%r (%s) — skipping staleness check",
                doc_id, exc,
            )
            age = timedelta(0)

        if age > timedelta(days=TRELLO_STALE_DAYS) and not (validated_1 and validated_2):
            try:
                client.ensure_list_id(TRELLO_FAILED_LIST_NAME)
                client.move_card_to_list(card_id, TRELLO_FAILED_LIST_NAME)
                client.add_comment(
                    card_id,
                    "Marked as failed translation — this card was pending for more than "
                    f"{TRELLO_STALE_DAYS} days without validation. "
                    f"Re-run with `python3 trello_gate.py retry {doc_id}` if you want to retry.",
                )
            except Exception as exc:
                logger.warning("Could not move stale card %r to failed list: %s", card_id, exc)
            state.mark_failed_stale(doc_id)
            logger.info(
                "[Trello gate] Card %r for doc_id=%r marked stale after %d days, "
                "moved to %r list",
                card_id, doc_id, TRELLO_STALE_DAYS, TRELLO_FAILED_LIST_NAME,
            )
            continue

        if validated_1 and validated_2:
            logger.info("Both validations complete for doc_id=%r — running comment resolution", doc_id)
            state.mark_handed_off(doc_id)

            try:
                client.move_card_to_list(card_id, translating_list)
                client.add_comment(
                    card_id,
                    "✅ Both validations complete. Reviewing comments…",
                )
            except Exception as e:
                logger.warning("Trello update before comment resolution failed: %s", e)

            print(f"\nBoth validations done for {row['blog_title']!r}.")
            print(f"Running comment resolution for doc_id={doc_id!r}...\n")

            try:
                summary = resolve_all_comments(doc_id)
            except Exception as e:
                logger.warning(
                    "Comment resolution fatal error for doc_id=%r: %s — resetting to pending",
                    doc_id, e,
                )
                try:
                    client.add_comment(
                        card_id,
                        f"❌ Comment resolution failed with an unexpected error: {e}\n"
                        "Translation paused. Check logs.",
                    )
                except Exception:
                    pass
                state.reset_to_pending(doc_id)
                continue

            drive_resolve_failures = [
                entry for entry in summary.get("failed", [])
                if DRIVE_RESOLVE_FAILURE_NOTE in entry.get("note", "")
            ]

            if drive_resolve_failures:
                # Edit was applied but Drive comment was not resolved. If we reset to pending
                # and the next poll sees both boxes still ticked, it would run Stage 9 again
                # and apply the same edit a second time. Untick first so the poller waits.
                logger.warning(
                    "Drive-resolve failure(s) for doc_id=%r — unticking checklist, "
                    "resetting to pending",
                    doc_id,
                )
                trello_msg = format_stage9_summary(summary, translation_triggered=False)
                try:
                    client.add_comment(card_id, trello_msg)
                    client.uncheck_all_checklist_items(card_id)
                    client.move_card_to_list(card_id, os.environ.get(
                        "TRELLO_PENDING_LIST_NAME", "To Do"
                    ))
                except Exception as e:
                    logger.warning("Could not update Trello after Drive-resolve failure: %s", e)
                state.reset_to_pending(doc_id)
                continue

            trello_msg = format_stage9_summary(summary, translation_triggered=True)
            try:
                client.add_comment(card_id, trello_msg)
            except Exception as e:
                logger.warning("Could not post Stage 9 summary to Trello: %s", e)

            print(f"Comment resolution complete. Starting translation for doc_id={doc_id!r}...\n")
            try:
                _run_translation(doc_id)
            except Exception as launch_err:
                # _run_translation already wrote mark_failed_error + Trello comment.
                # Catch here so the for-loop continues to process remaining pending cards.
                logger.error(
                    "Translation launch failed for doc_id=%r: %s", doc_id, launch_err
                )
        else:
            checked = sum([validated_1, validated_2])
            logger.info("Card %r: %d/2 validations complete — waiting", card_id, checked)


def _run_translation(doc_id):
    _venv_python = _ROOT / "keyword_forge" / ".venv" / "bin" / "python"
    if not _venv_python.exists():
        reason = (
            f"Venv interpreter not found at {_venv_python}. "
            "Run: cd keyword_forge && python -m venv .venv && pip install -r requirements.txt"
        )
        # Best-effort failure routing — must happen before raise so the card
        # doesn't stay stuck in handed_off with no error recorded.
        try:
            _state = TrelloState()
            _row = _state.get_by_doc_id(doc_id)
            if _row:
                _state.mark_failed_error(doc_id, reason=reason)
                try:
                    _client = TrelloClient()
                    _client.resolve_list_ids()
                    _client.move_card_to_list(_row["card_id"], TRELLO_FAILED_LIST_NAME)
                    _client.add_comment(
                        _row["card_id"],
                        f"❌ Translation launch failed — venv missing at {_venv_python}\n"
                        f"Re-run with `python3 trello_gate.py retry {doc_id}`",
                    )
                except Exception as _te:
                    logger.warning("[failure-routing] Trello update failed for doc_id=%r: %s", doc_id, _te)
        except Exception as _de:
            logger.error("[failure-routing] DB routing failed for doc_id=%r: %s", doc_id, _de)
        raise RuntimeError(reason)
    _trans_log = _ROOT / "logs" / "translation.log"
    _trans_log.parent.mkdir(exist_ok=True)
    with open(_trans_log, "a") as _f:
        _f.write(f"\n{'='*60}\n[{datetime.now().isoformat()}] Starting translation for doc_id={doc_id}\n")
    _trans_fh = open(_trans_log, "a")
    subprocess.Popen(
        [str(_venv_python), "translation_workflow.py", "--resume", doc_id],
        cwd=str(_ROOT),
        stdout=_trans_fh,
        stderr=_trans_fh,
    )


def cmd_poll():
    state = TrelloState()
    client = TrelloClient()
    try:
        client.resolve_list_ids()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    poll_once(state, client)


def cmd_retry(doc_id):
    state = TrelloState()
    row = state.get_by_doc_id(doc_id)

    if row is None:
        # No record — attempt to create card now
        print(f"No record found for doc_id={doc_id!r}.")
        blog_title = input("Enter the blog title to create a card: ").strip()
        if not blog_title:
            print("Error: blog title is required.")
            sys.exit(1)
        cmd_register(doc_id, blog_title)
        return

    if row["status"] == "failed":
        print(f"Retrying failed card for doc_id={doc_id!r}...")
        cmd_register(doc_id, row["blog_title"])
        return

    if row["status"] in ("failed_stale", "failed_error"):
        client = TrelloClient()
        try:
            client.resolve_list_ids()
        except RuntimeError as e:
            print(f"Error: {e}")
            sys.exit(1)
        pending_list = os.environ.get("TRELLO_PENDING_LIST_NAME", "To Do")
        try:
            client.move_card_to_list(row["card_id"], pending_list)
            client.uncheck_all_checklist_items(row["card_id"])
        except Exception as e:
            print(f"Warning: Trello update failed: {e}")
        state.reset_to_pending_new_clock(doc_id)
        label = "crash" if row["status"] == "failed_error" else "staleness timeout"
        print(f"Card re-activated (was failed due to {label}). 14-day staleness clock restarted.")
        return

    if row["status"] == "pending":
        # Re-check checklist right now and force handoff if both done
        client = TrelloClient()
        try:
            client.resolve_list_ids()
        except RuntimeError as e:
            print(f"Error: {e}")
            sys.exit(1)

        checklist_state = client.get_card_checklist_state(row["card_id"])
        item_1 = os.environ.get("TRELLO_CHECKLIST_ITEM_1", "Validated by Haleema")
        item_2 = os.environ.get("TRELLO_CHECKLIST_ITEM_2", "Validated by Jeremy")

        if checklist_state and checklist_state.get(item_1) and checklist_state.get(item_2):
            print("Both validations are done. Forcing handoff now...")
            poll_once(state, client)
        else:
            checked = sum([
                bool(checklist_state.get(item_1)) if checklist_state else False,
                bool(checklist_state.get(item_2)) if checklist_state else False,
            ])
            print(
                f"Card {row['card_id']!r} has {checked}/2 validations complete. "
                "Nothing to force yet."
            )
        return

    print(
        f"doc_id={doc_id!r} has status={row['status']!r}. "
        "Only 'pending', 'failed', 'failed_stale', and 'failed_error' cards can be retried."
    )


def cmd_status():
    state = TrelloState()
    rows = state.get_all()

    if not rows:
        print("No cards tracked yet.")
        return

    col_widths = [44, 30, 24, 13, 20]
    header = (
        f"{'doc_id':<{col_widths[0]}} "
        f"{'blog_title':<{col_widths[1]}} "
        f"{'card_id':<{col_widths[2]}} "
        f"{'status':<{col_widths[3]}} "
        f"{'created_at':<{col_widths[4]}}"
    )
    print(header)
    print("-" * sum(col_widths + [4]))

    for r in rows:
        title = r["blog_title"][:28] + ".." if len(r["blog_title"]) > 30 else r["blog_title"]
        created = r["created_at"][:19] if r["created_at"] else ""
        print(
            f"{r['doc_id']:<{col_widths[0]}} "
            f"{title:<{col_widths[1]}} "
            f"{r['card_id']:<{col_widths[2]}} "
            f"{r['status']:<{col_widths[3]}} "
            f"{created:<{col_widths[4]}}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Trello validation gate for the SEO-Forge translation pipeline"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register", help="Create a Trello card for an uploaded blog")
    reg.add_argument("doc_id", help="Google Doc ID of the uploaded English blog")
    reg.add_argument("blog_title", help="Title of the blog post")

    sub.add_parser("poll", help="Check all pending cards and trigger translations if ready")

    ret = sub.add_parser("retry", help="Retry a failed card or force-check a pending one")
    ret.add_argument("doc_id", help="Google Doc ID to retry")

    sub.add_parser("status", help="Show all tracked cards and their state")

    args = parser.parse_args()

    if args.command == "register":
        cmd_register(args.doc_id, args.blog_title)
    elif args.command == "poll":
        cmd_poll()
    elif args.command == "retry":
        cmd_retry(args.doc_id)
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
