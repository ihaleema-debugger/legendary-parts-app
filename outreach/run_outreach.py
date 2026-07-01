"""
s4→s6 runner — generate drafts, validate them, push survivors to Gmail.

Imports run_draft and run_validate directly; delegates Gmail creation to
run_to_gmail from outreach.s6_to_gmail. Fails loud on every violation:
no silent fallbacks, no try/except that swallows.

Code cannot send. run_to_gmail calls drafts().create() only.
A human presses Send.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outreach.stages.s4_draft    import run_draft
from outreach.stages.s4_validate import run_validate
from outreach.s6_to_gmail        import run_to_gmail

_DIR = Path(__file__).resolve().parent

_DEFAULT_CONTACTS  = _DIR / "config" / "contacts.json"
_DEFAULT_SENDER    = _DIR / "config" / "sender.json"
_DEFAULT_ARTEFACTS = _DIR / "config" / "artefacts.json"
_DEFAULT_TEMPLATES = _DIR / "config" / "templates.json"
_DEFAULT_DB        = _DIR / "outreach_state.db"
_DEFAULT_TOKEN     = _DIR / "secrets" / "token_haleema.json"


def run(
    contacts_path=None,
    sender_path=None,
    artefacts_path=None,
    templates_path=None,
    token_path=None,
):
    """Generate, validate, and push drafts to Gmail.

    Returns {drafted, validated, gmail_created, gmail_skipped, validation_blocks, draft_blocks}.
    Callers that need a dry-run can inspect the return dict instead of calling run_to_gmail.
    """
    # ── Stage 4a: generate ────────────────────────────────────────────────────
    draft_result = run_draft(
        contacts_path=contacts_path,
        sender_path=sender_path,
        artefacts_path=artefacts_path,
        templates_path=templates_path,
    )

    if draft_result["draft_blocks"] if "draft_blocks" in draft_result else draft_result.get("blocks"):
        blocks = draft_result.get("blocks", [])
        if blocks:
            print("\n[s4_draft] blocked drafts (loud):")
            for b in blocks:
                domain_label = b.get("domain") or "(null)"
                print(f"  BLOCK  {domain_label:<28}  reason={b['reason']}")

    drafted = draft_result["drafts"]
    print(
        f"\n[s4_draft]  total={draft_result['total']}  "
        f"drafted={draft_result['drafted']}  "
        f"blocked={draft_result['blocked']}  "
        f"skipped={draft_result['skipped']}"
    )

    if not drafted:
        print("[run_outreach] No drafts produced — nothing to validate or push.")
        return {
            "drafted":           0,
            "validated":         0,
            "gmail_created":     0,
            "gmail_skipped":     0,
            "validation_blocks": [],
            "draft_blocks":      draft_result.get("blocks", []),
        }

    # ── Stage 4b: validate ────────────────────────────────────────────────────
    val_result = run_validate(drafted)

    if val_result["blocks"]:
        print("\n[s4_validate] blocked drafts (loud):")
        for b in val_result["blocks"]:
            domain_label = b.get("domain") or "(null)"
            print(f"  BLOCK  {domain_label:<28}  violations:")
            for v in b["violations"]:
                print(f"           - {v}")

    print(
        f"\n[s4_validate]  total={val_result['total']}  "
        f"valid={val_result['valid']}  "
        f"blocked={val_result['blocked']}"
    )

    valid_drafts = val_result["valid_drafts"]

    if not valid_drafts:
        print("[run_outreach] No drafts survived validation — nothing pushed to Gmail.")
        return {
            "drafted":           draft_result["drafted"],
            "validated":         0,
            "gmail_created":     0,
            "gmail_skipped":     0,
            "validation_blocks": val_result["blocks"],
            "draft_blocks":      draft_result.get("blocks", []),
        }

    # ── Stage 6: push to Gmail ────────────────────────────────────────────────
    print(f"\n[s6_to_gmail]  pushing {len(valid_drafts)} draft(s) to Gmail…")
    tok = Path(token_path) if token_path else _DEFAULT_TOKEN
    gmail_result = run_to_gmail(valid_drafts, token_path=tok)

    print(
        f"\n[run_outreach] summary:\n"
        f"  drafted        : {draft_result['drafted']}\n"
        f"  validated      : {val_result['valid']}\n"
        f"  gmail_created  : {len(gmail_result['created'])}\n"
        f"  gmail_skipped  : {len(gmail_result['skipped'])}\n"
    )
    if gmail_result["created"]:
        for d in gmail_result["created"]:
            print(f"    CREATED  {d}")
    if gmail_result["skipped"]:
        for d in gmail_result["skipped"]:
            print(f"    SKIPPED  {d}  (draft_id already set)")

    return {
        "drafted":           draft_result["drafted"],
        "validated":         val_result["valid"],
        "gmail_created":     len(gmail_result["created"]),
        "gmail_skipped":     len(gmail_result["skipped"]),
        "validation_blocks": val_result["blocks"],
        "draft_blocks":      draft_result.get("blocks", []),
    }


# ── tests ──────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    """Tests use mock Gmail — no live API calls, no DB writes to the real DB."""
    import json
    import tempfile
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    print("Running run_outreach tests…")

    # ── shared fixtures ───────────────────────────────────────────────────────

    _SENDER = {
        "name": "Haleema Naz",
        "email": "haleema@legendary-parts.com",
        "linkedin_url": "https://linkedin.com/in/haleema",
        "title": "Owner",
    }
    _ARTEFACTS_L3 = {"lane_3": "https://drive.google.com/file/d/abc123/view"}
    _TEMPLATES_L3 = {
        "lane_3": {
            "en": {
                "subject_variants": [
                    "H-D fitment data for {org} — Legendary Parts",
                    "{org}: mechanic insight from Legendary Parts",
                ],
                "subject_fallback": "Expert mechanic insight — Legendary Parts",
                "body": (
                    "Hi {contact_name},\n\n"
                    "{personalization_hook}\n\n"
                    "Legendary Parts maps H-D OEM fitment patterns across the UK, French, "
                    "and German markets. Happy to share a data cut.\n\n"
                    "Profile and catalogue: {artefact_url}\n\n"
                    "{sender_name}\n{sender_title}, Legendary Parts\n"
                    "{sender_email}\n{sender_linkedin}"
                ),
            },
        }
    }

    def _lane3_contact(domain="testpub.com", org="Test Publication", hook="read your M8 reliability piece"):
        return {
            "domain": domain,
            "organisation": org,
            "lane": 3,
            "outreach_type": "pitch",
            "market": "UK",
            "language": "en",
            "proactive": True,
            "named_contacts": [{
                "name": "Test Editor",
                "role": "editor",
                "needs_lookup": False,
                "email": f"editor@{domain}",
                "candidate_status": "confirmed",
                "email_candidate": None,
                "candidate_source": None,
            }],
            "action_url": None,
            "personalization_hook": hook,
            "note": "",
        }

    def _write_files(tmp, contacts, sender=_SENDER, artefacts=_ARTEFACTS_L3, templates=_TEMPLATES_L3):
        cp = Path(tmp) / "contacts.json"
        sp = Path(tmp) / "sender.json"
        ap = Path(tmp) / "artefacts.json"
        tp = Path(tmp) / "templates.json"
        lp = Path(tmp) / "lanes.json"
        cp.write_text(json.dumps({"contacts": contacts}), encoding="utf-8")
        sp.write_text(json.dumps(sender), encoding="utf-8")
        ap.write_text(json.dumps(artefacts), encoding="utf-8")
        tp.write_text(json.dumps(templates), encoding="utf-8")
        lp.write_text('{"parked_lanes": []}', encoding="utf-8")
        return str(cp), str(sp), str(ap), str(tp)

    # ── T1: one valid contact → drafted=1, validated=1, gmail_created=1 ───────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp = _write_files(tmp, [_lane3_contact()])

        mock_service    = MagicMock()
        mock_draft_resp = {"id": "draft-abc", "message": {"threadId": "thread-xyz"}}
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = mock_draft_resp

        # Patch get_gmail_service AND OutreachState so no real DB or token is touched
        with patch("outreach.s6_to_gmail.get_gmail_service", return_value=mock_service), \
             patch("outreach.s6_to_gmail.OutreachState") as MockState:
            mock_state_inst = MagicMock()
            mock_state_inst.get_by_domain.return_value = None  # no existing draft
            MockState.return_value = mock_state_inst

            result = run(
                contacts_path=cp,
                sender_path=sp,
                artefacts_path=ap,
                templates_path=tp,
            )

        assert result["drafted"]       == 1, f"T1 drafted={result['drafted']}"
        assert result["validated"]     == 1, f"T1 validated={result['validated']}"
        assert result["gmail_created"] == 1, f"T1 gmail_created={result['gmail_created']}"
        assert result["gmail_skipped"] == 0, f"T1 gmail_skipped={result['gmail_skipped']}"
        # Confirm upsert was called with the right domain
        mock_state_inst.upsert_prospect.assert_called_once()
        call_args = mock_state_inst.upsert_prospect.call_args
        assert call_args[0][0] == "testpub.com", f"T1 upsert domain={call_args[0][0]}"
        assert call_args[1].get("gmail_draft_id") == "draft-abc", \
            f"T1 upsert draft_id={call_args[1].get('gmail_draft_id')}"
        print("  PASS  [T1]  1 valid contact → drafted=1, validated=1, gmail_created=1")

    # ── T2: existing draft_id in DB → gmail_skipped=1, upsert NOT called ──────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp = _write_files(tmp, [_lane3_contact()])

        mock_service = MagicMock()

        with patch("outreach.s6_to_gmail.get_gmail_service", return_value=mock_service), \
             patch("outreach.s6_to_gmail.OutreachState") as MockState:
            mock_state_inst = MagicMock()
            mock_state_inst.get_by_domain.return_value = {"gmail_draft_id": "existing-draft-id"}
            MockState.return_value = mock_state_inst

            result = run(
                contacts_path=cp,
                sender_path=sp,
                artefacts_path=ap,
                templates_path=tp,
            )

        assert result["gmail_created"] == 0, f"T2 gmail_created={result['gmail_created']}"
        assert result["gmail_skipped"] == 1, f"T2 gmail_skipped={result['gmail_skipped']}"
        # drafts().create() must NOT have been called
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        print("  PASS  [T2]  existing draft_id → gmail_skipped=1, create() not called")

    # ── T3: no sendable contact → drafted=0, nothing reaches Gmail ───────────
    with tempfile.TemporaryDirectory() as tmp:
        unsendable = {
            "domain": "noemail.com",
            "organisation": "No Email Pub",
            "lane": 3,
            "outreach_type": "pitch",
            "market": "UK",
            "language": "en",
            "proactive": True,
            "named_contacts": [{
                "name": None,
                "role": None,
                "needs_lookup": True,
                "email": None,
                "candidate_status": "none",
                "email_candidate": None,
                "candidate_source": None,
            }],
            "action_url": None,
            "personalization_hook": "some hook",
            "note": "",
        }
        cp, sp, ap, tp = _write_files(tmp, [unsendable])

        mock_service = MagicMock()

        with patch("outreach.s6_to_gmail.get_gmail_service", return_value=mock_service), \
             patch("outreach.s6_to_gmail.OutreachState"):
            result = run(
                contacts_path=cp,
                sender_path=sp,
                artefacts_path=ap,
                templates_path=tp,
            )

        assert result["drafted"]       == 0, f"T3 drafted={result['drafted']}"
        assert result["validated"]     == 0, f"T3 validated={result['validated']}"
        assert result["gmail_created"] == 0, f"T3 gmail_created={result['gmail_created']}"
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        print("  PASS  [T3]  no sendable contact → drafted=0, Gmail never called")

    # ── T4: validation failure → draft blocked, gmail_created=0 ──────────────
    #  Patch run_validate at the actual executing module's namespace so the
    #  mock is visible regardless of whether we're running as __main__ or
    #  imported (i.e. `__name__` is "outreach.run_outreach" when imported).
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp = _write_files(tmp, [_lane3_contact()])

        mock_service = MagicMock()

        fake_block = {
            "total": 1, "valid": 0, "blocked": 1,
            "blocks": [{"domain": "testpub.com", "organisation": "Test Publication",
                        "lane": 3, "violations": ["word_count_mismatch:999_vs_24"]}],
            "valid_drafts": [],
        }

        # __name__ is "__main__" when run directly, "outreach.run_outreach" when imported.
        with patch(f"{__name__}.run_validate", return_value=fake_block), \
             patch("outreach.s6_to_gmail.get_gmail_service", return_value=mock_service), \
             patch("outreach.s6_to_gmail.OutreachState"):
            result = run(
                contacts_path=cp,
                sender_path=sp,
                artefacts_path=ap,
                templates_path=tp,
            )

        assert result["validated"]              == 0, f"T4 validated={result['validated']}"
        assert result["gmail_created"]          == 0, f"T4 gmail_created={result['gmail_created']}"
        assert len(result["validation_blocks"]) == 1, \
            f"T4 validation_blocks={result['validation_blocks']}"
        mock_service.users.return_value.drafts.return_value.create.assert_not_called()
        print("  PASS  [T4]  run_validate returns block → gmail_created=0, create() not called")

    # ── T5: two contacts, one valid one unsendable → only valid one reaches Gmail
    with tempfile.TemporaryDirectory() as tmp:
        good   = _lane3_contact(domain="good.com",   org="Good Pub",   hook="saw your latest H-D feature")
        unsend = {
            "domain": "nosend.com",
            "organisation": "No Send Pub",
            "lane": 3,
            "outreach_type": "pitch",
            "market": "UK",
            "language": "en",
            "proactive": True,
            "named_contacts": [{
                "name": None, "role": None, "needs_lookup": True, "email": None,
                "candidate_status": "none", "email_candidate": None, "candidate_source": None,
            }],
            "action_url": None,
            "personalization_hook": "some hook text here",
            "note": "",
        }
        cp, sp, ap, tp = _write_files(tmp, [good, unsend])

        mock_service    = MagicMock()
        mock_draft_resp = {"id": "draft-good", "message": {"threadId": "thread-good"}}
        mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = mock_draft_resp

        with patch("outreach.s6_to_gmail.get_gmail_service", return_value=mock_service), \
             patch("outreach.s6_to_gmail.OutreachState") as MockState:
            mock_state_inst = MagicMock()
            mock_state_inst.get_by_domain.return_value = None
            MockState.return_value = mock_state_inst

            result = run(
                contacts_path=cp,
                sender_path=sp,
                artefacts_path=ap,
                templates_path=tp,
            )

        assert result["drafted"]       == 1, f"T5 drafted={result['drafted']}"
        assert result["validated"]     == 1, f"T5 validated={result['validated']}"
        assert result["gmail_created"] == 1, f"T5 gmail_created={result['gmail_created']}"
        # Confirm it was the good domain that was upserted
        call_domain = mock_state_inst.upsert_prospect.call_args[0][0]
        assert call_domain == "good.com", f"T5 wrong domain upserted: {call_domain}"
        print("  PASS  [T5]  2 contacts (1 sendable) → drafted=1, gmail_created=1, nosend.com blocked")

    print("\nAll run_outreach tests passed.")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description=(
            "Outreach runner — generates drafts (s4_draft), validates them (s4_validate), "
            "and pushes survivors to Gmail as DRAFTS (s6_to_gmail). "
            "No send path. A human presses Send."
        )
    )
    parser.add_argument("--contacts",  default=str(_DEFAULT_CONTACTS),  help="path to contacts.json")
    parser.add_argument("--sender",    default=str(_DEFAULT_SENDER),    help="path to sender.json")
    parser.add_argument("--artefacts", default=str(_DEFAULT_ARTEFACTS), help="path to artefacts.json")
    parser.add_argument("--templates", default=str(_DEFAULT_TEMPLATES), help="path to templates.json")
    parser.add_argument("--token",     default=str(_DEFAULT_TOKEN),     help="path to Gmail OAuth token")

    args = parser.parse_args()

    run(
        contacts_path=args.contacts,
        sender_path=args.sender,
        artefacts_path=args.artefacts,
        templates_path=args.templates,
        token_path=args.token,
    )


if __name__ == "__main__":
    main()
