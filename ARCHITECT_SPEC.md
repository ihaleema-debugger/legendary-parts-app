# Keyword Forge — Architect Specification

**For:** Claude Code
**Deliverable:** A standalone Python package that turns keyword gap exports into SEO-optimized blog drafts, with a CLI, a folder-watch mode, and a slash command.
**Constraint:** Structure the code so it can later be lifted into the KeyGap + Inkwell monorepo as `keygap/modules/forge/` with minimal refactor.

---

## 1. What you're building

A pipeline that:

1. Picks up a keyword gap export (`.csv`, `.xlsx`, or `.tsv`) from an inbox folder.
2. Parses it into normalized keyword records (keyword + volume + difficulty + CPC).
3. Asks Claude to group the keywords into semantic clusters — one cluster per distinct search intent.
4. For each cluster, asks Claude to generate 25-30 LSI (Latent Semantic Indexing) keywords.
5. For each cluster, asks Claude to write a ~700-word SEO blog draft following a user-provided shared guideline.
6. Writes each draft as a Markdown file with YAML frontmatter, plus a `manifest.json` summarizing the run.
7. Moves the source file to a `processed/` folder so it isn't re-processed.

Two entry points:

- **Manual:** `forge run path/to/file.csv`
- **Watch:** `forge watch` — polls the inbox folder and runs the pipeline whenever a new file lands.

Plus a Claude Code slash command `/keyword-forge` that wraps the CLI and handles preflight checks.

---

## 2. Non-negotiables

- **Single-purpose stage functions.** `parse_file`, `cluster_keywords`, `generate_lsis`, `write_blog`, and `export_run` must be pure(ish) functions that take data + config and return data. No file I/O inside the stage functions — file I/O lives in `pipeline.py`, `watcher.py`, `exporter.py`, and `cli.py` only. This is what makes the later KeyGap lift trivial.
- **Prompts live in markdown files**, not hardcoded in Python. Path: `prompts/*.md`. The writer must be able to edit a prompt without touching code.
- **Guideline is a single shared file** (`guideline.md`) loaded once per run. One blog per cluster, all blogs use the same guideline.
- **Retries on transient API failures.** 4xx client errors except 429 should fail fast; 429 and 5xx retry with exponential backoff, max 3 attempts.
- **Per-cluster failures must not abort the run.** Record in manifest, continue with remaining clusters.
- **Idempotent watcher.** A file is only processed once, on the poll tick *after* its size has stopped changing (avoids catching mid-upload files).
- **Config via `.env` with CLI flag overrides.** No values hardcoded in source.

---

## 3. Directory layout

Build exactly this structure:

```
keyword_forge/
├── .claude/
│   └── commands/
│       └── keyword-forge.md          # slash command prompt
├── keyword_forge/                    # importable package (same name as project root is fine)
│   ├── __init__.py                   # re-exports public API
│   ├── cli.py                        # Typer app — `forge` entrypoint
│   ├── config.py                     # env loading, path resolution, defaults
│   ├── models.py                     # pydantic: Keyword, Cluster, Run, RunConfig
│   ├── parser.py                     # CSV/XLSX → list[Keyword]
│   ├── anthropic_client.py           # thin Anthropic SDK wrapper with retries + JSON extraction
│   ├── clusters.py                   # cluster_keywords(keywords, cfg) → list[Cluster]
│   ├── lsi.py                        # generate_lsis(cluster, cfg) → list[str]
│   ├── writer.py                     # write_blog(cluster, cfg) → (markdown, word_count, warnings)
│   ├── exporter.py                   # export_run(run) → writes files to data/output/<run_id>/
│   ├── pipeline.py                   # run_pipeline(source, cfg) — orchestrator
│   └── watcher.py                    # watch(cfg) — folder-poll loop
├── prompts/
│   ├── cluster_system.md             # has {tightness_hint} placeholder
│   ├── lsi_system.md
│   └── writer_system.md
├── tests/
│   ├── __init__.py
│   ├── test_parser.py
│   ├── test_clusters.py              # mocks anthropic_client.call
│   └── fixtures/
│       └── sample_gap.csv
├── data/
│   ├── inbox/       (empty, gitkeep)
│   ├── processed/   (empty, gitkeep)
│   └── output/      (empty, gitkeep)
├── guideline.md                      # placeholder SEO guideline, user edits this
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
└── SPEC.md                           # this document, copied in verbatim
```

