"""Stage 1 — triage: auto-skip, keyword hints, homepage fetch, classify batch."""

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import requests
    from requests.exceptions import ConnectionError as ReqConnError, Timeout as ReqTimeout
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

from outreach.outreach_state import OutreachState

logger = logging.getLogger(__name__)

_FETCH_CAP    = 2      # max attempts before a row is permanently skipped from fetch
_THIN_CHARS   = 30     # extracted text shorter than this is considered unreliable

# ── blocklists — exact normalised-apex match only ────────────────────────────
# "notsimilarweb.com" WILL NOT match; only "similarweb.com" will.

STAT_MIRROR_BLOCKLIST = frozenset({
    "similarweb.com", "semrush.com", "ahrefs.com", "moz.com",
    "majestic.com",   "alexa.com",   "quantcast.com",
})

JUNK_PROFILE_BLOCKLIST = frozenset({
    "myspace.com", "bebo.com", "hi5.com",
})

# ── keyword hint patterns — first match wins ─────────────────────────────────
# Precedence: forum > news > moto.
#   'forum/community' is most specific — a supplier wouldn't have it in apex.
#   'news/magazine' is next; 'moto/bike/harley' is broadest, checked last.

_KW_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"forum|community|club|nation|passion|gruppe"),             "keyword:forum"),
    (re.compile(r"magazine|journal|news|presse|revue|media"),               "keyword:news"),
    (re.compile(r"moto|bike|motor|harley|hog|biker|chopper|cruiser|rider"), "keyword:moto"),
]

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en,de;q=0.9,fr;q=0.8"}

# ── helpers ───────────────────────────────────────────────────────────────────

def _keyword_hint(domain: str) -> str:
    for pattern, label in _KW_PATTERNS:
        if pattern.search(domain):
            return label
    return "no-signal"


