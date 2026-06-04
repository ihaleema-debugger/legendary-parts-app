---
description: End-to-end SEO toolkit — keyword gap to blog, backlink prospecting, competitor keyword research, and translation. Mode A: full run. Mode B: blog from cached clusters. Mode C: backlink gap. Mode D: competitor keywords via API. Mode E: translate approved blog (--resume <doc_id>).
argument-hint: "[competitor-domain location | blog from <run-id> | last | backlink <domain> | competitor keywords | --resume <doc_id>]"
---

You are executing the seo-forge workflow for Legendary Parts. Follow every step exactly. Never skip a stage. Never substitute inline logic for a skill.

## Step 0: Preflight

Run these checks silently before doing anything else. Surface errors only.

1. Project root contains `seo-forge.md`, `tools/semrush_scraper.py`, `scripts/semrush_gap.py`, `backlink_gap_workflow.py`, `tools/semrush_competitor_keywords.py`
2. `.env` file exists
3. `keyword_forge/guideline.md` exists and has more than 100 characters
4. For Modes A and C: verify `SEMRUSH_EMAIL` and `SEMRUSH_PASSWORD` are set in `.env`
5. For Mode D: verify `SEMRUSH_API_KEY` is set in `.env`
6. Python packages: run `python3 -c "import playwright, pandas, dotenv"` (Modes A/C/D). If it fails, tell the user what to install and stop.

If any required check fails, report the exact problem and stop. Do not continue.

---

## Step 1: Determine Mode

Examine `$ARGUMENTS`:

- **Starts with `--resume`** (e.g. `--resume 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`) → **Mode E**
- **Contains a domain AND a location** (e.g. `autozone.com "United States"`) → **Mode A**
- **Contains "blog from"** or a run-id matching `YYYY-MM-DD_*` → **Mode B**
- **"last"** alone → **Mode B**, use most recent run folder
- **Contains "backlink"** → **Mode C**
- **Contains "competitor keywords"** or "api keywords" → **Mode D**
- **Empty or ambiguous** → Ask:
  > Which mode?\n1. Mode A — keyword gap full run (Semrush scrape → filter → cluster → blog)\n2. Mode B — write another blog from a previous run's cached clusters\n3. Mode C — backlink gap analysis (find link-building prospects + contact emails)\n4. Mode D — competitor keyword research via Semrush API\n5. Mode E — translate an approved English blog into 8 languages (`--resume <doc_id>`)

Wait for the user's choice before proceeding.

---

## Mode A — Full Keyword Gap Run

### A1: Collect Inputs

Parse `competitor_domain` and `location` from `$ARGUMENTS` if both are present. Otherwise ask.

Generate run ID: `YYYY-MM-DD_<competitor-slug>_<location-slug>` (lowercase, spaces → hyphens)
Example: `2026-04-18_autozone_united-states`

Create run folder: `~/Desktop/seo-forge/<run_id>/`

Tell the user: "Starting run `<run_id>`."

### A2: Scrape Semrush

```bash
python scripts/semrush_gap.py <competitor_domain> "<location>" ~/Desktop/seo-forge/<run_id>/01_raw_keywords.csv
```

Stream output. If the script exits with code 1 or prints ERROR: stop and report the full error. Do not continue.

On success: confirm "`01_raw_keywords.csv` written."

**Session note:** If the scraper errors with a login failure, try deleting `semrush_session.json` and re-running. If it errors with "element not found" or a timeout, re-run with `--headful` flag added to the command and report what you observe.

### A3: Filter Keywords

```python
import pandas as pd
from pathlib import Path

run_folder = Path("~/Desktop/seo-forge/<run_id>").expanduser()
df = pd.read_csv(run_folder / "01_raw_keywords.csv")
df.columns = df.columns.str.strip()
kd_col = next((c for c in df.columns if "difficulty" in c.lower() or c.strip().upper() == "KD%"), None)
vol_col = next((c for c in df.columns if "volume" in c.lower()), None)
if not kd_col or not vol_col:
    raise ValueError(f"Could not find KD or Volume columns. Found: {list(df.columns)}")
df[kd_col] = pd.to_numeric(df[kd_col], errors="coerce")
df[vol_col] = pd.to_numeric(df[vol_col], errors="coerce")
filtered = df[(df[kd_col] < 30) & (df[vol_col] > 100)].copy()
filtered.to_csv(run_folder / "02_filtered_keywords.csv", index=False)
print(f"Filtered {len(df)} → {len(filtered)} keywords (KD<30, Volume>100)")
```

