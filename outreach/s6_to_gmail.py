"""
Stage 6 — push validated drafts to Gmail as DRAFTS.
No send path exists in this file. Human approval gate is held externally.
"""
import base64
from email.mime.text import MIMEText
from pathlib import Path

from outreach.gmail_client import get_gmail_service
from outreach.outreach_state import OutreachState

_DIR = Path(__file__).resolve().parent
_DEFAULT_TOKEN = _DIR / "secrets" / "token_haleema.json"


def run_to_gmail(valid_drafts, token_path=_DEFAULT_TOKEN):
    service = get_gmail_service(token_path=token_path)
    state   = OutreachState()

    created = []
    skipped = []

    for draft in valid_drafts:
        domain = draft["domain"]
        record = state.get_by_domain(domain)

        if record and record.get("gmail_draft_id"):
            print(f"  SKIP  {domain}  (draft_id already set)")
            skipped.append(domain)
            continue

        to_addr = draft.get("contact_email")
        if not to_addr:
            raise ValueError(f"no contact_email for domain={domain!r}")

        mime = MIMEText(draft["body"], "plain")
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

    print(f"\nDone — {len(created)} created, {len(skipped)} skipped.")
    return {"created": created, "skipped": skipped}
