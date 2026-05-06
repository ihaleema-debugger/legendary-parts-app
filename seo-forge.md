# seo-forge

**End-to-end SEO toolkit for Legendary Parts: keyword gap research, competitor keyword analysis, backlink prospecting, and blog content creation.**

This is a workflow, not a skill. It only runs when the user explicitly asks for it by name (e.g. "run seo-forge", "seo-forge backlink gap", "seo-forge competitor keywords"). Never trigger this workflow implicitly based on surrounding context.

---

## Modes

| Mode | What it does | Key script |
|------|-------------|------------|
| **A — Full keyword gap run** | Competitor domain + location → Semrush keyword gap → filter → cluster → LSIs → brief → blog | `scripts/semrush_gap.py` |
| **B — Blog from existing run** | Write another blog from a previous Mode A run's cached clusters (no re-scraping) | *(reads cached files)* |
| **C — Backlink gap analysis** | Find high-authority referring domains competitor has that Legendary Parts doesn't, with contact emails | `backlink_gap_workflow.py` |
| **D — Competitor keyword research** | Pull full organic keyword rankings for competitor domains via Semrush API, filter for HD/moto terms | `tools/semrush_competitor_keywords.py` |

**If the user is ambiguous about which mode they want, ask.** Do not assume.

---

## Prerequisites

Before running any mode, verify:

- `.env` file exists with credentials populated (see each mode for which keys are required)
- `.env` is listed in `.gitignore`
- Python 3.9+ installed

Mode-specific dependencies are listed in each mode's section below.

---

## Mode A — Full Keyword Gap Run

Runs stages 1 through 6 below, then stops and asks the user to pick a cluster for blog writing (stage 7).

**Triggered by:** phrases like "run seo-forge for autozone.com", "new seo-forge run", "start seo-forge"

**Requires in `.env`:** `SEMRUSH_EMAIL`, `SEMRUSH_PASSWORD`, `GOOGLE_SERVICE_ACCOUNT_PATH`, `GOOGLE_DRIVE_FOLDER_ID`, `GOOGLE_SHARED_DRIVE_ID`, `TRELLO_API_KEY`, `TRELLO_API_TOKEN`, `TRELLO_BOARD_ID`
**Python deps:** `playwright`, `pandas`, `python-dotenv`, `openpyxl`, `google-api-python-client`, `google-auth`, `requests`

### Stage 1 — Collect inputs

Ask the user for:
1. `competitor_domain` (e.g. `autozone.com`)
2. `location` (e.g. `United States`)

Generate a `run_id` in the format: `YYYY-MM-DD_<competitor-slug>_<location-slug>`
Example: `2026-04-18_autozone_united-states`

Create the run folder: `~/Desktop/seo-forge/<run_id>/`

### Stage 2 — Fetch keyword gap from Semrush

Run:
```bash
python scripts/semrush_gap.py <competitor_domain> "<location>" ~/Desktop/seo-forge/<run_id>/01_raw_keywords.csv
```

This script wraps `tools/semrush_scraper.py`, which:
- Loads cached session from `semrush_session.json` (skips login if valid)
- Logs in via `.env` credentials if session is missing or expired
- Navigates directly to the Keyword Gap tool via URL (more reliable than form-filling)
- Enters `legendary-parts.com` as root domain and competitor as comparison domain
- Paginates through all result pages
- Normalises column headers (Semrush varies these across plans and UI updates)
- Exports raw results to `01_raw_keywords.csv`

**If the script fails:** stop and report the exact error. Do not continue. See the Error Reference section for common fixes.

**Session caching:** On first run the browser logs in and saves cookies to `semrush_session.json`. Subsequent runs load cookies and skip login entirely. If the session expires mid-run:
```bash
rm semrush_session.json
# then re-run the stage
```

### Stage 3 — Filter keywords

Read `01_raw_keywords.csv`. Keep only rows where:
- `Keyword Difficulty` < 30
- `Volume` > 100

Save filtered result to `02_filtered_keywords.csv`.

