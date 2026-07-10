"""Outreach poller — cadence daemon.

Detects when a Gmail draft is gone (founder sent it) and queues the next follow-up
as a new draft. Every email — initial and follow-ups — goes through the same cycle:
draft sitting in Gmail → gone → advance step → queue the next touch if due.

No send path. drafts().create() only — messages.send is never called.
"""

import argparse
import base64
import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional, Tuple

from googleapiclient.errors import HttpError

from outreach.gmail_client import get_gmail_service
from outreach.outreach_state import OutreachState

logger = logging.getLogger(__name__)

_DIR               = Path(__file__).resolve().parent
_DEFAULT_TOKEN     = _DIR / "secrets" / "token_haleema.json"
_DEFAULT_SENDER    = _DIR / "config"  / "sender.json"
_DEFAULT_TEMPLATES = _DIR / "config"  / "templates.json"

# ── cadence thresholds ────────────────────────────────────────────────────────
# Days elapsed from the day-0 anchor (>= threshold means the touch is due).
# "Past the line" semantics — no upper bound; nothing is skipped if poller misses a day.
FOLLOWUP_2_MIN_DAY = 3
FOLLOWUP_3_MIN_DAY = 8
BREAKUP_MIN_DAY    = 14

# ── send_status vocabulary ────────────────────────────────────────────────────
# send_status records what WE did (sends), not what the recipient did — that's
# reply_status's job (see outreach_state.py), untouched by this daemon.
SEND_STATUS_IN_CADENCE = "in-cadence"   # cadence active; follow-ups will be drafted
SEND_STATUS_EXHAUSTED  = "exhausted"    # last scheduled touch sent; cadence ran its course
SEND_STATUS_WITHDRAWN  = "withdrawn"    # a watched draft was trashed or gone; we stopped,
                                         # reason unrecorded — see cadence_step for how far it got

# Watch a row iff it is actionable — inclusion, not exclusion. An exclusion
# test ("is this row finished?") fails open on any value outside the
# exclusion set; it's only safe if that enumeration is exhaustive, and
# send_status has held a value outside every enumeration written for it
# since the column was created (11 legacy 'declined' rows, predating this
# vocabulary). Inclusion fails closed instead: anything not explicitly
# recognised as active is simply not watched — see the WARNING log in
# run_poll() below for what happens to those rows instead of silence.
ACTIVE_STATES = {None, SEND_STATUS_IN_CADENCE}

# ── cadence map: cadence_step → (template_key, min_day) ──────────────────────
# step represents emails SENT so far; map gives the key for the NEXT touch.
# Lane-3 cadence: initial pitch + one follow-up, then exhausted. followup_3
# and breakup are intentionally absent — FOLLOWUP_3_MIN_DAY/BREAKUP_MIN_DAY
# and their templates.json entries are left defined and untouched; they are
# simply unreachable now, not deleted.
_CADENCE = {
    1: ("followup_2", FOLLOWUP_2_MIN_DAY),
}

# One past the last scheduled step: reaching it means the cadence is done.
# Derived from _CADENCE, not hardcoded — the only source of truth for where
# the cadence ends. Currently 2 (initial sent → step 1; followup_2 sent →
# step 2 → exhausted).
_COMPLETE_STEP = max(_CADENCE, default=0) + 1


# ── helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_elapsed(iso_str: str) -> int:
    """Integer days between the UTC ISO timestamp and now."""
    anchor = datetime.fromisoformat(iso_str)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - anchor).days


def _draft_state(service, draft_id: str) -> str:
    """Returns 'pending', 'sent', 'trashed', or 'gone'.

    Gmail returns HTTP 200 for sent and trashed drafts with changed labelIds —
    a 404 only occurs when the draft was hard-deleted outside normal send/trash flows.
    """
    try:
        result = service.users().drafts().get(userId="me", id=draft_id).execute()
        labels = result.get("message", {}).get("labelIds", [])
        if "SENT" in labels:
            return "sent"
        if "TRASH" in labels:
            return "trashed"
        return "pending"
    except HttpError as exc:
        if exc.resp.status == 404:
            return "gone"
        raise


