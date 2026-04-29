# Stage 9 Redesign — Handoff Document
**Date:** 2026-04-29  
**Session:** Stage 9 redesign execution + V-Rod end-to-end test  
**Status:** Stage 9 functionally complete. Two outstanding items before production use.

---

## 1. What Was Completed Today

### Stage 9 Redesign (Tasks 0–11)

The entire Stage 9 comment-resolution pipeline was redesigned to remove the Anthropic Python SDK and replace all model calls with `claude -p` subprocess invocations. The project now runs entirely inside a Claude Pro subscription with no API key or SDK dependency.

| Task | Commit | Description |
|------|--------|-------------|
| 0 | `a1283fd` | `chore: initial commit` — git repo initialised; baseline of existing codebase committed |
| 1 | `cc00286` | `feat(stage9): delete SDK-based comment_resolver_service and its tests` — removed `app/services/comment_resolver_service.py` and `tests/test_comment_resolver_service.py` (480 lines deleted) |
| 2 | `4881f98` | `test(stage9): add failing tests for claude_code_resolver` — 125-line test file written red-first |
| 3 | `d6f1d91` | `feat(stage9): implement claude_code_resolver subprocess wrapper` — `app/services/claude_code_resolver.py`; wraps `claude -p` calls, validates JSON schema, handles timeout/exit-code failures |
| 4 | `530315b` | `test(stage9): add failing tests for comment_resolution and trello_gate drive-resolve` — 397 lines of failing tests across two files |
| 5 | `b955c9c` | `feat(stage9): add TrelloClient.uncheck_all_checklist_items` — required for Drive-resolve failure rollback path |
| 6 | `e46c4e3` | `feat(stage9): implement comment_resolution with Drive-resolve failure handling` — `app/services/comment_resolution.py`; orchestrates resolve loop, routes by confidence, detects Drive-resolve failures |
| 7 | `af86c4e` | `feat(stage9): rewrite anthropic_client to use claude -p; remove SDK dependency` — `app/services/anthropic_client.py` slimmed from 150 → 45 lines |
| 8 | `3e373d4` | `feat(stage9): trello_gate calls resolve_all_comments directly; untick + warn on Drive-resolve failure` — `trello_gate.py` wired to new pipeline; Drive-resolve failure triggers checklist untick + card reset |
| 9 | `50720af` | `feat(stage9): rewrite comment_resolver.py CLI to use comment_resolution module` — CLI entry point updated |
| 10 | `555b2ba` | `chore(stage9): remove anthropic>=0.40; update .env.example for claude -p` — requirements cleaned |
| 11 | `4cee815` | `chore(stage9): automated acceptance verification passed` — all tests green at end of plan |

### Post-Plan Bugfix (discovered during V-Rod test)

| Commit | Description |
|--------|-------------|
| `276db55` | `fix(docs_client): include content field in resolve_comment PATCH body` — Drive v3 `comments.update` returns HTTP 400 "Comment content is required" when the body only contains `resolved: True`. Fix: fetch existing comment via `comments.get(fields="content")` first, then include `content` alongside `resolved: True` in the PATCH body. New test file `tests/test_docs_client.py` (3 tests) added red-first. |

### Final State

- **Total commits:** 13 (Tasks 0–11 + Drive-resolve bugfix + handoff docs)
- **Tests passing:** 113 / 113
- **Test command:** `python3 -m pytest tests/ --import-mode=importlib -q` (run from project root)
- **Stage 9 redesign:** Functionally complete and confirmed working for short single-sentence anchors

---

## 2. V-Rod Test Results

**Doc:** "Harley-Davidson VRSC V-Rod: Complete Buyer's and Owner's Guide"  
**Doc ID:** `10qYN4k1nolKG3sgmQ5i2Gmx-AG6zyxQuvUQsAFKrqJ4`  
**Card ID:** `69f0ad3f07163694906a201e`

### Run 1 (before Drive-resolve fix) — ~15:17–15:19

- Both checkboxes ticked (0/2 → 2/2 between Run 0 poll and Run 1)
- 2 comments found; both edits applied successfully to the doc:
  - `'A used Harley V-Rod usually sells for ab...'` → `'Used Harley V-Rod prices vary significan...'` at index 7522
  - `'aluminum'` → `'aluminium'` at index 300
- **Both Drive-resolves failed:** `HttpError 400 "Comment content is required"` — PATCH body only had `{"resolved": True}`
- **System rolled back correctly:**
  - Both checklist items unchecked on Trello card
  - Card moved back to "Blog drafts"
  - DB reset to `pending`
  - "Translation paused" Trello comment posted