Report: "Filtered X keywords down to Y keywords meeting the KD<30 / Volume>100 criteria."

If Y is zero, stop and tell the user. Do not continue to clustering.

### Stage 4 — Cluster keywords

Invoke the `keyword-clustering` skill, passing `02_filtered_keywords.csv` as input.

Save result to `<run_folder>/03_clusters.json`:

```json
{
  "run_id": "2026-04-18_autozone_united-states",
  "created_at": "ISO timestamp",
  "clusters": [
    {
      "id": 1,
      "name": "harley davidson batteries",
      "topic": "motorcycle batteries",
      "intent": "transactional",
      "keyword_count": 12,
      "total_volume": 4200,
      "avg_kd": 18,
      "primary_keyword": "harley davidson battery",
      "keywords": [ ... ],
      "status": "unused"
    }
  ]
}
```

Every cluster starts with `"status": "unused"`.

Also create per-cluster subfolders:
```
clusters/
├── cluster_01_harley-davidson-batteries/
│   └── keywords.csv
├── cluster_02_crash-bars/
│   └── keywords.csv
```

### Stage 5 — Show clusters to the user

```
Found 12 clusters from this run. Pick one to write a blog about:

1. harley davidson batteries (12 keywords, 4,200 total volume, avg KD 18) — transactional
2. crash bars (8 keywords, 2,100 total volume, avg KD 22) — commercial
...

Which cluster should I write a blog for? (enter a number)
```

Wait for the user's pick. Do not proceed until they respond with a number.

### Stage 6 — Generate LSIs + brief + blog

Once the user picks cluster N:

1. **LSIs** — invoke `lsi-generation` skill with the cluster's keywords. Save to `clusters/cluster_NN_<name>/lsis.md`.

2. **Brief** — invoke `content-brief` skill with the cluster's keywords + generated LSIs. Save to `clusters/cluster_NN_<name>/brief.md`.

3. **Blog** — invoke `seo-blog-writer` skill with:
   - The cluster's keywords (primary keyword = highest-volume keyword)
   - LSIs from step 1
   - Brief from step 2
   - `keyword_forge/guideline.md` as the style guide
   
   Save the full JSON output from seo-blog-writer to `clusters/cluster_NN_<name>/blog_blocks.json`. The `faq_schema` key in that JSON replaces the separate `faq_schema.html` file.

4. **Update status** — in `03_clusters.json`, set the chosen cluster's `status` to `"used"` and add `"used_at"` ISO timestamp.

### Stage 7 — Report (interim — Stage 8 follows immediately)

```
✅ Blog written for cluster N: "<cluster name>"
📄 ~/Desktop/seo-forge/<run_id>/clusters/cluster_NN_<name>/blog_blocks.json

Publishing to Drive and Trello now...
```

Do not stop here. Proceed to Stage 8 without asking the user.

### Stage 8 — Publish to Drive + Trello (automatic, non-optional)

**This stage runs automatically every time a blog is written. Never skip it. Never ask the user if they want to publish. Just do it.**

Run from the project root (`/Users/mac/Documents/SEO Agent Workflow/`). Title is extracted automatically from the first `{"level": "title"}` block in `blog_blocks.json`.

**A8b — Upload to Google Drive:**
```bash
cd "/Users/mac/Documents/SEO Agent Workflow" && python tools/publish_blog.py \
  --blocks-path "~/Desktop/seo-forge/<run_id>/clusters/cluster_NN_<name>/blog_blocks.json"
```

The script:
1. Reads `blog_blocks.json` and extracts the title from the first `{"level": "title"}` block
2. Creates an empty Google Doc via Drive API
3. Writes structured content (headings + links) via Docs API batchUpdate
4. Prints the Drive URL and Doc ID

**A8c — Create Trello validation card:**
The same script calls `trello_gate.cmd_register(doc_id, title)` automatically, which:
- Creates a card in the `TRELLO_PENDING_LIST_NAME` ("To Do") list
- Adds a "Validations" checklist with "Validated by Haleema" and "Validated by Jeremy" items
- Auto-starts `trello_poller.py` in the background (skips if already running)

