"""Stage 4 (validate) — independent re-check gate for Lane 1 drafts.

PUBLIC API
----------
run_validate(drafts: list[dict]) -> dict

Checks every draft dict produced by s4_draft against the same non-negotiables,
independently re-derived here (intentional redundancy — do NOT import from s4_draft):

  1. All required fields present and non-None
  2. cadence_stage == 0
  3. draft_status == "needs-review"
  4. body word count in [_BODY_MIN, _BODY_MAX]  (recomputed from body text)
  5. stored word_count matches recomputed word count exactly
  6. personalisation_count >= 2
  7. personalization_hook non-empty and present verbatim in body
  8. subject length in [_SUBJECT_MIN, _SUBJECT_MAX]
  9. subject contains no banned word (word-boundary match)
  10. body contains no <img> tag (case-insensitive)

ALL violations in a draft are collected before deciding its fate.
A draft with ANY violation is blocked and excluded from valid_drafts.
Non-dict elements in the input list are blocked with "malformed_draft_entry".

Returns {total, valid, blocked, blocks[], valid_drafts[]}.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List

# Invariant: no L1 draft reaches validate because s3 promote() and s4_draft both refuse parked lanes.

# ── constants (duplicated verbatim from s4_draft — intentional, not an import) ─

_BANNED_SUBJECT_WORDS = frozenset({
    "collaboration", "link", "insertion", "resources",
    "guest", "enhance", "backlink",
})

_SUBJECT_MIN = 20
_SUBJECT_MAX = 78

# Per-lane body word-count bounds.  Lane 3 editorial pitches must be ≤65 words.
_BODY_LIMITS: dict = {
    1: (45, 135),
    3: (25,  65),
}
_BODY_LIMIT_DEFAULT = (45, 135)

_REQUIRED_FIELDS = frozenset({
    "domain", "organisation", "lane", "contact_email",
    "subject", "body", "language",
    "word_count", "personalisation_count", "cadence_stage", "draft_status",
    "personalization_hook",
})


# ── helpers ───────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len([t for t in text.split() if t])


def _has_banned_word(text: str) -> bool:
    lower = text.lower()
    for word in _BANNED_SUBJECT_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", lower):
            return True
    return False


# ── core check ────────────────────────────────────────────────────────────────

def _check_draft(draft: dict) -> List[str]:
    """Return all violation strings for one draft dict; empty list means valid."""
    violations: List[str] = []

    # Check 1: required fields present and non-None
    for field in sorted(_REQUIRED_FIELDS):
        if field not in draft or draft[field] is None:
            violations.append(f"missing_field:{field}")

    # Cannot safely evaluate content checks if critical fields are absent.
    if violations:
        return violations

    # Check 2: cadence_stage must be 0
    if draft["cadence_stage"] != 0:
        violations.append(f"invalid_cadence_stage:{draft['cadence_stage']}")

    # Check 3: draft_status must be "needs-review"
    if draft["draft_status"] != "needs-review":
        violations.append(f"invalid_draft_status:{draft['draft_status']!r}")

    # Check 4 & 5: body word count — recomputed, not trusted from stored value;
    # also cross-check stored word_count for mismatch.
    lane = draft.get("lane")
    body_min, body_max = _BODY_LIMITS.get(lane, _BODY_LIMIT_DEFAULT)
    wc = _word_count(draft["body"])
    if not (body_min <= wc <= body_max):
        violations.append(f"body_word_count:{wc}_not_in_{body_min}-{body_max}(lane{lane})")
    if draft["word_count"] != wc:
        violations.append(
            f"word_count_mismatch:{draft['word_count']}_vs_{wc}"
        )

    # Check 6: personalisation_count >= 2
    pc = draft["personalisation_count"]
    if pc < 2:
        violations.append(f"insufficient_personalisation:{pc}")

    # Check 7: personalization_hook must be non-empty and present verbatim in body
    hook = draft.get("personalization_hook") or ""
    if not hook or hook not in draft["body"]:
        violations.append("personalization_hook_missing")

    # Check 8 & 9: subject length and banned-word scan (word-boundary regex)
    subj = draft["subject"]
    subj_len = len(subj)
    if not (_SUBJECT_MIN <= subj_len <= _SUBJECT_MAX):
        violations.append(f"subject_length:{subj_len}_not_in_{_SUBJECT_MIN}-{_SUBJECT_MAX}")
    if _has_banned_word(subj):
        violations.append(f"subject_banned_word:{subj!r}")

    # Check 10: no <img> tag in body (covers all tracking pixels — templates use none)
    if "<img" in draft["body"].lower():
        violations.append("body_contains_img_tag")

    return violations


# ── public API ────────────────────────────────────────────────────────────────

def run_validate(drafts) -> dict:
    """Independently validate drafts produced by s4_draft.

    Accepts a list of draft dicts (or any iterable).
    Non-dict elements are blocked as malformed_draft_entry.

    Returns {total, valid, blocked, blocks[], valid_drafts[]}.
    Drafts that pass all checks appear in valid_drafts unchanged.
    Drafts with any violation appear in blocks[] with a violations list.
    """
    out: dict = dict(total=0, valid=0, blocked=0, blocks=[], valid_drafts=[])

    for entry in drafts:
        out["total"] += 1

        # Malformed input guard — accepts hand-edited JSON
        if not isinstance(entry, dict):
            out["blocked"] += 1
            out["blocks"].append({
                "domain":       None,
                "organisation": None,
                "lane":         None,
                "violations":   ["malformed_draft_entry"],
            })
            continue

        violations = _check_draft(entry)
        if violations:
            out["blocked"] += 1
            out["blocks"].append({
                "domain":       entry.get("domain"),
                "organisation": entry.get("organisation"),
                "lane":         entry.get("lane"),
                "violations":   violations,
            })
        else:
            out["valid"] += 1
            out["valid_drafts"].append(entry)

    return out


# ── tests ─────────────────────────────────────────────────────────────────────

def _run_tests() -> None:
    print("Running s4_validate tests...")

    # Baseline valid draft — all non-negotiables satisfied.
    # word_count must match _word_count(body) exactly.
    _HOOK = "noticed Parts Europe just opened their UK stockist application portal"
    _BODY_TEXT = (
        "Dear Parts Europe team,\n\n"
        "I'm Haleema Naz, Owner at Legendary Parts — a European specialist in "
        "Harley-Davidson OEM and aftermarket parts, shipping to the UK, France, and Germany.\n\n"
        f"{_HOOK}\n\n"
        "We'd like to apply to join your authorised stockist programme. "
        "You can find our application via your dealer page at partseurope.eu/dealers/.\n\n"
        "Our company profile and full catalogue are available here: "
        "https://drive.google.com/file/d/abc123/view\n\n"
        "Happy to answer any questions about our range or order volumes.\n\n"
        "Best regards,\nHaleema Naz\nOwner, Legendary Parts\n"
        "haleema@legendary-parts.com\nhttps://linkedin.com/in/haleema"
    )
    _COMPUTED_WC = _word_count(_BODY_TEXT)

    _GOOD_DRAFT = {
        "domain":                "partseurope.eu",
        "organisation":          "Parts Europe",
        "lane":                  1,
        "contact_name":          "Parts Europe Team",
        "contact_email":         "dealers@partseurope.eu",
        "subject":               "Parts Europe: dealer application, Legendary Parts",
        "body":                  _BODY_TEXT,
        "language":              "en",
        "language_defaulted":    False,
        "word_count":            _COMPUTED_WC,
        "personalisation_count": 2,
        "personalization_hook":  _HOOK,
        "cadence_stage":         0,
        "draft_status":          "needs-review",
    }

    def mutate(base, **overrides):
        d = dict(base)
        d.update(overrides)
        return d

    # ── T1: valid draft passes ─────────────────────────────────────────────────
    result = run_validate([_GOOD_DRAFT])
    assert result["valid"]   == 1,           f"T1 valid={result['valid']}"
    assert result["blocked"] == 0,           f"T1 blocked={result['blocked']}"
    assert result["valid_drafts"][0] is _GOOD_DRAFT, "T1 draft identity"
    print(f"  PASS  [T1]  valid draft (wc={_COMPUTED_WC}) → valid=1, blocked=0")

    # ── T2: body ≤5 words → body_word_count ───────────────────────────────────
    short_body = "Dear team, Hi."
    assert _word_count(short_body) <= 5
    result = run_validate([mutate(_GOOD_DRAFT, body=short_body,
                                  word_count=_word_count(short_body))])
    assert result["blocked"] == 1, f"T2 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("body_word_count" in v for v in viols), f"T2 violations={viols}"
    print(f"  PASS  [T2]  body ≤5 words (wc={_word_count(short_body)}) → body_word_count")

    # ── T3: body 200 words → body_word_count ──────────────────────────────────
    long_body = " ".join(["word"] * 200)
    result = run_validate([mutate(_GOOD_DRAFT, body=long_body,
                                  word_count=_word_count(long_body))])
    assert result["blocked"] == 1, f"T3 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("body_word_count" in v for v in viols), f"T3 violations={viols}"
    print("  PASS  [T3]  body 200 words → body_word_count violation")

    # ── T4: personalisation_count=1 → insufficient_personalisation ────────────
    result = run_validate([mutate(_GOOD_DRAFT, personalisation_count=1)])
    assert result["blocked"] == 1, f"T4 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("insufficient_personalisation" in v for v in viols), f"T4 violations={viols}"
    print("  PASS  [T4]  personalisation_count=1 → insufficient_personalisation")

    # ── T5: subject 11 chars → subject_length ─────────────────────────────────
    short_subj = "Hi Parts EU"
    assert len(short_subj) < _SUBJECT_MIN
    result = run_validate([mutate(_GOOD_DRAFT, subject=short_subj)])
    assert result["blocked"] == 1, f"T5 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("subject_length" in v for v in viols), f"T5 violations={viols}"
    print(f"  PASS  [T5]  subject {len(short_subj)} chars → subject_length")

    # ── T6: subject 90 chars → subject_length ─────────────────────────────────
    long_subj = "A" * 90
    assert len(long_subj) > _SUBJECT_MAX
    result = run_validate([mutate(_GOOD_DRAFT, subject=long_subj)])
    assert result["blocked"] == 1, f"T6 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("subject_length" in v for v in viols), f"T6 violations={viols}"
    print(f"  PASS  [T6]  subject {len(long_subj)} chars → subject_length")

    # ── T7: subject contains "backlink" → subject_banned_word (word boundary) ─
    banned_subj = "Backlink opportunity for Parts Europe — Legendary Parts"
    assert _SUBJECT_MIN <= len(banned_subj) <= _SUBJECT_MAX
    result = run_validate([mutate(_GOOD_DRAFT, subject=banned_subj)])
    assert result["blocked"] == 1, f"T7 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("subject_banned_word" in v for v in viols), f"T7 violations={viols}"
    # Confirm word-boundary: "collaborative" should NOT trigger "collaboration"
    safe_subj = "A collaborative approach at Parts Europe, Legendary Parts HQ"
    assert _SUBJECT_MIN <= len(safe_subj) <= _SUBJECT_MAX
    r2 = run_validate([mutate(_GOOD_DRAFT, subject=safe_subj)])
    assert r2["valid"] == 1, (
        f"T7 word-boundary FAIL: 'collaborative' triggered banned 'collaboration': "
        f"{r2['blocks']}"
    )
    print("  PASS  [T7]  'backlink' → subject_banned_word; 'collaborative' ≠ 'collaboration'")

    # ── T8: body contains <img ...> → body_contains_img_tag ───────────────────
    img_body = _BODY_TEXT + '\n<img src="x.png" width="1" height="1">'
    result = run_validate([mutate(_GOOD_DRAFT, body=img_body,
                                  word_count=_word_count(img_body))])
    assert result["blocked"] == 1, f"T8 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert "body_contains_img_tag" in viols, f"T8 violations={viols}"
    print("  PASS  [T8]  body has <img> → body_contains_img_tag")

    # ── T9: cadence_stage=1 → invalid_cadence_stage ───────────────────────────
    result = run_validate([mutate(_GOOD_DRAFT, cadence_stage=1)])
    assert result["blocked"] == 1, f"T9 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("invalid_cadence_stage" in v for v in viols), f"T9 violations={viols}"
    print("  PASS  [T9]  cadence_stage=1 → invalid_cadence_stage")

    # ── T10: draft_status="approved" → invalid_draft_status ───────────────────
    result = run_validate([mutate(_GOOD_DRAFT, draft_status="approved")])
    assert result["blocked"] == 1, f"T10 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("invalid_draft_status" in v for v in viols), f"T10 violations={viols}"
    print("  PASS  [T10] draft_status='approved' → invalid_draft_status")

    # ── T11: stored word_count=70 but body is 200 words → word_count_mismatch ─
    body_200 = " ".join(["word"] * 200)
    result = run_validate([mutate(_GOOD_DRAFT, body=body_200, word_count=70)])
    assert result["blocked"] == 1, f"T11 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert any("word_count_mismatch" in v for v in viols), f"T11 violations={viols}"
    print("  PASS  [T11] stored wc=70 but body is 200 words → word_count_mismatch")

    # ── T12: hook absent from body → personalization_hook_missing ────────────────
    body_no_hook = _BODY_TEXT.replace(_HOOK, "We saw your website recently")
    result = run_validate([mutate(_GOOD_DRAFT, body=body_no_hook,
                                  word_count=_word_count(body_no_hook))])
    assert result["blocked"] == 1, f"T12 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert "personalization_hook_missing" in viols, f"T12 violations={viols}"
    print("  PASS  [T12] hook absent from body → personalization_hook_missing")

    # ── T13: 5 simultaneous violations → all reported in one block ────────────
    multi_bad = mutate(
        _GOOD_DRAFT,
        cadence_stage=2,                   # invalid_cadence_stage
        draft_status="sent",               # invalid_draft_status
        personalisation_count=0,           # insufficient_personalisation
        subject="Hi",                      # subject_length (2 chars)
        body="No hook present here.",      # body_word_count + personalization_hook_missing
        word_count=4,
    )
    result = run_validate([multi_bad])
    assert result["blocked"] == 1, f"T13 blocked={result['blocked']}"
    viols = result["blocks"][0]["violations"]
    assert len(viols) >= 5, f"T13 expected >=5 violations, got {len(viols)}: {viols}"
    assert any("invalid_cadence_stage"        in v for v in viols), "T13 cadence"
    assert any("invalid_draft_status"         in v for v in viols), "T13 status"
    assert any("insufficient_personalisation" in v for v in viols), "T13 personalisation"
    assert any("subject_length"               in v for v in viols), "T13 subject_length"
    assert "personalization_hook_missing"        in viols,          "T13 hook_missing"
    print(f"  PASS  [T13] 5-violation draft → {len(viols)} violations all reported")

    # ── T14: 2 good + 1 bad → valid=2, blocked=1, correct domain split ────────
    bad_draft = mutate(_GOOD_DRAFT, domain="bad.eu", cadence_stage=1)
    _HOOK2 = "noticed Good2 recently extended their stockist network across Europe"
    _BODY2 = _BODY_TEXT.replace(_HOOK, _HOOK2).replace("Parts Europe", "Good2")
    good_draft2 = mutate(
        _GOOD_DRAFT,
        domain="good2.eu",
        organisation="Good2",
        contact_email="info@good2.eu",
        body=_BODY2,
        word_count=_word_count(_BODY2),
        personalization_hook=_HOOK2,
    )
    result = run_validate([_GOOD_DRAFT, bad_draft, good_draft2])
    assert result["total"]   == 3, f"T14 total={result['total']}"
    assert result["valid"]   == 2, f"T14 valid={result['valid']}"
    assert result["blocked"] == 1, f"T14 blocked={result['blocked']}"
    valid_domains  = {d["domain"] for d in result["valid_drafts"]}
    blocked_domain = result["blocks"][0]["domain"]
    assert "partseurope.eu" in valid_domains,  f"T14 valid_domains={valid_domains}"
    assert "good2.eu"       in valid_domains,  f"T14 valid_domains={valid_domains}"
    assert blocked_domain   == "bad.eu",       f"T14 blocked_domain={blocked_domain}"
    print("  PASS  [T14] 2 good + 1 bad → valid=2, blocked=1, correct split")

    # ── PLUS: malformed entry (non-dict) → malformed_draft_entry, no crash ────
    result = run_validate([_GOOD_DRAFT, "not-a-dict", 42])
    assert result["total"]   == 3, f"PLUS total={result['total']}"
    assert result["valid"]   == 1, f"PLUS valid={result['valid']}"
    assert result["blocked"] == 2, f"PLUS blocked={result['blocked']}"
    for b in result["blocks"]:
        assert b["violations"] == ["malformed_draft_entry"], \
            f"PLUS unexpected violations={b['violations']}"
    print("  PASS  [PLUS] non-dict entries → malformed_draft_entry, no crash")

    # ── T15: lane-3 draft within 25-65 words → valid ─────────────────────────
    _HOOK_L3 = "I read your M8 reliability piece last month"
    _BODY_L3 = (
        "Hi Fixture Editor,\n\n"
        + _HOOK_L3 + "\n\n"
        "Legendary Parts maps H-D OEM fitment patterns across the UK, French, "
        "and German markets. Happy to share a data cut, a mechanic quote, or a "
        "short expert piece.\n\n"
        "Profile and catalogue: https://drive.google.com/placeholder-lane3-artifact\n\n"
        "Haleema Naz\nSEO Outreach Lead, Legendary Parts\n"
        "haleema@legendary-parts.com\nhttps://linkedin.com/in/haleema"
    )
    _WC_L3 = _word_count(_BODY_L3)
    assert 25 <= _WC_L3 <= 65, f"T15 setup: body is {_WC_L3} words, must be 25-65"
    _GOOD_DRAFT_L3 = mutate(
        _GOOD_DRAFT,
        lane=3,
        subject="H-D fitment data for Fixture Editorial Co — Legendary Parts",
        body=_BODY_L3,
        word_count=_WC_L3,
        personalisation_count=2,
        personalization_hook=_HOOK_L3,
    )
    result = run_validate([_GOOD_DRAFT_L3])
    assert result["valid"]   == 1, f"T15 valid={result['valid']}, blocks={result['blocks']}"
    assert result["blocked"] == 0, f"T15 blocked={result['blocked']}"
    print(f"  PASS  [T15] lane-3 draft ({_WC_L3} words, limit 25-65) → valid=1")

    # ── T16: lane-3 body >65 words → body_word_count(lane3);
    #         same body under lane 1 → valid (proves limits are per-lane) ──────
    _EXTRA = (
        " We cover thousands of H-D fitment cases across the UK, "
        "France, and Germany each quarter."
    )
    _BODY_L3_LONG = _BODY_L3 + _EXTRA
    _WC_L3_LONG   = _word_count(_BODY_L3_LONG)
    assert _WC_L3_LONG > 65,  f"T16 setup: long body only {_WC_L3_LONG} words — extend it"
    assert _WC_L3_LONG <= 135, f"T16 setup: long body {_WC_L3_LONG} also exceeds lane-1 max"

    # Lane 3 must fail
    result_l3 = run_validate([
        mutate(_GOOD_DRAFT_L3, body=_BODY_L3_LONG, word_count=_WC_L3_LONG)
    ])
    assert result_l3["blocked"] == 1, f"T16 lane-3 blocked={result_l3['blocked']}"
    viols_l3 = result_l3["blocks"][0]["violations"]
    assert any("body_word_count" in v and "lane3" in v for v in viols_l3), \
        f"T16 lane-3 violations missing body_word_count(lane3): {viols_l3}"

    # Same body under lane 1 must pass (67 words is within lane-1's 45-135)
    result_l1 = run_validate([
        mutate(_GOOD_DRAFT,
               body=_BODY_L3_LONG,
               word_count=_WC_L3_LONG,
               personalization_hook=_HOOK_L3,
               personalisation_count=2)
    ])
    assert result_l1["valid"] == 1, \
        f"T16 lane-1 valid={result_l1['valid']}, blocks={result_l1['blocks']}"
    print(
        f"  PASS  [T16] lane-3 {_WC_L3_LONG}-word body → body_word_count(lane3); "
        f"same body lane-1 → valid"
    )

    print("\nAll s4_validate tests passed.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    if "--test" in sys.argv:
        _run_tests()
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="Stage 4 (validate): independently re-check Lane 1 drafts."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser(
        "validate",
        help="Validate a JSON file of drafts from s4_draft.",
    )
    p_val.add_argument(
        "--drafts-file",
        help="Path to JSON file containing {drafts:[...]} or a bare array. "
             "Reads from stdin if omitted.",
    )

    args = parser.parse_args()

    if args.cmd == "validate":
        if args.drafts_file:
            with open(args.drafts_file, encoding="utf-8") as f:
                raw = json.load(f)
        else:
            raw = json.load(sys.stdin)

        drafts = raw.get("drafts", raw) if isinstance(raw, dict) else raw

        print("s4_validate — checking drafts…")
        result = run_validate(drafts)
        print(f"  total   : {result['total']}")
        print(f"  valid   : {result['valid']}")
        print(f"  blocked : {result['blocked']}")

        if result["blocks"]:
            print("  blocked drafts:")
            for b in result["blocks"]:
                print(f"    {b['domain'] or '(null)':<28}  violations:")
                for v in b["violations"]:
                    print(f"      - {v}")

        if result["valid_drafts"]:
            print("  valid drafts:")
            for d in result["valid_drafts"]:
                print(f"    {d['domain']:<28}  [{d['language']}] {d['subject']!r}")
                print(f"      wc={d['word_count']}  personalisation={d['personalisation_count']}")


if __name__ == "__main__":
    main()
