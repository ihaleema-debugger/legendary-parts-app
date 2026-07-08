"""
Piece 4 — commit built records into contacts.json.
Skips duplicates on domain. Backs up before writing. Prints a report.

Run from the repo root:
    python outreach/stages/s_sheet_commit.py
    python outreach/stages/s_sheet_commit.py --update-hooks --dry-run --tab 'Feuille 2'
    python outreach/stages/s_sheet_commit.py --update-hooks --tab 'Feuille 2'
    python outreach/stages/s_sheet_commit.py --test
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from outreach.stages.s_sheet_build import build_records

_CONTACTS_PATH = Path(__file__).parents[2] / "outreach" / "config" / "contacts.json"
_BACKUP_PATH = _CONTACTS_PATH.with_suffix(".json.bak")


def _load_contacts(path: Path) -> dict:
    """Read + validate a contacts.json-shaped file."""
    if not path.exists():
        raise FileNotFoundError(
            f"contacts.json not found at: {path}\n"
            "Check the path. This script will not create a blank file."
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"contacts.json is not valid JSON: {e}\n"
            f"File: {path}"
        ) from e

    if "contacts" not in data or not isinstance(data["contacts"], list):
        raise RuntimeError(
            f"contacts.json must have a top-level 'contacts' list.\n"
            f"Got keys: {list(data.keys())}"
        )

    return data


def _classify_hook(existing_hook: str, new_hook: str) -> str:
    """Return "blank_sheet_hook", "unchanged", or "updated".

    A blank/whitespace-only sheet Hook is never applied — protects an
    existing hand-written hook from being silently wiped by an empty cell.
    If both sides are already blank, that's "unchanged" (nothing to protect).
    """
    if not new_hook.strip():
        return "blank_sheet_hook" if existing_hook.strip() else "unchanged"
    if existing_hook == new_hook:
        return "unchanged"
    return "updated"


def commit_records(sheet_id: str | None = None, tab: str | None = None,
                    contacts_path: str | None = None) -> dict:
    """Append new sheet records into contacts.json. Returns a summary dict."""

    new_records = build_records(sheet_id, tab)

    contacts_file = Path(contacts_path) if contacts_path else _CONTACTS_PATH
    backup_file = contacts_file.with_suffix(".json.bak")
    data = _load_contacts(contacts_file)

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
    shutil.copy2(contacts_file, backup_file)

    data["contacts"] = existing + to_add
    contacts_file.write_text(
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


def update_hooks(sheet_id: str | None = None, tab: str | None = None,
                  dry_run: bool = False, contacts_path: str | None = None,
                  build_fn=None) -> dict:
    """Refresh personalization_hook on domains already in contacts.json.

    Never adds or removes contacts — only overwrites personalization_hook on
    records matched by domain. Every other field on those records is left
    exactly as-is. Backs up contacts.json before writing, and only writes at
    all if dry_run is False and at least one hook actually changed.
    """
    fn = build_fn or build_records
    records = fn(sheet_id, tab)

    contacts_file = Path(contacts_path) if contacts_path else _CONTACTS_PATH
    backup_file = contacts_file.with_suffix(".json.bak")
    data = _load_contacts(contacts_file)

    existing = data["contacts"]
    # NOTE: if contacts.json ever has duplicate domains (shouldn't happen via
    # commit_records()'s own dedup, but could via hand-editing), this keeps
    # only the last match — same silent-last-match assumption already present
    # in s_sheet_remove.py's remove_stale().
    existing_by_domain = {c["domain"]: c for c in existing if c.get("domain") is not None}

    updated = []
    unchanged = []
    blank_sheet_hook = []
    not_found = []

    for rec in records:
        domain = rec["domain"]
        new_hook = rec.get("personalization_hook") or ""
        match = existing_by_domain.get(domain)

        if match is None:
            not_found.append(domain)
            continue

        old_hook = match.get("personalization_hook") or ""
        bucket = _classify_hook(old_hook, new_hook)

        if bucket == "blank_sheet_hook":
            blank_sheet_hook.append((domain, old_hook))
        elif bucket == "unchanged":
            unchanged.append((domain, old_hook))
        else:  # "updated"
            updated.append((domain, old_hook, new_hook))
            if not dry_run:
                match["personalization_hook"] = new_hook  # mutates `data` in place

    written = False
    if not dry_run and updated:
        shutil.copy2(contacts_file, backup_file)
        contacts_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written = True

    return {
        "sheet_rows": len(records),
        "total_contacts": len(existing),
        "updated": updated,
        "unchanged": unchanged,
        "blank_sheet_hook": blank_sheet_hook,
        "not_found": not_found,
        "dry_run": dry_run,
        "written": written,
        "backup_path": str(backup_file) if written else None,
    }


def _print_update_hooks_report(s: dict, tab: str | None) -> None:
    if s["dry_run"]:
        print("DRY RUN — no files will be changed.")
        print()

    print(f"Sheet rows checked: {s['sheet_rows']} (tab={tab or 'default'}).")
    print()

    print(f"Updated: {len(s['updated'])}.")
    for domain, old, new in s["updated"]:
        print(f"  * {domain}")
        print(f"      old: \"{old or '(blank)'}\"")
        print(f"      new: \"{new}\"")

    if s["unchanged"]:
        print()
        print(f"Unchanged (sheet hook identical): {len(s['unchanged'])}.")
        for domain, hook in s["unchanged"]:
            print(f"  ~ {domain}")

    if s["blank_sheet_hook"]:
        print()
        print(f"PROTECTED (sheet hook blank, existing hook kept): {len(s['blank_sheet_hook'])}.")
        for domain, old in s["blank_sheet_hook"]:
            print(f"  ! {domain}  kept: \"{old}\"")

    if s["not_found"]:
        print()
        print(f"Not found in contacts.json (nothing to update): {len(s['not_found'])}.")
        for domain in s["not_found"]:
            print(f"  ? {domain}")

    print()
    if s["dry_run"]:
        print(f"DRY RUN complete. {len(s['updated'])} domain(s) would be updated. "
              "Re-run without --dry-run to write.")
    elif s["written"]:
        print(f"Wrote {len(s['updated'])} hook update(s) to contacts.json. "
              f"Backup: {s['backup_path']}")
    else:
        print("No changes to apply — contacts.json not touched, no backup created.")


def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    import argparse

    parser = argparse.ArgumentParser(description="Commit built records into contacts.json.")
    parser.add_argument("--sheet-id", default=None, help="Google Sheet ID (default: SHEET_ID constant)")
    parser.add_argument("--tab", default=None, help="Sheet tab name (default: first sheet, range 'A:ZZ')")
    parser.add_argument(
        "--update-hooks", action="store_true",
        help="Update personalization_hook on domains already in contacts.json. Does not add or remove contacts.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --update-hooks: show the old->new hook diff, write and back up nothing. Requires --update-hooks.",
    )
    args = parser.parse_args()

    if args.dry_run and not args.update_hooks:
        parser.error(
            "--dry-run only works together with --update-hooks. "
            "Add --update-hooks, or drop --dry-run."
        )

    if args.update_hooks:
        s = update_hooks(args.sheet_id, args.tab, dry_run=args.dry_run)
        _print_update_hooks_report(s, args.tab)
        return

    s = commit_records(args.sheet_id, args.tab)

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


# ── self-tests (no live network / Sheets calls) ─────────────────────────────

def _run_tests() -> None:
    import tempfile
    from unittest.mock import patch

    print("Running s_sheet_commit tests...")

    # T1 — _classify_hook pure-function cases
    assert _classify_hook("old", "new") == "updated"
    assert _classify_hook("same", "same") == "unchanged"
    assert _classify_hook("has a hook", "") == "blank_sheet_hook"
    assert _classify_hook("", "") == "unchanged"
    assert _classify_hook("", "   ") == "unchanged"
    print("  PASS  [T1]  _classify_hook: updated / unchanged / blank-protects")

    def _write_contacts(tmp, contacts):
        p = Path(tmp) / "contacts.json"
        p.write_text(json.dumps({"contacts": contacts}, indent=2), encoding="utf-8")
        return p

    # T2 — one real update: written, backed up, on-disk reflects new hook
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "a.com", "personalization_hook": "old hook"}])
        fake = lambda sheet_id, tab: [{"domain": "a.com", "personalization_hook": "new hook"}]
        result = update_hooks(contacts_path=str(cp), build_fn=fake)
        assert result["updated"] == [("a.com", "old hook", "new hook")], result["updated"]
        assert result["written"] is True, result
        assert cp.with_suffix(".json.bak").exists(), "expected backup file to be created"
        on_disk = json.loads(cp.read_text())
        assert on_disk["contacts"][0]["personalization_hook"] == "new hook", on_disk
    print("  PASS  [T2]  one real update -> written=True, backup created, on-disk updated")

    # T3 — identical hook -> unchanged, no write, no backup
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "b.com", "personalization_hook": "same"}])
        fake = lambda sheet_id, tab: [{"domain": "b.com", "personalization_hook": "same"}]
        before_bytes = cp.read_bytes()
        result = update_hooks(contacts_path=str(cp), build_fn=fake)
        assert result["unchanged"] == [("b.com", "same")], result["unchanged"]
        assert result["written"] is False, result
        assert not cp.with_suffix(".json.bak").exists()
        assert cp.read_bytes() == before_bytes
    print("  PASS  [T3]  identical hook -> unchanged, written=False, no backup")

    # T4 — sheet domain not present in contacts.json
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "known.com", "personalization_hook": "x"}])
        fake = lambda sheet_id, tab: [{"domain": "unknown.com", "personalization_hook": "y"}]
        result = update_hooks(contacts_path=str(cp), build_fn=fake)
        assert result["not_found"] == ["unknown.com"], result["not_found"]
        assert result["written"] is False, result
    print("  PASS  [T4]  sheet domain absent from contacts.json -> not_found")

    # T5 — blank sheet hook protects existing non-blank hook
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "d.com", "personalization_hook": "don't erase me"}])
        fake = lambda sheet_id, tab: [{"domain": "d.com", "personalization_hook": ""}]
        result = update_hooks(contacts_path=str(cp), build_fn=fake)
        assert result["blank_sheet_hook"] == [("d.com", "don't erase me")], result["blank_sheet_hook"]
        assert result["written"] is False, result
        assert json.loads(cp.read_text())["contacts"][0]["personalization_hook"] == "don't erase me"
    print("  PASS  [T5]  blank sheet hook protects existing non-blank hook")

    # T6 — dry_run computes the diff but writes and backs up nothing
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "e.com", "personalization_hook": "dry old"}])
        fake = lambda sheet_id, tab: [{"domain": "e.com", "personalization_hook": "dry new"}]
        before_bytes = cp.read_bytes()
        result = update_hooks(contacts_path=str(cp), build_fn=fake, dry_run=True)
        assert result["updated"] == [("e.com", "dry old", "dry new")], result["updated"]
        assert result["written"] is False, result
        assert not cp.with_suffix(".json.bak").exists()
        assert cp.read_bytes() == before_bytes
    print("  PASS  [T6]  dry_run -> diff computed, nothing written or backed up")

    # T7 — default commit_records() add/skip path is unaffected
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write_contacts(tmp, [{"domain": "existing.com", "personalization_hook": "x"}])
        fake_records = [
            {
                "domain": "existing.com", "organisation": "Existing", "lane": 3,
                "outreach_type": "link_building", "market": "multi", "language": "en",
                "proactive": True, "named_contacts": [], "action_url": None,
                "note": None, "fetch_attempts": 0, "personalization_hook": "irrelevant-here",
            },
            {
                "domain": "new.com", "organisation": "New", "lane": 3,
                "outreach_type": "link_building", "market": "multi", "language": "en",
                "proactive": True, "named_contacts": [], "action_url": None,
                "note": None, "fetch_attempts": 0, "personalization_hook": "irrelevant-here",
            },
        ]
        with patch(f"{__name__}.build_records", return_value=fake_records):
            result = commit_records(contacts_path=str(cp))
        assert result["added"] == 1, result
        assert result["skipped"] == 1, result
        assert result["added_domains"] == ["new.com"], result
        assert result["skipped_domains"] == ["existing.com"], result
    print("  PASS  [T7]  default commit_records() add/skip path unaffected")

    # T8 — end-to-end future-row path: a fresh SUPPLIER row (shaped exactly as
    # s_sheet_build.build_records() now produces it, with reason_code carried
    # alongside note) survives commit_records()'s untouched pass-through into
    # contacts.json, then gets blocked by s4_draft's reason_supplier guard.
    # No live sheet/network calls — build_records is patched.
    with tempfile.TemporaryDirectory() as tmp:
        from outreach.stages.s4_draft import run_draft

        cp = _write_contacts(tmp, [])
        fake_supplier_row = [{
            "domain": "thunderbike.de",
            "organisation": "Thunderbike",
            "lane": 3,
            "outreach_type": "link_building",
            "market": "multi",
            "language": "en",
            "proactive": True,
            "named_contacts": [{
                "name": None, "email": "info@thunderbike.de", "needs_lookup": False,
                "role": None, "email_candidate": None, "candidate_source": None,
                "candidate_status": "confirmed",
            }],
            "action_url": None,
            "note": "Reason: SUPPLIER. Angle: German custom Harley parts manufacturer.",
            "reason_code": "SUPPLIER",
            "fetch_attempts": 0,
            "personalization_hook": "noticed Thunderbike's new custom parts catalogue",
        }]

        with patch(f"{__name__}.build_records", return_value=fake_supplier_row):
            commit_result = commit_records(contacts_path=str(cp))
        assert commit_result["added"] == 1, commit_result
        assert commit_result["added_domains"] == ["thunderbike.de"], commit_result

        on_disk = json.loads(cp.read_text())
        assert on_disk["contacts"][0]["reason_code"] == "SUPPLIER", on_disk

        sp = Path(tmp) / "sender.json";    sp.write_text("{}")
        ap = Path(tmp) / "artefacts.json"; ap.write_text("{}")
        tp = Path(tmp) / "templates.json"; tp.write_text("{}")
        lp = Path(tmp) / "lanes.json";     lp.write_text('{"parked_lanes": []}')

        draft_result = run_draft(str(cp), str(sp), str(ap), str(tp), str(lp))
        assert draft_result["drafted"] == 0, draft_result
        assert draft_result["blocked"] == 1, draft_result
        assert draft_result["blocks"][0]["reason"] == "reason_supplier", draft_result["blocks"]
        assert draft_result["blocks"][0]["domain"] == "thunderbike.de", draft_result["blocks"]
    print("  PASS  [T8]  end-to-end: sheet Reason='SUPPLIER' survives build->commit->"
          "contacts.json, blocked at draft as reason_supplier")

    print("\nAll s_sheet_commit tests passed.")


if __name__ == "__main__":
    main()
