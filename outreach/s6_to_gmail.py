"""
Stage 6 — push validated drafts to Gmail as DRAFTS.
No send path exists in this file. Human approval gate is held externally.

Before drafting, refuses any domain whose prospects row has a non-NULL
send_status (i.e. anything other than the untouched/new state) — that means
outreach/poller.py's cadence daemon already owns this domain (mid-cadence,
complete, or declined) and a brand-new initial-pitch draft would duplicate
or clash with that in-flight relationship. See outreach/poller.py's
SEND_STATUS_* constants for the non-NULL vocabulary.
"""
import base64
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outreach.gmail_client import get_gmail_service
from outreach.outreach_state import OutreachState

_DIR = Path(__file__).resolve().parent
_DEFAULT_TOKEN = _DIR / "secrets" / "token_haleema.json"


def run_to_gmail(valid_drafts, token_path=_DEFAULT_TOKEN, db_path=None):
    """Push validated drafts to Gmail as DRAFTS.

    Returns {created, skipped, refused}:
      created  — domains a new Gmail draft was created for.
      skipped  — domains that already had a gmail_draft_id set.
      refused  — domains whose row has a non-NULL send_status (mid-cadence,
                 complete, or declined); each entry is
                 {"domain", "send_status", "cadence_step"}.

    db_path overrides the default outreach_state.db (test injection only —
    mirrors outreach/poller.py's run_poll(db_path=...) pattern).
    """
    service = get_gmail_service(token_path=token_path)
    state   = OutreachState(db_path=db_path)

    created = []
    skipped = []
    refused = []

    for draft in valid_drafts:
        domain = draft["domain"]
        record = state.get_by_domain(domain)

        # Refuses on ANY non-NULL send_status, including SEND_STATUS_COMPLETE
        # — a cleanly-finished cadence is therefore permanently un-draftable
        # by the sheet track too. Correct for now (there is no re-pitch
        # concept yet), but a future 'exhausted' terminal state (distinct
        # from 'complete') would need its own explicit re-pitch path through
        # this guard — not built here.
        if record and record.get("send_status") is not None:
            send_status  = record.get("send_status")
            cadence_step = record.get("cadence_step")
            print(
                f"  REFUSE {domain}  send_status={send_status!r}  "
                f"cadence_step={cadence_step}  "
                f"reason=domain already owned by the cadence poller "
                f"(mid-cadence, complete, or declined) — refusing to draft "
                f"a duplicate initial pitch"
            )
            refused.append({
                "domain": domain,
                "send_status": send_status,
                "cadence_step": cadence_step,
            })
            continue

        if record and record.get("gmail_draft_id"):
            print(f"  SKIP  {domain}  (draft_id already set)")
            skipped.append(domain)
            continue

        to_addr = draft.get("contact_email")
        if not to_addr:
            raise ValueError(f"no contact_email for domain={domain!r}")

        email_text = draft["body"]
        if draft.get("sign_off"):
            email_text = f"{draft['body']}\n\n{draft['sign_off']}"
        mime = MIMEText(email_text, "plain")
        mime["to"]      = to_addr
        mime["subject"] = draft["subject"]
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

        result = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()

        draft_id  = result["id"]
        thread_id = result["message"]["threadId"]

        state.upsert_prospect(
            domain,
            gmail_draft_id=draft_id,
            gmail_thread_id=thread_id,
            contact_email=to_addr,
        )
        print(f"  DRAFT {domain}  draft_id={draft_id}")
        created.append(domain)

    print(f"\nDone — {len(created)} created, {len(skipped)} skipped, {len(refused)} refused.")
    return {"created": created, "skipped": skipped, "refused": refused}


