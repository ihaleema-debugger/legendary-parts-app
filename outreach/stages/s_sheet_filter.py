"""
Standalone script: read the outreach Google Sheet and print which rows
are ready for outreach.  Writes nothing.  Touches no other file.

Run from the repo root:
    python outreach/stages/s_sheet_filter.py
"""

from outreach.stages.s_sheet_read import read_sheet

EXPECTED_HEADERS = [
    "Referring Domain",
    "Authority Score",
    "Email",
    "Decision",
    "Priority",
    "Hook",
    "Reason",
    "Angle",
]


def _is_real_email(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    if v.upper() == "TODO":
        return False
    return "@" in v


def filter_rows() -> list[dict]:
    """Return one column-keyed dict per row that passes the outreach filter.

    Raises RuntimeError if any expected column is absent from the sheet header.
    """
    rows = read_sheet()
    header_row, *data_rows = rows

    col = {name: idx for idx, name in enumerate(header_row)}

    missing = [h for h in EXPECTED_HEADERS if h not in col]
    if missing:
        raise RuntimeError(
            f"Sheet header is missing expected columns: {missing}\n"
            f"Actual header: {header_row}"
        )

    n_cols = len(header_row)
    decision_idx = col["Decision"]
    email_idx = col["Email"]

    passed = []

    for raw_row in data_rows:
        row = list(raw_row) + [""] * (n_cols - len(raw_row))

        if row[decision_idx].strip().lower() != "outreach":
            continue

        if not _is_real_email(row[email_idx]):
            continue

        passed.append({name: row[idx] for name, idx in col.items()})

    return passed


def main() -> None:
    rows = read_sheet()
    header_row, *data_rows = rows

    col = {name: idx for idx, name in enumerate(header_row)}

    missing = [h for h in EXPECTED_HEADERS if h not in col]
    if missing:
        raise RuntimeError(
            f"Sheet header is missing expected columns: {missing}\n"
            f"Actual header: {header_row}"
        )

    n_cols = len(header_row)
    domain_idx = col["Referring Domain"]
    email_idx = col["Email"]
    decision_idx = col["Decision"]

    passed = []   # list of (domain, email)
    problems = [] # list of (domain, reason)
    outreach_count = 0

    for raw_row in data_rows:
        row = list(raw_row) + [""] * (n_cols - len(raw_row))

        decision = row[decision_idx].strip()

        if decision.lower() != "outreach":
            continue

        outreach_count += 1
        domain = row[domain_idx].strip()
        email = row[email_idx].strip()

        if _is_real_email(email):
            passed.append((domain, email))
        else:
            problems.append((domain, "Outreach but no valid email"))

    # ── Output ────────────────────────────────────────────────────────────────
    print("=" * 60)
    print("PASSED")
    print("=" * 60)
    if passed:
        for domain, email in passed:
            print(f"  {domain}  ->  {email}")
    else:
        print("  (none)")

    print()
    print("=" * 60)
    print("SKIPPED (PROBLEMS)")
    print("=" * 60)
    if problems:
        for domain, reason in problems:
            print(f"  {domain}  ->  {reason}")
    else:
        print("  No problems.")

    print()
    print(
        f"Outreach rows: {outreach_count}.  "
        f"Passed: {len(passed)}.  "
        f"Skipped for problems: {len(problems)}."
    )


if __name__ == "__main__":
    main()