**If the script fails:** stop and report the exact error. Do not silently skip. The blog is always saved locally at `blog_blocks.json` regardless — it is never lost. The user can re-run Stage 8 manually: `python tools/publish_blog.py --blocks-path <path>`.

After Stage 8 completes, give the final report:
```
☁️  Uploaded to Drive: <webViewLink>
🗂️  Trello card created: <card_id>
    Waiting for validation by Haleema and Jeremy before translation begins.

X unused clusters remain from this run.
To write another blog from this run: /seo-forge blog from <run_id>
```

### Stage 9 — Comment Resolution (automatic, runs before translation)

**Triggered automatically** by `trello_poller.py` once both Trello checklist items are ticked. The poller calls `comment_resolver.py --resume <doc_id>` before starting translation. No manual action needed under normal conditions.

**What it does:**

1. Fetches all unresolved comments from the Google Doc (Drive API `comments.list`).
2. If there are no comments, logs "No comments to resolve" and exits immediately — translation starts without delay.
3. For each comment, classifies it using Claude into one of:
   - **direct** — Jeremy gave an explicit instruction (e.g. "change X to Y", "V-Rod uses Revolution engine, not Twin Cam"). Edit is applied immediately.
   - **interpretive** — Jeremy flagged something without a specific fix (e.g. "this sounds awkward"). Claude researches with up to 3 web searches and proposes a revision.
4. Applies each edit to the Google Doc at the exact anchor position (`deleteContentRange + insertText` via Docs API).
5. Marks each comment resolved in the Doc (Drive API `comments.update`).
6. Logs every change to the `comment_resolutions` table in `trello_state.db`.
7. Posts a summary comment on the Trello card.
8. Exits 0 → translation starts. Exits 1 → translation is paused (see below).

**On failure (any comment could not be auto-resolved):**

The Trello card receives a comment:
```
Comment resolution incomplete: N comment(s) could not be auto-resolved.
Translation paused. Resolve manually in the doc and tick the
'Validated by Jeremy' box again to retry.
```

To retry: resolve the remaining comments manually in the Google Doc, then untick and re-tick "Validated by Jeremy" on the Trello card. The poller will pick it up on the next cycle.

**State stored in:** `trello_state.db` → `comment_resolutions` table (columns: `id`, `doc_id`, `comment_id`, `category`, `original_text`, `revised_text`, `claude_reasoning`, `resolved_at`).

**Requires:** `ANTHROPIC_API_KEY` and `COMMENT_RESOLVER_MODEL` (defaults to `claude-sonnet-4-5`) in `.env`.

---

## Mode B — Blog from Existing Run

**Triggered by:** phrases like "write another blog from the last seo-forge run", "seo-forge blog from [run folder name]", "next blog from autozone run"

### Stage B1 — Locate the run

Ask the user which run to use (or infer from their phrasing if they named it).

If they say "the last one" or similar, list `~/Desktop/seo-forge/` sorted by date descending and pick the most recent, then confirm with the user before proceeding.

### Stage B2 — Load clusters and show unused ones only

Read `<run_folder>/03_clusters.json`. Filter to `status == "unused"`.

Display with **original cluster IDs preserved** (gaps in numbering are expected and intentional):

```
From run 2026-04-18_autozone_united-states:
11 unused clusters remaining.

1. harley davidson batteries (12 keywords, 4,200 total volume, avg KD 18) — transactional
4. engine parts (6 keywords, 900 total volume, avg KD 28) — informational
...

Which cluster should I write a blog for? (enter a number)
```

If zero unused clusters remain, tell the user the run is exhausted and suggest starting a fresh Mode A run.

### Stage B3 — Generate LSIs + brief + blog

Same as Mode A Stage 6. Check for an existing `blog_blocks.json` first — if one exists, warn the user and ask for confirmation before overwriting.

### Stage B4 — Report (interim — Stage B5 follows immediately)