def _render(
    templates: dict, prospect: dict, sender: dict, template_key: str
) -> Tuple[str, str]:
    """Return (subject, body). Raises KeyError loud if template key is missing."""
    lane = prospect.get("lane")
    lang = (prospect.get("language") or "en").lower()[:2]
    name = (prospect.get("contact_name") or "").strip()
    no_name_greeting = {"en": "Hi there,", "fr": "Bonjour,", "de": "Hallo,"}
    if name:
        greeting = {"en": f"Hi {name},", "fr": f"Bonjour {name},", "de": f"Hallo {name},"}[lang]
    else:
        greeting = no_name_greeting[lang]
    locale_tpl = templates[f"lane_{lane}"][template_key][lang]   # KeyError = fail loud
    ctx = {
        "org":                  prospect.get("organisation", ""),
        "greeting":             greeting,
        "contact_name":         prospect.get("contact_name") or "",
        "sender_name":          sender.get("name", ""),
        "sender_title":         sender.get("title", ""),
        "sender_email":         sender.get("email", ""),
        "sender_linkedin":      sender.get("linkedin_url", ""),
        "personalization_hook": prospect.get("personalisation_facts") or "",
        "artefact_url":         prospect.get("artefact_drive_link") or "",
    }
    return locale_tpl["subject"].format(**ctx), locale_tpl["body"].format(**ctx)


def _create_draft(service, to: str, subject: str, body: str, thread_id: str) -> dict:
    """Create a Gmail draft replying into thread_id. Returns the full API result."""
    mime          = MIMEText(body, "plain")
    mime["to"]      = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    return service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": thread_id}},
    ).execute()


# ── core ──────────────────────────────────────────────────────────────────────