Replace `<run_id>` with the actual run ID. Report the result. If filtered count is 0, stop.

### A4: Cluster Keywords

Invoke the `keyword-clustering` skill:
```
Skill tool: skill: "keyword-clustering"
```
Pass it `02_filtered_keywords.csv`.

After the skill completes, build `03_clusters.json` from the cluster output. Every cluster starts with `"status": "unused"`. Structure:

```json
{
  "run_id": "<run_id>",
  "created_at": "<ISO timestamp>",
  "competitor_domain": "<domain>",
  "location": "<location>",
  "clusters": [
    {
      "id": 1,
      "name": "<name>",
      "topic": "<topic>",
      "intent": "<intent>",
      "keyword_count": N,
      "total_volume": N,
      "avg_kd": N,
      "primary_keyword": "<highest-volume keyword>",
      "keywords": ["kw1", "kw2"],
      "status": "unused"
    }
  ]
}
```

Create `clusters/cluster_NN_<slug>/keywords.csv` per cluster.

### A5: Show Clusters + Choose Research Mode

Present clusters and ask for both a cluster number and research mode in one prompt:

```
Found N clusters. Choose a cluster and research mode:

  1. <name> (X keywords, X,XXX vol, KD XX) — transactional
  2. <name> (X keywords, X,XXX vol, KD XX) — informational
  ...

Research mode:
  [S] Standard — generate draft from cluster context (faster)
  [D] Deep     — web research pass first, 15–20 sources, then draft (~4 min extra)

Enter: <cluster number> <S or D>   e.g. "2 D" or "1 S"
```

Wait for the user's response. Parse into `chosen_cluster` (number) and `research_mode` ("S" or "D").
If the user enters only a number with no mode, ask once: "Standard [S] or Deep [D]?"

### A5b: Deep Research (skip if Standard mode)

Only execute this step if `research_mode == "D"`.

**Goal:** Gather 15–20 web sources relevant to the chosen cluster before writing the blog.

1. Derive 3–4 search queries from the cluster's primary keyword and 2–3 supporting keywords.
   Example queries for "harley davidson battery replacement":
   - "harley davidson battery replacement guide 2024"
   - "motorcycle battery maintenance tips harley"
   - "best batteries for harley davidson touring"
   - "harley davidson battery size chart"