---

## 4. Data models (`keyword_forge/models.py`)

Use Pydantic v2. Define:

**`Keyword`**
- `keyword: str`
- `volume: int = 0`
- `difficulty: float = 0.0`
- `cpc: float = 0.0`
- `raw: dict` (the original row, preserved)

**`Cluster`**
- `id: str` (8-char hex, default-generated)
- `name: str`
- `keywords: list[str]`
- `lsis: list[str] = []`
- `blog_markdown: str = ""`
- `word_count: int = 0`
- `error: str | None = None`
- property `primary_keyword` → `keywords[0]` or `name` fallback
- method `aggregate(lookup: dict[str, Keyword]) -> dict` returning `{volume, avg_difficulty, avg_cpc}`

**`RunConfig`**
- `model: str = "claude-sonnet-4-5"`
- `tightness: Literal["loose","balanced","tight"] = "balanced"`
- `lsi_count: int = 28`
- `word_count: int = 700`
- `max_concurrent: int = 3`
- `strict: bool = False`
- `keyword_column: str = "auto"`
- `guideline: str = ""` (populated from file at pipeline start)

**`Run`**
- `id: str` — format `YYYYMMDD-HHMMSS-<6 hex chars>`
- `source_file: str`
- `started_at: datetime`
- `finished_at: datetime | None`
- `config: RunConfig`
- `keywords: list[Keyword]`
- `clusters: list[Cluster]`
- `failures: list[dict]`
- `warnings: list[str]`
- method `manifest(output_dir: Path) -> dict` — the dict serialized into `manifest.json`

Manifest shape:

```json
{
  "run_id": "...",
  "source_file": "...",
  "model": "...",
  "tightness": "balanced",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 12.3,
  "keyword_count": 180,
  "cluster_count": 14,
  "blog_count": 13,
  "total_words": 9100,
  "clusters": [
    {"id":"...","name":"...","keyword_count":5,"lsi_count":28,"word_count":712,"has_blog":true,"error":null}
  ],
  "failures": [],
  "warnings": [],
  "output_dir": "..."
}
```

---

## 5. Configuration (`keyword_forge/config.py`)

- Load `.env` at import time with `python-dotenv`.
- Resolve project root by walking up from `cwd` looking for a directory that contains both `pyproject.toml` and `guideline.md`. Fall back to `cwd`.
- Expose these functions: `api_key()`, `inbox_dir()`, `output_dir()`, `processed_dir()`, `guideline_path()`, `watch_interval()`, `load_guideline()`, `load_prompt(name)`, `default_run_config()`, `ensure_dirs()`.
- `api_key()` raises `RuntimeError` with a clear message if `ANTHROPIC_API_KEY` is missing.
- `load_guideline()` raises if the file is missing or under 100 chars (treats sub-100 as placeholder).
- `load_prompt(name)` reads `prompts/{name}.md` and raises if missing.

**`.env.example`:**
```
ANTHROPIC_API_KEY=sk-ant-...
FORGE_MODEL=claude-sonnet-4-5
FORGE_CLUSTER_TIGHTNESS=balanced
FORGE_LSI_COUNT=28
FORGE_WORD_COUNT=700
FORGE_INBOX_DIR=./data/inbox
FORGE_OUTPUT_DIR=./data/output
FORGE_PROCESSED_DIR=./data/processed
FORGE_GUIDELINE_PATH=./guideline.md
FORGE_WATCH_INTERVAL=10
FORGE_MAX_CONCURRENT=3
FORGE_KEYWORD_COLUMN=auto
```

