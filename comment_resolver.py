#!/usr/bin/env python3
"""Stage 9 — Comment Resolution CLI.

Called by trello_gate.py after both Trello checklist items are ticked,
before translation_workflow.py is invoked.

Usage:
    python comment_resolver.py --resume <doc_id>

Exit codes:
    0 — all comments resolved (or there were none); translation may proceed
    1 — one or more comments could not be auto-resolved; translation is paused
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(_ROOT))

from app.services.trello_client import TrelloClient
from app.services.trello_state import TrelloState
from app.services.comment_resolver_service import resolve_comments, build_trello_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_INCOMPLETE_MSG = (
    "Comment resolution incomplete: {n} comment(s) could not be auto-resolved. "
    "Translation paused. Resolve manually in the doc and tick the "
    "'Validated by Jeremy' box again to retry."
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 9: resolve Google Doc comments before translation"
    )
    parser.add_argument(
        "--resume",
        metavar="DOC_ID",
        required=True,
        help="Google Doc ID to process",
    )
    args = parser.parse_args()

    doc_id = args.resume
    model = os.environ.get("COMMENT_RESOLVER_MODEL", "claude-sonnet-4-5")

    state = TrelloState()
    row = state.get_by_doc_id(doc_id)
    if row is None:
        print(
            f"Error: no Trello record found for doc_id={doc_id!r}. "
            "Was this doc registered via trello_gate.py register?"
        )
        sys.exit(1)

    card_id = row["card_id"]

    client = TrelloClient()
    try:
        client.resolve_list_ids()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    try:
        direct, interpretive, skipped = resolve_comments(doc_id, state, model)
    except Exception as e:
        logger.error("Fatal error during comment resolution for doc_id=%r: %s", doc_id, e)
        _try_post(
            client,
            card_id,
            f"❌ Comment resolution failed with an unexpected error: {e}\n"
            "Translation paused. Check logs and resolve the issue manually.",
        )
        sys.exit(1)

    if not direct and not interpretive and not skipped:
        logger.info("No comments to resolve for doc_id=%r — proceeding to translation", doc_id)
        sys.exit(0)

    if skipped:
        summary = _INCOMPLETE_MSG.format(n=len(skipped))
        print(summary)
        _try_post(client, card_id, summary)
        sys.exit(1)

    summary = build_trello_summary(direct, interpretive, 0)
    _try_post(client, card_id, summary)
    logger.info(
        "Comment resolution complete for doc_id=%r: %d direct, %d interpretive",
        doc_id, len(direct), len(interpretive),
    )
    sys.exit(0)


def _try_post(client: TrelloClient, card_id: str, text: str) -> None:
    try:
        client.add_comment(card_id, text)
    except Exception as e:
        logger.warning("Could not post Trello comment: %s", e)


if __name__ == "__main__":
    main()