Same interim report as Mode A Stage 7. Do not stop here. Proceed to Stage B5 without asking the user.

### Stage B5 — Publish to Drive + Trello (automatic, non-optional)

Identical to Mode A Stage 8. Run:

```bash
cd "/Users/mac/Documents/SEO Agent Workflow" && python tools/publish_blog.py \
  --blocks-path "~/Desktop/seo-forge/<run_id>/clusters/cluster_NN_<name>/blog_blocks.json"
```

Same Drive upload, Trello card creation, failure handling, and final report format as Stage 8.

---

## Mode C — Backlink Gap Analysis

Find high-authority referring domains that link to a competitor but not to Legendary Parts. Output includes contact emails for outreach.

**Triggered by:** phrases like "seo-forge backlink gap", "backlink analysis for partseurope.eu", "find link building prospects"

**Requires in `.env`:** `SEMRUSH_EMAIL`, `SEMRUSH_PASSWORD`
**Python deps:** `playwright`, `requests`, `python-dotenv`, `openpyxl`, `pandas`

### Stage C1 — Collect inputs

Ask for:
- `my_domain` (default: `legendary-parts.com`)
- `competitor_domain` (e.g. `partseurope.eu`)

### Stage C2 — Run the backlink gap scraper

**Standard run:**
```bash
python backlink_gap_workflow.py --my-domain <my_domain> --competitor <competitor_domain>
```

**Debug run (browser visible — use if selectors fail):**
```bash
python backlink_gap_workflow.py --headful --my-domain <my_domain> --competitor <competitor_domain>
```

The script automatically:
1. Loads cached session from `semrush_session.json` (shared with Mode A)
2. Navigates to the Backlink Gap tool via direct URL
3. Fills domains and clicks "Find prospects"
4. Clicks the "Best" tab (highest-authority domains linking to competitor but NOT to my domain)
5. Applies Authority Score > 20 filter (falls back to Python filtering if UI filter fails)
6. Triggers export → downloads CSV
7. For each referring domain, scrapes `/contact`, `/contact-us`, `/about`, `/about-us`, `/` for a contact email (1.5s delay between domains)
8. Exports enriched results to `~/Desktop/backlink_gap_<competitor>_<YYYYMMDD>.xlsx`

Stream terminal output to the user. Debug screenshots are saved to `.tmp/debug_backlink_*.png`.

If the script exits with error: stop and report. See Error Reference below.

### Stage C3 — Report

Read the terminal summary output (printed by the script) and relay to the user:
- How many prospects were found
- Authority Score threshold applied
- How many contact emails were found vs TODO
- File path on Desktop

Remind the user:
- TODO cells in the Email column are yellow-highlighted (need manual follow-up)
- Authority Score > 20 filter is applied
- Results sorted by Authority Score descending

---

## Mode D — Competitor Keyword Research via API

Pull full organic keyword rankings for competitor domains across multiple markets via the Semrush API. Use when you want a broad landscape view (not a head-to-head gap like Mode A).

**Triggered by:** phrases like "seo-forge competitor keywords", "api keyword research", "pull competitor rankings"

**Requires in `.env`:** `SEMRUSH_API_KEY`
**Note:** Uses Semrush API units (separate from the Playwright scraping). See API Budget below.

### Stage D1 — Check prerequisites

Verify `SEMRUSH_API_KEY` is set in `.env`. If not, tell the user:
> "Add your Semrush API key to `.env` as `SEMRUSH_API_KEY`. Find it in Semrush under Management → API."

### Stage D2 — (Optional) Adjust configuration

Ask the user if they want to change any of these defaults (otherwise proceed with defaults):

| Setting | Default | Location |
|---------|---------|----------|
| `COMPETITORS` | Hardcoded list | Top of `tools/semrush_competitor_keywords.py` |
| `DISPLAY_LIMIT` | 5,000 | Top of script (costs API units per 10 rows) |
| `MIN_VOLUME` | 70 | Top of script |