---

## 6. Parser (`keyword_forge/parser.py`)

**Public:** `parse_file(path: Path | str, keyword_column: str = "auto") -> list[Keyword]`

Behavior:

- Read based on extension: `.csv` → `pd.read_csv`, `.tsv` → `pd.read_csv(sep="\t")`, `.xlsx`/`.xls` → `pd.read_excel`. All with `dtype=str, keep_default_na=False`.
- Detect keyword column: prefer exact case-insensitive match on `"Keyword"`, then regex `/keyword/i`, then fall back to column 0.
- Detect metric columns by regex (case-insensitive): volume `(volume|search[\s_]*vol)`, difficulty `(difficulty|\bkd\b)`, CPC `\bcpc\b`.
- Coerce numeric strings: strip commas, `$`, whitespace. Fall back to 0 on failure (never raise).
- Deduplicate by `keyword.lower().strip()`, keeping first occurrence.
- Skip empty keyword cells.

Also expose helper: `keyword_lookup(keywords) -> dict[str, Keyword]` keyed by lowercased keyword.

---

## 7. Anthropic client (`keyword_forge/anthropic_client.py`)

Thin wrapper. Do NOT write a full SDK; use the official `anthropic` package.

**Public:**
- `call(system: str, user: str, *, model: str, max_tokens: int = 4000, max_retries: int = 3) -> str` — returns concatenated text from response content blocks.
- `extract_json(text: str) -> Any` — tries direct `json.loads`, then fenced ```` ```json ... ``` ```` block, then first `[...]` match, then first `{...}` match. Raises `ValueError` with a truncated preview of the response if all fail.
- `ping(model: str) -> bool` — sends a one-word call and returns success bool (swallows exceptions).

Retry logic: on `APIStatusError` with status 400-499 that isn't 429, raise immediately. On any other `APIError` or 429/5xx, `time.sleep(2**attempt)` and retry.

Cache a module-level `Anthropic` client after first construction.

---

## 8. Clustering (`keyword_forge/clusters.py`)

**Public:** `cluster_keywords(keywords: list[Keyword], cfg: RunConfig) -> tuple[list[Cluster], list[str]]`

Returns `(clusters, warnings)`.

Behavior:

1. Return `([], [])` immediately if `keywords` is empty.
2. Build unique, sorted list of keyword strings.
3. Load `prompts/cluster_system.md`, substitute `{tightness_hint}` using this map:
   - `loose`: "Prefer fewer, broader clusters. Aim for 5-10 keywords per cluster; err on the side of merging."
   - `balanced`: "Aim for cohesive clusters of roughly 4-8 keywords each."
   - `tight`: "Prefer tighter, narrower clusters. Aim for 2-5 keywords per cluster; err on the side of splitting."
4. User message: `"Group these N keywords into semantic clusters:\n\n- kw1\n- kw2\n..."`.
5. Call Claude with `max_tokens=8000`.
6. Extract JSON. Accept both `{"clusters": [...]}` and bare `[...]`.
7. For each returned cluster: drop keywords not present in original input (log as warning). Skip clusters with empty `name` or `keywords`. Create `Cluster` objects.
8. Detect orphans (input keywords not placed in any cluster). If `cfg.strict`, raise. Otherwise, warn and dump them into a final `"Unclustered"` cluster so they aren't lost.

---

## 9. LSI generation (`keyword_forge/lsi.py`)

**Public:** `generate_lsis(cluster: Cluster, cfg: RunConfig) -> list[str]`

Behavior:

