"""Stage 3 — enrich: discover contact email candidates from domain contact pages.

SAFETY CONTRACT (a test proves each clause):
  run_enrich() NEVER writes the `email` field on any named_contact.
  run_enrich() NEVER sets needs_lookup = False.
  run_enrich() NEVER sets candidate_status = "confirmed".

  The ONLY route to a sendable record is promote(), called explicitly by a human.

Schema additions on first backfill (each named_contacts entry):
  email_candidate   str|null     — candidate found by s3; null if nothing yet
  candidate_source  str|null     — provenance e.g. "fetched:hd-forum.de/impressum"
  candidate_status  str          — "none" | "unconfirmed" | "confirmed"

Schema addition on each top-level record:
  fetch_attempts    int          — tracks domain fetches against _FETCH_CAP

Step-2 validation NC_KEYS update:
  NC_KEYS = {"name","email","needs_lookup","role",
             "email_candidate","candidate_source","candidate_status"}
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import requests
    from requests.exceptions import ConnectionError as ReqConnError, Timeout as ReqTimeout
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)

# Reuse s1's network constants — single source of truth, no redeclaration.
from outreach.stages.s1_triage import _FETCH_CAP, _HEADERS
from outreach.lanes import load_parked_lanes
from outreach.outreach_state import OutreachState

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "contacts.json"

# Language-specific contact/legal paths. Homepage ("/") is always prepended.
_CONTACT_PATHS: Dict[str, List[str]] = {
    "de": ["/impressum", "/kontakt"],
    "fr": ["/mentions-legales", "/contact"],
    "en": ["/contact", "/about"],
}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_NOREPLY_RE   = re.compile(r"no.?reply|noreply", re.IGNORECASE)
_JUNK_WORD_RE = re.compile(r"example\.|sentry|wordpress", re.IGNORECASE)
_IMAGE_EXT_RE = re.compile(r"\.(png|jpg|gif|svg|webp|css|js)$", re.IGNORECASE)

_EMAIL_SYNTAX_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_S_NONE        = "none"
_S_UNCONFIRMED = "unconfirmed"
_S_CONFIRMED   = "confirmed"


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _load_contacts(config_path: Path) -> List[dict]:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)["contacts"]


def _save_contacts(contacts: List[dict], config_path: Path) -> None:
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"contacts": contacts}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _backfill_schema(contacts: List[dict]) -> None:
    """Ensure candidate fields and fetch_attempts exist on every record/contact."""
    for record in contacts:
        record.setdefault("fetch_attempts", 0)
        record.setdefault("personalization_hook", "")
        for nc in record.get("named_contacts", []):
            nc.setdefault("email_candidate",  None)
            nc.setdefault("candidate_source", None)
            nc.setdefault("candidate_status", _S_NONE)


# ── network ───────────────────────────────────────────────────────────────────

def _fetch_path(domain: str, path: str) -> Tuple[Optional[str], Optional[str]]:
    """Fetch https://{domain}{path}; fall back to www. variant.
    Returns (html_or_None, fail_reason_or_None).
    Uses s1's _HEADERS and follows the same error-handling pattern.
    """
    urls = [f"https://{domain}{path}", f"https://www.{domain}{path}"]
    last_reason: Optional[str] = None
    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code < 400:
                return (resp.text, None)
            last_reason = f"http-{resp.status_code}"
        except ReqTimeout:
            last_reason = "timeout"
        except ReqConnError:
            last_reason = "connection-error"
        except Exception as exc:
            last_reason = type(exc).__name__
    return (None, last_reason)


def _is_junk(addr: str) -> bool:
    lower = addr.lower()
    if _NOREPLY_RE.search(lower):
        return True
    if _JUNK_WORD_RE.search(lower):
        return True
    domain_part = lower.rsplit("@", 1)[-1] if "@" in lower else lower
    if _IMAGE_EXT_RE.search(domain_part):
        return True
    return False


def _extract_emails(html: str) -> List[str]:
    """Return de-duplicated non-junk email addresses from html."""
    seen: set = set()
    result: List[str] = []
    for addr in _EMAIL_RE.findall(html):
        lower = addr.lower()
        if lower in seen:
            continue
        seen.add(lower)
        if _is_junk(addr):
            continue
        result.append(addr)
    return result


def _paths_for(language: str) -> List[str]:
    """Homepage first, then language-specific paths."""
    specific = _CONTACT_PATHS.get(language.lower(), _CONTACT_PATHS["en"])
    return ["/"] + specific


# ── core ──────────────────────────────────────────────────────────────────────

def run_enrich(
    config_path: Optional[str] = None,
    fetch_fn=None,
) -> dict:
    """Discover email candidates for all backlog contacts.

    fetch_fn(domain, path) -> (html_or_None, fail_reason_or_None) is injectable for tests.
    Returns {fetched, candidates_found, no_email, fetch_failed, null_domain, skipped, total}.
    """
    if fetch_fn is None:
        fetch_fn = _fetch_path

    cfg = Path(config_path) if config_path else Path(os.environ.get("OUTREACH_CONTACTS_FILE") or _CONFIG_PATH)
    contacts = _load_contacts(cfg)
    _backfill_schema(contacts)

    stats = dict(
        fetched=0, candidates_found=0, no_email=0,
        fetch_failed=0, null_domain=0, skipped=0,
        total=len(contacts),
    )
    worklist: List[dict] = []

    for record in contacts:
        domain   = record.get("domain")
        lane     = record.get("lane")
        org      = record.get("organisation", "")
        language = record.get("language", "en")
        ncs      = record.get("named_contacts", [])

        # L8 self-claim — named_contacts==[] by design; no email needed
        if not ncs:
            stats["skipped"] += 1
            continue

        # Contacts that still need a candidate (needs_lookup and not already done)
        actionable = [
            nc for nc in ncs
            if nc.get("needs_lookup") is True
            and nc.get("candidate_status") not in (_S_UNCONFIRMED, _S_CONFIRMED)
        ]

        if not actionable:
            stats["skipped"] += 1
            continue

        # PHASE B — null domain; cannot fetch without guessing
        if domain is None:
            stats["null_domain"] += 1
            worklist.append({"organisation": org, "domain": None, "lane": lane, "reason": "null-domain"})
            continue

        # PHASE A — has domain; enforce retry cap
        if record.get("fetch_attempts", 0) >= _FETCH_CAP:
            stats["fetch_failed"] += 1
            worklist.append({"organisation": org, "domain": domain, "lane": lane, "reason": "fetch-failed"})
            continue

        # Fetch homepage + contact/legal paths
        paths     = _paths_for(language)
        found:   List[Tuple[str, str]] = []   # (addr, source_url)
        got_html = False

        for path in paths:
            html, _ = fetch_fn(domain, path)
            if html is not None:
                got_html = True
                source = f"fetched:{domain}{path}"
                for addr in _extract_emails(html):
                    found.append((addr, source))

        record["fetch_attempts"] = record.get("fetch_attempts", 0) + 1
        stats["fetched"] += 1

        if found:
            best_addr, best_src = found[0]
            for nc in actionable:
                # SAFETY: only candidate fields written here; email and needs_lookup untouched
                nc["email_candidate"]  = best_addr
                nc["candidate_source"] = best_src
                nc["candidate_status"] = _S_UNCONFIRMED
            stats["candidates_found"] += 1
        else:
            reason = "no-email-found" if got_html else "fetch-failed"
            worklist.append({"organisation": org, "domain": domain, "lane": lane, "reason": reason})
            if got_html:
                stats["no_email"] += 1
            else:
                stats["fetch_failed"] += 1

    _save_contacts(contacts, cfg)
    wl_path = cfg.parent / "enrichment_worklist.json"
    with open(wl_path, "w", encoding="utf-8") as f:
        json.dump(worklist, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return stats


# ── promote (human gate) ──────────────────────────────────────────────────────

def _parse_lane(val: str) -> Optional[int]:
    """Convert CLI lane string to int or None."""
    if val.strip().lower() in ("null", "none", ""):
        return None
    return int(val)


def promote(
    domain: str,
    lane: Optional[int],
    role: str,
    email: str,
    hook: str,
    db_path: str,
    artefacts_path: str,
    config_path: Optional[str] = None,
    lanes_path: Optional[str] = None,
) -> None:
    """Set email=ADDR, needs_lookup=False, candidate_status="confirmed", personalization_hook=HOOK.

    The ONLY function that can produce a sendable contact record.
    Locates the named_contact by (domain, lane, role).
    Exits non-zero on validation failure or ambiguous lookup.
    Requires a non-empty hook — a record without a real hook is not sendable.
    """
    if not hook or not hook.strip():
        print(
            "ERROR: --hook is required and must not be empty or whitespace. "
            "Write a real, specific reason for reaching out to this recipient.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _EMAIL_SYNTAX_RE.match(email):
        print(f"ERROR: invalid email syntax: {email!r}", file=sys.stderr)
        sys.exit(1)

    cfg = Path(config_path) if config_path else Path(os.environ.get("OUTREACH_CONTACTS_FILE") or _CONFIG_PATH)
    contacts = _load_contacts(cfg)
    _backfill_schema(contacts)

    matches = [
        r for r in contacts
        if r.get("domain") == domain and r.get("lane") == lane
    ]

    if not matches:
        print(f"ERROR: no record for domain={domain!r} lane={lane!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"ERROR: ambiguous — {len(matches)} records for domain={domain!r} lane={lane!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    record    = matches[0]

    # Guard A: refuse if the record's lane is parked — primary chokepoint before any write.
    effective_lane = record.get("lane")
    parked = load_parked_lanes(lanes_path)
    if effective_lane in parked:
        print(
            f"ERROR: lane {effective_lane} is parked — promote() refused. "
            f"Lane {effective_lane} (supplier) is suspended and cannot enter the draft path. "
            f"To re-activate, remove {effective_lane} from parked_lanes in "
            f"outreach/config/lanes.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    nc_hits   = [nc for nc in record.get("named_contacts", []) if nc.get("role") == role]

    if not nc_hits:
        print(
            f"ERROR: no named_contact with role={role!r} in domain={domain!r} lane={lane!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(nc_hits) > 1:
        print(
            f"ERROR: ambiguous — {len(nc_hits)} contacts with role={role!r} in {domain!r} lane={lane!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    nc = nc_hits[0]

    # validate render-context fields; write to DB before any contacts.json mutation
    organisation_val = record.get("organisation")
    if not organisation_val:
        print(f"ERROR: 'organisation' missing or empty for domain={domain!r}", file=sys.stderr)
        sys.exit(1)

    contact_name_val = nc.get("name")
    if not contact_name_val:
        print(f"ERROR: 'name' missing or empty on named_contact for domain={domain!r}", file=sys.stderr)
        sys.exit(1)

    with open(artefacts_path, encoding="utf-8") as _af:
        _artefacts = json.load(_af)
    artefact_url = _artefacts.get(f"lane_{lane}")
    if not artefact_url:
        print(f"ERROR: artefacts['lane_{lane}'] missing or empty for domain={domain!r}", file=sys.stderr)
        sys.exit(1)

    OutreachState(db_path=db_path).upsert_prospect(
        domain,
        organisation=organisation_val,
        contact_name=contact_name_val,
        contact_email=email,
        language=record.get("language"),
        personalisation_facts=hook.strip(),
        artefact_drive_link=artefact_url,
    )

    nc["email"]            = email
    nc["needs_lookup"]     = False
    nc["candidate_status"] = _S_CONFIRMED
    if nc.get("email_candidate") is None:
        nc["email_candidate"]  = email
        nc["candidate_source"] = "human-promote"

    record["personalization_hook"] = hook.strip()

    _save_contacts(contacts, cfg)
    print(f"Promoted: {domain!r} lane={lane!r} role={role!r} → {email!r}")


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    import os
    import tempfile

    print("Running s3 tests...")

    def make_cfg(contacts_list, tmp_dir) -> Path:
        p = Path(tmp_dir) / "contacts.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"contacts": contacts_list}, f)
        return p

    def load(cfg: Path) -> List[dict]:
        return _load_contacts(cfg)

    def base_record(domain="hd-forum.de", lane=2, language="de", ncs=None) -> dict:
        if ncs is None:
            ncs = [{"name": "Test Admin", "email": None, "needs_lookup": True, "role": "forum-admin"}]
        return {
            "domain": domain, "organisation": f"Org-{domain}", "lane": lane,
            "outreach_type": "vendor-enquiry", "market": "DE", "language": language,
            "proactive": True, "named_contacts": ncs, "action_url": None, "note": "",
        }

    HTML_WITH_EMAIL    = "<html><body>Contact: admin@hd-forum.de</body></html>"
    HTML_WITHOUT_EMAIL = "<html><body>No contact info here.</body></html>"

    # ── T1: domain record, mock returns email ──────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record()], tmp)

        def mock_t1(domain, path):
            return (HTML_WITH_EMAIL, None)

        stats = run_enrich(str(cfg), fetch_fn=mock_t1)
        c = load(cfg)
        nc = c[0]["named_contacts"][0]

        assert nc["email_candidate"] == "admin@hd-forum.de",   f"T1 email_candidate: {nc['email_candidate']}"
        assert "hd-forum.de" in (nc["candidate_source"] or ""), f"T1 candidate_source: {nc['candidate_source']}"
        assert nc["candidate_status"] == "unconfirmed",         f"T1 status: {nc['candidate_status']}"
        assert nc["email"] is None,       f"T1 email must stay null, got {nc['email']}"
        assert nc["needs_lookup"] is True, f"T1 needs_lookup must stay True"
        assert stats["candidates_found"] == 1
        print("  PASS  [T1] email candidate set; email/needs_lookup untouched")

    # ── T2: mock returns no email ──────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record()], tmp)

        def mock_t2(domain, path):
            return (HTML_WITHOUT_EMAIL, None)

        stats = run_enrich(str(cfg), fetch_fn=mock_t2)
        c  = load(cfg)
        nc = c[0]["named_contacts"][0]

        assert nc["candidate_status"] == "none", f"T2 status: {nc['candidate_status']}"

        wl = json.loads((cfg.parent / "enrichment_worklist.json").read_text())
        assert len(wl) == 1 and wl[0]["reason"] == "no-email-found", f"T2 worklist: {wl}"
        assert stats["no_email"] == 1
        print("  PASS  [T2] no email found → candidate_status stays 'none', worklist 'no-email-found'")

    # ── T3: all fetches fail, cap reached ─────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record()], tmp)

        fail_calls: list = []

        def mock_fail(domain, path):
            fail_calls.append((domain, path))
            return (None, "timeout")

        # Run 1: attempts 0→1
        stats1 = run_enrich(str(cfg), fetch_fn=mock_fail)
        c1 = load(cfg)
        assert c1[0]["fetch_attempts"] == 1
        assert c1[0]["named_contacts"][0]["candidate_status"] == "none"
        assert stats1["fetch_failed"] == 1

        # Run 2: attempts 1→2 (== _FETCH_CAP)
        fail_calls.clear()
        stats2 = run_enrich(str(cfg), fetch_fn=mock_fail)
        c2 = load(cfg)
        assert c2[0]["fetch_attempts"] == 2 == _FETCH_CAP

        # Run 3: at cap — fetch_fn MUST NOT be called
        fail_calls.clear()
        stats3 = run_enrich(str(cfg), fetch_fn=mock_fail)
        assert fail_calls == [], f"T3 fetch_fn called when at cap: {fail_calls}"
        assert stats3["fetch_failed"] == 1
        wl = json.loads((cfg.parent / "enrichment_worklist.json").read_text())
        assert wl[0]["reason"] == "fetch-failed", f"T3 worklist reason: {wl}"
        print("  PASS  [T3] fetch cap respected; fetch_attempts honoured; worklist 'fetch-failed'")

    # ── T4: null-domain record ─────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        rec = base_record()
        rec["domain"] = None
        cfg = make_cfg([rec], tmp)

        t4_calls: list = []

        def mock_t4(domain, path):
            t4_calls.append((domain, path))
            return (HTML_WITH_EMAIL, None)

        stats = run_enrich(str(cfg), fetch_fn=mock_t4)
        assert t4_calls == [], f"T4 fetch_fn called for null domain: {t4_calls}"
        assert stats["null_domain"] == 1
        wl = json.loads((cfg.parent / "enrichment_worklist.json").read_text())
        assert wl[0]["reason"] == "null-domain"
        print("  PASS  [T4] null-domain record not fetched; worklist 'null-domain'")

    # ── T5: L8 self-claim (named_contacts=[]) ──────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        rec = base_record()
        rec["lane"] = 8
        rec["outreach_type"] = "self-claim"
        rec["named_contacts"] = []
        cfg = make_cfg([rec], tmp)

        t5_calls: list = []

        def mock_t5(domain, path):
            t5_calls.append((domain, path))
            return (HTML_WITH_EMAIL, None)

        stats = run_enrich(str(cfg), fetch_fn=mock_t5)
        assert t5_calls == [], f"T5 fetch_fn called for L8: {t5_calls}"
        assert stats["skipped"] == 1
        wl = json.loads((cfg.parent / "enrichment_worklist.json").read_text())
        assert wl == [], f"T5 L8 should not appear on worklist: {wl}"
        print("  PASS  [T5] L8 self-claim skipped; not on worklist")

    # ── T6: already-confirmed contact not re-fetched ───────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        ncs = [{"name": "Test", "email": "real@hd-forum.de", "needs_lookup": False,
                "role": "forum-admin", "email_candidate": "real@hd-forum.de",
                "candidate_source": "human-promote", "candidate_status": _S_CONFIRMED}]
        cfg = make_cfg([base_record(ncs=ncs)], tmp)

        t6_calls: list = []

        def mock_t6(domain, path):
            t6_calls.append((domain, path))
            return (HTML_WITH_EMAIL, None)

        stats = run_enrich(str(cfg), fetch_fn=mock_t6)
        assert t6_calls == [], f"T6 fetch_fn called for confirmed contact: {t6_calls}"
        assert stats["skipped"] == 1
        c = load(cfg)
        nc = c[0]["named_contacts"][0]
        assert nc["email"] == "real@hd-forum.de"    # untouched
        assert nc["needs_lookup"] is False           # untouched
        print("  PASS  [T6] already-confirmed contact skipped; not re-fetched")

    # ── T7: re-run with existing unconfirmed → idempotent ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        ncs = [{"name": None, "email": None, "needs_lookup": True, "role": "forum-admin",
                "email_candidate": "existing@hd-forum.de",
                "candidate_source": "fetched:hd-forum.de/",
                "candidate_status": _S_UNCONFIRMED}]
        rec = base_record(ncs=ncs)
        rec["fetch_attempts"] = 1
        cfg = make_cfg([rec], tmp)

        t7_calls: list = []

        def mock_t7(domain, path):
            t7_calls.append((domain, path))
            return ("<html>new@hd-forum.de</html>", None)

        run_enrich(str(cfg), fetch_fn=mock_t7)
        assert t7_calls == [], f"T7 re-fetched when unconfirmed already exists: {t7_calls}"
        c = load(cfg)
        nc = c[0]["named_contacts"][0]
        assert nc["email_candidate"] == "existing@hd-forum.de", f"T7 overwrote: {nc['email_candidate']}"
        assert nc["candidate_status"] == "unconfirmed"
        print("  PASS  [T7] existing unconfirmed not re-fetched; value preserved")

    # ── T8: promote happy path ─────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record()], tmp)
        _backfill_schema(_load_contacts(cfg))   # ensure candidate fields exist for load check

        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({
            "lane_1": "https://drive.google.com/fake-lane1",
            "lane_2": "https://drive.google.com/fake-lane2",
            "lane_3": "https://drive.google.com/fake-lane3",
        }))

        promote("hd-forum.de", 2, "forum-admin", "admin@hd-forum.de",
                "saw HD-Forum just opened a paid vendor section",
                str(db_p), str(art_p), str(cfg))

        c = load(cfg)
        nc = c[0]["named_contacts"][0]
        assert nc["email"]            == "admin@hd-forum.de", f"T8 email: {nc['email']}"
        assert nc["needs_lookup"]     is False,               f"T8 needs_lookup: {nc['needs_lookup']}"
        assert nc["candidate_status"] == "confirmed",         f"T8 status: {nc['candidate_status']}"
        print("  PASS  [T8] promote sets email, needs_lookup=False, candidate_status=confirmed")

    # ── T9: promote with unknown (domain, lane, role) → non-zero exit ─────────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record()], tmp)

        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({"lane_2": "https://drive.google.com/fake-lane2"}))

        exit_codes: list = []
        real_exit = sys.exit

        def fake_exit(code=0):
            exit_codes.append(code)
            raise SystemExit(code)

        sys.exit = fake_exit
        try:
            try:
                promote("nonexistent.de", 2, "forum-admin", "test@test.com", "some hook",
                        str(db_p), str(art_p), str(cfg))
            except SystemExit:
                pass
            assert exit_codes and exit_codes[-1] != 0, f"T9 expected non-zero exit; got {exit_codes}"
            print("  PASS  [T9] promote with unknown domain exits non-zero, writes nothing")
        finally:
            sys.exit = real_exit

    # ── T10: GUARD — run_enrich never writes email / needs_lookup / confirmed ──
    with tempfile.TemporaryDirectory() as tmp:
        contacts_mix = [
            base_record("hd-forum.de",  2, "de"),     # domain: get email
            base_record("hdforums.com", 2, "en"),     # domain: get email
            {**base_record(), "domain": None},        # null domain
        ]
        cfg = make_cfg(contacts_mix, tmp)

        # snapshot email/needs_lookup state before enrichment
        raw_before = json.loads(cfg.read_text())["contacts"]
        before_state = {
            (r.get("organisation"), nc.get("role")): (nc.get("email"), nc.get("needs_lookup"))
            for r in raw_before
            for nc in r.get("named_contacts", [])
        }

        def mock_t10(domain, path):
            return (HTML_WITH_EMAIL, None)

        run_enrich(str(cfg), fetch_fn=mock_t10)

        after_contacts = load(cfg)
        for record in after_contacts:
            for nc in record.get("named_contacts", []):
                key = (record.get("organisation"), nc.get("role"))
                before_email, before_nl = before_state.get(key, (None, None))
                if before_email is None:
                    assert nc.get("email") is None, \
                        f"T10 GUARD FAIL: run_enrich wrote email on {key}"
                if before_nl is True:
                    assert nc.get("needs_lookup") is True, \
                        f"T10 GUARD FAIL: run_enrich set needs_lookup=False on {key}"
                assert nc.get("candidate_status") != "confirmed", \
                    f"T10 GUARD FAIL: run_enrich set candidate_status=confirmed on {key}"

        print("  PASS  [T10] GUARD: no email written, no needs_lookup=False, no confirmed status")

    # ── T_P1: promote() on parked lane → non-zero exit, message names lane + lanes.json ─
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record(lane=1)], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": [1]}')

        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({"lane_1": "https://drive.google.com/fake-lane1"}))

        exit_codes: list = []
        real_exit   = sys.exit
        real_stderr = sys.stderr
        captured    = __import__("io").StringIO()

        def fake_exit_p1(code=0):
            exit_codes.append(code)
            raise SystemExit(code)

        sys.exit   = fake_exit_p1
        sys.stderr = captured
        try:
            try:
                promote("hd-forum.de", 1, "forum-admin", "admin@hd-forum.de",
                        "saw HD-Forum open a paid vendor section",
                        str(db_p), str(art_p), str(cfg), str(lanes_cfg))
            except SystemExit:
                pass
        finally:
            sys.exit   = real_exit
            sys.stderr = real_stderr

        assert exit_codes and exit_codes[-1] != 0, \
            f"T_P1 expected non-zero exit; got {exit_codes}"
        msg = captured.getvalue()
        assert "parked" in msg.lower(), f"T_P1 'parked' not in stderr: {msg!r}"
        assert "lanes.json" in msg, f"T_P1 'lanes.json' not in stderr: {msg!r}"
        assert "1" in msg, f"T_P1 lane number not in stderr: {msg!r}"
        c = _load_contacts(cfg)
        assert c[0]["named_contacts"][0].get("email") is None, "T_P1 GUARD: email was written"
        print("  PASS  [T_P1] promote() on parked lane → non-zero exit, stderr names lane + lanes.json, no write")

    # ── T_P2: promote() on non-parked lane (lane=3) with valid record → succeeds ─
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record(lane=3)], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": [1]}')

        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({
            "lane_1": "https://drive.google.com/fake-lane1",
            "lane_2": "https://drive.google.com/fake-lane2",
            "lane_3": "https://drive.google.com/fake-lane3",
        }))

        promote("hd-forum.de", 3, "forum-admin", "admin@hd-forum.de",
                "saw HD-Forum open a paid vendor section",
                str(db_p), str(art_p), str(cfg), str(lanes_cfg))

        c = _load_contacts(cfg)
        assert c[0]["named_contacts"][0]["email"] == "admin@hd-forum.de", \
            "T_P2 promote did not write email for lane=3"
        print("  PASS  [T_P2] promote() lane=3 (non-parked) → succeeds, email written")

    # ── T_P5a: reversibility — parked_lanes=[] lets lane=1 promote through ──────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record(lane=1)], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": []}')

        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({
            "lane_1": "https://drive.google.com/fake-lane1",
            "lane_2": "https://drive.google.com/fake-lane2",
            "lane_3": "https://drive.google.com/fake-lane3",
        }))

        real_stderr = sys.stderr
        captured    = __import__("io").StringIO()
        sys.stderr  = captured
        try:
            promote("hd-forum.de", 1, "forum-admin", "admin@hd-forum.de",
                    "saw HD-Forum open a paid vendor section",
                    str(db_p), str(art_p), str(cfg), str(lanes_cfg))
        finally:
            sys.stderr = real_stderr

        msg = captured.getvalue()
        assert "parked" not in msg.lower(), \
            f"T_P5a got parked-message with empty parked_lanes: {msg!r}"
        c = _load_contacts(cfg)
        assert c[0]["named_contacts"][0]["email"] == "admin@hd-forum.de", \
            "T_P5a reversibility fail: email not written when lane=1 un-parked"
        print("  PASS  [T_P5a] reversibility: parked_lanes=[] → lane=1 promote succeeds")

    # ── None-lane resolution: NOT present in current code ─────────────────────
    # promote() filters by r.get("lane") == lane; lane=None matches only null-lane
    # records. A domain with lane=1 cannot be reached via lane=None. Extra test
    # (promote lane=None resolves to parked lane) does not apply.

    # ── T_MISSING_ORG: empty organisation → hard-fail before DB write ──────────
    with tempfile.TemporaryDirectory() as tmp:
        rec = base_record(lane=3)
        rec["organisation"] = ""  # break: empty org
        cfg = make_cfg([rec], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": [1]}')
        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({"lane_3": "https://drive.google.com/fake-lane3"}))

        exit_codes_mo: list = []
        real_exit   = sys.exit
        real_stderr = sys.stderr
        captured_mo = __import__("io").StringIO()

        def fake_exit_mo(code=0):
            exit_codes_mo.append(code)
            raise SystemExit(code)

        sys.exit   = fake_exit_mo
        sys.stderr = captured_mo
        try:
            try:
                promote("hd-forum.de", 3, "forum-admin", "admin@hd-forum.de",
                        "saw HD-Forum open a paid vendor section",
                        str(db_p), str(art_p), str(cfg), str(lanes_cfg))
            except SystemExit:
                pass
        finally:
            sys.exit   = real_exit
            sys.stderr = real_stderr

        assert exit_codes_mo and exit_codes_mo[-1] != 0, \
            f"T_MISSING_ORG expected non-zero exit; got {exit_codes_mo}"
        msg_mo = captured_mo.getvalue()
        assert "organisation" in msg_mo, f"T_MISSING_ORG 'organisation' not in stderr: {msg_mo!r}"
        assert "hd-forum.de" in msg_mo,  f"T_MISSING_ORG domain not in stderr: {msg_mo!r}"
        row = OutreachState(db_path=str(db_p)).get_by_domain("hd-forum.de")
        assert row is None, f"T_MISSING_ORG: DB row was written before hard-fail: {row}"
        print("  PASS  [T_MISSING_ORG] empty organisation → non-zero exit, stderr names field+domain, no DB write")

    # ── T_MISSING_NAME: contact name None → hard-fail before DB write ──────────
    with tempfile.TemporaryDirectory() as tmp:
        ncs_mn = [{"name": None, "email": None, "needs_lookup": True, "role": "forum-admin"}]
        rec = base_record(lane=3, ncs=ncs_mn)
        cfg = make_cfg([rec], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": [1]}')
        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({"lane_3": "https://drive.google.com/fake-lane3"}))

        exit_codes_mn: list = []
        real_exit   = sys.exit
        real_stderr = sys.stderr
        captured_mn = __import__("io").StringIO()

        def fake_exit_mn(code=0):
            exit_codes_mn.append(code)
            raise SystemExit(code)

        sys.exit   = fake_exit_mn
        sys.stderr = captured_mn
        try:
            try:
                promote("hd-forum.de", 3, "forum-admin", "admin@hd-forum.de",
                        "saw HD-Forum open a paid vendor section",
                        str(db_p), str(art_p), str(cfg), str(lanes_cfg))
            except SystemExit:
                pass
        finally:
            sys.exit   = real_exit
            sys.stderr = real_stderr

        assert exit_codes_mn and exit_codes_mn[-1] != 0, \
            f"T_MISSING_NAME expected non-zero exit; got {exit_codes_mn}"
        msg_mn = captured_mn.getvalue()
        assert "name" in msg_mn,         f"T_MISSING_NAME 'name' not in stderr: {msg_mn!r}"
        assert "hd-forum.de" in msg_mn,  f"T_MISSING_NAME domain not in stderr: {msg_mn!r}"
        row = OutreachState(db_path=str(db_p)).get_by_domain("hd-forum.de")
        assert row is None, f"T_MISSING_NAME: DB row was written before hard-fail: {row}"
        print("  PASS  [T_MISSING_NAME] name=None → non-zero exit, stderr names field+domain, no DB write")

    # ── T_MISSING_ARTEFACT: lane_3 key absent → hard-fail before DB write ──────
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg([base_record(lane=3)], tmp)
        lanes_cfg = Path(tmp) / "lanes.json"
        lanes_cfg.write_text('{"parked_lanes": [1]}')
        db_p  = Path(tmp) / "state.db"
        art_p = Path(tmp) / "artefacts.json"
        art_p.write_text(json.dumps({"lane_1": "https://drive.google.com/fake-lane1"}))  # lane_3 absent

        exit_codes_ma: list = []
        real_exit   = sys.exit
        real_stderr = sys.stderr
        captured_ma = __import__("io").StringIO()

        def fake_exit_ma(code=0):
            exit_codes_ma.append(code)
            raise SystemExit(code)

        sys.exit   = fake_exit_ma
        sys.stderr = captured_ma
        try:
            try:
                promote("hd-forum.de", 3, "forum-admin", "admin@hd-forum.de",
                        "saw HD-Forum open a paid vendor section",
                        str(db_p), str(art_p), str(cfg), str(lanes_cfg))
            except SystemExit:
                pass
        finally:
            sys.exit   = real_exit
            sys.stderr = real_stderr

        assert exit_codes_ma and exit_codes_ma[-1] != 0, \
            f"T_MISSING_ARTEFACT expected non-zero exit; got {exit_codes_ma}"
        msg_ma = captured_ma.getvalue()
        assert "lane_3" in msg_ma or "artefact" in msg_ma.lower(), \
            f"T_MISSING_ARTEFACT field not in stderr: {msg_ma!r}"
        assert "hd-forum.de" in msg_ma, f"T_MISSING_ARTEFACT domain not in stderr: {msg_ma!r}"
        row = OutreachState(db_path=str(db_p)).get_by_domain("hd-forum.de")
        assert row is None, f"T_MISSING_ARTEFACT: DB row was written before hard-fail: {row}"
        print("  PASS  [T_MISSING_ARTEFACT] lane_3 absent → non-zero exit, stderr names field+domain, no DB write")

    print("\nAll s3 tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Stage 3: enrich — discover contact email candidates."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_enrich = sub.add_parser("enrich", help="Discover email candidates from domain pages")
    p_enrich.add_argument("--db", help="unused (kept for CLI symmetry with other stages)")

    p_promote = sub.add_parser("promote", help="Human gate: promote a candidate to confirmed")
    p_promote.add_argument("--domain",    required=True)
    p_promote.add_argument("--lane",      required=True,
                           help='Lane number or "null" for event records')
    p_promote.add_argument("--role",      required=True)
    p_promote.add_argument("--email",     required=True)
    p_promote.add_argument("--hook",      required=True,
                           help="Human-written personalisation hook (required — must be non-empty)")
    p_promote.add_argument("--db",        required=True, help="path to outreach_state.db")
    p_promote.add_argument("--artefacts", required=True, help="path to artefacts.json")

    args = parser.parse_args()

    if args.cmd == "enrich":
        print("s3 enrich — discovering email candidates…")
        summary = run_enrich()
        print(f"  total records   : {summary['total']}")
        print(f"  skipped         : {summary['skipped']}")
        print(f"  null-domain     : {summary['null_domain']}")
        print(f"  fetched         : {summary['fetched']}")
        print(f"  candidates found: {summary['candidates_found']}")
        print(f"  no email found  : {summary['no_email']}")
        print(f"  fetch failed    : {summary['fetch_failed']}")
        print(f"Worklist written → {_CONFIG_PATH.parent / 'enrichment_worklist.json'}")

    elif args.cmd == "promote":
        lane = _parse_lane(args.lane)
        promote(args.domain, lane, args.role, args.email, args.hook, args.db, args.artefacts)


if __name__ == "__main__":
    main()
