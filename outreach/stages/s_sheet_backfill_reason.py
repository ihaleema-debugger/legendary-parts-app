"""
One-time backfill — restore reason_code on sheet-track contacts.json records
that predate the field, by parsing it out of the free-text `note` produced by
s_sheet_build._build_note() (format: "Reason: X" or "Reason: X. Angle: Y").

Never touches records that already have a non-blank reason_code, and never
touches records whose note doesn't start with "Reason: " — those are left
exactly as-is. Backs up before writing, writes only if something changed.

Run from the repo root:
    python outreach/stages/s_sheet_backfill_reason.py --dry-run
    python outreach/stages/s_sheet_backfill_reason.py
    python outreach/stages/s_sheet_backfill_reason.py --test
"""

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

_CONTACTS_PATH = Path(__file__).parents[2] / "outreach" / "config" / "contacts.json"

_REASON_PREFIX = "Reason: "
_ANGLE_SEPARATOR = ". Angle: "


def _extract_reason_code(note) -> str | None:
    """Mirror s_sheet_build._build_note()'s join format in reverse.

    Returns the reason code if `note` starts with "Reason: ", else None.
    """
    if not isinstance(note, str) or not note.startswith(_REASON_PREFIX):
        return None
    remainder = note[len(_REASON_PREFIX):]
    if _ANGLE_SEPARATOR in remainder:
        remainder = remainder.split(_ANGLE_SEPARATOR, 1)[0]
    return remainder.strip()


def backfill_reason_codes(contacts_path: str | None = None, dry_run: bool = False) -> dict:
    """Backfill reason_code on records that are missing it, parsed from `note`.

    Returns {checked, backfilled, backfilled_domains, dry_run, written, backup_path}.
    """
    cp = Path(contacts_path) if contacts_path else _CONTACTS_PATH
    backup_path = cp.with_suffix(".json.bak")

    data = json.loads(cp.read_text(encoding="utf-8"))
    contacts = data.get("contacts", [])

    backfilled = []
    for record in contacts:
        if (record.get("reason_code") or "").strip():
            continue
        reason_code = _extract_reason_code(record.get("note"))
        if reason_code:
            record["reason_code"] = reason_code
            backfilled.append((record.get("domain"), reason_code))

    written = False
    if backfilled and not dry_run:
        shutil.copy2(cp, backup_path)
        cp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written = True

    return {
        "checked": len(contacts),
        "backfilled": len(backfilled),
        "backfilled_domains": backfilled,
        "dry_run": dry_run,
        "written": written,
        "backup_path": str(backup_path) if written else None,
    }


def _print_report(result: dict) -> None:
    if result["dry_run"]:
        print("DRY RUN — no files will be changed.")
        print()

    print(f"Checked: {result['checked']} contact(s).")
    print(f"Backfilled: {result['backfilled']}.")
    for domain, reason_code in result["backfilled_domains"]:
        print(f"  + {domain or '(null domain)'}  ->  reason_code={reason_code!r}")

    print()
    if result["dry_run"]:
        print(f"DRY RUN complete. {result['backfilled']} record(s) would be updated. "
              "Re-run without --dry-run to write.")
    elif result["written"]:
        print(f"Wrote {result['backfilled']} backfilled record(s). Backup: {result['backup_path']}")
    else:
        print("No changes to apply — contacts.json not touched, no backup created.")