1. Load `prompts/lsi_system.md`.
2. User message: cluster name + seed keywords as bullets + explicit request for exactly `cfg.lsi_count` LSIs, with example shape `["lsi1","lsi2",...]`.
3. Call Claude with `max_tokens=2000`.
4. Extract JSON, verify it's a list.
5. Dedupe against seed keywords (case-insensitive), dedupe against each other (case-insensitive).
6. Trim to `cfg.lsi_count`.

Does NOT catch exceptions — the orchestrator handles per-cluster errors.

---

## 10. Blog writer (`keyword_forge/writer.py`)

**Public:** `write_blog(cluster: Cluster, cfg: RunConfig) -> tuple[str, int, list[str]]`

Returns `(markdown, word_count, warnings)`.

Behavior:

1. Load `prompts/writer_system.md`.
2. Build user message with: full `cfg.guideline`, separator, topic/primary keyword, target keywords bullets, LSI keywords bullets, word count target, and 5 explicit rules (follow guideline, primary in H1/first100/one H2, weave naturally, stay within ±10%, pure markdown).
3. Call Claude with `max_tokens=4000`.
4. Clean the response:
   - Unwrap a fence if the entire response is wrapped in ```` ```markdown ... ``` ```` or ```` ``` ... ``` ````.
   - If the response doesn't start with `#`, strip a leading "Here is..." preamble.
5. Word count: strip markdown syntax (`#*_`[]()\``) and count whitespace-separated tokens.
6. Warn if word count is outside ±15% of `cfg.word_count`.
7. Warn if `cluster.lsis` was empty.

---

## 11. Exporter (`keyword_forge/exporter.py`)

**Public:** `export_run(run: Run, log_lines: list[str] | None = None) -> Path`

Behavior:

1. Create `config.output_dir() / run.id` (recursive).
2. For each cluster with a non-empty `blog_markdown`: write `<slug>.md` containing YAML frontmatter + the markdown body.
3. Write `manifest.json` (pretty-printed, `default=str` for datetimes).
4. If `log_lines` provided, write `_run.log`.
5. Return the output directory path.

Slug function: lowercase, strip non-word/whitespace/hyphens, collapse whitespace/underscores to hyphens, trim leading/trailing hyphens, max 60 chars, fall back to `"untitled"`.

Frontmatter keys: `title`, `run_id`, `cluster_id`, `primary_keyword`, `target_keywords` (list), `lsi_keywords` (list), `word_count`, `aggregate_volume`, `aggregate_avg_difficulty`, `aggregate_avg_cpc`, `model`, `generated` (ISO timestamp), `source_file`.

---

## 12. Pipeline orchestrator (`keyword_forge/pipeline.py`)

**Public:**
- `run_pipeline(source_path: Path | str, cfg: RunConfig | None = None) -> Run`
- `archive_source(source: Path, run: Run, failed: bool = False) -> Path`

`run_pipeline` behavior:

1. Resolve `source` to absolute Path.
2. If `cfg` is None, use `config.default_run_config()`.
3. If `cfg.guideline` is empty, load from `config.load_guideline()`.
4. Create `Run` object. Initialize empty log list. Define a local `log_line(msg)` that prints AND appends to the list with ISO timestamp.
5. **Stage 1 — Parse:** `run.keywords = parser.parse_file(source, cfg.keyword_column)`. Log count + duration. If empty, add warning, finalize run with `exporter.export_run`, return.
6. **Stage 2 — Cluster:** call `clusters.cluster_keywords`, assign to `run.clusters`, extend warnings. Log.
7. **Stage 3 — LSI (parallel):** use `concurrent.futures.ThreadPoolExecutor(max_workers=cfg.max_concurrent)`. Submit `lsi.generate_lsis(c, cfg)` for each cluster. On success set `c.lsis`; on exception set `c.error = f"LSI failed: {e}"` and log. Do not abort.
8. **Stage 4 — Blogs (parallel):** same executor pattern, but skip clusters where `c.error` is set. On success set `c.blog_markdown` and `c.word_count`, extend `run.warnings` with writer warnings. On exception set `c.error`, append to `run.failures`.
9. Set `run.finished_at = datetime.now()`.
10. Call `exporter.export_run(run, log)`.
11. Return `run`.

