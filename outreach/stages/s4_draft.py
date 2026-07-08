"""Stage 4 — draft: Lane 1 supplier email draft generator (language-aware).

PUBLIC API
----------
run_draft(contacts_path, sender_path, artefacts_path, templates_path) -> dict

Precondition gate (first failure per record wins):
  0. lane in parked_lanes             -> block, reason "lane_parked"
  0b. reason_code == "SUPPLIER"       -> block, reason "reason_supplier"
  1. domain is None                   -> skip,  reason "null_domain"
  2. language not in templates        -> block, reason "unsupported_language"
  3. sender.json incomplete           -> block, reason "sender_incomplete"
  4. no sendable named_contact        -> block, reason "no_sendable_contact"
  5. artefacts["lane_1"] falsy        -> block, reason "no_artefact"
  6. action_url is None/empty         -> block, reason "insufficient_personalisation"

Sendable predicate mirrors s3_enrich.promote():
  nc["needs_lookup"] is False  AND  nc["email"] is truthy
  AND  nc["candidate_status"] == "confirmed"
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from outreach.lanes import load_parked_lanes

_CONTACTS_PATH  = Path(__file__).parent.parent / "config" / "contacts.json"
_SENDER_PATH    = Path(__file__).parent.parent / "config" / "sender.json"
_ARTEFACTS_PATH = Path(__file__).parent.parent / "config" / "artefacts.json"
_TEMPLATES_PATH = Path(__file__).parent.parent / "config" / "templates.json"

_SUPPORTED_LANES = frozenset({1, 3})
_LANE_CONF = {
    1: {"template_key": "lane_1", "artefact_key": "lane_1", "requires_action_url": True},
    3: {"template_key": "lane_3", "artefact_key": "lane_3", "requires_action_url": False},
}
_SENDABLE_STATUS = "confirmed"   # mirrors s3_enrich._S_CONFIRMED

_BANNED_SUBJECT_WORDS = frozenset({
    "collaboration", "link", "insertion", "resources",
    "guest", "enhance", "backlink",
})

_SUBJECT_MIN = 20
_SUBJECT_MAX = 78
_BODY_MIN    = 45
_BODY_MAX    = 135


# ── I/O ───────────────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    """Return {} when path is missing; parse otherwise."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_contacts(path: Path) -> List[dict]:
    return _load_json(path).get("contacts", [])


def _check_no_domain_lane_collision(contacts: List[dict]) -> None:
    lanes_by_domain: dict = {}
    for record in contacts:
        domain = record.get("domain")
        if not domain:
            continue
        lanes_by_domain.setdefault(domain, set()).add(record.get("lane"))
    collisions = {
        domain: sorted(lanes)
        for domain, lanes in lanes_by_domain.items()
        if len(lanes) > 1
    }
    if collisions:
        parts = "; ".join(
            f"{domain!r} in lanes {lanes}"
            for domain, lanes in collisions.items()
        )
        raise ValueError(
            f"contacts.json has domain/lane collisions — {parts}. "
            "Each non-null domain must belong to exactly one lane "
            "(the prospects DB is keyed on domain alone). "
            "Split into distinct domains or pick one lane."
        )


# ── predicates ────────────────────────────────────────────────────────────────

def _is_sender_complete(sender: dict) -> bool:
    return all(sender.get(k) for k in ("name", "email", "linkedin_url", "title"))


def _get_sendable_contact(record: dict) -> Optional[dict]:
    """Return first named_contact where promote() completed, else None."""
    for nc in record.get("named_contacts", []):
        if (
            nc.get("needs_lookup") is False
            and nc.get("email")
            and nc.get("candidate_status") == _SENDABLE_STATUS
        ):
            return nc
    return None


# ── subject builder ───────────────────────────────────────────────────────────

def _has_banned_word(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in _BANNED_SUBJECT_WORDS)


def _build_subject(org: str, locale_tpl: dict) -> str:
    """Try subject_variants (English banned-word scan); cascade to subject_fallback."""
    for variant in locale_tpl.get("subject_variants", []):
        filled = variant.replace("{org}", org)
        if _SUBJECT_MIN <= len(filled) <= _SUBJECT_MAX and not _has_banned_word(filled):
            return filled
    return locale_tpl["subject_fallback"]


