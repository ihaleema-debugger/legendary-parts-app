"""Stage 2 — route: map reason_code → lane + mode using the playbook's routing table."""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from outreach.outreach_state import OutreachState

logger = logging.getLogger(__name__)

# ── editorial sub-classification patterns ────────────────────────────────────
# Order matters: journalist/news first, then custom-build, then how-to, then affiliate.
# First match wins.

_EDITORIAL_PATTERNS: List[Tuple[re.Pattern, int]] = [
    (re.compile(r"journalist|magazine|news|press"),                      3),
    (re.compile(r"custom|build|cafe[\s\-]racer|chopper|bobber"),        4),
    (re.compile(r"how[\s\-]to|maintenance|repair|tutorial|guide|blog"), 5),
    (re.compile(r"affiliate|youtube|channel|influencer|review"),        7),
]

_DIRECTORY_L8 = re.compile(r"directory|listing|claim")
_DIRECTORY_L6 = re.compile(r"resource|association|club|hog|ffmc")

# No-action codes — these carry decision='skip' from s1's _REQUIRED_DECISION enforcement.
# Reaching the outreach branch with one of these indicates inconsistent state.
_NO_ACTION_CODES = frozenset({
    "MARKETPLACE", "JUNK-PROFILE", "STAT-MIRROR", "IRRELEVANT-GEO",
})


# ── sub-classifiers ───────────────────────────────────────────────────────────

def _sub_classify_editorial(row: dict) -> Optional[int]:
    """
    Return lane (3, 4, 5, or 7) using only the human-written angle and the
    structured triage_hint keyword part. Homepage snapshot is intentionally
    excluded — free-text scan is not reliable enough to select a send lane
    under the founder's real identity.

    Returns None when no signal is found; caller routes the row to review.
    """
    angle   = (row.get("angle") or "").lower()
    hint_kw = (row.get("triage_hint") or "").split("|")[0].lower()

    # (a) angle field — human-written during triage, most trustworthy
    for pattern, lane in _EDITORIAL_PATTERNS:
        if pattern.search(angle):
            return lane

    # (b) structured keyword hint set by s1
    if "keyword:news" in hint_kw:
        return 3
    if "keyword:moto" in hint_kw:
        return 5
    # keyword:forum in a REL-EDITORIAL row is contradictory — fall through to None

    return None


def _sub_classify_directory(row: dict) -> Optional[Tuple[int, str]]:
    """
    Return (lane, mode) using angle then triage_hint keyword part only.
    L8 (directory/self-claim) is checked before L6 (resource/pitch) within
    each source field; angle is checked before hint.

    Returns None when no signal is found; caller routes the row to review.
    """
    angle   = (row.get("angle") or "").lower()
    hint_kw = (row.get("triage_hint") or "").split("|")[0].lower()

    for text in (angle, hint_kw):
        if _DIRECTORY_L8.search(text):
            return (8, "self-claim")
        if _DIRECTORY_L6.search(text):
            return (6, "pitch")

    return None


# ── run_route ─────────────────────────────────────────────────────────────────

