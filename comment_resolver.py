#!/usr/bin/env python3
"""Stage 9 — Comment Resolution CLI (standalone entry point).

The Trello poller calls resolve_all_comments() directly; this script is for manual use.

Usage:
    python comment_resolver.py --resume <doc_id>

Exit codes:
    0 — resolution complete (or no comments found)
    1 — fatal error (initial fetch failed or unexpected exception)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(_ROOT))

from app.services.trello_client import TrelloClient
from app.services.trello_state import TrelloState
from app.services.comment_resolution import resolve_all_comments, format_stage9_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 9: resolve Google Doc comments via Claude Code (claude -p)"
    )
    parser.add_argument("--resume", metavar="DOC_ID", required=True,
                        help="Google Doc ID to process")
    args = parser.parse_args()

    doc_id = args.resume

    state = TrelloState()
    row = state.get_by_doc_id(doc_id)
    if row is None:
        print(f"Error: no Trello record for doc_id={doc_id!r}. "
              "Register via trello_gate.py register first.")
        sys.exit(1)

    card_id = row["card_id"]
    client = TrelloClient()
    try:
        client.resolve_list_ids()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        summary = resolve_all_comments(doc_id)
    except Exception as e:
        logger.error("Fatal error for doc_id=%r: %s", doc_id, e)
        _try_post(client, card_id,
                  f"Comment resolution failed with an unexpected error: {e}\n"
                  "Check logs and resolve manually.")
        sys.exit(1)

    _try_post(client, card_id, format_stage9_summary(summary))
    logger.info(
        "Done for doc_id=%r: %d applied, %d flagged, %d failed",
        doc_id, len(summary["applied"]), len(summary["flagged_low_confidence"]),
        len(summary["failed"]),
    )
    sys.exit(0)


def _try_post(client: TrelloClient, card_id: str, text: str) -> None:
    try:
        client.add_comment(card_id, text)
    except Exception as e:
        logger.warning("Could not post Trello comment: %s", e)


if __name__ == "__main__":
    main()