# ── tests ──────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    """Tests use a real temp SQLite OutreachState (db_path=) — this is the DB
    guard's own logic under test, not something to mock away — plus a mocked
    Gmail service (same idiom as run_outreach.py's _run_tests). No live API
    calls, no writes to the real DB/token.
    """
    import tempfile
    from pathlib import Path as _Path
    from unittest.mock import MagicMock, patch

    from outreach.outreach_state import OutreachState as _OutreachState
    from outreach.poller import SEND_STATUS_IN_CADENCE, SEND_STATUS_DECLINED

    print("Running s6_to_gmail tests...")

    _DRAFT = {
        "domain": "testpub.com",
        "contact_email": "editor@testpub.com",
        "subject": "Test subject",
        "body": "Test body",
        "sign_off": "",
    }

    def _mock_service(draft_id="draft-abc", thread_id="thread-xyz"):
        svc = MagicMock()
        svc.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": draft_id, "message": {"threadId": thread_id},
        }
        return svc

    # ── T1: send_status='in-cadence' → refused, no draft created ─────────────
    with tempfile.TemporaryDirectory() as tmp:
        db = str(_Path(tmp) / "state.db")
        state = _OutreachState(db_path=db)
        state.upsert_prospect("testpub.com", send_status=SEND_STATUS_IN_CADENCE, cadence_step=1)

        mock_service = _mock_service()
        with patch(f"{__name__}.get_gmail_service", return_value=mock_service):
            result = run_to_gmail([_DRAFT], db_path=db)

        assert result["created"] == [], f"T1 created={result['created']}"
        assert len(result["refused"]) == 1, f"T1 refused={result['refused']}"
        assert result["refused"][0]["domain"]       == "testpub.com"
        assert result["refused"][0]["send_status"]  == SEND_STATUS_IN_CADENCE
        assert result["refused"][0]["cadence_step"] == 1
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        print("  PASS  [T1]  send_status='in-cadence' → refused, create() not called")

    # ── T2: send_status='declined' → refused, no draft created ───────────────
    with tempfile.TemporaryDirectory() as tmp:
        db = str(_Path(tmp) / "state.db")
        state = _OutreachState(db_path=db)
        state.upsert_prospect("testpub.com", send_status=SEND_STATUS_DECLINED, cadence_step=0)

        mock_service = _mock_service()
        with patch(f"{__name__}.get_gmail_service", return_value=mock_service):
            result = run_to_gmail([_DRAFT], db_path=db)

        assert result["created"] == [], f"T2 created={result['created']}"
        assert len(result["refused"]) == 1, f"T2 refused={result['refused']}"
        assert result["refused"][0]["send_status"] == SEND_STATUS_DECLINED
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        print("  PASS  [T2]  send_status='declined' → refused, create() not called")

    # ── T3: no row at all for the domain → drafts normally ────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        db = str(_Path(tmp) / "state.db")   # empty DB — no row inserted

        mock_service = _mock_service(draft_id="draft-new1", thread_id="thread-new1")
        with patch(f"{__name__}.get_gmail_service", return_value=mock_service):
            result = run_to_gmail([_DRAFT], db_path=db)

        assert result["refused"] == [], f"T3 refused={result['refused']}"
        assert result["created"] == ["testpub.com"], f"T3 created={result['created']}"
        after = _OutreachState(db_path=db).get_by_domain("testpub.com")
        assert after["gmail_draft_id"] == "draft-new1"
        print("  PASS  [T3]  no row at all → drafts normally, row created with draft_id")

    # ── T4: row exists, send_status NULL, no prior draft → drafts normally ───
    with tempfile.TemporaryDirectory() as tmp:
        db = str(_Path(tmp) / "state.db")
        state = _OutreachState(db_path=db)
        # Row exists from an earlier stage (e.g. s1_triage/s2_route/s3_enrich) —
        # send_status was never touched by poller.py, so it is NULL, and no
        # draft has ever been created. This MUST still draft normally.
        state.upsert_prospect("testpub.com", authority_score=40, decision="outreach")
        before = state.get_by_domain("testpub.com")
        assert before["send_status"]    is None, f"T4 precondition send_status={before['send_status']!r}"
        assert before["gmail_draft_id"] is None, f"T4 precondition gmail_draft_id={before['gmail_draft_id']!r}"

        mock_service = _mock_service(draft_id="draft-new2", thread_id="thread-new2")
        with patch(f"{__name__}.get_gmail_service", return_value=mock_service):
            result = run_to_gmail([_DRAFT], db_path=db)

        assert result["refused"] == [], f"T4 refused={result['refused']}"
        assert result["created"] == ["testpub.com"], f"T4 created={result['created']}"
        after = state.get_by_domain("testpub.com")
        assert after["gmail_draft_id"] == "draft-new2"
        assert after["authority_score"] == 40, \
            f"T4 earlier-stage column clobbered: authority_score={after['authority_score']}"
        print("  PASS  [T4]  row exists, send_status NULL, no prior draft → drafts normally")

    print("\nAll s6_to_gmail tests passed.")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)