# ── body builder ──────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _build_body(
    record: dict,
    contact: dict,
    sender: dict,
    artefact_url: str,
    locale_tpl: dict,
    contact_name: str = "",
) -> Tuple[str, str, List[str]]:
    """Return (body, sign_off, personalisation).

    If locale_tpl has a "sign_off" piece (lane 3 today), it's rendered
    separately and NOT included in `body` — it's appended after the body at
    send time (s6_to_gmail) but excluded from word-count validation, since
    the 25-65 word lane-3 ceiling is meant for the pitch, not the signature.
    Locales with no "sign_off" key (lane 1 today) are unaffected: the
    signature stays embedded in `body` exactly as before, and sign_off
    returns "".
    """
    org                  = record["organisation"]
    action_url           = record.get("action_url") or ""
    personalization_hook = record.get("personalization_hook", "")

    format_kwargs = dict(
        org=org,
        contact_name=contact_name,
        sender_name=sender["name"],
        sender_title=sender["title"],
        action_url=action_url,
        artefact_url=artefact_url,
        sender_email=sender["email"],
        sender_linkedin=sender["linkedin_url"],
        personalization_hook=personalization_hook,
    )

    body = locale_tpl["body"].format(**format_kwargs)
    sign_off_tpl = locale_tpl.get("sign_off", "")
    sign_off = sign_off_tpl.format(**format_kwargs) if sign_off_tpl else ""

    personalisation: List[str] = []
    if personalization_hook and personalization_hook in body:
        personalisation.append("hook")
    if action_url and action_url in body:
        personalisation.append(f"action_url '{action_url}'")
    if artefact_url and artefact_url in body:
        personalisation.append("artefact_url")

    # Sanity guards — template design must never include tracking pixels
    body_lower = body.lower()
    assert "<img" not in body_lower, "body template must not contain <img>"
    assert "1x1" not in body, "body template must not contain pixel dimensions"

    return body, sign_off, personalisation


# ── core ──────────────────────────────────────────────────────────────────────