def _extract_visible_text(html: str) -> str:
    """Title + first 600 chars of visible body text; script/style/nav stripped."""
    soup = None
    try:
        from bs4 import BeautifulSoup
        for parser in ("lxml", "html.parser"):
            try:
                soup = BeautifulSoup(html, parser)
                break
            except Exception:
                continue
    except ImportError:
        pass

    if soup is None:
        clean = re.sub(
            r"<(script|style|nav|header|footer)[^>]*>.*?</\1>",
            " ", html, flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", clean)
        return re.sub(r"\s+", " ", text).strip()[:600]

    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    body  = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()
    combined = (f"{title}: " if title else "") + body
    return combined[:600]


def _fetch_one(domain: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Fetch the homepage. Returns (domain, snapshot_or_None, fail_reason_or_None).
    Tries https://{domain} first; retries https://www.{domain} on any error or 4xx/5xx.
    """
    urls = [f"https://{domain}", f"https://www.{domain}"]
    last_reason: Optional[str] = None

    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                return (domain, _extract_visible_text(resp.text), None)
            last_reason = f"http-{resp.status_code}"
        except ReqTimeout:
            last_reason = "timeout"
        except ReqConnError:
            last_reason = "connection-error"
        except Exception as exc:
            last_reason = type(exc).__name__

    return (domain, None, last_reason)


# ── fetch ─────────────────────────────────────────────────────────────────────

def run_fetch(
    db_path: Optional[str] = None,
    fetch_fn: Optional[Callable] = None,
) -> dict:
    """
    Phase A: exact-apex junk auto-skip (→ status=closed).
    Phase B: keyword hint for all non-skipped rows (never sets decision).
    Phase C: concurrent homepage fetch. Eligibility: snapshot IS NULL AND
             fetch_attempts < _FETCH_CAP. Both thin and failed outcomes
             increment fetch_attempts and leave snapshot NULL — they are
             retried on the next run until the cap is reached.
             All DB writes happen on the main thread after futures complete.

    fetch_fn is injectable for tests; defaults to _fetch_one.
    Snapshot semantics: homepage_snapshot is non-NULL only for a usable fetch.
    The string "" is NEVER written. Reason always lives in triage_hint.
    """
    if fetch_fn is None:
        fetch_fn = _fetch_one

    state     = OutreachState(db_path) if db_path else OutreachState()
    prospects = state.get_pending_triage()

    # ── Phase A: junk auto-skip ───────────────────────────────────────────────
    to_process: List[dict] = []
    auto_skipped = 0

    for p in prospects:
        d = p["domain"]
        if d in STAT_MIRROR_BLOCKLIST:
            state.upsert_prospect(d, decision="skip", reason_code="STAT-MIRROR", status="closed")
            auto_skipped += 1
        elif d in JUNK_PROFILE_BLOCKLIST:
            state.upsert_prospect(d, decision="skip", reason_code="JUNK-PROFILE", status="closed")
            auto_skipped += 1
        else:
            to_process.append(p)

    # ── Phase B: keyword hint ─────────────────────────────────────────────────
    # Runs for ALL non-skipped rows. Preserves an existing keyword part so
    # re-runs don't overwrite a hint that was already correctly set.
    kw_hint_map: Dict[str, str] = {}

    for p in to_process:
        domain   = p["domain"]
        existing = p.get("triage_hint") or ""
        kw_part  = existing.split("|")[0]
        if kw_part.startswith(("keyword:", "no-signal")):
            kw_hint_map[domain] = kw_part          # already set — preserve
        else:
            kw_part = _keyword_hint(domain)
            kw_hint_map[domain] = kw_part
            state.upsert_prospect(domain, triage_hint=kw_part)

    # ── Phase C: determine eligibility ───────────────────────────────────────
    # homepage_snapshot IS NOT NULL → already has usable content, skip.
    # snapshot IS NULL, attempts >= cap → permanently skipped (appears in classify).
    # snapshot IS NULL, attempts < cap → eligible for (re)fetch.
    already_snapshotted = [
        p for p in to_process
        if p.get("homepage_snapshot") is not None
    ]
    at_cap_list = [
        p for p in to_process
        if p.get("homepage_snapshot") is None
        and (p.get("fetch_attempts") or 0) >= _FETCH_CAP
    ]
    needs_fetch = [
        p for p in to_process
        if p.get("homepage_snapshot") is None
        and (p.get("fetch_attempts") or 0) < _FETCH_CAP
    ]

    # Snapshot of current attempt counts before we mutate anything
    fa_map = {p["domain"]: (p.get("fetch_attempts") or 0) for p in needs_fetch}
    retried = sum(1 for v in fa_map.values() if v >= 1)

    # Network I/O in the pool; results collected; all writes on the main thread
    fetch_results: List[Tuple[str, Optional[str], Optional[str]]] = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_fn, p["domain"]): p["domain"] for p in needs_fetch}
        for fut in as_completed(futures):
            fetch_results.append(fut.result())

    fetched_ok   = 0
    fetch_failed: Dict[str, int] = {}
    thin_content = 0

    for domain, snapshot, fail_reason in fetch_results:
        kw_part      = kw_hint_map.get(domain, "no-signal")
        new_attempts = fa_map.get(domain, 0) + 1

        if fail_reason:
            # fetch-failed: snapshot stays NULL, hint records reason, attempts++
            full_hint = f"{kw_part}|fetch-failed:{fail_reason}"
            state.upsert_prospect(domain, triage_hint=full_hint, fetch_attempts=new_attempts)
            fetch_failed[fail_reason] = fetch_failed.get(fail_reason, 0) + 1

        elif snapshot and len(snapshot) >= _THIN_CHARS:
            # usable content — the only case where snapshot is stored
            state.upsert_prospect(domain, triage_hint=kw_part,
                                  homepage_snapshot=snapshot, fetch_attempts=new_attempts)
            fetched_ok += 1

        else:
            # thin/empty: snapshot stays NULL so retry budget still applies
            full_hint = f"{kw_part}|thin-content"
            state.upsert_prospect(domain, triage_hint=full_hint, fetch_attempts=new_attempts)
            thin_content += 1

    return {
        "auto_skipped":        auto_skipped,
        "fetched_ok":          fetched_ok,
        "fetch_failed":        fetch_failed,
        "thin_content":        thin_content,
        "already_snapshotted": len(already_snapshotted),
        "retried":             retried,
        "at_cap":              len(at_cap_list),
    }


# ── classify ──────────────────────────────────────────────────────────────────

def run_classify(
    db_path: Optional[str] = None,
    decisions_path: Optional[str] = None,
) -> None:
    """Print the pending triage batch (includes capped rows). Apply decisions if given."""
    state     = OutreachState(db_path) if db_path else OutreachState()
    prospects = state.get_pending_triage()

    if not prospects:
        print("No prospects pending triage.")
        return

    print(f"\n{'─' * 70}")
    print(f"Pending triage: {len(prospects)} prospects")
    print(f"{'─' * 70}\n")

    for i, p in enumerate(prospects, 1):
        domain   = p["domain"]
        as_val   = p.get("authority_score") or "?"
        hint     = p.get("triage_hint") or "(none)"
        snap     = p.get("homepage_snapshot") or ""
        attempts = p.get("fetch_attempts") or 0
        cap_note = f"  [CAPPED — no retry]" if (not snap and attempts >= _FETCH_CAP) else ""
        snap_disp = (f'"{snap[:120]}..."' if len(snap) > 120 else f'"{snap}"') if snap else "(none)"

        print(f"[{i}] {domain}  AS={as_val}  hint={hint}{cap_note}")
        print(f"    snapshot: {snap_disp}")
        print(f"    → decision: ?  priority: ?  reason_code: ?  angle: ?")
        print()

    if not decisions_path:
        return

    with open(decisions_path, encoding="utf-8") as f:
        decisions = json.load(f)

    written  = 0
    rejected: List[Tuple[str, str]] = []

    for entry in decisions:
        domain = entry.get("domain", "")
        try:
            state.set_triage(
                domain      = domain,
                decision    = entry.get("decision", ""),
                priority    = entry.get("priority", ""),
                reason_code = entry.get("reason_code", ""),
                angle       = entry.get("angle", ""),
            )
            written += 1
        except (ValueError, KeyError) as exc:
            rejected.append((domain, str(exc)))

    print(f"Classify results: {written} written, {len(rejected)} rejected")
    for domain, msg in rejected:
        print(f"  REJECTED {domain!r}: {msg}")


# ── summary print ─────────────────────────────────────────────────────────────

def _print_fetch_summary(s: dict) -> None:
    failed_total = sum(s["fetch_failed"].values())
    print(f"  auto-skipped (junk):    {s['auto_skipped']}")
    print(f"  already had snapshot:   {s['already_snapshotted']}")
    print(f"  fetched OK:             {s['fetched_ok']}")
    print(f"  thin/empty:             {s['thin_content']}")
    print(f"  fetch failed:           {failed_total}")
    for reason, count in sorted(s["fetch_failed"].items()):
        print(f"    {reason}: {count}")
    print(f"  retried (attempt 2):    {s['retried']}")
    print(f"  at cap / not retried:   {s['at_cap']}")


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    import io as _io
    import json as _json
    import os
    import tempfile

    print("Running s1_triage tests...")

    GOOD_SNAP = "Valid homepage content for this domain exceeding thirty chars easily."

    # ── Part 1: core + retry behavior ─────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db1   = os.path.join(tmp, "db1.db")
        st1   = OutreachState(db1)

        st1.upsert_prospect("similarweb.com",   authority_score=80)
        st1.upsert_prospect("notsemrush.com",   authority_score=40)
        st1.upsert_prospect("moto-station.com", authority_score=45)
        st1.upsert_prospect("hd-forum.de",      authority_score=52)
        st1.upsert_prospect("thin-page.com",    authority_score=30)
        st1.upsert_prospect("already.com",      authority_score=35,
                            homepage_snapshot="Pre-existing snapshot content here.")

        def mock_run1(domain):
            if domain == "hd-forum.de":   return (domain, None, "timeout")
            if domain == "thin-page.com": return (domain, "Hi", None)   # < _THIN_CHARS
            return (domain, GOOD_SNAP, None)

        s1 = run_fetch(db1, fetch_fn=mock_run1)

        # T1: blocklist closes similarweb.com
        sim = st1.get_by_domain("similarweb.com")
        assert sim["status"] == "closed" and sim["reason_code"] == "STAT-MIRROR", \
            f"status={sim['status']} reason={sim['reason_code']}"
        print("  PASS  [T1] exact-apex blocklist closes similarweb.com")

        # T2: near-miss not blocked
        ns = st1.get_by_domain("notsemrush.com")
        assert ns["status"] != "closed"
        print("  PASS  [T2] 'notsemrush.com' NOT blocked")

        assert s1["auto_skipped"] == 1
        print("  PASS  [T3] auto_skipped count=1")

        # T4: keyword hint only
        moto = st1.get_by_domain("moto-station.com")
        assert moto["triage_hint"] and "keyword:" in moto["triage_hint"]
        assert moto["decision"] is None and moto["reason_code"] is None
        print("  PASS  [T4] keyword hit writes triage_hint, leaves decision/reason_code NULL")

        # T5 (updated): fetch failure → snapshot NULL, fetch_attempts=1
        fde = st1.get_by_domain("hd-forum.de")
        assert fde["status"] == "intake"
        assert fde["homepage_snapshot"] is None
        assert "fetch-failed" in (fde["triage_hint"] or "")
        assert fde["fetch_attempts"] == 1, f"expected 1, got {fde['fetch_attempts']}"
        print("  PASS  [T5] fetch failure → snapshot NULL, fetch_attempts=1, hint has fetch-failed")

        # T6 (updated): thin → snapshot NULL (not ''), fetch_attempts=1
        thin = st1.get_by_domain("thin-page.com")
        assert "thin-content" in (thin["triage_hint"] or "")
        assert thin["homepage_snapshot"] is None, \
            f"snapshot must be NULL for thin; got {thin['homepage_snapshot']!r}"
        assert thin["fetch_attempts"] == 1, f"expected 1, got {thin['fetch_attempts']}"
        print("  PASS  [T6] thin content → snapshot NULL (not ''), fetch_attempts=1, hint has thin-content")

        # T7: already-snapshotted row untouched
        assert s1["already_snapshotted"] == 1
        al = st1.get_by_domain("already.com")
        assert al["homepage_snapshot"] == "Pre-existing snapshot content here."
        print("  PASS  [T7] already-snapshotted row skipped, snapshot preserved")

        # ── Run 2: both hd-forum and thin-page eligible (attempts=1 < 2) ─────
        log2: List[str] = []

        def mock_run2(domain):
            log2.append(domain)
            if domain == "hd-forum.de":   return (domain, None, "connection-error")
            if domain == "thin-page.com": return (domain, "Hi", None)
            return (domain, GOOD_SNAP, None)

        s2 = run_fetch(db1, fetch_fn=mock_run2)

        # T8 (updated): both NULL-snapshot rows re-fetched
        assert set(log2) == {"hd-forum.de", "thin-page.com"}, \
            f"expected both re-fetched; got {log2}"
        print(f"  PASS  [T8] run 2 re-fetches hd-forum.de + thin-page.com")

        fde2  = st1.get_by_domain("hd-forum.de")
        thin2 = st1.get_by_domain("thin-page.com")
        assert fde2["fetch_attempts"]  == 2, f"hd-forum: expected 2, got {fde2['fetch_attempts']}"
        assert thin2["fetch_attempts"] == 2, f"thin-page: expected 2, got {thin2['fetch_attempts']}"
        assert s2["retried"] == 2
        assert s2["at_cap"]  == 0
        print("  PASS  [new] run 2: fetch_attempts=2, summary retried=2 at_cap=0")

        # ── Run 3: both at cap — not re-fetched ───────────────────────────────
        log3: List[str] = []

        def mock_run3(domain):
            log3.append(domain)
            return (domain, GOOD_SNAP, None)

        s3 = run_fetch(db1, fetch_fn=mock_run3)
        assert log3 == [], f"run 3 should fetch nothing; got {log3}"
        assert s3["at_cap"] == 2, f"expected at_cap=2, got {s3['at_cap']}"
        print("  PASS  [new] run 3: capped rows not re-fetched, at_cap=2")

        # ── Successful fetch never re-fetched ─────────────────────────────────
        log_succ: List[str] = []

        def mock_succ(domain):
            log_succ.append(domain)
            return (domain, GOOD_SNAP, None)

        run_fetch(db1, fetch_fn=mock_succ)
        assert "moto-station.com" not in log_succ
        assert "notsemrush.com"   not in log_succ
        print("  PASS  [new] successful rows (snapshot set) never re-fetched")

        # ── snapshot never stored as '' ───────────────────────────────────────
        bad = [r["domain"] for r in st1.get_all() if r.get("homepage_snapshot") == ""]
        assert not bad, f"homepage_snapshot stored as '' for: {bad}"
        print("  PASS  [new] homepage_snapshot never stored as empty string")

    # ── Part 2: classify ──────────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp2:
        db2 = os.path.join(tmp2, "db2.db")
        st2 = OutreachState(db2)

        st2.upsert_prospect("hd-forum.de",      authority_score=52)
        st2.upsert_prospect("moto-station.com", authority_score=45)

        run_fetch(db2, fetch_fn=lambda d: (d, GOOD_SNAP, None))

        dec_path = os.path.join(tmp2, "decisions.json")
        with open(dec_path, "w", encoding="utf-8") as f:
            _json.dump([
                {"domain": "hd-forum.de", "decision": "outreach", "priority": "high",
                 "reason_code": "UGC-FORUM", "angle": "vendor program application"},
                {"domain": "moto-station.com", "decision": "outreach", "priority": "high",
                 "reason_code": "NOT-A-CODE", "angle": "test"},
            ], f)

        old_stdout, sys.stdout = sys.stdout, _io.StringIO()
        run_classify(db2, dec_path)
        output, sys.stdout = sys.stdout.getvalue(), old_stdout

        hdf = st2.get_by_domain("hd-forum.de")
        assert hdf["status"] == "triaged", f"got {hdf['status']}"
        assert "1 written"  in output, f"missing '1 written' in:\n{output}"
        assert "1 rejected" in output, f"missing '1 rejected' in:\n{output}"
        print("  PASS  [T9] classify: valid applied, invalid rejected, batch not aborted")

    print("\nAll s1 tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Stage 1: triage — auto-skip, keyword hints, homepage fetch, classify."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Auto-skip junk, set hints, fetch homepages")
    p_fetch.add_argument("--db", help="path to outreach_state.db")

    p_cls = sub.add_parser("classify", help="Print triage batch; optionally apply decisions")
    p_cls.add_argument("--db",        help="path to outreach_state.db")
    p_cls.add_argument("--decisions", dest="decisions", help="path to decisions JSON file")

    args = parser.parse_args()

    if args.cmd == "fetch":
        print("s1 fetch — auto-skip, keyword hints, homepage fetch")
        summary = run_fetch(args.db)
        _print_fetch_summary(summary)

    elif args.cmd == "classify":
        run_classify(args.db, getattr(args, "decisions", None))


if __name__ == "__main__":
    main()
