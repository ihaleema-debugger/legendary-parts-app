"""Stage 0 — intake: normalise + dedup a Semrush referring-domains export, write to DB."""

import argparse
import csv
import io
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

# Allow `python outreach/stages/s0_intake.py` from project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from outreach.outreach_state import OutreachState

logger = logging.getLogger(__name__)

# ── column aliases (lower-stripped) ──────────────────────────────────────────

_DOMAIN_ALIASES = {"referring domain", "domain"}
_AS_ALIASES     = {"authority score", "as", "domain authority score"}
_EMAIL_ALIASES  = {"email"}

# ── helpers ───────────────────────────────────────────────────────────────────

def _normalise_domain(raw: str) -> str:
    """
    lowercase → strip protocol → strip leading www. → keep apex only.
    "https://www.Moto-Station.com/blog/" → "moto-station.com"
    """
    d = raw.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].rstrip(". \t")
    return d


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        return ","


def _coerce_as(raw: str) -> int:
    """Parse AS to int; return 0 on blank or non-numeric (→ LOW-AS skip path)."""
    try:
        return int(str(raw).strip().strip('"').strip())
    except (ValueError, TypeError):
        return 0


def _safe_col(row: list, idx: Optional[int]) -> str:
    """Return row[idx] if idx is set and in bounds, else empty string."""
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


# ── core ──────────────────────────────────────────────────────────────────────

def run_intake(csv_path: str, db_path: Optional[str] = None) -> dict:
    """Read csv_path, normalise, dedup, write to DB. Returns summary counts."""
    state = OutreachState(db_path) if db_path else OutreachState()

    # --- read and decode ---
    text = Path(csv_path).read_bytes().decode("utf-8-sig")
    delimiter = _detect_delimiter(text[:4096])
    all_rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))

    if not all_rows:
        print("ERROR: CSV is empty.")
        sys.exit(1)

    # --- resolve columns ---
    raw_headers = all_rows[0]
    norm_headers = [h.strip().lower() for h in raw_headers]

    col_domain = next((i for i, h in enumerate(norm_headers) if h in _DOMAIN_ALIASES), None)
    col_as     = next((i for i, h in enumerate(norm_headers) if h in _AS_ALIASES), None)
    col_email  = next((i for i, h in enumerate(norm_headers) if h in _EMAIL_ALIASES), None)

    if col_domain is None or col_as is None:
        seen = ", ".join(repr(h) for h in raw_headers[:20])
        missing = []
        if col_domain is None:
            missing.append("domain (tried: 'Referring Domain', 'Domain')")
        if col_as is None:
            missing.append("authority score (tried: 'Authority Score', 'AS', 'Domain Authority Score')")
        print(f"ERROR: required column(s) not found: {', '.join(missing)}")
        print(f"       headers seen: {seen}")
        sys.exit(1)

    data_rows = all_rows[1:]
    total_rows   = len(data_rows)
    blank_skipped = 0

    # --- normalise + dedup in memory (highest AS wins) ---
    # {normalised_domain: {'authority_score': int, 'email_on_file': str|None}}
    best: Dict[str, dict] = {}

    for row in data_rows:
        raw_domain = _safe_col(row, col_domain)
        norm_domain = _normalise_domain(raw_domain)

        if not norm_domain:
            blank_skipped += 1
            continue

        as_val = _coerce_as(_safe_col(row, col_as))
        email_raw = _safe_col(row, col_email).strip()
        email = email_raw if email_raw else None

        if norm_domain not in best or as_val > best[norm_domain]["authority_score"]:
            best[norm_domain] = {"authority_score": as_val, "email_on_file": email}

    after_dedup = len(best)

    # --- write to DB ---
    existing = {r["domain"] for r in state.get_all()}

    inserted_new    = 0
    already_existed = 0
    low_as_skip     = 0

    for domain, info in best.items():
        as_val = info["authority_score"]
        email  = info["email_on_file"]

        is_new = domain not in existing

        if as_val > 20:
            kwargs: dict = {
                "source": "competitor-sheet",
                "authority_score": as_val,
                "status": "intake",
            }
            if email:
                kwargs["email_on_file"] = email
            state.upsert_prospect(domain, **kwargs)
        else:
            kwargs = {
                "authority_score": as_val,
                "decision": "skip",
                "triage_hint": "LOW-AS",
                "status": "closed",
            }
            if email:
                kwargs["email_on_file"] = email
            state.upsert_prospect(domain, **kwargs)
            low_as_skip += 1

        if is_new:
            inserted_new += 1
        else:
            already_existed += 1

    return {
        "total_rows":      total_rows,
        "blank_skipped":   blank_skipped,
        "after_dedup":     after_dedup,
        "inserted_new":    inserted_new,
        "already_existed": already_existed,
        "low_as_skip":     low_as_skip,
    }


