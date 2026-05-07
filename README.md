# SEO Agent Workflow

End-to-end SEO content pipeline for Legendary Parts. Covers keyword gap analysis, blog generation, and multilingual translation.

Run any mode via the `/seo-forge` slash command in Claude Code.

---

## Trello Validation Gate

### What it does

After an English blog is generated and uploaded to Google Drive (step A8b in Mode A/B), a Trello card is automatically created in the configured board. The card contains a checklist with two items: **Validated by Haleema** and **Validated by Jeremy**.

A background poller (`trello_poller.py`) checks every 5 minutes. When both checklist items are marked complete, the poller automatically starts the translation workflow (`translation_workflow.py --resume <doc_id>`) — no manual `/seo-forge --resume` command needed.

When all 8 translations finish, the Trello card is moved to the "Done" list and a comment is posted with links to every translated Google Doc.

### Getting your Trello API key and token

1. Go to https://trello.com/power-ups/admin
2. Create a new Power-Up (or use an existing one) to get your **API Key**
3. Click "Token" next to your API Key to generate a **Token** with read/write access
4. Copy both values into your `.env` file

### Setting environment variables

Copy `.env.example` to `.env` and fill in the Trello section:

```
TRELLO_API_KEY=your_key_here
TRELLO_API_TOKEN=your_token_here
TRELLO_BOARD_ID=1x4Uql2u          # default: the configured company board
TRELLO_PENDING_LIST_NAME=To Do    # name of the list for new cards
TRELLO_TRANSLATING_LIST_NAME=Doing
TRELLO_DONE_LIST_NAME=Done
TRELLO_CHECKLIST_NAME=Validations
TRELLO_CHECKLIST_ITEM_1=Validated by Haleema
TRELLO_CHECKLIST_ITEM_2=Validated by Jeremy
TRELLO_POLLING_INTERVAL_MINUTES=5
```

The three list names (`To Do`, `Doing`, `Done`) are the defaults on any new Trello board. On startup the poller resolves these names to IDs via the Trello API — if any named list is missing, you'll get a clear error telling you which one.

### Switching from personal test workspace to company workspace

Update only the `.env` values — no code changes required:

```
TRELLO_BOARD_ID=<company_board_id>
TRELLO_PENDING_LIST_NAME=<list_name_on_company_board>
# etc.
```

### Starting the background poller

In a terminal, from the project root:

```bash
cd ~/Documents/SEO\ Agent\ Workflow
python3 trello_poller.py
```

The poller runs until you press Ctrl+C. To run it in the background:

```bash
python3 trello_poller.py &
```

The polling interval defaults to `TRELLO_POLLING_INTERVAL_MINUTES` (5 minutes). Override for a single run:

```bash
python3 trello_poller.py --interval 2   # check every 2 minutes
```

### Manual commands

```bash
# Check status of all tracked cards
python3 trello_gate.py status

# Manually register a card if automatic creation failed
python3 trello_gate.py register <doc_id> "Blog Title Here"

# Force-check a card right now (or re-create a failed one)
python3 trello_gate.py retry <doc_id>

# Run one poll cycle manually
python3 trello_gate.py poll
```

### State database

Card state is stored in `trello_state.db` (SQLite) in the project root. This file is automatically created on first use. It tracks `doc_id`, `card_id`, `blog_title`, `status` (`pending` → `handed_off` → `completed`), and timestamps.

---

## Stage 9 — Comment Resolution

Before translation begins, the poller automatically runs `comment_resolver.py --resume <doc_id>` to process any unresolved comments Jeremy left in the Google Doc.

### How it works

1. **Zero comments** → exits immediately, translation proceeds.
2. **Direct comments** (explicit instruction, e.g. "use Revolution engine not Twin Cam") → Claude generates the exact replacement and applies it via the Docs API.
3. **Interpretive comments** (open-ended flag, e.g. "this sounds awkward") → Claude uses web search (up to 3 searches per comment) to research authentic phrasing, proposes a revision, and applies it.
4. Each resolved comment is marked resolved in the Doc and logged to `trello_state.db`.
5. A summary is posted to the Trello card, then translation starts automatically.

### Retry after failure

If any comment cannot be auto-resolved, the Trello card receives an error message and translation is paused. To retry:

1. Resolve the remaining comments manually in the Google Doc.
2. Untick "Validated by Jeremy" on the Trello card.
3. Re-tick "Validated by Jeremy" — the poller will retry comment resolution on the next cycle.

### Environment variables

```
ANTHROPIC_API_KEY=          # required — used for classification and edit generation
COMMENT_RESOLVER_MODEL=claude-sonnet-4-5   # optional, this is the default
```

### Manual run

```bash
python3 comment_resolver.py --resume <doc_id>
```

---

## V-Rod Translation Run — Status Log

### 2026-05-07 — All 8 languages complete