def run_route(db_path: Optional[str] = None) -> dict:
    """
    Process all status='triaged' prospects:

      decision='skip'    → status='closed', mode='none'
      decision='review'  → leave unchanged (already in human queue)
      decision='outreach', deterministic code             → lane+mode, status='routed'
      decision='outreach', REL-EDITORIAL, sub-classify OK → lane+mode, status='routed'
      decision='outreach', REL-EDITORIAL, ambiguous        → decision='review'
      decision='outreach', REL-DIRECTORY, sub-classify OK → lane+mode, status='routed'
      decision='outreach', REL-DIRECTORY, ambiguous        → decision='review'

    Raises RuntimeError if a no-action reason_code carries decision='outreach' —
    that indicates inconsistent state and must be fixed before the batch continues.

    Returns {total, routed, closed, sent_to_review}.
    """
    state     = OutreachState(db_path) if db_path else OutreachState()
    prospects = state.get_pending_route()

    routed         = 0
    closed         = 0
    sent_to_review = 0

    for p in prospects:
        domain   = p["domain"]
        decision = p["decision"]
        reason   = p["reason_code"]

        # ── skip ──────────────────────────────────────────────────────────────
        if decision == "skip":
            state.upsert_prospect(domain, status="closed", lane=None, mode="none")
            closed += 1
            logger.info("route close  domain=%r reason_code=%r", domain, reason)
            continue

        # ── review ────────────────────────────────────────────────────────────
        if decision == "review":
            continue

        # ── outreach ──────────────────────────────────────────────────────────
        if reason in _NO_ACTION_CODES:
            raise RuntimeError(
                f"domain={domain!r}: reason_code={reason!r} has decision='outreach' "
                f"but is a no-action code — state is inconsistent, fix before continuing"
            )

        if reason == "SUPPLIER":
            state.upsert_prospect(domain, lane=1, mode="application", status="routed")
            routed += 1
            logger.info("route routed domain=%r lane=1 mode=application", domain)

        elif reason == "UGC-FORUM":
            state.upsert_prospect(domain, lane=2, mode="application", status="routed")
            routed += 1
            logger.info("route routed domain=%r lane=2 mode=application", domain)

        elif reason == "GEN-NEWS":
            state.upsert_prospect(domain, lane=3, mode="pitch", status="routed")
            routed += 1
            logger.info("route routed domain=%r lane=3 mode=pitch", domain)

        elif reason == "REL-EDITORIAL":
            lane = _sub_classify_editorial(p)
            if lane is not None:
                state.upsert_prospect(domain, lane=lane, mode="pitch", status="routed")
                routed += 1
                logger.info("route routed domain=%r lane=%d mode=pitch (editorial)", domain, lane)
            else:
                state.upsert_prospect(domain, decision="review")
                sent_to_review += 1
                logger.info("route review domain=%r REL-EDITORIAL sub-classify ambiguous", domain)

        elif reason == "REL-DIRECTORY":
            result = _sub_classify_directory(p)
            if result is not None:
                lane, mode = result
                state.upsert_prospect(domain, lane=lane, mode=mode, status="routed")
                routed += 1
                logger.info("route routed domain=%r lane=%d mode=%s (directory)", domain, lane, mode)
            else:
                state.upsert_prospect(domain, decision="review")
                sent_to_review += 1
                logger.info("route review domain=%r REL-DIRECTORY sub-classify ambiguous", domain)

        else:
            logger.warning(
                "route skip   domain=%r reason_code=%r unrecognized; left unchanged",
                domain, reason,
            )

    total = len(prospects)
    logger.info(
        "run_route done: total=%d routed=%d closed=%d sent_to_review=%d",
        total, routed, closed, sent_to_review,
    )
    return {
        "total":          total,
        "routed":         routed,
        "closed":         closed,
        "sent_to_review": sent_to_review,
    }


# ── summary print ─────────────────────────────────────────────────────────────

