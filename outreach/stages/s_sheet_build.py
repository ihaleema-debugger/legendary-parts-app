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


def build_records() -> list[dict]:
    """Return one contacts.json-shaped dict per passing sheet row."""
    rows = filter_rows()
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
                "fetch_attempts": 0,
                "personalization_hook": row.get("Hook", ""),
            }
        )

    return records


def main() -> None:
    records = build_records()
    print(json.dumps(records, indent=2))
    print()
    print(f"Built {len(records)} record(s).")


if __name__ == "__main__":
    main()
