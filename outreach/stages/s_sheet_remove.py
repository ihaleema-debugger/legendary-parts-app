"""
Remove stale sheet-imported records from contacts.json so they can be
re-imported fresh with updated data from the sheet.

Derives the domain list from build_records() — stays in sync with the sheet.
Refuses to remove any record that already has a non-blank personalization_hook
(protects anything hand-edited in contacts.json).

Run from the repo root:
    python outreach/stages/s_sheet_remove.py
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from outreach.stages.s_sheet_build import build_records

_CONTACTS_PATH = Path(__file__).parents[2] / "outreach" / "config" / "contacts.json"
_BACKUP_PATH = _CONTACTS_PATH.with_suffix(".json.bak")


def remove_stale() -> dict:
    """Remove sheet-derived domains from contacts.json. Returns a summary dict."""

    # 1. Get the target domains from the sheet
    sheet_records = build_records()
    target_domains = {r["domain"] for r in sheet_records}

    # 2. Read existing contacts.json
    if not _CONTACTS_PATH.exists():
        raise FileNotFoundError(
            f"contacts.json not found at: {_CONTACTS_PATH}\n"
            "Check the path."
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

    # 3. Classify each target domain
    to_remove = []    # (domain, hook_was_blank)
    protected = []    # domain has a non-blank hook — skip to protect hand edits
    not_found = []    # domain not in contacts.json at all

    for domain in sorted(target_domains):
        match = next((c for c in existing if c.get("domain") == domain), None)
        if match is None:
            not_found.append(domain)
            continue
        hook = (match.get("personalization_hook") or "").strip()
        if hook:
            protected.append((domain, hook))
        else:
            to_remove.append(domain)

    # 4. Back up, then write
    remove_set = set(to_remove)
    kept = [c for c in existing if c.get("domain") not in remove_set]

    shutil.copy2(_CONTACTS_PATH, _BACKUP_PATH)
    data["contacts"] = kept
    _CONTACTS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return {
        "before": before_count,
        "removed": to_remove,
        "protected": protected,
        "not_found": not_found,
        "after": len(kept),
    }


def main() -> None:
    s = remove_stale()

    print(f"Before: {s['before']} contacts.")
    print()

    print(f"Removed: {len(s['removed'])}.")
    for d in s["removed"]:
        print(f"  - {d}")

    if s["protected"]:
        print()
        print(f"PROTECTED (non-blank hook — NOT removed): {len(s['protected'])}.")
        for d, hook in s["protected"]:
            print(f"  ! {d}  hook: \"{hook}\"")

    if s["not_found"]:
        print()
        print(f"Not found in contacts.json (nothing to remove): {len(s['not_found'])}.")
        for d in s["not_found"]:
            print(f"  ? {d}")

    print()
    print(f"After: {s['after']} contacts.")


if __name__ == "__main__":
    main()