def _print_summary(s: dict) -> None:
    print(f"  total processed:  {s['total']}")
    print(f"  routed:           {s['routed']}")
    print(f"  closed:           {s['closed']}")
    print(f"  sent to review:   {s['sent_to_review']}")


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    import os
    import tempfile

    print("Running s2_route tests...")

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "s2_test.db")
        st = OutreachState(db)

        # Each row: (domain, authority_score, reason_code, decision, priority, angle, hint, snapshot)
        rows = [
            # deterministic single-lane codes
            ("supplier.com",      60, "SUPPLIER",      "outreach", "high",   "active stockist",             "no-signal",     None),
            ("ugc-forum.de",      55, "UGC-FORUM",     "outreach", "high",   "vendor program",              "keyword:forum", None),
            ("gen-news.fr",       50, "GEN-NEWS",       "outreach", "medium", "data story",                  "keyword:news",  None),
            # REL-EDITORIAL sub-classified via angle
            ("moto-mag.fr",       45, "REL-EDITORIAL", "outreach", "high",   "journalist at Moto Magazine", "keyword:news",  None),
            ("custom-builds.com", 40, "REL-EDITORIAL", "outreach", "medium", "custom build blog",           "no-signal",     None),
            ("maint-blog.de",     38, "REL-EDITORIAL", "outreach", "medium", "maintenance how-to blog",     "keyword:moto",  None),
            ("yt-affiliate.com",  35, "REL-EDITORIAL", "outreach", "low",    "YouTube affiliate channel",   "no-signal",     None),
            # T8: no angle signal, no useful hint → review
            ("ed-nosignal.com",   30, "REL-EDITORIAL", "outreach", "low",    "",                            "no-signal",     None),
            # T9: snapshot has "magazine" but angle/hint are blank → STILL review (snapshot must NOT auto-route)
            ("ed-snap-only.com",  30, "REL-EDITORIAL", "outreach", "low",    "",                            "no-signal",     "This is a motorcycle magazine review site"),
            # REL-DIRECTORY sub-classified via angle
            ("hog-clubs.org",     42, "REL-DIRECTORY", "outreach", "medium", "resource page for clubs",     "no-signal",     None),
            ("dir-listing.com",   38, "REL-DIRECTORY", "outreach", "low",    "directory listing",           "no-signal",     None),
            # T12: no signal → review
            ("dir-nosignal.com",  35, "REL-DIRECTORY", "outreach", "low",    "",                            "no-signal",     None),
            # no-action codes with decision=skip
            ("marketplace.com",   25, "MARKETPLACE",   "skip",     "low",    "marketplace",                 "no-signal",     None),
            ("irrelevant.au",     20, "IRRELEVANT-GEO","skip",     "low",    "irrelevant geo",              "no-signal",     None),
            # UNKNOWN lands as decision=review
            ("unknown-site.com",  30, "UNKNOWN",       "review",   "low",    "",                            "no-signal",     None),
        ]

        for domain, AS, rc, dec, pri, angle, hint, snap in rows:
            st.upsert_prospect(domain, authority_score=AS)
            st.set_triage(domain, decision=dec, priority=pri, reason_code=rc,
                          angle=angle, triage_hint=hint, homepage_snapshot=snap)

        # T16: already-routed row — s2 must not re-process it
        st.upsert_prospect("already-routed.com", authority_score=55)
        st.set_triage("already-routed.com", decision="outreach", priority="high",
                      reason_code="SUPPLIER", angle="active stockist", triage_hint="no-signal")
        st.upsert_prospect("already-routed.com", status="routed", lane=1, mode="application")

        # ── run s2 ────────────────────────────────────────────────────────────
        summary = run_route(db)

        def get(d):
            return st.get_by_domain(d)

        # T1
        r = get("supplier.com")
        assert r["lane"] == 1 and r["mode"] == "application" and r["status"] == "routed", \
            f"T1 SUPPLIER: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T1]  SUPPLIER → L1, application, routed")

        # T2
        r = get("ugc-forum.de")
        assert r["lane"] == 2 and r["mode"] == "application" and r["status"] == "routed", \
            f"T2: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T2]  UGC-FORUM → L2, application, routed")

        # T3
        r = get("gen-news.fr")
        assert r["lane"] == 3 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T3: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T3]  GEN-NEWS → L3, pitch, routed")

        # T4
        r = get("moto-mag.fr")
        assert r["lane"] == 3 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T4: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T4]  REL-EDITORIAL journalist → L3, pitch, routed")

        # T5
        r = get("custom-builds.com")
        assert r["lane"] == 4 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T5: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T5]  REL-EDITORIAL custom build → L4, pitch, routed")

        # T6
        r = get("maint-blog.de")
        assert r["lane"] == 5 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T6: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T6]  REL-EDITORIAL maintenance how-to → L5, pitch, routed")

        # T7
        r = get("yt-affiliate.com")
        assert r["lane"] == 7 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T7: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T7]  REL-EDITORIAL YouTube affiliate → L7, pitch, routed")

        # T8
        r = get("ed-nosignal.com")
        assert r["decision"] == "review" and r["status"] == "triaged", \
            f"T8: decision={r['decision']} status={r['status']}"
        print("  PASS  [T8]  REL-EDITORIAL no signal → decision=review, triaged")

        # T9 — safety: snapshot must NOT auto-route
        r = get("ed-snap-only.com")
        assert r["decision"] == "review" and r["status"] == "triaged", \
            f"T9: decision={r['decision']} status={r['status']}"
        print("  PASS  [T9]  REL-EDITORIAL snapshot-only → decision=review (snapshot must NOT auto-route)")

        # T10
        r = get("hog-clubs.org")
        assert r["lane"] == 6 and r["mode"] == "pitch" and r["status"] == "routed", \
            f"T10: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T10] REL-DIRECTORY resource page → L6, pitch, routed")

        # T11
        r = get("dir-listing.com")
        assert r["lane"] == 8 and r["mode"] == "self-claim" and r["status"] == "routed", \
            f"T11: lane={r['lane']} mode={r['mode']} status={r['status']}"
        print("  PASS  [T11] REL-DIRECTORY directory listing → L8, self-claim, routed")

        # T12
        r = get("dir-nosignal.com")
        assert r["decision"] == "review" and r["status"] == "triaged", \
            f"T12: decision={r['decision']} status={r['status']}"
        print("  PASS  [T12] REL-DIRECTORY no signal → decision=review, triaged")

        # T13
        r = get("marketplace.com")
        assert r["status"] == "closed" and r["mode"] == "none", \
            f"T13: status={r['status']} mode={r['mode']}"
        print("  PASS  [T13] MARKETPLACE (skip) → closed, mode=none")

        # T14
        r = get("irrelevant.au")
        assert r["status"] == "closed" and r["mode"] == "none", \
            f"T14: status={r['status']} mode={r['mode']}"
        print("  PASS  [T14] IRRELEVANT-GEO (skip) → closed, mode=none")

        # T15
        r = get("unknown-site.com")
        assert r["status"] == "triaged" and r["decision"] == "review", \
            f"T15: status={r['status']} decision={r['decision']}"
        print("  PASS  [T15] UNKNOWN (review) → triaged, unchanged")

        # T16
        r = get("already-routed.com")
        assert r["status"] == "routed" and r["lane"] == 1, \
            f"T16: status={r['status']} lane={r['lane']}"
        print("  PASS  [T16] already-routed row not re-processed")

        # Summary
        assert summary["total"] == 15, \
            f"expected total=15, got {summary['total']}"
        assert summary["routed"] == 9, \
            f"expected routed=9 (T1-T7, T10, T11), got {summary['routed']}"
        assert summary["closed"] == 2, \
            f"expected closed=2 (T13, T14), got {summary['closed']}"
        assert summary["sent_to_review"] == 3, \
            f"expected sent_to_review=3 (T8, T9, T12), got {summary['sent_to_review']}"
        print("  PASS  [summary] total=15, routed=9, closed=2, sent_to_review=3")

    print("\nAll s2 tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Stage 2: route — map triage classification to outreach lane + mode."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_route = sub.add_parser("route", help="Route all triaged prospects to lanes")
    p_route.add_argument("--db", help="path to outreach_state.db")

    args = parser.parse_args()

    if args.cmd == "route":
        print("s2 route — mapping triage classifications to outreach lanes")
        summary = run_route(args.db)
        _print_summary(summary)


if __name__ == "__main__":
    main()
