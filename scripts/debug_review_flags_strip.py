"""Diagnostic: show what the Review Flags stripper sees and removes.

Usage:
    python scripts/debug_review_flags_strip.py <file_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import re
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from app.services.drive_uploader import _get_service
from workflows.Publishers.gdoc_reader import _strip_review_flags


def main(file_id: str) -> None:
    service = _get_service()
    raw = service.files().export(
        fileId=file_id, mimeType="text/html"
    ).execute()
    html = raw.decode("utf-8") if isinstance(raw, bytes) else raw

    body = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    inner = body.group(1).strip() if body else html

    print("=" * 70)
    print("RAW BODY — last 1000 chars")
    print("=" * 70)
    print(inner[-1000:])
    print()

    stripped = _strip_review_flags(inner)
    print("=" * 70)
    print(f"STRIPPED BODY — last 1000 chars (total length: {len(stripped)})")
    print("=" * 70)
    print(stripped[-1000:])
    print()

    if "review flags" in stripped.lower():
        print("⚠️  'Review Flags' still present after stripping")
    else:
        print("✓ 'Review Flags' fully removed")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/debug_review_flags_strip.py <file_id>")
        sys.exit(1)
    main(sys.argv[1])