`archive_source` behavior: ensure `processed_dir` exists, move source to `processed_dir / f"{run.id}-{source.name}{'.failed' if failed else ''}"`.

---

## 13. Watcher (`keyword_forge/watcher.py`)

**Public:** `watch(cfg: RunConfig | None = None) -> None` (blocks)

Behavior:

1. Install SIGINT and SIGTERM handlers that set a module-level `_shutdown` flag.
2. Resolve `cfg`, ensure dirs exist.
3. Maintain `known_sizes: dict[Path, int]` across iterations.
4. Loop until `_shutdown`:
   a. Enumerate inbox files with supported extensions (`.csv`, `.xlsx`, `.xls`, `.tsv`).
   b. For each file, record current size. If same file was seen with the same (non-zero) size last tick, mark it stable.
   c. Replace `known_sizes` with the current tick's map.
   d. For each stable file:
      - Call `run_pipeline(path, cfg)`.
      - Compute `failed = bool(run.failures) or not any(c.blog_markdown for c in run.clusters)`.
      - Call `archive_source(path, run, failed)`.
      - Log outcome. On catastrophic exception from `run_pipeline`, log but do NOT archive — leave the file for manual inspection.
   e. Sleep `watch_interval()` seconds in 1-second ticks so shutdown is responsive.
5. Print "exited cleanly" on loop exit.

---

## 14. CLI (`keyword_forge/cli.py`)

Use Typer + Rich. Entry point `forge = keyword_forge.cli:app` in `pyproject.toml`.

**Commands:**

- `forge run <file>` — flags: `--model`, `--tightness`, `--lsi-count`, `--word-count`, `--max-concurrent`, `--strict`, `--keyword-column`, `--archive/--no-archive` (default true). Calls `run_pipeline`, optionally archives, prints a Rich table summary.
- `forge watch` — same flags as `run` (minus file/keyword-column/archive). Calls `watcher.watch`.
- `forge clusters <file>` — parse + cluster only, print cluster JSON to stdout. Useful for iterating on the clustering prompt without spending LSI/writer tokens.
- `forge guideline show` — print guideline to stdout.
- `forge guideline edit` — open `guideline.md` in `$EDITOR` (default `nano`).
- `forge doctor` — preflight check. Rich table with rows for: API key present, guideline loaded, each prompt file loaded, data dirs exist, API ping succeeds. Exit 1 on any red row.

Summary table after `forge run`: columns `cluster | kw | lsi | words | status` (✓ / no blog / error). Followed by warnings list (truncated to 10), failures list, and final `Output: <path>` line.

---

## 15. Prompts

Write these three files. They need to work well as-is but be easy to iterate on.

**`prompts/cluster_system.md`:**

```
You are an expert SEO strategist specializing in keyword topic modeling. Your task is to group keywords into SEMANTIC CLUSTERS where each cluster represents ONE distinct search intent or subtopic that could become ONE blog post.

## Rules

- Every input keyword must appear in exactly one cluster.
- Cluster names are short, descriptive topic labels (3-6 words). Avoid brand names unless they're core to the intent. Avoid starting with "Best" or "Top" — those are article titles, not topic labels.
- {tightness_hint}
- Near-duplicates, plurals, and keywords sharing a core informational or transactional intent belong together.
- Avoid catch-all or "miscellaneous" clusters. A 1-2 keyword cluster is acceptable when the intent is genuinely distinct.

## Output

Return ONLY valid JSON. No preamble, no markdown code fences.

Shape: {"clusters": [{"name": "...", "keywords": ["kw1","kw2"]}]}
```

**`prompts/lsi_system.md`:**