**API budget estimate:** `(DISPLAY_LIMIT / 10) × (num_competitors × num_databases)`
- Default: ~2,400 units (actual rows are usually lower)
- Keep `DISPLAY_LIMIT` ≤ 1,000 on standard plans (requests above 1,000 return ERROR 132)

### Stage D3 — Run the tool

**Normal run (uses 30-day cache — zero API units for cached entries):**
```bash
python3 tools/semrush_competitor_keywords.py
```

**Force fresh data (busts cache — costs full API budget):**
```bash
python3 tools/semrush_competitor_keywords.py --force
```

Stream output. The script batches API calls (3 calls, then a 120s pause) to stay within rate limits. First run: ~35 min. Subsequent runs with cache: instant.

What to watch for:
- `ERROR 132 :: API UNITS BALANCE IS ZERO` → out of units, wait for monthly reset
- `ERROR 135 :: API limit reached` → reduce `DISPLAY_LIMIT`
- `ERROR 14 :: no data` → normal for some competitor/country combos, safe to ignore

### Stage D4 — Review output

```
.tmp/competitor_keywords_YYYYMMDD_HHMMSS.xlsx
```

Five sheets — work through in this order:

1. **Keyword Gap** — keywords competitors rank for that Legendary Parts doesn't (top 10). Highest-opportunity targets.
2. **Harley Davidson** — HD-specific terms. Good for model-specific pages and blog posts.
3. **Generic Motorcycle** — broader moto terms. Good for top-of-funnel content.
4. **Master Keywords** — full combined list. Sort by `# Competitors Ranking` to find terms multiple competitors consistently rank for.
5. **Raw Data** — one row per keyword × competitor × country.

Key columns: `# Competitors Ranking`, `Max Search Volume`, `Keyword Difficulty`, `Best Position`.

### Stage D5 — Report

Tell the user:
- File path
- Total unique keywords found
- Keyword Gap count (highest-priority for action)
- Any ERROR lines encountered during the run

---

## Folder Structure (Mode A/B reference)

```
~/Desktop/seo-forge/
└── 2026-04-18_autozone_united-states/
    ├── 01_raw_keywords.csv
    ├── 02_filtered_keywords.csv
    ├── 03_clusters.json              # source of truth for used/unused status
    └── clusters/
        ├── cluster_01_harley-davidson-batteries/
        │   ├── keywords.csv
        │   ├── lsis.md               # only if cluster has been used
        │   ├── brief.md              # only if cluster has been used
        │   └── blog_blocks.json      # only if cluster has been used (faq_schema is inside)
        ├── cluster_02_crash-bars/
        │   └── keywords.csv          # unused — keywords only
        └── ...
```

`blog_blocks.json` presence is a secondary signal of "used" status. `03_clusters.json` is the source of truth.

---

## Shared Reference

### Session management (Modes A and C)

Both Mode A and Mode C share `semrush_session.json` for Playwright session persistence.

- **First run:** browser opens (headless), logs in, saves cookies
- **Subsequent runs:** cookies loaded, login skipped (much faster)
- **Session expired:** delete the file and re-run: `rm semrush_session.json`
- **CAPTCHA or rate limiting:** wait 10–15 min, delete the session file, retry. Never run multiple scrapers simultaneously against the same Semrush account.

### Valid locations (Modes A and C)

| Display Name | Semrush DB Code |
|-------------|-----------------|
| United States | `us` |
| United Kingdom | `uk` |
| France | `fr` |
| Germany | `de` |
| Spain | `es` |
| Italy | `it` |

### Selector brittleness (Modes A and C)

Semrush uses React with dynamically generated class names. Selectors can break after UI updates. When a scraper stage fails with a timeout or "element not found":

1. Re-run with `--headful` flag to watch the browser
2. Open DevTools (F12) and inspect the broken element
3. Update the selector in the relevant scraper file:
   - Keyword Gap: `tools/semrush_scraper.py` → `_extract_table_page()` / `_has_next_page()`
   - Backlink Gap: `tools/semrush_backlink_scraper.py` → the relevant step function