def _print_summary(s: dict) -> None:
    print(f"  rows read:        {s['total_rows']}")
    print(f"  blank/summary:    {s['blank_skipped']}  skipped")
    print(f"  after dedup:      {s['after_dedup']}")
    print(f"  inserted new:     {s['inserted_new']}")
    print(f"  already existed:  {s['already_existed']}")
    print(f"  LOW-AS skip:      {s['low_as_skip']}")
    check = s["inserted_new"] + s["already_existed"]
    if check != s["after_dedup"]:
        print(f"  WARNING: inserted_new + already_existed ({check}) != after_dedup ({s['after_dedup']})")


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    print("Running s0_intake tests...")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path  = os.path.join(tmpdir, "test.db")
        csv_path = os.path.join(tmpdir, "test.csv")

        # Fixture covers:
        #  - duplicate domain (moto-station.com appears twice; keep AS=45)
        #  - www + protocol + path normalisation
        #  - AS≤20 row (low-authority.com, AS=15) → closed/LOW-AS
        #  - blank/summary row (empty domain) → skipped
        #  - missing Email column → NULL, no crash
        fixture = (
            "Referring Domain,Authority Score\r\n"
            "https://www.Moto-Station.com/blog/,45\r\n"
            "moto-station.com,30\r\n"          # dupe, lower AS → discarded
            "low-authority.com,15\r\n"          # AS≤20 → closed
            ",0\r\n"                             # blank domain → skipped
            "hd-forum.de,52\r\n"
        )
        Path(csv_path).write_text(fixture, encoding="utf-8")

        # --- run 1 ---
        s1 = run_intake(csv_path, db_path)
        state = OutreachState(db_path)

        # dedup + normalisation
        row = state.get_by_domain("moto-station.com")
        assert row is not None, "moto-station.com missing after intake"
        assert row["authority_score"] == 45, f"expected AS=45, got {row['authority_score']}"
        assert row["status"] == "intake"
        print("  PASS  dedup: highest AS kept; www+protocol+path normalised to apex")

        # LOW-AS row
        low = state.get_by_domain("low-authority.com")
        assert low is not None, "low-authority.com missing"
        assert low["status"] == "closed"
        assert low["decision"] == "skip"
        assert low["triage_hint"] == "LOW-AS"
        print("  PASS  AS≤20 → status=closed, decision=skip, triage_hint=LOW-AS")

        # blank row skipped
        assert s1["blank_skipped"] == 1, f"expected 1 blank, got {s1['blank_skipped']}"
        print("  PASS  blank/summary row skipped and counted")

        # missing Email column → NULL
        assert row["email_on_file"] is None
        print("  PASS  missing Email column → NULL, no crash")

        # counts reconcile
        check = s1["inserted_new"] + s1["already_existed"]
        assert check == s1["after_dedup"], f"counts broken: {check} != {s1['after_dedup']}"
        print("  PASS  summary counts reconcile")

        # LOW-AS rows must NOT appear in triage queue
        pending = state.get_pending_triage()
        assert not any(r["domain"] == "low-authority.com" for r in pending)
        print("  PASS  LOW-AS row absent from triage queue")

        # --- run 2: idempotency ---
        s2 = run_intake(csv_path, db_path)
        assert s2["inserted_new"] == 0, f"re-run inserted {s2['inserted_new']} new rows"
        assert s2["already_existed"] == s1["after_dedup"]
        all_domains = [r["domain"] for r in state.get_all()]
        assert all_domains.count("moto-station.com") == 1
        # triage data must be intact after re-run
        row2 = state.get_by_domain("moto-station.com")
        assert row2["status"] == "intake"   # re-intake must NOT reset triaged rows to intake
        print("  PASS  idempotent: re-run creates no dupes, counts stable")

        # --- semicolon-delimited variant ---
        csv_semi = os.path.join(tmpdir, "semi.csv")
        Path(csv_semi).write_text(
            "Referring Domain;Authority Score\r\n"
            "biker-news.de;38\r\n",
            encoding="utf-8",
        )
        db_semi = os.path.join(tmpdir, "semi.db")
        s_semi = run_intake(csv_semi, db_semi)
        assert s_semi["inserted_new"] == 1
        assert OutreachState(db_semi).get_by_domain("biker-news.de")["authority_score"] == 38
        print("  PASS  semicolon-delimited CSV parsed correctly")

    print("\nAll s0 tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 0: intake a Semrush referring-domains CSV into the outreach DB."
    )
    parser.add_argument("csv", nargs="?", help="path to CSV file")
    parser.add_argument("--db", help="path to outreach_state.db (default: outreach/outreach_state.db)")
    parser.add_argument("--test", action="store_true", help="run built-in tests and exit")
    args = parser.parse_args()

    if args.test:
        _run_tests()
        return

    if not args.csv:
        parser.print_help()
        sys.exit(1)

    print(f"Intake: {args.csv}")
    summary = run_intake(args.csv, args.db)
    _print_summary(summary)


if __name__ == "__main__":
    main()