- **Conclusion:** Safety net worked as designed; text edits were applied but comments were not resolved.

### Run 2 (after Drive-resolve fix) — ~16:01–16:02

3 comments found (2 originals + 1 leftover from Run 1 whose anchor was already replaced).

| # | Comment ID | Type | Result |
|---|-----------|------|--------|
| 1 | `AAAB5BTkn4s` | Interpretive, multi-sentence paragraph anchor | ❌ "Text not found" — anchor mismatch (see §3) |
| 2 | `AAAB5BTkn4o` | Directive, short single-sentence anchor | ✅ Applied + Drive-resolved successfully |
| 3 | `AAAB5BQHkpo` | Leftover from Run 1 | ❌ "Text not found" — expected; original text replaced in Run 1 |

- **No Drive-resolve failures.** Fix confirmed working.
- **Card not rolled back.** DB status: `handed_off`. Card location: "Translating".
- **Translation triggered** but exited code 1: `config/translation_guidelines.md` not found (separate blocker, unrelated to Stage 9).

Full log saved to: `STAGE9_LAST_POLL_LOG.txt`

---

## 3. Known Limitation Discovered

**Multi-sentence / paragraph anchors fail more often than single-sentence anchors.**

In Run 2, Comment 1 (`AAAB5BTkn4s`) failed with "Text not found" even though the user confirmed the paragraph had NOT been changed by any prior edit. The anchor_text returned by `claude -p` was:

```
'The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog.'
```

This string did not appear verbatim in the document. The paragraph itself was present and unchanged — the failure was a mismatch between what `claude -p` returned as `anchor_text` and what is literally in the doc. Suspected causes: subtle whitespace differences, a missing or extra sentence, punctuation divergence, or light paraphrasing by the model.

**This is not a regression from today's work.** It is a pre-existing design limitation that was first exposed by realistic multi-comment testing. Single-sentence directives (Comment 2) work correctly.

---

## 4. Outstanding Items for Next Session

### Priority 1 — Diagnose Comment 1 anchor failure

1. Open the V-Rod doc and find the paragraph near the intro containing "unlike anything else in the Milwaukee catalog" (or similar wording).
2. Copy the exact literal text from the doc.
3. Compare to the anchor_text in `STAGE9_LAST_POLL_LOG.txt` (`'The Harley-Davidson VRSC V-Rod is unlike anything else in the Milwaukee catalog.'`).
4. Identify the exact divergence (missing word, different punctuation, different capitalisation, etc.).

This tells you whether the fix needs to target the prompt (ask for verbatim anchors) or the matcher (tolerate minor differences).

### Priority 2 — Fix long-anchor matching

Options to evaluate (pick one approach):

| Option | Where | Trade-off |
|--------|-------|-----------|
| **Whitespace-tolerant matching** in `apply_text_replacement` | `docs_client.py` | Handles normalisation differences; may produce false matches on repeated phrases |
| **Prompt tightening** — require `claude -p` to return the exact quoted text as `anchor_text` | `claude_code_resolver.py` prompt | Fixes root cause; depends on model compliance |
| **Post-validation** — reject resolver output where `anchor_text` is not findable in the doc before writing edits | `comment_resolution.py` | Safe but surfaces failures earlier rather than fixing them |
| **Route long anchors differently** — use `noop` or `flag` for anchors longer than N words | `comment_resolution.py` | Avoids the problem; doesn't solve it |

Recommended starting point: prompt tightening + whitespace-normalised fallback matcher. Write failing tests first.

### Priority 3 — Translation workflow blocker

`translation_workflow.py` requires `config/translation_guidelines.md` (a 298-line file that defines translation rules). It does not exist in the current working tree.

- Check if it exists elsewhere on this machine: `find /Users/mac/Documents -name "translation_guidelines.md" 2>/dev/null`
- If not found, recreate from memory or from a prior session's context.
- This is **unrelated to Stage 9** — Stage 9 comment resolution completes successfully before translation is invoked.

### Priority 4 — Manual cleanup in Drive UI

Comment `AAAB5BQHkpo` is still open in the V-Rod doc. Its anchor text (`'A used Harley V-Rod usually sells for about €10,500...'`) was replaced by Run 1, so the system can never auto-resolve it. **Manually mark it as resolved in the Google Doc UI.**

---

## 5. Current State of V-Rod Doc and Trello Card

### Google Doc

| Comment ID | Status | Notes |
|-----------|--------|-------|
| `AAAB5BTkn4s` | Open | Paragraph unchanged; anchor mismatch prevented resolution — needs next-session fix |
| `AAAB5BTkn4o` | Resolved ✅ | Edit applied (`found on 2008` → `is for 2008`) and Drive-resolved |
| `AAAB5BQHkpo` | Open | Leftover from Run 1; needs manual Drive UI resolution |