def run_draft(
    contacts_path:  Optional[str] = None,
    sender_path:    Optional[str] = None,
    artefacts_path: Optional[str] = None,
    templates_path: Optional[str] = None,
    lanes_path:     Optional[str] = None,
) -> dict:
    """Generate Lane 1 supplier drafts from enriched contacts.

    Returns {total, drafted, blocked, skipped, blocks[], drafts[]}.
    Reads config files only — never writes to disk.
    """
    cp = Path(contacts_path) if contacts_path else Path(os.environ.get("OUTREACH_CONTACTS_FILE") or _CONTACTS_PATH)
    sp = Path(sender_path)    if sender_path    else _SENDER_PATH
    ap = Path(artefacts_path) if artefacts_path else _ARTEFACTS_PATH
    tp = Path(templates_path) if templates_path else _TEMPLATES_PATH

    contacts  = _load_contacts(cp)
    _check_no_domain_lane_collision(contacts)
    sender    = _load_json(sp)
    artefacts = _load_json(ap)
    templates = _load_json(tp)
    parked_lanes = load_parked_lanes(lanes_path)

    out: dict = dict(total=0, drafted=0, blocked=0, skipped=0, blocks=[], drafts=[])

    for record in contacts:
        lane = record.get("lane")
        if lane not in _SUPPORTED_LANES:
            continue

        conf = _LANE_CONF[lane]

        out["total"] += 1
        domain = record.get("domain")
        org    = record.get("organisation", "")
        _base  = {"domain": domain, "organisation": org, "lane": lane}

        # Guard B: lane parked — defensive catch for contacts already marked sendable.
        if lane in parked_lanes:
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "lane_parked"})
            continue

        # Guard C: SUPPLIER reason — never drafted, regardless of lane/priority.
        if (record.get("reason_code") or "").strip().upper() == "SUPPLIER":
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "reason_supplier"})
            continue

        # Gate 1: null domain — cannot draft without a known domain
        if domain is None:
            out["skipped"] += 1
            out["blocks"].append({**_base, "reason": "null_domain"})
            continue

        # Gate 2: language resolution and template lookup
        raw_lang = record.get("language")
        lang = ((raw_lang or "").lower().strip()) or "en"
        if len(lang) > 2:
            lang = lang[:2]
        language_defaulted = not bool(raw_lang)

        lane_tpls = templates.get(conf["template_key"], {})
        if lang not in lane_tpls:
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "unsupported_language"})
            continue

        locale_tpl = lane_tpls[lang]

        # Gate 3: personalization_hook must be present and non-empty
        if not record.get("personalization_hook", "").strip():
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "missing_hook"})
            continue

        # Gate 4: sender identity must be fully populated
        if not _is_sender_complete(sender):
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "sender_incomplete"})
            continue

        # Gate 5: at least one confirmed sendable contact
        contact = _get_sendable_contact(record)
        if contact is None:
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "no_sendable_contact"})
            continue

        # Gate 6: lane artefact (company profile / catalogue Drive link) required
        artefact_url = artefacts.get(conf["artefact_key"], "")
        if not artefact_url:
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "no_artefact"})
            continue

        # Gate 7: action_url required for lanes that need a 2nd personalisation element via URL
        if conf["requires_action_url"] and not record.get("action_url"):
            out["blocked"] += 1
            out["blocks"].append({**_base, "reason": "insufficient_personalisation"})
            continue

        # Build draft
        subject = _build_subject(org, locale_tpl)
        body, sign_off, personalisation = _build_body(
            record, contact, sender, artefact_url, locale_tpl,
            contact_name=contact.get("name") or "",
        )
        wc = _word_count(body)

        out["drafted"] += 1
        out["drafts"].append({
            "domain":                domain,
            "organisation":          org,
            "lane":                  lane,
            "contact_name":          contact.get("name"),
            "contact_email":         contact["email"],
            "subject":               subject,
            "body":                  body,
            "sign_off":              sign_off,
            "language":              lang,
            "language_defaulted":    language_defaulted,
            "word_count":            wc,
            "personalisation_count": len(personalisation),
            "personalization_hook":  record.get("personalization_hook", ""),
            "cadence_stage":         0,
            "draft_status":          "needs-review",
        })

    return out


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    import tempfile

    print("Running s4_draft tests...")

    # ── shared fixtures ───────────────────────────────────────────────────────

    _GOOD_SENDER = {
        "name": "Haleema Naz",
        "email": "haleema@legendary-parts.com",
        "linkedin_url": "https://linkedin.com/in/haleema",
        "title": "Owner",
        "needs_lookup": False,
        "note": "Founder identity for all outreach.",
    }

    _BAD_SENDER = {
        "name": None, "email": None, "linkedin_url": None, "title": None,
        "needs_lookup": True, "note": "",
    }

    _GOOD_ARTEFACTS = {"lane_1": "https://drive.google.com/file/d/abc123/view"}
    _EMPTY_ARTEFACTS: dict = {}

    # Minimal bilingual templates for fully self-contained tests
    _MINIMAL_TEMPLATES = {
        "lane_1": {
            "en": {
                "subject_variants": [
                    "{org}: dealer application, Legendary Parts",
                    "Legendary Parts — dealer application, {org}",
                ],
                "subject_fallback": "Authorised dealer enquiry — Legendary Parts",
                "body": (
                    "Dear {org} team,\n\n"
                    "I'm {sender_name}, {sender_title} at Legendary Parts — a European specialist in "
                    "Harley-Davidson OEM and aftermarket parts, shipping to the UK, France, and Germany.\n\n"
                    "{personalization_hook}\n\n"
                    "We'd like to apply to join your authorised stockist programme. "
                    "You can find our application via your dealer page at {action_url}.\n\n"
                    "Our company profile and full catalogue are available here: {artefact_url}\n\n"
                    "Happy to answer any questions about our range or order volumes.\n\n"
                    "Best regards,\n{sender_name}\n{sender_title}, Legendary Parts\n"
                    "{sender_email}\n{sender_linkedin}"
                ),
            },
            "fr": {
                "subject_variants": [
                    "{org} : demande revendeur agréé, Legendary Parts",
                    "Legendary Parts — demande revendeur, {org}",
                ],
                "subject_fallback": "Demande revendeur agréé — Legendary Parts",
                "body": (
                    "Bonjour {org},\n\n"
                    "Je suis {sender_name}, {sender_title} chez Legendary Parts — spécialiste "
                    "européen des pièces Harley-Davidson OEM et aftermarket, livrant au "
                    "Royaume-Uni, en France et en Allemagne.\n\n"
                    "{personalization_hook}\n\n"
                    "Nous souhaitons rejoindre votre réseau de revendeurs agréés. "
                    "Vous pouvez soumettre notre demande via {action_url}.\n\n"
                    "Notre profil d'entreprise et notre catalogue : {artefact_url}\n\n"
                    "Nous sommes à votre disposition pour toute question.\n\n"
                    "Cordialement,\n{sender_name}\n{sender_title}, Legendary Parts\n"
                    "{sender_email}\n{sender_linkedin}"
                ),
            },
        }
    }

    def make_contact(
        domain="partseurope.eu",
        org="Parts Europe",
        lang="en",
        sendable=True,
        action_url="partseurope.eu/dealers/",
        hook="noticed Parts Europe just opened their UK stockist application portal",
    ) -> dict:
        nc = {
            "name": "Parts Europe Team",
            "role": "dealer-program",
            "needs_lookup": False if sendable else True,
            "email": "dealers@partseurope.eu" if sendable else None,
            "candidate_status": "confirmed" if sendable else "none",
            "email_candidate": None,
            "candidate_source": None,
        }
        return {
            "domain": domain,
            "organisation": org,
            "lane": 1,
            "outreach_type": "application",
            "market": "multi",
            "language": lang,
            "proactive": True,
            "named_contacts": [nc],
            "action_url": action_url,
            "personalization_hook": hook,
            "note": "EU distributor.",
        }

    def make_files(tmp, contacts_list, sender_data, artefacts_data, templates_data=None):
        cp = Path(tmp) / "contacts.json"
        sp = Path(tmp) / "sender.json"
        ap = Path(tmp) / "artefacts.json"
        tp = Path(tmp) / "templates.json"
        lp = Path(tmp) / "lanes.json"
        with open(cp, "w", encoding="utf-8") as f:
            json.dump({"contacts": contacts_list}, f, ensure_ascii=False)
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(sender_data, f)
        with open(ap, "w", encoding="utf-8") as f:
            json.dump(artefacts_data, f)
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(
                templates_data if templates_data is not None else _MINIMAL_TEMPLATES,
                f, ensure_ascii=False,
            )
        with open(lp, "w", encoding="utf-8") as f:
            json.dump({"parked_lanes": []}, f)
        return str(cp), str(sp), str(ap), str(tp), str(lp)

    # ── T1: happy path (en) ───────────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, f"T1 drafted={result['drafted']}"
        d = result["drafts"][0]
        assert d["domain"] == "partseurope.eu"
        assert d["draft_status"] == "needs-review"
        assert d["cadence_stage"] == 0
        assert d["language"] == "en"
        assert d["contact_email"] == "dealers@partseurope.eu"
        print("  PASS  [T1]  happy path (en) → 1 draft, all required fields present")

    # ── T2: sender all-None → sender_incomplete ───────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _BAD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T2 drafted={result['drafted']}"
        reasons = [b["reason"] for b in result["blocks"]]
        assert "sender_incomplete" in reasons, f"T2 reasons={reasons}"
        print("  PASS  [T2]  sender all-None → drafted=0, reason=sender_incomplete")

    # ── T3: contact needs_lookup=True / no email → no_sendable_contact ────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact(sendable=False)], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T3 drafted={result['drafted']}"
        assert result["blocks"][0]["reason"] == "no_sendable_contact", \
            f"T3 reason={result['blocks']}"
        print("  PASS  [T3]  unsendable contact → drafted=0, reason=no_sendable_contact")

    # ── T4: artefacts={} → no_artefact ───────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _EMPTY_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T4 drafted={result['drafted']}"
        assert result["blocks"][0]["reason"] == "no_artefact", \
            f"T4 reason={result['blocks']}"
        print("  PASS  [T4]  no artefact → drafted=0, reason=no_artefact")

    # ── T5: happy → word_count in 45..135 ────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        wc = result["drafts"][0]["word_count"]
        assert _BODY_MIN <= wc <= _BODY_MAX, \
            f"T5 word_count={wc}, expected {_BODY_MIN}–{_BODY_MAX}"
        print(f"  PASS  [T5]  word_count={wc} in {_BODY_MIN}–{_BODY_MAX}")

    # ── T6: happy → personalisation_count >= 2 ───────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        pc = result["drafts"][0]["personalisation_count"]
        assert pc >= 2, f"T6 personalisation_count={pc}"
        print(f"  PASS  [T6]  personalisation_count={pc} >= 2")

    # ── T7: happy → subject fits 20-78 chars, no banned words ─────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        subj = result["drafts"][0]["subject"]
        assert _SUBJECT_MIN <= len(subj) <= _SUBJECT_MAX, \
            f"T7 subject len={len(subj)}: {subj!r}"
        assert not _has_banned_word(subj), f"T7 banned word in subject: {subj!r}"
        print(f"  PASS  [T7]  subject len={len(subj)}, no banned words: {subj!r}")

    # ── T8: happy → cadence_stage=0 and draft_status="needs-review" ──────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        d = result["drafts"][0]
        assert d["cadence_stage"] == 0, f"T8 cadence_stage={d['cadence_stage']}"
        assert d["draft_status"] == "needs-review", f"T8 draft_status={d['draft_status']}"
        print("  PASS  [T8]  cadence_stage=0, draft_status='needs-review'")

    # ── T9: happy → body has no <img> and no pixel dimensions ────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        body = result["drafts"][0]["body"]
        assert "<img" not in body.lower(), "T9 body contains <img>"
        assert "1x1" not in body, "T9 body contains pixel dimensions"
        print("  PASS  [T9]  body has no <img> and no pixel dimensions")

    # ── T10: GUARD — sender complete, artefact+action_url set, 3 contacts,
    #         NONE sendable → drafted=0 ────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        contacts_mix = [
            # not sendable: needs_lookup=True, email=None
            make_contact(domain="a.eu", org="Org A", sendable=False, action_url="a.eu/dealers/"),
            # not sendable: needs_lookup=True, email=None, candidate_status="none"
            {
                "domain": "b.eu", "organisation": "Org B", "lane": 1,
                "outreach_type": "application", "market": "multi", "language": "en",
                "proactive": True, "action_url": "b.eu/dealers/", "note": "",
                "personalization_hook": "saw Org B recently extended EU distribution",
                "named_contacts": [{
                    "name": None, "email": None, "needs_lookup": True, "role": None,
                    "candidate_status": "none", "email_candidate": None,
                    "candidate_source": None,
                }],
            },
            # not sendable: email set but candidate_status="unconfirmed", needs_lookup=True
            {
                "domain": "c.eu", "organisation": "Org C", "lane": 1,
                "outreach_type": "application", "market": "multi", "language": "en",
                "proactive": True, "action_url": "c.eu/dealers/", "note": "",
                "personalization_hook": "noticed Org C just launched a new dealer portal",
                "named_contacts": [{
                    "name": "Test User", "email": "test@c.eu", "needs_lookup": True,
                    "role": "manager", "candidate_status": "unconfirmed",
                    "email_candidate": "test@c.eu", "candidate_source": "fetched:c.eu/",
                }],
            },
        ]
        cp, sp, ap, tp, lp = make_files(
            tmp, contacts_mix, _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T10 GUARD FAIL: drafted={result['drafted']}"
        assert result["blocked"] == 3, f"T10 expected blocked=3, got {result['blocked']}"
        for b in result["blocks"]:
            assert b["reason"] == "no_sendable_contact", \
                f"T10 unexpected reason {b['reason']!r} for {b['domain']}"
        print("  PASS  [T10] GUARD: 3 unsendable contacts → drafted=0, all no_sendable_contact")

    # ── T11: language="fr" → French draft produced ────────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp,
            [make_contact(domain="motomag.com", org="Moto Magazine", lang="fr",
                          action_url="motomag.com/dealers/")],
            _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, f"T11 drafted={result['drafted']}"
        d = result["drafts"][0]
        assert d["language"] == "fr", f"T11 language={d['language']}"
        assert d["language_defaulted"] is False, \
            f"T11 language_defaulted={d['language_defaulted']}"
        print(f"  PASS  [T11] language='fr' → French draft, language_defaulted=False")

    # ── T12: language="xx" (unsupported) → unsupported_language ──────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact(lang="xx")], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T12 drafted={result['drafted']}"
        assert result["blocks"][0]["reason"] == "unsupported_language", \
            f"T12 reason={result['blocks'][0]['reason']}"
        print("  PASS  [T12] language='xx' → drafted=0, reason=unsupported_language")

    # ── T13: language field missing → defaults to 'en', language_defaulted=True
    with tempfile.TemporaryDirectory() as tmp:
        contact_no_lang = make_contact()
        del contact_no_lang["language"]
        cp, sp, ap, tp, lp = make_files(
            tmp, [contact_no_lang], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, f"T13 drafted={result['drafted']}"
        d = result["drafts"][0]
        assert d["language"] == "en", f"T13 language={d['language']}"
        assert d["language_defaulted"] is True, \
            f"T13 language_defaulted={d['language_defaulted']}"
        print("  PASS  [T13] language missing → defaults to 'en', language_defaulted=True")

    # ── T14: personalization_hook empty → missing_hook ────────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        contact_no_hook = make_contact(hook="")
        cp, sp, ap, tp, lp = make_files(
            tmp, [contact_no_hook], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T14 drafted={result['drafted']}"
        assert result["blocked"] == 1, f"T14 blocked={result['blocked']}"
        assert result["blocks"][0]["reason"] == "missing_hook", \
            f"T14 reason={result['blocks'][0]['reason']}"
        print("  PASS  [T14] empty hook → drafted=0, reason=missing_hook")

    # ── T15: GUARD — same non-null domain in two different lanes → ValueError ──
    collision_contacts = [
        {"domain": "example.com", "lane": 1},
        {"domain": "example.com", "lane": 3},
    ]
    try:
        _check_no_domain_lane_collision(collision_contacts)
        raise AssertionError("T15: expected ValueError, got none")
    except ValueError as exc:
        assert "example.com" in str(exc), f"T15: domain not in error: {exc}"
        assert "1" in str(exc) and "3" in str(exc), f"T15: lanes not in error: {exc}"
        print("  PASS  [T15] GUARD: same domain in lanes 1+3 → ValueError with domain+lanes in message")

    # ── T16: GUARD — two null-domain records in different lanes → no raise ──────
    null_domain_contacts = [
        {"domain": None, "lane": 2},
        {"domain": None, "lane": 3},
    ]
    _check_no_domain_lane_collision(null_domain_contacts)
    print("  PASS  [T16] GUARD: two null-domain records in different lanes → no raise")

    # ── T17: GUARD — contacts.fixture.json passes (no collision today) ──────────
    fixture_path = Path(__file__).parent.parent / "config" / "contacts.fixture.json"
    _check_no_domain_lane_collision(_load_contacts(fixture_path))
    print("  PASS  [T17] GUARD: contacts.fixture.json → no collision")

    # ── T18: GUARD — real contacts.json passes (no collision today) ─────────────
    real_path = Path(__file__).parent.parent / "config" / "contacts.json"
    _check_no_domain_lane_collision(_load_contacts(real_path))
    print("  PASS  [T18] GUARD: contacts.json (real) → no collision")

    # ── T_P3: pre-seeded sendable lane-1 contact + parked_lanes=[1]
    #         → drafted=0, blocked=1, reason=="lane_parked" ────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        Path(lp).write_text('{"parked_lanes": [1]}')  # overwrite empty default
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T_P3 drafted={result['drafted']}"
        assert result["blocked"] == 1, f"T_P3 blocked={result['blocked']}"
        assert result["blocks"][0]["reason"] == "lane_parked", \
            f"T_P3 reason={result['blocks'][0]['reason']}"
        assert result["blocks"][0]["lane"] == 1, \
            f"T_P3 lane in block={result['blocks'][0]['lane']}"
        print("  PASS  [T_P3] sendable lane-1 + parked_lanes=[1] → drafted=0, blocked=1, reason=lane_parked")

    # ── T_P4: sendable lane-3 contact + parked_lanes=[1] → drafts normally ────
    with tempfile.TemporaryDirectory() as tmp:

        _LANE3_TEMPLATES = {
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
        _GOOD_ARTEFACTS_L3 = {"lane_3": "https://drive.google.com/file/d/abc123/view"}
        lane3_contact = {
            "domain": "hdmag.com",
            "organisation": "HD Magazine",
            "lane": 3,
            "outreach_type": "editorial",
            "market": "multi",
            "language": "en",
            "proactive": True,
            "named_contacts": [{
                "name": "Editor",
                "role": "editor",
                "needs_lookup": False,
                "email": "editor@hdmag.com",
                "candidate_status": "confirmed",
                "email_candidate": None,
                "candidate_source": None,
            }],
            "action_url": None,
            "personalization_hook": "read your M8 reliability piece last month",
            "note": "",
        }
        cp, sp, ap, tp, lp = make_files(
            tmp, [lane3_contact], _GOOD_SENDER, _GOOD_ARTEFACTS_L3, _LANE3_TEMPLATES,
        )
        Path(lp).write_text('{"parked_lanes": [1]}')  # lane 1 parked; lane 3 must be unaffected
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, \
            f"T_P4 lane-3 should draft normally; drafted={result['drafted']}, blocks={result['blocks']}"
        lane_parked_blocks = [b for b in result["blocks"] if b.get("reason") == "lane_parked"]
        assert lane_parked_blocks == [], \
            f"T_P4 lane-3 got lane_parked block: {lane_parked_blocks}"
        print("  PASS  [T_P4] sendable lane-3 + parked_lanes=[1] → drafted=1, no lane_parked block")

    # ── T_P5b: reversibility — parked_lanes=[] lets lane-1 draft through ──────
    with tempfile.TemporaryDirectory() as tmp:
        cp, sp, ap, tp, lp = make_files(
            tmp, [make_contact()], _GOOD_SENDER, _GOOD_ARTEFACTS,
        )
        # lp already contains {"parked_lanes": []} from make_files — no overwrite needed
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, \
            f"T_P5b reversibility fail: drafted={result['drafted']}, blocks={result['blocks']}"
        lane_parked_blocks = [b for b in result["blocks"] if b.get("reason") == "lane_parked"]
        assert lane_parked_blocks == [], \
            f"T_P5b got unexpected lane_parked block: {lane_parked_blocks}"
        print("  PASS  [T_P5b] reversibility: parked_lanes=[] → lane-1 drafts normally")

    # ── T_S1: reason_code="SUPPLIER", otherwise fully valid lane-3 record
    #          → drafted=0, blocked=1, reason="reason_supplier" ──────────────
    with tempfile.TemporaryDirectory() as tmp:
        supplier_contact = {
            "domain": "thunderbike.de",
            "organisation": "Thunderbike",
            "lane": 3,
            "outreach_type": "link_building",
            "market": "multi",
            "language": "en",
            "proactive": True,
            "reason_code": "SUPPLIER",
            "named_contacts": [{
                "name": None, "email": "info@thunderbike.de", "needs_lookup": False,
                "role": None, "email_candidate": None, "candidate_source": None,
                "candidate_status": "confirmed",
            }],
            "action_url": None,
            "note": "Reason: SUPPLIER. Angle: German custom Harley parts manufacturer.",
            "personalization_hook": "noticed Thunderbike's new custom parts catalogue",
        }
        cp, sp, ap, tp, lp = make_files(
            tmp, [supplier_contact], _GOOD_SENDER, _GOOD_ARTEFACTS_L3, _LANE3_TEMPLATES,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 0, f"T_S1 drafted={result['drafted']}"
        assert result["blocked"] == 1, f"T_S1 blocked={result['blocked']}"
        assert result["blocks"][0]["reason"] == "reason_supplier", \
            f"T_S1 reason={result['blocks'][0]['reason']}"
        assert result["blocks"][0]["domain"] == "thunderbike.de", \
            f"T_S1 domain={result['blocks'][0]['domain']}"
        print("  PASS  [T_S1] reason_code='SUPPLIER' → drafted=0, blocked=1, reason=reason_supplier")

    # ── T_S2: reason_code="REL-EDITORIAL" → drafts normally (no over-match) ──
    with tempfile.TemporaryDirectory() as tmp:
        editorial_contact = dict(lane3_contact)
        editorial_contact["reason_code"] = "REL-EDITORIAL"
        cp, sp, ap, tp, lp = make_files(
            tmp, [editorial_contact], _GOOD_SENDER, _GOOD_ARTEFACTS_L3, _LANE3_TEMPLATES,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, f"T_S2 drafted={result['drafted']}"
        reasons = [b["reason"] for b in result["blocks"]]
        assert "reason_supplier" not in reasons, f"T_S2 unexpected block: {reasons}"
        print("  PASS  [T_S2] reason_code='REL-EDITORIAL' → drafts normally, no over-match")

    # ── T_S3: mixed batch — one SUPPLIER, one REL-EDITORIAL
    #          → drafted=1, blocked=1, and the block is the SUPPLIER domain ──
    with tempfile.TemporaryDirectory() as tmp:
        supplier2 = dict(supplier_contact)
        supplier2["domain"] = "thunderbike.com"
        editorial2 = dict(lane3_contact)
        editorial2["domain"] = "hdmag.com"
        cp, sp, ap, tp, lp = make_files(
            tmp, [supplier2, editorial2], _GOOD_SENDER, _GOOD_ARTEFACTS_L3, _LANE3_TEMPLATES,
        )
        result = run_draft(cp, sp, ap, tp, lp)
        assert result["drafted"] == 1, f"T_S3 drafted={result['drafted']}"
        assert result["blocked"] == 1, f"T_S3 blocked={result['blocked']}"
        assert result["drafts"][0]["domain"] == "hdmag.com", \
            f"T_S3 drafted domain={result['drafts'][0]['domain']}"
        assert result["blocks"][0]["domain"] == "thunderbike.com", \
            f"T_S3 blocked domain={result['blocks'][0]['domain']}"
        assert result["blocks"][0]["reason"] == "reason_supplier", \
            f"T_S3 reason={result['blocks'][0]['reason']}"
        print("  PASS  [T_S3] mixed batch: SUPPLIER skipped (named), REL-EDITORIAL drafts")

    print("\nAll s4 tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Stage 4: draft — generate Lane 1 supplier email drafts."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_draft = sub.add_parser("draft", help="Generate drafts from contacts.json")
    p_draft.add_argument("--contacts",  help="path to contacts.json")
    p_draft.add_argument("--sender",    help="path to sender.json")
    p_draft.add_argument("--artefacts", help="path to artefacts.json")
    p_draft.add_argument("--templates", help="path to templates.json")

    args = parser.parse_args()

    if args.cmd == "draft":
        print("s4 draft — generating Lane 1 supplier drafts…")
        result = run_draft(
            contacts_path=args.contacts,
            sender_path=args.sender,
            artefacts_path=args.artefacts,
            templates_path=args.templates,
        )
        print(f"  total L1 records : {result['total']}")
        print(f"  drafted          : {result['drafted']}")
        print(f"  blocked          : {result['blocked']}")
        print(f"  skipped          : {result['skipped']}")
        if result["blocks"]:
            print("  blocks:")
            for b in result["blocks"]:
                print(f"    {b['domain'] or '(null)':<25}  {b['reason']}")
        if result["drafts"]:
            print("  drafts:")
            for d in result["drafts"]:
                print(f"    {d['domain']:<25}  [{d['language']}] {d['subject']!r}")
                print(f"      words={d['word_count']}  personalisation={d['personalisation_count']}")


if __name__ == "__main__":
    main()
