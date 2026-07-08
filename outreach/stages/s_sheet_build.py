"""
Piece 3 — build contacts.json records from filtered sheet rows.
Prints only. Writes nothing.

Run from the repo root:
    python outreach/stages/s_sheet_build.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from outreach.stages.s_sheet_filter import filter_rows

_LANE = 3


def _org_from_domain(domain: str) -> str:
    label = domain.split(".")[0]
    return label.replace("-", " ").title()


def _build_note(reason: str, angle: str):
    parts = []
    if reason.strip():
        parts.append(f"Reason: {reason.strip()}")
    if angle.strip():
        parts.append(f"Angle: {angle.strip()}")
    return ". ".join(parts) if parts else None


def build_records(sheet_id: str | None = None, tab: str | None = None) -> list[dict]:
    """Return one contacts.json-shaped dict per passing sheet row."""
    rows = filter_rows(sheet_id, tab)
    records = []

    for row in rows:
        domain = row["Referring Domain"].strip()
        records.append(
            {
                "domain": domain,
                "organisation": _org_from_domain(domain),
                "lane": _LANE,
                "outreach_type": "link_building",
                "market": "multi",
                "language": "en",
                "proactive": True,
                "named_contacts": [
                    {
                        "name": None,
                        "email": row["Email"].strip(),
                        "needs_lookup": False,
                        "role": None,
                        "email_candidate": None,
                        "candidate_source": None,
                        "candidate_status": "confirmed",
                    }
                ],
                "action_url": None,
                "note": _build_note(row.get("Reason", ""), row.get("Angle", "")),
                "reason_code": row.get("Reason", "").strip(),
                "fetch_attempts": 0,
                "personalization_hook": row.get("Hook", ""),
            }
        )

    return records


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    from unittest.mock import patch

    print("Running s_sheet_build tests...")

    def _row(reason="", angle="", hook="", domain="example.com", email="hi@example.com"):
        return {
            "Referring Domain": domain,
            "Authority Score": "50",
            "Email": email,
            "Decision": "outreach",
            "Priority": "Med",
            "Hook": hook,
            "Reason": reason,
            "Angle": angle,
        }

    # T1: Reason="SUPPLIER" -> reason_code=="SUPPLIER" on the built record
    with patch(f"{__name__}.filter_rows", return_value=[_row(reason="SUPPLIER", angle="EU distributor")]):
        records = build_records()
        assert len(records) == 1, f"T1 len={len(records)}"
        assert records[0]["reason_code"] == "SUPPLIER", f"T1 reason_code={records[0]['reason_code']!r}"
        assert records[0]["note"] == "Reason: SUPPLIER. Angle: EU distributor", \
            f"T1 note={records[0]['note']!r}"
    print("  PASS  [T1]  Reason='SUPPLIER' -> reason_code='SUPPLIER', note unchanged")

    # T2: Reason="REL-EDITORIAL" -> reason_code=="REL-EDITORIAL"
    with patch(f"{__name__}.filter_rows", return_value=[_row(reason="REL-EDITORIAL")]):
        records = build_records()
        assert records[0]["reason_code"] == "REL-EDITORIAL", \
            f"T2 reason_code={records[0]['reason_code']!r}"
    print("  PASS  [T2]  Reason='REL-EDITORIAL' -> reason_code='REL-EDITORIAL'")

    # T3: blank Reason -> reason_code=="" (never absent, never None)
    with patch(f"{__name__}.filter_rows", return_value=[_row(reason="")]):
        records = build_records()
        assert records[0]["reason_code"] == "", f"T3 reason_code={records[0]['reason_code']!r}"
    print("  PASS  [T3]  blank Reason -> reason_code=''")

    # T4: Reason with surrounding whitespace -> stripped
    with patch(f"{__name__}.filter_rows", return_value=[_row(reason="  SUPPLIER  ")]):
        records = build_records()
        assert records[0]["reason_code"] == "SUPPLIER", f"T4 reason_code={records[0]['reason_code']!r}"
    print("  PASS  [T4]  Reason with whitespace -> stripped to 'SUPPLIER'")

    print("\nAll s_sheet_build tests passed.")


def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    import argparse

    parser = argparse.ArgumentParser(description="Build contacts.json-shaped records from filtered sheet rows.")
    parser.add_argument("--sheet-id", default=None, help="Google Sheet ID (default: SHEET_ID constant)")
    parser.add_argument("--tab", default=None, help="Sheet tab name (default: first sheet, range 'A:ZZ')")
    args = parser.parse_args()

    records = build_records(args.sheet_id, args.tab)
    print(json.dumps(records, indent=2))
    print()
    print(f"Built {len(records)} record(s).")


if __name__ == "__main__":
    main()
