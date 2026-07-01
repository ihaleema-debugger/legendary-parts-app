#!/usr/bin/env python3
"""Background daemon that polls Trello every N minutes for completed validations.

Usage:
  python3 trello_poller.py            # uses TRELLO_POLLING_INTERVAL_MINUTES from .env (default 5)
  python3 trello_poller.py --interval 2   # override interval in minutes

Press Ctrl+C to stop.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

sys.path.insert(0, str(_ROOT))

from app.services.trello_client import TrelloClient
from app.services.trello_state import TrelloState
from trello_gate import poll_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def run(interval_minutes, card_id=None):
    state = TrelloState()
    client = TrelloClient()

    try:
        client.resolve_list_ids()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if card_id:
        print(f"Trello poller started — watching card {card_id} every {interval_minutes} minute(s). Press Ctrl+C to stop.")
        logger.info("Poller started with interval=%dm, card_id=%s", interval_minutes, card_id)
    else:
        print(f"Trello poller started — checking every {interval_minutes} minute(s). Press Ctrl+C to stop.")
        logger.info("Poller started with interval=%dm", interval_minutes)

    while True:
        try:
            poll_once(state, client, card_id=card_id)
        except Exception as e:
            logger.warning("poll_once raised an unexpected error: %s", e)

        time.sleep(interval_minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="Trello validation gate poller")
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Polling interval in minutes (overrides TRELLO_POLLING_INTERVAL_MINUTES)",
    )
    parser.add_argument(
        "--card-id",
        default=None,
        help="Only poll this specific Trello card ID (skips all other pending cards)",
    )
    args = parser.parse_args()

    interval = args.interval or int(os.environ.get("TRELLO_POLLING_INTERVAL_MINUTES", "5"))
    run(interval, card_id=args.card_id)


if __name__ == "__main__":
    main()
