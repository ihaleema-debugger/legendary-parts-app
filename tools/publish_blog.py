#!/usr/bin/env python3
"""Publish a structured blog post to Google Drive and create a Trello validation card.

Usage:
    python tools/publish_blog.py --blocks-path path/to/blog_blocks.json

The JSON file must have the shape:
    {
      "blocks": [{"level": "title"|"h3"|"h4"|"p", "text": "...", "links": [...]}, ...],
      "faq_schema": "<script>...</script>",
      "metadata": {"primary_keyword": "...", "target_word_count": 850, "actual_word_count": 913}
    }

Steps performed:
    1. Reads and parses the JSON file
    2. Validates block schema (each block must have "level" and "text")
    3. Extracts title from the first block with level == "title"
    4. Creates an empty Google Doc via Drive API
    5. Writes structured content via Docs API batchUpdate (headings + links)
    6. Calls trello_gate.cmd_register() to create a Trello validation card

Required .env keys:
    GOOGLE_SERVICE_ACCOUNT_PATH, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHARED_DRIVE_ID
    TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID, TRELLO_PENDING_LIST_NAME
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.drive_uploader import create_doc
from app.services.docs_client import write_structured_doc
import trello_gate


def _validate_blocks(blocks: list) -> None:
    """Raise ValueError if blocks list is empty or any block is missing required keys."""
    if not blocks:
        raise ValueError("blocks list is empty")
    for i, block in enumerate(blocks):
        if "level" not in block:
            raise ValueError(f"Block {i} is missing required key 'level': {block!r}")
        if "text" not in block:
            raise ValueError(f"Block {i} is missing required key 'text': {block!r}")


def _extract_title(blocks: list) -> str:
    """Return text of first block with level == 'title'. Raises ValueError if none found."""
    for block in blocks:
        if block.get("level") == "title" and block.get("text"):
            return block["text"]
    raise ValueError(
        "No title block found in blocks JSON. "
        "First block must have level='title' with non-empty text."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish structured blog to Google Drive + Trello"
    )
    parser.add_argument(
        "--blocks-path",
        required=True,
        help="Path to blog_blocks.json produced by seo-blog-writer",
    )
    args = parser.parse_args()

    blocks_path = Path(args.blocks_path).expanduser().resolve()
    if not blocks_path.exists():
        print(f"Error: blocks file not found: {blocks_path}", file=sys.stderr)
        sys.exit(1)

    # Parse JSON — fail clearly if malformed
    try:
        payload = json.loads(blocks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {blocks_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if "blocks" not in payload:
        print("Error: JSON is missing top-level 'blocks' key", file=sys.stderr)
        sys.exit(1)

    blocks = payload["blocks"]

    # Validate block schema before touching Drive
    try:
        _validate_blocks(blocks)
        title = _extract_title(blocks)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Create empty Google Doc
    print(f"Creating Google Doc: '{title}'")
    try:
        file_meta = create_doc(title=title)
    except RuntimeError as e:
        print(f"Error: Doc creation failed — {e}", file=sys.stderr)
        sys.exit(1)

    doc_id = file_meta["id"]
    drive_url = file_meta["webViewLink"]
    print(f"  Doc ID  : {doc_id}")
    print(f"  Drive   : {drive_url}")

    # Write structured content (headings + links)
    print("Writing structured content...")
    try:
        write_structured_doc(doc_id, blocks)
    except Exception as e:
        print(f"Error: write_structured_doc failed — {e}", file=sys.stderr)
        sys.exit(1)

    # Create Trello validation card
    print(f"Creating Trello validation card: '{title}'")
    trello_gate.cmd_register(doc_id, title)

    print(f"\nPublished.")
    print(f"  Drive : {drive_url}")


if __name__ == "__main__":
    main()