def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    import argparse

    parser = argparse.ArgumentParser(
        description="One-time backfill: restore reason_code from note on sheet-track contacts.json records."
    )
    parser.add_argument("--contacts", default=None, help="path to contacts.json (default: real config file)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    args = parser.parse_args()

    result = backfill_reason_codes(contacts_path=args.contacts, dry_run=args.dry_run)
    _print_report(result)


# ── self-tests (no live network) ────────────────────────────────────────────

def _run_tests() -> None:
    import tempfile

    print("Running s_sheet_backfill_reason tests...")

    def _write(tmp, contacts):
        p = Path(tmp) / "contacts.json"
        p.write_text(json.dumps({"contacts": contacts}, indent=2), encoding="utf-8")
        return p

    # T1: note "Reason: SUPPLIER. Angle: ..." and no reason_code -> backfilled
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [{
            "domain": "thunderbike.de",
            "note": "Reason: SUPPLIER. Angle: German custom Harley parts manufacturer.",
        }])
        result = backfill_reason_codes(contacts_path=str(cp))
        assert result["backfilled"] == 1, result
        assert result["backfilled_domains"] == [("thunderbike.de", "SUPPLIER")], \
            result["backfilled_domains"]
        assert result["written"] is True, result
        on_disk = json.loads(cp.read_text())
        assert on_disk["contacts"][0]["reason_code"] == "SUPPLIER", on_disk
        assert cp.with_suffix(".json.bak").exists(), "expected backup file to be created"
    print("  PASS  [T1]  note 'Reason: SUPPLIER. Angle: ...' -> backfilled reason_code='SUPPLIER'")

    # T2: note "Reason: X" with no Angle part -> backfilled
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [{"domain": "a.com", "note": "Reason: REL-EDITORIAL"}])
        result = backfill_reason_codes(contacts_path=str(cp))
        assert result["backfilled_domains"] == [("a.com", "REL-EDITORIAL")], \
            result["backfilled_domains"]
    print("  PASS  [T2]  note 'Reason: X' (no Angle) -> backfilled correctly")

    # T3: record already has reason_code -> left untouched, no backup
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [{
            "domain": "b.com", "reason_code": "SUPPLIER",
            "note": "Reason: SUPPLIER. Angle: something else entirely.",
        }])
        before = cp.read_bytes()
        result = backfill_reason_codes(contacts_path=str(cp))
        assert result["backfilled"] == 0, result
        assert result["written"] is False, result
        assert not cp.with_suffix(".json.bak").exists()
        assert cp.read_bytes() == before
    print("  PASS  [T3]  record already has reason_code -> untouched, no backup")

    # T4: no "Reason:" prefix / missing note / no note key -> untouched, no crash
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [
            {"domain": "c.com", "note": "Angle: no reason label here."},
            {"domain": "d.com", "note": None},
            {"domain": "e.com"},
        ])
        result = backfill_reason_codes(contacts_path=str(cp))
        assert result["backfilled"] == 0, result
        assert result["written"] is False, result
    print("  PASS  [T4]  no 'Reason:' prefix / missing note / no note key -> untouched, no crash")

    # T5: dry_run computes the diff but writes and backs up nothing
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [{"domain": "f.com", "note": "Reason: SUPPLIER."}])
        before = cp.read_bytes()
        result = backfill_reason_codes(contacts_path=str(cp), dry_run=True)
        assert result["backfilled"] == 1, result
        assert result["written"] is False, result
        assert not cp.with_suffix(".json.bak").exists()
        assert cp.read_bytes() == before
    print("  PASS  [T5]  dry_run -> diff computed, nothing written or backed up")

    # T6: mixed batch — one to backfill, one already set, one no-match
    with tempfile.TemporaryDirectory() as tmp:
        cp = _write(tmp, [
            {"domain": "thunderbike.com", "note": "Reason: SUPPLIER. Angle: EU distributor."},
            {"domain": "motomag.com", "reason_code": "REL-EDITORIAL", "note": "Reason: REL-EDITORIAL."},
            {"domain": "noreason.com", "note": "Angle: just an angle."},
        ])
        result = backfill_reason_codes(contacts_path=str(cp))
        assert result["backfilled"] == 1, result
        assert result["backfilled_domains"] == [("thunderbike.com", "SUPPLIER")], \
            result["backfilled_domains"]
    print("  PASS  [T6]  mixed batch -> only the missing-reason_code SUPPLIER row is backfilled")

    print("\nAll s_sheet_backfill_reason tests passed.")


if __name__ == "__main__":
    main()