```
You are an SEO expert generating LSI (Latent Semantic Indexing) keywords — semantically related terms that reinforce topic relevance without being exact-match duplicates of the seeds.

## Good LSIs include
- Synonyms and near-synonyms
- Related entities (brands, models, part numbers, specs)
- Co-occurring terms from the same semantic field
- Contextual modifiers (material, use case, compatibility, size)
- Question-based variations ("how to", "what is", "why does")

## Avoid
- Exact-match duplicates of seed keywords
- Generic filler ("information about", "guide to")
- LSIs that pull toward a different cluster's intent

## Output
Return ONLY a valid JSON array of strings. No preamble, no fences.
Example: ["first lsi", "second lsi", ...]
```

**`prompts/writer_system.md`:**

```
You are a senior SEO content writer producing publication-ready drafts.

## Strict requirements
- Follow the user's SEO GUIDELINE block exactly. It overrides any default you would otherwise apply.
- Output pure Markdown. No code fences around the whole post. No "Here is..." preamble. No closing meta-commentary.
- Start directly with the H1.
- Use the primary keyword in the H1, within the first 100 words of body text, and in at least one H2.
- Weave target keywords naturally. Never stuff.
- Distribute LSI keywords across the body for semantic depth. One-off mentions are fine; forced repetition is not.
- Hit the target word count within ±10%.

## Quality bar
- Every paragraph earns its place. Cut hedges and throat-clearing.
- Assume the reader is intelligent and already interested — no clickbait, no aggressive CTAs, no exclamation marks unless the guideline asks for them.
- Specific beats generic: concrete part numbers, measurements, compatibility notes beat vague reassurance.

## Output
Pure Markdown, starting with `# <title>`. Nothing else.
```

---

## 16. Slash command (`.claude/commands/keyword-forge.md`)

YAML frontmatter:

```yaml
---
description: Run the Keyword Forge pipeline on a keyword gap export (or start watch mode).
argument-hint: "[file-path | watch | inbox]"
---
```

Body tells Claude Code to:

1. **Preflight silently:** confirm project root (look for `SPEC.md` + `pyproject.toml`); create `.venv` if missing; `pip install -e .` if not installed; check `.env` exists (copy from `.env.example` and stop if missing API key); check `guideline.md` has >100 real chars (warn if placeholder); run `.venv/bin/forge doctor` and surface errors.
2. **Interpret `$ARGUMENTS`:**
   - Empty or `watch` → run `forge watch`, stream output, tell user Ctrl+C stops it.
   - File path with `.csv`/`.xlsx`/`.tsv` → `forge run <path>`.
   - `inbox` or directory path → list files in `data/inbox/` and ask which to process or offer watch mode.
   - Anything else → answer conversationally, don't run.
3. **After `forge run`:** read `data/output/<run-id>/manifest.json`. Summarize: run ID, cluster count, blog count, total words, failures, output path. List blog filenames with cluster names + word counts. Don't echo full blog contents.
4. **Behavior rules:** don't reinstall deps every invocation; surface `_run.log` lines on error; never `git commit`/`push` unprompted; for one-off setting tweaks pass CLI flags rather than editing `.env`.

---

## 17. Supporting files

**`guideline.md`:** placeholder with clear comment that user must replace it. Include a Legendary Parts-flavored example so Haleema can see the expected shape (tone rules, structure rules, linking rules, prohibited phrasing, audience). Must be over 100 chars so `doctor` passes.

**`.gitignore`:** `.venv/`, `.env`, `__pycache__/`, `*.pyc`, `data/inbox/*`, `data/processed/*`, `data/output/*`, `!data/**/.gitkeep`, `.DS_Store`, `.pytest_cache/`, `*.egg-info/`.

**`pyproject.toml`:**
- Python ≥3.10
- Deps: `anthropic>=0.40`, `pydantic>=2.5`, `typer>=0.12`, `rich>=13.7`, `pandas>=2.1`, `openpyxl>=3.1`, `python-dotenv>=1.0`
- Dev extras: `pytest>=7.4`, `pytest-mock>=3.12`, `ruff>=0.4`
- Script: `forge = keyword_forge.cli:app`

**`README.md`:** install steps (clone, venv, `pip install -e .`, copy `.env.example` → `.env`, add API key, edit `guideline.md`), usage examples for each CLI command, a diagram of the data flow, a short "how to slot this into KeyGap later" section.

---

## 18. Tests

Two test files with real coverage, not smoke tests.

**`tests/fixtures/sample_gap.csv`:** 15-20 rows, columns `Keyword,Search Volume,KD,CPC`, realistic Legendary Parts-style data (motorcycle parts: batteries, tires, oil filters, etc.), including 2 duplicate keyword rows and 1 row with an empty keyword cell.

**`tests/test_parser.py`:**
- parses the fixture, returns expected count after dedupe
- volumes and difficulties are correctly coerced to numeric
- empty-keyword row is dropped
- duplicate keyword is dropped (first wins)
- explicit `keyword_column` override works
- invalid `keyword_column` raises `ValueError`

**`tests/test_clusters.py`:**
- mocks `anthropic_client.call` to return a known JSON string
- verifies clusters are built correctly
- verifies orphan handling: orphans go into `"Unclustered"` in non-strict mode
- verifies `strict=True` raises on orphans
- verifies dropped-keyword warning fires when Claude returns a keyword not in input

---

## 19. Build order

Build in this order. Commit after each numbered step. After each commit, run `pytest` (from step 3 onward) and confirm green before moving on.

1. `pyproject.toml`, `.env.example`, `.gitignore`, `guideline.md` placeholder, empty `data/` dirs with `.gitkeep`, `SPEC.md` (this file), `README.md` skeleton.
2. `models.py`, `config.py`, `__init__.py`.
3. `parser.py` + `tests/fixtures/sample_gap.csv` + `tests/test_parser.py`. Run tests.
4. `anthropic_client.py`. Manually test with a tiny `ping()` script.
5. Write all three prompts in `prompts/`.
6. `clusters.py` + `tests/test_clusters.py` (mocked). Run tests.
7. `lsi.py`.
8. `writer.py`.
9. `exporter.py`.
10. `pipeline.py`.
11. `cli.py` with just `run`, `doctor`, `guideline`, `clusters` commands. Test end-to-end with a small real CSV.
12. `watcher.py` + `forge watch` command. Test by dropping a file into inbox while watcher runs.
13. `.claude/commands/keyword-forge.md`.
14. Polish README with real usage examples.

---

## 20. Success criteria

You're done when all of these are true:

- `forge doctor` shows all green on a fresh clone (after `.env` + guideline are filled in).
- `forge run tests/fixtures/sample_gap.csv` completes without crashing, writes a `manifest.json` and at least one `.md` file per cluster to `data/output/<run_id>/`.
- `forge watch` picks up a file dropped into `data/inbox/` on the next poll tick, processes it, and moves it to `data/processed/`.
- `forge clusters <file>` prints valid JSON to stdout.
- All tests pass.
- The slash command `/keyword-forge data/inbox/sample_gap.csv` works end-to-end from inside Claude Code.
- Running `ruff check .` produces zero errors.

---

## 21. Future-proofing notes (don't implement, just don't block)

- **LiteLLM swap:** `anthropic_client.py` should be the ONLY file that imports from the `anthropic` package. When we later swap to LiteLLM for multi-provider routing, only this file changes.
- **Celery-readiness:** `parse_file`, `cluster_keywords`, `generate_lsis`, `write_blog`, `export_run` must not read/write globals or config at call time — everything they need comes in via arguments. This is what makes each a trivial `@celery.task`.
- **DB-readiness:** the `Run` pydantic model should serialize cleanly to a Postgres `jsonb` column. Don't introduce non-serializable fields.

---

**End of specification.** Build it.