2. Use the web_search tool (Claude's built-in search) to run each query. Collect up to 5 URLs per query.

3. For each unique URL collected (target: 15–20 total, minimum: 10):
   - Record: `url`, `title`, publication `date` (if visible in snippet), and a 2–3 sentence extractive `summary` of the most relevant passage.

4. **Source count check:** If fewer than 10 unique sources were gathered after all queries, stop and report:
   `"Deep research returned only N sources (minimum 10 required). Check your network connection or broaden the cluster keywords."` Do NOT proceed to A6.

5. Build the research bundle JSON:

```json
{
  "cluster_id": "<8-char hex from 03_clusters.json>",
  "primary_keyword": "<highest-volume keyword>",
  "queries_used": ["q1", "q2", "q3", "q4"],
  "sources": [
    {
      "url": "https://...",
      "title": "Page title from search result",
      "date": "2024-03-15",
      "summary": "2-3 sentence extractive summary of the most relevant passages."
    }
  ],
  "gathered_at": "<ISO 8601 timestamp>",
  "source_count": N
}
```

6. Save bundle as `clusters/cluster_NN_<slug>/research_bundle.json` locally.

7. Upload bundle to Google Drive (same folder as the blog doc will go):

```bash
python3 - <<'PYEOF'
import os, sys, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path.home() / "Documents/SEO Agent Workflow"))
from app.services.drive_uploader import upload_json_to_drive

bundle_path = Path.home() / "Desktop/seo-forge/<RUN_ID>/clusters/<CLUSTER_SLUG>/research_bundle.json"
bundle = json.loads(bundle_path.read_text())
folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
result = upload_json_to_drive("<CLUSTER_SLUG>-research-bundle.json", bundle, folder_id)
print(f"Research bundle: {result['webViewLink']}")
PYEOF
```

Replace `<RUN_ID>` and `<CLUSTER_SLUG>` with actual values. Print the Drive link to the user:

```
🔍 Research complete: N sources gathered.
   Bundle: <Drive link>
   Proceeding to write blog grounded in these sources...
```

### A6: Generate LSIs

Invoke:
```
Skill tool: skill: "lsi-generation"
```
Primary keyword = highest-volume keyword in the chosen cluster. Pass all cluster keywords as context. Content type: blog post, target word count: 700.

Save output to `clusters/cluster_NN_<slug>/lsis.md`.

### A7: Generate Content Brief

Invoke:
```
Skill tool: skill: "content-brief"
```
Pass: primary keyword, cluster keywords, content type (blog post), LSIs from A6.

Save output to `clusters/cluster_NN_<slug>/brief.md`.

### A8: Write the Blog

**If Standard mode:**
Invoke:
```
Skill tool: skill: "seo-blog-writer"
```
Pass: primary keyword, cluster keywords, LSIs from `lsis.md`, brief from `brief.md`. Read `keyword_forge/guideline.md` and pass its full contents as the style guide.

Save blog markdown to `clusters/cluster_NN_<slug>/blog.md`.
Save FAQ schema JSON-LD to `clusters/cluster_NN_<slug>/faq_schema.html`.

**If Deep mode:**
Invoke:
```
Skill tool: skill: "seo-blog-writer"
```
Pass: primary keyword, cluster keywords, LSIs from `lsis.md`, brief from `brief.md`, guideline from `keyword_forge/guideline.md`, AND the research bundle sources from A5b as additional grounding context.

Additional instructions for the blog writer in deep mode:
- Cite sources inline using `[1]`, `[2]`, ... markers tied to the bundle's source index (1-based).
- Append a `## Sources` section at the end listing all sources used, numbered to match inline citations. Format: `[N] Title — URL`
- The blog must still follow all existing structure, tone, and word-count rules from the guideline. Citations add grounding only — they do not change the output format.

Save blog markdown to `clusters/cluster_NN_<slug>/blog.md`.
Save FAQ schema JSON-LD to `clusters/cluster_NN_<slug>/faq_schema.html`.

### A8b: Upload to Google Drive

After saving `blog.md`, upload it to Google Drive and record the doc ID.

Run from the project root (`~/Documents/SEO Agent Workflow`):

```bash
python3 - <<'PYEOF'
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path.home() / "Documents/SEO Agent Workflow"))
from app.services.drive_uploader import upload_blog_to_drive

# Replace <RUN_ID> and <CLUSTER_SLUG> with actual values
blog_path = Path.home() / "Desktop/seo-forge/<RUN_ID>/clusters/<CLUSTER_SLUG>/blog.md"
content = blog_path.read_text(encoding="utf-8")
result = upload_blog_to_drive(title="<CLUSTER_NAME>", content=content)
print(f"Google Doc ID : {result['id']}")
print(f"Link          : {result['webViewLink']}")
PYEOF
```

Replace `<RUN_ID>`, `<CLUSTER_SLUG>`, and `<CLUSTER_NAME>` with the actual values. Print the returned **Google Doc ID** and link to the user:

```
📄 Google Doc: <webViewLink>
🔑 Doc ID: <id>
```

Save the doc ID to `clusters/cluster_NN_<slug>/drive_doc_id.txt` for reference.

**If Deep mode:** The research bundle was already uploaded to Drive in step A5b. No additional action needed here.

### A8c: Create Trello Validation Card

After the Drive upload succeeds, register the doc with the Trello gate so Haleema and Jeremy can validate it:

```bash
cd ~/Documents/SEO\ Agent\ Workflow
python3 trello_gate.py register "<DOC_ID>" "<CLUSTER_NAME>"
```

Replace `<DOC_ID>` with the Google Doc ID from A8b and `<CLUSTER_NAME>` with the blog title.

If the command prints a warning (e.g. Trello credentials not set), report it to the user — the blog is already safely saved to Drive.

Print to user:
```
🃏 Trello card created for validation.
   Haleema and Jeremy can now check off their items on the card.
   Translation will start automatically once both validations are complete.
   (To force-check now: python3 trello_gate.py retry <DOC_ID>)
   (To start the background poller: python3 trello_poller.py)
```

### A9: Update Cluster Status

In `03_clusters.json`, update the chosen cluster:
```json
{ "status": "used", "used_at": "<ISO timestamp>" }
```

Write updated JSON back to the run folder.

### A10: Report

```
✅ Blog written for cluster N: "<cluster name>"
📄 ~/Desktop/seo-forge/<run_id>/clusters/cluster_NN_<slug>/blog.md

X unused clusters remain.
To write another blog: /seo-forge blog from <run_id>
```

---

## Mode B — Blog from Existing Run

### B1: Locate the Run

"last" → list `~/Desktop/seo-forge/` sorted desc, pick the most recent, confirm with user.

Named run → verify `~/Desktop/seo-forge/<run_id>/03_clusters.json` exists.

Otherwise → ask: "Which run? (enter a run ID or say 'last')"

### B2: Show Unused Clusters + Choose Research Mode

Read `03_clusters.json`. Filter to `status == "unused"`.

If zero: "All clusters from run `<run_id>` have been used. Start a new run with `/seo-forge <competitor> <location>`." Stop.

Display with **original cluster IDs preserved** (gaps in numbering are expected) and ask for both cluster and research mode:

```
From run <run_id>:
X unused clusters remaining.

  2. <name> (X keywords, X,XXX vol, KD XX) — commercial
  4. <name> (X keywords, X,XXX vol, KD XX) — informational
  ...

Research mode:
  [S] Standard — generate draft from cluster context (faster)
  [D] Deep     — web research pass first, 15–20 sources, then draft (~4 min extra)

Enter: <cluster number> <S or D>   e.g. "2 D" or "4 S"
```

Wait for the user's response. Parse into `chosen_cluster` (number) and `research_mode` ("S" or "D").
If the user enters only a number with no mode, ask once: "Standard [S] or Deep [D]?"

### B3: Check for Existing Blog

If `blog.md` already exists in the target cluster folder:
> "Cluster N already has a blog at `cluster_NN_<slug>/blog.md`. Overwrite it? (yes/no)"
Wait. If no, stop.

### B4: Generate LSIs + Brief + Blog

Same as Mode A steps A6, A7, A5b (if Deep mode), A8, and A8b (including the Google Drive upload step).

### B5: Update Status + Report

Same as Mode A steps A9, A10.

---

## Mode C — Backlink Gap Analysis

### C1: Collect Inputs

Ask for:
- `my_domain` (default: `legendary-parts.com`)
- `competitor_domain` (e.g. `partseurope.eu`)

### C2: Run the Backlink Gap Scraper

**Standard run:**
```bash
python backlink_gap_workflow.py --my-domain <my_domain> --competitor <competitor_domain>
```

**Debug run (if selectors fail or Semrush UI has changed):**
```bash
python backlink_gap_workflow.py --headful --my-domain <my_domain> --competitor <competitor_domain>
```

Stream all terminal output to the user. Debug screenshots are saved to `.tmp/debug_backlink_*.png` — read these if something fails.

The script handles: session loading → Backlink Gap navigation → "Best" tab selection (highest-authority domains linking to competitor but NOT to my domain) → Authority Score > 20 filter → CSV export → contact email scraping per domain (1.5s delay, checks `/contact`, `/contact-us`, `/about`, `/about-us`, `/`) → XLSX export to Desktop.

If the script exits with an error: stop and report the full error message and the relevant debug screenshot path.

**Session note:** This script shares `semrush_session.json` with Mode A. If session is expired, delete it and re-run.

### C3: Report

Read the terminal summary printed by the script and relay to the user:
- Competitor domain
- Prospects found
- Emails found vs TODO
- Output file path on Desktop

Remind the user:
- TODO cells in the Email column are yellow-highlighted — need manual follow-up
- Sorted by Authority Score descending
- Only domains linking to competitor but NOT to `my_domain` are included ("Best" tab)

---

## Mode D — Competitor Keyword Research via API

### D1: Verify API Key

Check `.env` for `SEMRUSH_API_KEY`. If missing:
> "Add your Semrush API key to `.env` as `SEMRUSH_API_KEY`. Find it in Semrush under Management → API." Stop.

### D2: (Optional) Configuration

Ask if the user wants to adjust any of these before running:
- **Competitor list** — edit `COMPETITORS` at the top of `tools/semrush_competitor_keywords.py`
- **Display limit** — default 5,000 rows (keep ≤ 1,000 on standard plans)
- **Min volume** — default 70

Otherwise proceed with defaults.

**API budget reminder:** Standard plans cap at 1,000 rows per request — going above returns ERROR 132. Budget ≈ `(DISPLAY_LIMIT / 10) × (num_competitors × num_databases)` units.

### D3: Run

**With cache (zero API units for cached entries):**
```bash
python3 tools/semrush_competitor_keywords.py
```

**Force fresh data:**
```bash
python3 tools/semrush_competitor_keywords.py --force
```

Stream output. First run: ~35 min. Subsequent runs with cache: instant. The script batches calls (3 per window, then a 120s pause) — do not interrupt during batch pauses.

### D4: Report

Tell the user:
- Output file path: `.tmp/competitor_keywords_YYYYMMDD_HHMMSS.xlsx`
- Total unique keywords found
- Keyword Gap count
- Any ERROR lines encountered (ERROR 14 is safe to ignore; ERROR 132/135 need action)

Suggest they open the file and work through sheets in order: Keyword Gap → Harley Davidson → Generic Motorcycle → Master Keywords.

---

## Mode E — Translate Approved Blog

**Triggered by:** `--resume <doc_id>` where `<doc_id>` is the Google Doc ID of an approved English blog previously uploaded in step A8b or B4.

**Requires in `.env`:** `ANTHROPIC_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_PATH`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL`, `SHOPIFY_ADMIN_API_TOKEN`, `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_STORE_URL`

**Requires in `config/`:** `translation_guidelines.md` (your custom guidelines — do not delete)

### E1: Validate

```bash
cd ~/Documents/SEO\ Agent\ Workflow
python3 translation_workflow.py --validate <doc_id>
```

This checks the doc ID format and confirms the service account can access the doc. If it fails, stop and report the error. Do not continue.

### E2: Translate all 8 languages

```bash
cd ~/Documents/SEO\ Agent\ Workflow
python3 translation_workflow.py --resume <doc_id>
```

This runs 8 translation tasks sequentially, one language at a time. Total runtime typically 5–7 minutes for all 8 languages. Stream all output to the user as it arrives. Each line reports a language completing (✓) or failing (✗).

The workflow:
1. Fetches the English blog from Drive
2. Loads `config/translation_guidelines.md`
3. Connects to Shopify Admin API (replaces legacy CSV URL lookup)
4. Translates into FR, DE, ES, IT, NL, PL, SL, PT sequentially
5. Localizes internal links via Shopify API queries (three-branch logic)
6. Runs 5 validation checks per translation
7. Saves each translated doc to the same Drive folder as the source
8. Sends an email summary to `NOTIFY_EMAIL`
- Research bundle JSON (if present in the cluster folder from Deep mode) is not passed to translation tasks and does not affect this workflow.

### E3: Report results

After the command completes, present the output as a table:

```
| Language   | Status  | Doc Link | Flags |
|------------|---------|----------|-------|
| French     | ✓       | [link]   | 2W    |
| German     | ✓       | [link]   | 5W    |
| ...        |         |          |       |
```

If any language failed, show the error message. The email has already been sent with the same summary.

**Single-language dry run (for testing):**
```bash
python3 translation_workflow.py --dry-run --lang fr <doc_id>
```

---

## Rules

1. **Never reinvoke the Semrush scraper in Mode B.** Missing cached files = incomplete run, not a trigger to re-scrape.

2. **Always pass `guideline.md` to seo-blog-writer.** Read `keyword_forge/guideline.md` and include it as style context.

3. **Invoke skills via the Skill tool.** Never reimplement clustering, LSI, brief, or blog logic inline.

4. **Never overwrite `blog.md` without confirmation.** Always check first.

5. **One cluster per invocation.** Multiple blogs = multiple invocations.

6. **Fail loudly.** Any stage failure → stop, report exact error, name the stage.

7. **Preserve original cluster IDs in Mode B.** Never renumber.

8. **Mode E: always run `--validate` before `--resume`.** If validation fails, stop and report — do not continue to translation.

9. **Mode E: never modify `config/translation_guidelines.md`.** It is the user's curated file. Never overwrite, replace, or regenerate it.

10. **Deep mode requires ≥ 10 sources.** If web research returns fewer than 10 unique sources, stop and report — do not generate a draft with insufficient grounding.

11. **Never auto-select deep mode.** The user always picks S or D explicitly at the selection prompt. Do not infer research mode from cluster difficulty, keyword count, or any other heuristic.