def run_poll(
    token_path=None,
    db_path=None,
    templates_path=None,
    sender_path=None,
    _service=None,      # injectable for tests; never set in production
) -> dict:
    """Detect sent drafts and queue follow-up drafts for all active prospects.

    Returns {checked, advanced, prepared, skipped, errors}.
    No send path: drafts().create() only — messages.send is never called.
    """
    token_path     = Path(token_path)     if token_path     else _DEFAULT_TOKEN
    templates_path = Path(templates_path) if templates_path else _DEFAULT_TEMPLATES
    sender_path    = Path(sender_path)    if sender_path    else _DEFAULT_SENDER

    service   = _service or get_gmail_service(token_path=token_path)
    state     = OutreachState(db_path=db_path)
    templates = (
        json.loads(templates_path.read_text(encoding="utf-8"))
        if templates_path.exists() else {}
    )
    sender = (
        json.loads(sender_path.read_text(encoding="utf-8"))
        if sender_path.exists() else {}
    )

    # Watched iff send_status in ACTIVE_STATES — covers a fresh prospect with
    # no draft yet (NULL) and one whose initial draft is pending/unsent
    # (also NULL — Phase A below is what needs to see it), plus anything
    # actively mid-cadence. exhausted/withdrawn are correctly, silently
    # excluded (expected terminal states, not an error). Anything else —
    # legacy or mistyped values this vocabulary has never recognised — is
    # also excluded, but loudly: see the WARNING below, not silence.
    to_watch = []
    all_prospects = state.get_all()
    for p in all_prospects:
        status = p.get("send_status")
        if status in ACTIVE_STATES:
            to_watch.append(p)
        elif status not in (SEND_STATUS_EXHAUSTED, SEND_STATUS_WITHDRAWN):
            logger.warning(
                "domain=%r has unrecognised send_status=%r — not watched. "
                "Known values: NULL, %r, %r, %r. This row needs a backfill "
                "or manual correction, not silence.",
                p.get("domain"), status,
                SEND_STATUS_IN_CADENCE, SEND_STATUS_EXHAUSTED, SEND_STATUS_WITHDRAWN,
            )

    stats = dict(checked=0, advanced=0, prepared=0, skipped=0, retired=0, errors=0)

    for prospect in to_watch:
        domain = prospect["domain"]
        step   = prospect.get("cadence_step") or 0

        if step >= _COMPLETE_STEP:
            # A row already at or past the ceiling when this cycle runs —
            # most likely one that reached this step under a longer
            # _CADENCE before it was trimmed. Retire it instead of
            # stranding it: left alone, it would stay in ACTIVE_STATES
            # (send_status never changes on its own) and keep re-entering
            # to_watch every cycle forever, making zero Gmail calls and
            # zero progress, silently piling up in stats['skipped'] with
            # no way out.
            if prospect.get("send_status") == SEND_STATUS_IN_CADENCE:
                state.upsert_prospect(domain, send_status=SEND_STATUS_EXHAUSTED)
                stats["retired"] += 1
                logger.info(
                    "retired domain=%r reason=past_cadence_ceiling step=%d (>= %d)",
                    domain, step, _COMPLETE_STEP,
                )
            else:
                stats["skipped"] += 1
            continue

        stats["checked"] += 1

        try:
            draft_id = prospect.get("gmail_draft_id")

            # ── Phase A: draft is waiting — what did the founder do with it? ─────
            if draft_id:
                label = _draft_state(service, draft_id)

                if label == "pending":
                    stats["skipped"] += 1
                    continue                          # still in drafts folder, check next run

                if label in ("trashed", "gone"):
                    state.upsert_prospect(domain,
                                          send_status=SEND_STATUS_WITHDRAWN,
                                          gmail_draft_id=None)
                    stats["retired"] += 1
                    if label == "trashed":
                        logger.info("retired domain=%r reason=trashed (draft deleted without sending)", domain)
                    else:
                        logger.info("retired domain=%r reason=gone (draft 404, hard-deleted)", domain)
                    continue

                # label == "sent": founder sent it → advance step
                new_step = step + 1
                updates  = {"cadence_step": new_step, "gmail_draft_id": None}

                if step == 0:
                    # Initial email just sent: set day-0 anchor ONCE, never moved again.
                    updates["last_action_date"] = _utcnow()
                    updates["send_status"]      = SEND_STATUS_IN_CADENCE

                if new_step >= _COMPLETE_STEP:
                    updates["send_status"] = SEND_STATUS_EXHAUSTED

                state.upsert_prospect(domain, **updates)
                stats["advanced"] += 1
                logger.info("advanced domain=%r step=%d→%d", domain, step, new_step)

                # Refresh local view so Phase B sees the updated state immediately.
                prospect = {**prospect, **updates}
                step     = new_step
                draft_id = None

            # ── Phase B: is the next touch due? ──────────────────────────────────
            if (
                prospect.get("send_status") == SEND_STATUS_IN_CADENCE
                and not prospect.get("gmail_draft_id")
                and step < _COMPLETE_STEP
            ):
                template_key, min_day = _CADENCE.get(step, (None, None))
                if template_key is None:
                    stats["skipped"] += 1
                    continue

                day0    = prospect.get("last_action_date")
                elapsed = _days_elapsed(day0) if day0 else 0

                if elapsed < min_day:
                    stats["skipped"] += 1
                    continue                          # not yet due

                # Due — prepare the next touch as a draft only.
                contact_email = prospect.get("contact_email")
                if not contact_email:
                    raise ValueError(f"no contact_email on domain={domain!r}")

                thread_id     = prospect.get("gmail_thread_id") or ""
                subject, body = _render(templates, prospect, sender, template_key)
                result        = _create_draft(service, contact_email, subject, body, thread_id)

                state.upsert_prospect(
                    domain,
                    gmail_draft_id  = result["id"],
                    gmail_thread_id = result["message"]["threadId"],
                )
                logger.info(
                    "prepared domain=%r template=%r draft=%s",
                    domain, template_key, result["id"],
                )
                stats["prepared"] += 1

        except Exception as exc:
            logger.error("domain=%r error=%r", domain, exc, exc_info=True)
            stats["errors"] += 1

    return stats


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    print("Running poller tests...")

    _FAKE_TEMPLATES = {
        "lane_1": {
            "followup_2": {"en": {"subject": "FU2 {org}", "body": "FU2 body {org}. {sender_name}"}},
            "followup_3": {"en": {"subject": "FU3 {org}", "body": "FU3 body {org}. {sender_name}"}},
            "breakup":    {"en": {"subject": "Breakup {org}", "body": "Breakup {org}. {sender_name}"}},
        }
    }
    _FAKE_SENDER = {
        "name": "Haleema Naz", "email": "h@lp.com",
        "linkedin_url": "https://linkedin.com/in/h", "title": "Test",
    }

    # ── fake Gmail service ────────────────────────────────────────────────────

    class _FakeResp:
        def __init__(self, status):
            self.status = status
            self.reason = "Error"

    class _FakeReq:
        def __init__(self, result=None, err=None):
            self._result, self._err = result, err

        def execute(self):
            if self._err:
                raise self._err
            return self._result

    class _FakeDrafts:
        def __init__(self, svc):
            self._svc = svc

        def get(self, userId, id):
            self._svc.get_calls.append(id)
            if id not in self._svc.existing:
                return _FakeReq(err=HttpError(resp=_FakeResp(404), content=b"Not Found"))
            labels = self._svc.existing[id]
            return _FakeReq(result={"id": id, "message": {"labelIds": labels}})

        def create(self, userId, body):
            new_id = f"fake-{len(self._svc.created) + 1}"
            self._svc.existing[new_id] = ["DRAFT"]
            self._svc.created.append(new_id)
            thread = body.get("message", {}).get("threadId", "fake-thread")
            return _FakeReq(result={"id": new_id, "message": {"threadId": thread}})

    class _FakeUsers:
        def __init__(self, svc):
            self._svc = svc

        def drafts(self):
            return _FakeDrafts(self._svc)

    class _FakeService:
        def __init__(self, existing=None):
            # existing: dict[draft_id → labelIds list]
            # Also accepts a plain set for backward compat → all treated as ["DRAFT"]
            if isinstance(existing, set):
                self.existing = {k: ["DRAFT"] for k in existing}
            else:
                self.existing = dict(existing or {})
            self.created = []
            self.get_calls = []  # draft_ids drafts().get() was actually called with

        def users(self):
            return _FakeUsers(self)

        def mark_sent(self, draft_id):
            """Simulate the founder sending a draft via the Gmail UI."""
            if draft_id in self.existing:
                self.existing[draft_id] = ["SENT"]

        def remove(self, draft_id):
            """Simulate hard deletion of a draft (subsequent get returns 404)."""
            self.existing.pop(draft_id, None)

    # ── test helpers ──────────────────────────────────────────────────────────

    def make_db(tmp_dir, **fields) -> Path:
        db = Path(tmp_dir) / "test.db"
        OutreachState(db_path=db).upsert_prospect("test.com", status="approved", **fields)
        return db

    def make_db_raw(tmp_dir, **fields) -> Path:
        """Like make_db, but inserts via raw SQL — bypasses upsert_prospect's
        ENUMS validation entirely. Simulates a legacy row written before a
        column's vocabulary was constrained, exactly how the real 11
        'declined' rows exist in outreach_state.db today: upsert_prospect
        would now refuse to write "declined", but the row was already there
        before that constraint existed and nothing has touched it since."""
        import sqlite3
        db = Path(tmp_dir) / "test.db"
        OutreachState(db_path=db)  # creates schema only
        fields.setdefault("status", "approved")
        fields.setdefault("created_at", "2026-01-01T00:00:00+00:00")
        fields.setdefault("updated_at", "2026-01-01T00:00:00+00:00")
        cols = ["domain"] + list(fields.keys())
        vals = ["test.com"] + list(fields.values())
        placeholders = ", ".join(["?"] * len(vals))
        conn = sqlite3.connect(str(db))
        conn.execute(f"INSERT INTO prospects ({', '.join(cols)}) VALUES ({placeholders})", vals)
        conn.commit()
        conn.close()
        return db

    def get_record(db) -> dict:
        return OutreachState(db_path=db).get_by_domain("test.com")

    def write_json(tmp_dir, name, data) -> Path:
        p = Path(tmp_dir) / name
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    # ── T1: draft still exists → record unchanged ─────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService(existing={"d-001"})
        before = get_record(db)
        run_poll(_service=svc, db_path=db)
        after  = get_record(db)
        assert after["cadence_step"]    == before["cadence_step"],    \
            f"T1 cadence_step changed: {after['cadence_step']}"
        assert after["send_status"]     == before["send_status"],     \
            f"T1 send_status changed: {after['send_status']}"
        assert after["last_action_date"] == before["last_action_date"], \
            f"T1 last_action_date changed"
        assert len(svc.created) == 0, f"T1 draft created: {svc.created}"
        print("  PASS  [T1] draft still exists → record unchanged")

    # ── T2: labelIds=['SENT'], first detection → day-0 stamped, cadence opened ──
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService(existing={"d-001": ["SENT"]})   # founder sent it
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"]     == SEND_STATUS_IN_CADENCE, \
            f"T2 send_status={after['send_status']!r}"
        assert after["cadence_step"]    == 1,         f"T2 step={after['cadence_step']}"
        assert after["gmail_draft_id"]  is None,      f"T2 draft_id={after['gmail_draft_id']!r}"
        assert after["last_action_date"] is not None, "T2 last_action_date not stamped"
        print("  PASS  [T2] labelIds=['SENT'] → advanced, send_status='in-cadence', day-0 stamped")

    # ── T3: in-cadence, not yet due → no draft prepared ───────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        day0 = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db  = make_db(tmp,
            cadence_step=1, send_status=SEND_STATUS_IN_CADENCE,
            last_action_date=day0, gmail_thread_id="t-001", contact_email="a@b.com",
        )
        svc = _FakeService()
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert len(svc.created) == 0,      f"T3 draft created when not due: {svc.created}"
        assert after["cadence_step"] == 1,  f"T3 step changed: {after['cadence_step']}"
        print("  PASS  [T3] in-cadence, 1 day elapsed → not due, no draft")

    # ── T4: due at day 3 → FU2 prepared; cadence_step stays 1 ────────────────
    with tempfile.TemporaryDirectory() as tmp:
        day0 = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        db  = make_db(tmp,
            cadence_step=1, send_status=SEND_STATUS_IN_CADENCE,
            last_action_date=day0, gmail_thread_id="t-001",
            contact_email="a@b.com", lane=1, language="en",
        )
        tp  = write_json(tmp, "templates.json", _FAKE_TEMPLATES)
        sp  = write_json(tmp, "sender.json",    _FAKE_SENDER)
        svc = _FakeService()
        run_poll(_service=svc, db_path=db, templates_path=tp, sender_path=sp)
        after = get_record(db)
        assert len(svc.created) == 1,         f"T4 expected 1 draft, got {len(svc.created)}"
        assert after["cadence_step"] == 1,    f"T4 step advanced prematurely: {after['cadence_step']}"
        assert after["gmail_draft_id"] == svc.created[0], \
            f"T4 draft_id mismatch: {after['gmail_draft_id']!r}"
        print("  PASS  [T4] day 3 → FU2 prepared, cadence_step still 1 (advance on send)")

    # ── T5: idempotency — FU2 already prepared, re-run → no duplicate ─────────
    with tempfile.TemporaryDirectory() as tmp:
        day0 = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        db  = make_db(tmp,
            cadence_step=1, send_status=SEND_STATUS_IN_CADENCE,
            last_action_date=day0, gmail_thread_id="t-001",
            gmail_draft_id="existing-fu2",            # FU2 already prepared
            contact_email="a@b.com", lane=1, language="en",
        )
        tp  = write_json(tmp, "templates.json", _FAKE_TEMPLATES)
        sp  = write_json(tmp, "sender.json",    _FAKE_SENDER)
        svc = _FakeService(existing={"existing-fu2"})  # draft still in Gmail
        run_poll(_service=svc, db_path=db, templates_path=tp, sender_path=sp)
        assert len(svc.created) == 0,          f"T5 duplicate draft created: {svc.created}"
        after = get_record(db)
        assert after["gmail_draft_id"] == "existing-fu2", \
            f"T5 draft_id overwritten: {after['gmail_draft_id']!r}"
        print("  PASS  [T5] idempotency: FU2 prepared, re-run → no duplicate")

    # ── T6: cadence_step=4 → do nothing ──────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, cadence_step=4, send_status=SEND_STATUS_EXHAUSTED)
        svc = _FakeService()
        before = get_record(db)
        run_poll(_service=svc, db_path=db)
        after  = get_record(db)
        assert after["cadence_step"] == 4, f"T6 step changed: {after['cadence_step']}"
        assert len(svc.created) == 0,      f"T6 draft created: {svc.created}"
        print("  PASS  [T6] cadence_step=4 → nothing done")

    # ── T7: SCOPE — 'status' column is never touched by the poller ────────────
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        assert get_record(db)["status"] == "approved", "T7 fixture setup error"
        svc = _FakeService()                           # d-001 not found → 404 → retire path
        run_poll(_service=svc, db_path=db)
        after_status = get_record(db)["status"]
        assert after_status == "approved", \
            f"T7 SCOPE FAIL: 'status' changed to {after_status!r}"
        print("  PASS  [T7] SCOPE: poller never writes 'status' column")

    # ── T8: end-to-end chain (2-email cadence) — initial sent → step 1 →
    #         followup_2 drafted → sent → step 2 → exhausted. One follow-up,
    #         then stop. No third draft is ever created. ────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        tp = write_json(tmp, "templates.json", _FAKE_TEMPLATES)
        sp = write_json(tmp, "sender.json",    _FAKE_SENDER)
        db = make_db(tmp,
            cadence_step=0, gmail_draft_id="initial-id", gmail_thread_id="t-000",
            contact_email="a@b.com", lane=1, language="en",
        )
        svc = _FakeService(existing={"initial-id": ["SENT"]})  # initial pitch already sent

        # Run 1: initial SENT → step 0→1, day-0 stamped to now — too soon for
        # followup_2 (elapsed ≈ 0 < FOLLOWUP_2_MIN_DAY), so nothing prepared yet.
        run_poll(_service=svc, db_path=db, templates_path=tp, sender_path=sp)
        r = get_record(db)
        assert r["cadence_step"] == 1, f"T8-R1 step={r['cadence_step']}"
        assert r["send_status"]  == SEND_STATUS_IN_CADENCE, f"T8-R1 send_status={r['send_status']!r}"
        assert r["last_action_date"] is not None, "T8-R1 day-0 not stamped"
        assert len(svc.created) == 0, f"T8-R1 unexpected draft: {svc.created}"

        # Simulate FOLLOWUP_2_MIN_DAY+ days passing — same technique T4/T5 use
        # above (seed last_action_date directly rather than waiting in real time).
        day0_past = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        OutreachState(db_path=db).upsert_prospect("test.com", last_action_date=day0_past)

        # Run 2: now due — followup_2 prepared.
        run_poll(_service=svc, db_path=db, templates_path=tp, sender_path=sp)
        r = get_record(db)
        assert r["cadence_step"] == 1,               f"T8-R2 step changed prematurely: {r['cadence_step']}"
        assert len(svc.created) == 1,                f"T8-R2 expected 1 draft, got {svc.created}"
        assert r["gmail_draft_id"] == svc.created[0], f"T8-R2 draft_id={r['gmail_draft_id']!r}"

        # Run 3: followup_2 SENT → step 1→2 → exhausted. No third draft.
        svc.mark_sent(svc.created[0])
        run_poll(_service=svc, db_path=db, templates_path=tp, sender_path=sp)
        r = get_record(db)
        assert r["cadence_step"]   == 2,                     f"T8-R3 step={r['cadence_step']}"
        assert r["send_status"]    == SEND_STATUS_EXHAUSTED, f"T8-R3 send_status={r['send_status']!r}"
        assert r["gmail_draft_id"] is None,                  f"T8-R3 draft_id={r['gmail_draft_id']!r}"
        assert len(svc.created) == 1, \
            f"T8-R3 a third draft was created: {svc.created}"
        print("  PASS  [T8] end-to-end chain: initial→followup_2→exhausted "
              "(one follow-up, then stop — no third draft)")

    # ── T9: labelIds=['DRAFT'] → pending → skipped, record unchanged ──────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService(existing={"d-001": ["DRAFT"]})
        before = get_record(db)
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["cadence_step"]     == before["cadence_step"],     "T9 cadence_step changed"
        assert after["send_status"]      == before["send_status"],      "T9 send_status changed"
        assert after["last_action_date"] == before["last_action_date"], "T9 last_action_date changed"
        assert after["gmail_draft_id"]   == "d-001",                    "T9 draft_id cleared"
        print("  PASS  [T9] labelIds=['DRAFT'] → pending → skipped, record unchanged")

    # ── T10: labelIds=['SENT'] → advanced, day-0 stamped, cadence opened ──────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService(existing={"d-001": ["SENT"]})
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"]      == SEND_STATUS_IN_CADENCE, \
            f"T10 send_status={after['send_status']!r}"
        assert after["cadence_step"]     == 1,    f"T10 step={after['cadence_step']}"
        assert after["gmail_draft_id"]   is None, f"T10 draft_id={after['gmail_draft_id']!r}"
        assert after["last_action_date"] is not None, "T10 last_action_date not stamped"
        print("  PASS  [T10] labelIds=['SENT'] → advanced, day-0 stamped, send_status='in-cadence'")

    # ── T11: labelIds=['DRAFT','TRASH'] → trashed → retired, withdrawn ────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService(existing={"d-001": ["DRAFT", "TRASH"]})
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"]    == SEND_STATUS_WITHDRAWN, \
            f"T11 send_status={after['send_status']!r}"
        assert after["gmail_draft_id"] is None, f"T11 draft_id still set: {after['gmail_draft_id']!r}"
        assert after["cadence_step"]   == 0,    f"T11 cadence_step advanced: {after['cadence_step']}"
        assert after["last_action_date"] is None, "T11 last_action_date wrongly stamped"
        print("  PASS  [T11] labelIds=['DRAFT','TRASH'] → trashed → retired, send_status='withdrawn'")

    # ── T12: HttpError 404 → gone → retired, withdrawn ─────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)
        svc = _FakeService()                           # d-001 not in existing → 404 → gone
        run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"]    == SEND_STATUS_WITHDRAWN, \
            f"T12 send_status={after['send_status']!r}"
        assert after["gmail_draft_id"] is None, f"T12 draft_id still set"
        assert after["cadence_step"]   == 0,    f"T12 cadence_step advanced: {after['cadence_step']}"
        print("  PASS  [T12] HttpError 404 → gone → retired, send_status='withdrawn'")

    # ── T13: HttpError 500 → _draft_state re-raises; outer handler counts error ─
    with tempfile.TemporaryDirectory() as tmp:
        db = make_db(tmp, gmail_draft_id="d-001", gmail_thread_id="t-001", cadence_step=0)

        class _500Drafts:
            def get(self, userId, id):
                return _FakeReq(err=HttpError(resp=_FakeResp(500), content=b"Server Error"))
            def create(self, userId, body):
                raise AssertionError("create must not be called on a 500 path")

        class _500Users:
            def drafts(self): return _500Drafts()

        class _500Service:
            def users(self): return _500Users()

        # Verify _draft_state itself re-raises the 500
        raised_500 = False
        try:
            _draft_state(_500Service(), "d-001")
        except HttpError as exc:
            raised_500 = (exc.resp.status == 500)
        assert raised_500, "T13 _draft_state did not re-raise HttpError 500"

        # Verify run_poll counts it as an error (outer per-prospect guard)
        stats = run_poll(_service=_500Service(), db_path=db)
        assert stats["errors"] == 1, f"T13 expected errors=1, got {stats['errors']}"
        print("  PASS  [T13] HttpError 500 → _draft_state re-raises; outer handler counts as error")

    # ── T14: send_status='declined' (legacy value, predates this vocabulary)
    #         → NOT watched, zero Gmail calls. Asserted on the mock's actual
    #         call count, not just on stats['checked'] ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db_raw(tmp, send_status="declined", gmail_draft_id="d-001",
                           gmail_thread_id="t-001", cadence_step=2)
        svc = _FakeService(existing={"d-001": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 0, f"T14 checked={stats['checked']}"
        assert svc.get_calls == [], f"T14 Gmail drafts().get() was called: {svc.get_calls}"
        print("  PASS  [T14] send_status='declined' (legacy value) → not watched, zero Gmail calls")

    # ── T15: send_status='banana' — a value nobody will ever add to the
    #         vocab, proving the fail-closed property in general, not just
    #         for the one legacy value we already know about ────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db_raw(tmp, send_status="banana", gmail_draft_id="d-002", gmail_thread_id="t-002")
        svc = _FakeService(existing={"d-002": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 0, f"T15 checked={stats['checked']}"
        assert svc.get_calls == [], f"T15 Gmail drafts().get() was called: {svc.get_calls}"
        print("  PASS  [T15] send_status='banana' (never enumerated) → not watched, zero Gmail calls")

    # ── T16: send_status NULL and 'in-cadence' ARE watched ────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, gmail_draft_id="d-003", gmail_thread_id="t-003")  # no send_status → NULL
        svc = _FakeService(existing={"d-003": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 1, f"T16a NULL send_status checked={stats['checked']}"
        assert svc.get_calls == ["d-003"], f"T16a Gmail get() calls={svc.get_calls}"

    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, send_status=SEND_STATUS_IN_CADENCE, cadence_step=1,
                       gmail_draft_id="d-004", gmail_thread_id="t-004")
        svc = _FakeService(existing={"d-004": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 1, f"T16b in-cadence checked={stats['checked']}"
        assert svc.get_calls == ["d-004"], f"T16b Gmail get() calls={svc.get_calls}"
    print("  PASS  [T16] send_status NULL and 'in-cadence' → watched")

    # ── T17: send_status 'exhausted' and 'withdrawn' are NOT watched
    #         (recognised terminal states — expected, no WARNING for these) ─
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, send_status=SEND_STATUS_EXHAUSTED, cadence_step=4,
                       gmail_draft_id="d-005", gmail_thread_id="t-005")
        svc = _FakeService(existing={"d-005": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 0, f"T17a exhausted checked={stats['checked']}"
        assert svc.get_calls == [], f"T17a Gmail get() calls={svc.get_calls}"

    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, send_status=SEND_STATUS_WITHDRAWN,
                       gmail_draft_id="d-006", gmail_thread_id="t-006")
        svc = _FakeService(existing={"d-006": ["DRAFT"]})
        stats = run_poll(_service=svc, db_path=db)
        assert stats["checked"] == 0, f"T17b withdrawn checked={stats['checked']}"
        assert svc.get_calls == [], f"T17b Gmail get() calls={svc.get_calls}"
    print("  PASS  [T17] send_status 'exhausted' and 'withdrawn' → not watched")

    # ── T18: WARNING fires for unrecognised values ('declined', 'banana')
    #         and stays silent for all four known values (NULL, in-cadence,
    #         exhausted, withdrawn) ────────────────────────────────────────
    from unittest.mock import patch as _mock_patch

    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db_raw(tmp, send_status="declined", gmail_draft_id="d-007", gmail_thread_id="t-007")
        svc = _FakeService(existing={"d-007": ["DRAFT"]})
        with _mock_patch.object(logger, "warning") as mock_warn:
            run_poll(_service=svc, db_path=db)
        assert mock_warn.call_count == 1, \
            f"T18a expected 1 WARNING for 'declined', got {mock_warn.call_count}"
        assert "declined" in str(mock_warn.call_args), \
            f"T18a WARNING didn't name the value: {mock_warn.call_args}"

    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db_raw(tmp, send_status="banana", gmail_draft_id="d-008", gmail_thread_id="t-008")
        svc = _FakeService(existing={"d-008": ["DRAFT"]})
        with _mock_patch.object(logger, "warning") as mock_warn:
            run_poll(_service=svc, db_path=db)
        assert mock_warn.call_count == 1, \
            f"T18b expected 1 WARNING for 'banana', got {mock_warn.call_count}"
        assert "banana" in str(mock_warn.call_args), \
            f"T18b WARNING didn't name the value: {mock_warn.call_args}"

    for status, extra in [
        (None,                   {}),
        (SEND_STATUS_IN_CADENCE, {"cadence_step": 1}),
        (SEND_STATUS_EXHAUSTED,  {"cadence_step": 4}),
        (SEND_STATUS_WITHDRAWN,  {}),
    ]:
        with tempfile.TemporaryDirectory() as tmp:
            fields = dict(gmail_draft_id="d-009", gmail_thread_id="t-009", **extra)
            if status is not None:
                fields["send_status"] = status
            db  = make_db(tmp, **fields)
            svc = _FakeService(existing={"d-009": ["DRAFT"]})
            with _mock_patch.object(logger, "warning") as mock_warn:
                run_poll(_service=svc, db_path=db)
            assert mock_warn.call_count == 0, \
                f"T18c send_status={status!r} unexpectedly triggered WARNING: {mock_warn.call_args_list}"
    print("  PASS  [T18] WARNING fires only for unrecognised values, "
          "silent for NULL/in-cadence/exhausted/withdrawn")

    # ── T19: SCOPE — send_status vocabulary rejects 'declined' and 'replied';
    #         ENUMS enforces this before any write reaches the DB, so no
    #         production code path can write either value to send_status ────
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "scope.db"
        state = OutreachState(db_path=db)
        for bad_value in ("declined", "replied"):
            raised = False
            try:
                state.upsert_prospect("test.com", send_status=bad_value)
            except ValueError as exc:
                raised = bad_value in str(exc)
            assert raised, f"T19 send_status={bad_value!r} was accepted or raised the wrong error"
    print("  PASS  [T19] SCOPE: send_status rejects 'declined' and 'replied' "
          "(ENUMS enforces the 3-value vocabulary)")

    # ── T20: cadence_step == _COMPLETE_STEP (2), send_status='in-cadence'
    #         → retired to 'exhausted' THIS cycle, zero Gmail calls. This is
    #         the hole found during the trim's design review — closed by the
    #         retire-instead-of-strand branch at the top of the loop. ───────
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, cadence_step=2, send_status=SEND_STATUS_IN_CADENCE)  # no draft waiting
        svc = _FakeService()
        stats = run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"] == SEND_STATUS_EXHAUSTED, \
            f"T20 send_status={after['send_status']!r}"
        assert stats["checked"] == 0, f"T20 checked={stats['checked']} (should never enter the main body)"
        assert stats["retired"] == 1, f"T20 retired={stats['retired']}"
        assert svc.get_calls == [], f"T20 Gmail drafts().get() called: {svc.get_calls}"
        assert svc.created   == [], f"T20 Gmail drafts().create() called: {svc.created}"
        print("  PASS  [T20] cadence_step=2, send_status='in-cadence' → retired "
              "to 'exhausted', zero Gmail calls")

    # ── T21: cadence_step=3 (above the new ceiling) → also retired, not
    #         stranded — proves this isn't an off-by-one fix for exactly 2 ──
    with tempfile.TemporaryDirectory() as tmp:
        db  = make_db(tmp, cadence_step=3, send_status=SEND_STATUS_IN_CADENCE)
        svc = _FakeService()
        stats = run_poll(_service=svc, db_path=db)
        after = get_record(db)
        assert after["send_status"] == SEND_STATUS_EXHAUSTED, \
            f"T21 send_status={after['send_status']!r}"
        assert stats["retired"] == 1, f"T21 retired={stats['retired']}"
        assert svc.get_calls == [], f"T21 Gmail drafts().get() called: {svc.get_calls}"
        print("  PASS  [T21] cadence_step=3 (above ceiling) → also retired, not stranded")

    # ── T22: _COMPLETE_STEP is derived from _CADENCE, not hardcoded ────────
    assert _COMPLETE_STEP == 2, f"T22 _COMPLETE_STEP={_COMPLETE_STEP}, expected 2"
    assert _COMPLETE_STEP == max(_CADENCE, default=0) + 1, \
        f"T22 _COMPLETE_STEP={_COMPLETE_STEP} != max(_CADENCE, default=0)+1"
    print("  PASS  [T22] _COMPLETE_STEP == 2, derived from _CADENCE (not hardcoded)")

    print(f"\nAll 22 poller tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Outreach cadence poller: detect sent drafts and queue follow-ups."
    )
    parser.add_argument("--db",        help="path to outreach_state.db")
    parser.add_argument("--token",     help="path to Gmail token JSON")
    parser.add_argument("--templates", help="path to templates.json")
    parser.add_argument("--sender",    help="path to sender.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    stats = run_poll(
        token_path     = args.token,
        db_path        = args.db,
        templates_path = args.templates,
        sender_path    = args.sender,
    )
    print(f"  checked  : {stats['checked']}")
    print(f"  advanced : {stats['advanced']}")
    print(f"  prepared : {stats['prepared']}")
    print(f"  retired  : {stats['retired']}")
    print(f"  skipped  : {stats['skipped']}")
    print(f"  errors   : {stats['errors']}")


if __name__ == "__main__":
    main()