### Trello Card

- **Card ID:** `69f0ad3f07163694906a201e`
- **Current list:** Translating
- **Checklist state:** Both items ticked (they were not unchecked after Run 2 — no Drive-resolve failures means no rollback)
- **DB status:** `handed_off` (set 2026-04-28T12:51:15)

---

## 6. Files Modified Today

### Modified (existing files changed)

| File | What changed |
|------|-------------|
| `app/services/anthropic_client.py` | Rewrote to use `claude -p` subprocess; removed Anthropic SDK dependency; slimmed ~105 lines |
| `app/services/docs_client.py` | Fixed `resolve_comment`: now fetches existing comment content before PATCH; added `comments().get()` call |
| `app/services/trello_client.py` | Added `uncheck_all_checklist_items()` method for Drive-resolve failure rollback |
| `comment_resolver.py` | Rewrote CLI to delegate to `comment_resolution.resolve_all_comments()` |
| `trello_gate.py` | Wired `poll_once` to call `resolve_all_comments` directly; added Drive-resolve failure detection, checklist untick, card reset, and summary Trello comment |
| `requirements.txt` | Removed `anthropic>=0.40` |
| `.env.example` | Updated for `claude -p` configuration (removed SDK vars, added `CLAUDE_MODEL`) |

### Added (new files)

| File | What it does |
|------|-------------|
| `app/services/claude_code_resolver.py` | Subprocess wrapper: invokes `claude -p` with a structured prompt, parses JSON response, validates schema (`action`, `anchor_text`, `replacement_text`, `confidence`, `rationale`), returns `None` on any failure |
| `app/services/comment_resolution.py` | Orchestration layer: loops over unresolved comments, calls `claude_code_resolver`, routes by confidence (high/medium → apply, low → flag + apply), calls `apply_text_replacement`, calls `resolve_comment`, handles Drive-resolve failures, returns structured summary dict |
| `tests/test_claude_code_resolver.py` | 6 tests: valid JSON in markdown fences, valid JSON bare, malformed JSON, timeout, non-zero exit, schema mismatch |
| `tests/test_comment_resolution.py` | 24 tests: empty doc, high/medium/low confidence routing, noop action, apply failures, Drive-resolve failures, loop continuation, format_stage9_summary |
| `tests/test_docs_client.py` | 3 tests: PATCH body includes `content` + `resolved`, `get` called before `update`, correct `fileId`/`commentId` targeting |
| `tests/test_trello_gate_stage9.py` | 5 tests: Drive-resolve failure blocks translation, resets DB to pending, unticks checklist, normal flow triggers translation, partial failure (non-Drive-resolve) does not block |

### Deleted (removed files)

| File | Reason |
|------|--------|
| `app/services/comment_resolver_service.py` | Replaced by `claude_code_resolver.py` + `comment_resolution.py` |
| `tests/test_comment_resolver_service.py` | Tests for deleted service |

---

## 7. Git Log

```
276db55 fix(docs_client): include content field in resolve_comment PATCH body
4cee815 chore(stage9): automated acceptance verification passed
555b2ba chore(stage9): remove anthropic>=0.40; update .env.example for claude -p
50720af feat(stage9): rewrite comment_resolver.py CLI to use comment_resolution module
3e373d4 feat(stage9): trello_gate calls resolve_all_comments directly; untick + warn on Drive-resolve failure
af86c4e feat(stage9): rewrite anthropic_client to use claude -p; remove SDK dependency
e46c4e3 feat(stage9): implement comment_resolution with Drive-resolve failure handling
b955c9c feat(stage9): add TrelloClient.uncheck_all_checklist_items
530315b test(stage9): add failing tests for comment_resolution and trello_gate drive-resolve
d6f1d91 feat(stage9): implement claude_code_resolver subprocess wrapper
4881f98 test(stage9): add failing tests for claude_code_resolver
cc00286 feat(stage9): delete SDK-based comment_resolver_service and its tests
a1283fd chore: initial commit — baseline before Stage 9 redesign
```

---

## 8. How to Resume Next Session

```bash
cd "/Users/mac/Documents/SEO Agent Workflow"
git log --oneline          # verify you're at 276db55 or later
python3 -m pytest tests/ --import-mode=importlib -q   # confirm 113 passed
python3 trello_gate.py status                          # confirm V-Rod card is handed_off
```

Then open `STAGE9_LAST_POLL_LOG.txt` and the V-Rod Google Doc side-by-side to diagnose the Comment 1 anchor mismatch (§4, Priority 1).
