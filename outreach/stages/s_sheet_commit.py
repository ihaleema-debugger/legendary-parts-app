"""
Piece 4 — commit built records into contacts.json.
Skips duplicates on domain. Backs up before writing. Prints a report.

Run from the repo root:
    python outreach/stages/s_sheet_commit.py
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from outreach.stages.s_sheet_build import build_records

_CONTACTS_PATH = Path(__file__).parents[2] / "outreach" / "config" / "contacts.json"
_BACKUP_PATH = _CONTACTS_PATH.with_suffix(".json.bak")


def commit_records() -> dict:
    """Append new sheet records into contacts.json. Returns a summary dict."""

    new_records = build_records()

    if not _CONTACTS_PATH.exists():
        raise FileNotFoundError(
            f"contacts.json not found at: {_CONTACTS_PATH}\n"
            "Check the path. This script will not create a blank file."
        )

    try:
        data = json.loads(_CONTACTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"contacts.json is not valid JSON: {e}\n"
            f"File: {_CONTACTS_PATH}"
        ) from e

    if "contacts" not in data or not isinstance(data["contacts"], list):
        raise RuntimeError(
            f"contacts.json must have a top-level 'contacts' list.\n"
            f"Got keys: {list(data.keys())}"
        )

    existing = data["contacts"]
    before_count = len(existing)

    # null domains never match a new record (new records always have a real domain)
    existing_domains = {c["domain"] for c in existing if c.get("domain") is not None}

    to_add = []
    skipped_domains = []
    for rec in new_records:
        if rec["domain"] in existing_domains:
            skipped_domains.append(rec["domain"])
        else:
            to_add.append(rec)

    # back up before touching the file
    shutil.copy2(_CONTACTS_PATH, _BACKUP_PATH)

    data["contacts"] = existing + to_add
    _CONTACTS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "before": before_count,
        "added": len(to_add),
        "added_domains": [r["domain"] for r in to_add],
        "skipped": len(skipped_domains),
        "skipped_domains": skipped_domains,
        "after": before_count + len(to_add),
    }


def main() -> None:
    s = commit_records()

    print(f"Before: {s['before']} contacts.")
    print()

    print(f"Added: {s['added']}.")
    for d in s["added_domains"]:
        print(f"  + {d}")

    print()
    print(f"Skipped (already present): {s['skipped']}.")
    for d in s["skipped_domains"]:
        print(f"  ~ {d}")

    print()
    print(f"After: {s['after']} contacts.")


if __name__ == "__main__":
    main()