**Doc:** Harley-Davidson VRSC V-Rod: Complete Buyer's and Owner's Guide
**Doc ID:** `10qYN4k1nolKG3sgmQ5i2Gmx-AG6zyxQuvUQsAFKrqJ4`

| Lang | Status | Expansion | Flags | Drive Doc ID |
|------|--------|-----------|-------|--------------|
| FR | ✓ complete (prior session) | — | — | (spot-checked) |
| DE | ✓ complete (prior session) | — | — | (spot-checked) |
| ES | ✓ complete (prior session) | — | — | (spot-checked) |
| IT | ✓ complete (prior session) | — | — | (spot-checked) |
| PL | ✓ complete 2026-05-07 | +36% ⚠ | 14 | `10fRTJC6TwulqThJhnM73ZN_TXLs7L2R-R2UFnOnbkEw` |
| SL | ✓ complete 2026-05-07 | +38% ⚠ | 18 | `11fDYFBiaI0xBlCD9a2yv4s4pFkci13lxmlGD0FUKHZM` |
| NL | ✓ complete 2026-05-07 | +3% ✓ | 14 | `1nlJNbNDlXT8cfovfKOUqzeGG2Jlhndht1OEwCqm8BQY` |
| PT | ✓ complete 2026-05-07 | +55% ⚠ | 13 | `1U_jNeifao6bq9x3yWWjfjNirKtuxNORxPCpDrfnT5_8` |

Word count expansion is measured in alpha tokens vs English source (~1,075). Slavic/Romance languages expand due to morphology — the ±15% rule added to guidelines (Section 13) will constrain future runs.

---

### Known bugs in the translation write path

#### Bug A — Body section heading level (non-deterministic)
- **Symptom:** FR/DE/ES/IT body sections rendered as Heading 2 in Drive UI. PL/SL/NL/PT rendered correctly as Heading 3. Same model and prompt — translator improvised heading levels.
- **Root cause:** No explicit heading-preservation instruction in the translator prompt.
- **Fix applied:** Section 13 added to `config/translation_guidelines.md` (2026-05-07) — "Preserve every heading tag at its exact level."
- **Status:** Prompt fix deployed. Needs verification on next run.

#### Bug B — FAQ questions always Heading 3 (constant, all 8 languages)
- **Symptom:** FAQ questions in the dedicated FAQ section render as Heading 3 in Drive UI. Expected: Heading 4.
- **Root cause:** `translation_doc_writer.py:113` — `faq_html` is hardcoded with `<h3>` tags.
- **Fix applied:** Changed `<h3>`/`</h3>` to `<h4>`/`</h4>` in `_build_html` (one-line change). Fixed 2026-05-07.
- **Status:** ✅ Fixed. Existing V-Rod docs will be correct on next re-generation; Bobber run (FAQ array empty) unaffected.

#### Bug C — Stray H2 subtitle after title (non-deterministic)
- **Symptom:** All 4 new docs (PL/SL/NL/PT) contained an H2 duplicate of the title immediately after the H1, not present in the English source.
- **Root cause:** Translator adding an unrequested subtitle heading in the `body_markdown` output.
- **Fix applied:** Section 13 in `config/translation_guidelines.md` — "Do not insert an H2 subtitle between H1 and the first body H3."
- **Status:** Prompt fix deployed. Needs verification on next run.

All bugs from the V-Rod run are now either fixed in code or addressed via prompt rules. The Drive parents fallback (404 warning during the run) is documented in Operational Notes below.

---

### Important: `--resume` has no skip-completed logic

`translation_workflow.py --resume <doc_id>` reruns **all 8 languages** every time. There is no per-language state tracking. If a partial run needs to be resumed (some languages already done), use `--lang` per remaining language:

```bash
python3 translation_workflow.py --lang nl 10qYN4k1nolKG3sgmQ5i2Gmx-AG6zyxQuvUQsAFKrqJ4
python3 translation_workflow.py --lang pl 10qYN4k1nolKG3sgmQ5i2Gmx-AG6zyxQuvUQsAFKrqJ4
# etc.
```

`--lang` without `--dry-run` runs in full production mode (saves to Drive, emails if SMTP configured, Trello update silently skips if card is already `completed`).

---

## Operational Notes

### Drive `parents` field — 404 warning and fallback

**Symptom:** During translation runs, a 404 warning is logged when the workflow tries to read the `parents` field of the source doc. Translated docs land in the service account's My Drive root instead of alongside the source doc.

**Root cause:** The service account does not have read access to the source doc's parent folder. The Drive API returns 404 on the `parents` metadata field in this case.

**Behavior:** The fallback is intentional — the workflow continues and uploads translated docs to My Drive root rather than failing. Output is not lost, just misplaced.

**Fix (permissions, not code):** Grant the service account at least **Viewer** access to the source doc's parent folder in Google Drive. After that, the workflow will place translated docs in the correct folder automatically.

**Until then:** After each translation run, manually move the translated docs from My Drive root into the correct folder.