4. Re-run to verify
5. Update this workflow with what changed

### Error reference

| Error | Mode | Cause | Fix |
|-------|------|-------|-----|
| `LoginError: SEMRUSH_EMAIL/PASSWORD missing` | A, C | `.env` not configured | Copy `.env.example` → `.env`, fill credentials |
| `LoginError: still on login page after submit` | A, C | Bad credentials or 2FA enabled | Check credentials; disable 2FA in Semrush account settings |
| `EmptyResultsError` | A, C | No keyword/backlink gap for these domains | Try a different competitor or location |
| Table not found / timeout | A, C | Semrush UI changed or slow load | Run `--headful` to inspect; update selectors in scraper |
| Session expired mid-run | A, C | Long gap between runs | Delete `semrush_session.json` and re-run |
| `ERROR 132 :: API UNITS BALANCE IS ZERO` | D | API units depleted | Wait for monthly reset or buy more units |
| `ERROR 135 :: API limit reached` | D | `DISPLAY_LIMIT` too high | Reduce `DISPLAY_LIMIT` to ≤ 1,000 |
| `ERROR 14 :: no data` | D | No data for that competitor/country combo | Normal — safe to ignore |
| `SEMRUSH_API_KEY is not set` | D | Missing key in `.env` | Add `SEMRUSH_API_KEY=...` to `.env` |
| Could not click "Find prospects" | C | Semrush UI changed | Run `--headful`, check `debug_backlink_02_after_fill.png`, update selectors |
| Export download failed | C | Export button changed or CAPTCHA | Run `--headful`, check `debug_backlink_06_after_export.png`, update selectors |
| `Drive upload failed: 403` | A, B | Service account lacks access to the Shared Drive folder | Share the Drive folder with the service account email; ensure `GOOGLE_SHARED_DRIVE_ID` is correct |
| `Drive upload failed: 404` | A, B | `GOOGLE_DRIVE_FOLDER_ID` points to a non-existent folder | Verify the folder ID in Drive; update `.env` |
| `GOOGLE_SERVICE_ACCOUNT_PATH` file not found | A, B | Key file missing or wrong path | Confirm `secrets/legendary-parts-203a804edea2.json` exists; update path in `.env` |
| `Trello API error 401` | A, B | Invalid Trello API key or token | Regenerate token at trello.com/power-ups/admin; update `.env` |
| `The following Trello list names were not found` | A, B | List name in `.env` doesn't match actual board | Check `TRELLO_PENDING_LIST_NAME` against board list names |
| Trello card created but poller not starting | A, B | `pgrep` unavailable or permissions issue | Start manually: `python3 trello_poller.py` |

---

## Rules

1. **Never reimplement skill logic inline.** Always invoke `keyword-clustering`, `lsi-generation`, `content-brief`, `seo-blog-writer` via the Skill tool. If a skill fails, report the failure — do not substitute with inline logic.

2. **Never re-scrape Semrush in Mode B.** If cached files are missing, stop and tell the user the run folder is incomplete.

3. **Guideline is the single source of truth for style.** Always pass `keyword_forge/guideline.md` to `seo-blog-writer`. Never inline style rules in the workflow.

4. **Respect the used/unused tracking.** Never show "used" clusters in Mode B's selection list. Never silently overwrite an existing blog — if the user picks a used cluster by mistake, warn them and ask for confirmation.

5. **One cluster per invocation.** This workflow writes one blog at a time. If the user wants multiple blogs, they invoke the workflow multiple times.

6. **Fail loudly.** If any stage fails, stop immediately and report the exact problem. Never skip a stage or substitute placeholder content.

7. **Preserve original cluster IDs in Mode B.** Cluster 3 always means cluster 3. Never renumber.

8. **Stage 8 / Stage B5 is mandatory and automatic.** Every completed blog must be uploaded to Drive and have a Trello card created before the workflow is considered done. Never skip these steps, never ask the user if they want to publish, and never end the workflow at Stage 7 / Stage B4.
