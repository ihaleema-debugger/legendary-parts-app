#!/usr/bin/env python3
"""Publish a blog post to Google Drive and create a Trello validation card.

Usage:
    python tools/publish_blog.py --blog-path path/to/blog.md --title "Blog Title"

Steps performed:
    1. Reads the markdown file at --blog-path
    2. Uploads it to Google Drive as a Google Doc (supportsAllDrives=True)
    3. Calls trello_gate.cmd_register() to create a Trello validation card
       and auto-start the background poller

Required .env keys:
    GOOGLE_SERVICE_ACCOUNT_PATH, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SHARED_DRIVE_ID
    TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID, TRELLO_PENDING_LIST_NAME
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.services.drive_uploader import upload_blog_to_drive
import trello_gate


def main():
    parser = argparse.ArgumentParser(
        description="Upload blog to Google Drive and register Trello validation card"
    )
    parser.add_argument("--blog-path", required=True, help="Path to blog.md file")
    parser.add_argument("--title", required=True, help="Blog post title (used for Drive filename and Trello card name)")
    args = parser.parse_args()

    blog_path = Path(args.blog_path).expanduser().resolve()
    if not blog_path.exists():
        print(f"Error: blog file not found: {blog_path}", file=sys.stderr)
        sys.exit(1)

    content = blog_path.read_text(encoding="utf-8")

    # A8b — Upload to Google Drive
    print(f"Uploading to Google Drive: '{args.title}'")
    try:
        file_meta = upload_blog_to_drive(title=args.title, content=content)
    except RuntimeError as e:
        print(f"Error: Drive upload failed — {e}", file=sys.stderr)
        sys.exit(1)

    doc_id = file_meta["id"]
    drive_url = file_meta["webViewLink"]
    print(f"  Doc ID  : {doc_id}")
    print(f"  Drive   : {drive_url}")

    # A8c — Create Trello validation card (cmd_register also auto-starts the poller)
    print(f"Creating Trello validation card: '{args.title}'")
    trello_gate.cmd_register(doc_id, args.title)

    print(f"\nPublished.")
    print(f"  Drive : {drive_url}")


if __name__ == "__main__":
    main()
