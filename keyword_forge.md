# Keyword Forge — Project Progress

**Location:** `/Users/mac/Documents/SEO Agent Workflow/keyword_forge/`
**Status:** Complete — all 14 tasks built, tests passing, ruff clean
**Built:** 2026-04-17

---

## What It Does

Takes keyword gap CSV/XLSX/TSV exports and runs them through a 4-stage pipeline:

1. **Parse** — reads the file, normalises columns, deduplicates
2. **Cluster** — asks Claude to group keywords by search intent
3. **LSI** — asks Claude to generate latent semantic indexing keywords per cluster
4. **Write** — asks Claude to write a ~700-word SEO blog draft per cluster

Outputs: one `.md` file per cluster (YAML frontmatter + blog body) + `manifest.json` + `_run.log`

---

## Quick Start

```bash
cd "/Users/mac/Documents/SEO Agent Workflow/keyword_forge"
source .venv/bin/activate

# Add your API key first (blank in .env by default)
# Edit .env → ANTHROPIC_API_KEY=sk-ant-...

forge doctor                              # Preflight — should be all green
forge run tests/fixtures/sample_gap.csv  # End-to-end test with fixture
forge watch                              # Watch data/inbox/ for new files
forge clusters data/inbox/file.csv      # Cluster only (no blog writing)
forge guideline show                     # View/edit content guideline
```

---

## File Map

```
keyword_forge/
├── .claude/commands/keyword-forge.md   # /keyword-forge slash command
├── keyword_forge/                      # Importable Python package
│   ├── __init__.py                     # Public API re-exports
│   ├── cli.py                          # Typer CLI (forge entrypoint)
│   ├── config.py                       # .env loading, path resolution
│   ├── models.py                       # Pydantic: Keyword, Cluster, Run, RunConfig
│   ├── parser.py                       # CSV/XLSX/TSV → list[Keyword]
│   ├── anthropic_client.py             # Anthropic SDK wrapper + retries + JSON extract
│   ├── clusters.py                     # cluster_keywords() → list[Cluster]
│   ├── lsi.py                          # generate_lsis() → list[str]
│   ├── writer.py                       # write_blog() → (markdown, word_count, warnings)
│   ├── exporter.py                     # export_run() → writes data/output/<run_id>/
│   ├── pipeline.py                     # run_pipeline() orchestrator (parallel stages)
│   └── watcher.py                      # watch() folder-poll loop
├── prompts/
│   ├── cluster_system.md               # Clustering prompt ({tightness_hint} placeholder)
│   ├── lsi_system.md                   # LSI generation prompt
│   └── writer_system.md               # Blog writing prompt
├── tests/
│   ├── test_parser.py                  # 7 tests (TDD)
│   ├── test_clusters.py               # 5 tests (mocked anthropic_client)
│   └── fixtures/sample_gap.csv        # 15 motorcycle parts keywords
├── data/
│   ├── inbox/                          # Drop files here for forge watch
│   ├── processed/                      # Archived after processing
│   └── output/                         # Run outputs (gitignored)
├── guideline.md                        # Legendary Parts SEO guideline (edit this)
├── pyproject.toml                      # Python >=3.9, deps, forge entrypoint
├── .env.example                        # Copy to .env, add ANTHROPIC_API_KEY
└── SPEC.md                             # Full architect specification
```

---

## CLI Commands

| Command | What it does |
|---------|-------------|
| `forge run <file>` | Full pipeline: parse → cluster → LSI → blog → export |
| `forge watch` | Poll `data/inbox/` every 10s, process new files automatically |
| `forge clusters <file>` | Parse + cluster only (no LSI/blog — cheap for prompt tuning) |
| `forge guideline show` | Print current SEO guideline |
| `forge guideline edit` | Open guideline.md in $EDITOR |
| `forge doctor` | Preflight check (API key, guideline, prompts, dirs, ping) |

**Common flags for `forge run`:**
```bash
--model claude-opus-4-6     # Override model
--tightness tight           # loose / balanced / tight
--word-count 900            # Target blog length
--lsi-count 20              # LSI keywords per cluster
--no-archive                # Don't move source to processed/
--strict                    # Fail if any keywords are unclustered
```

---

## Configuration

All config via `.env` — never edit source for one-off tweaks, use CLI flags instead.

| Env var | Default | Description |
|---------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key |
| `FORGE_MODEL` | `claude-sonnet-4-5` | Claude model |
| `FORGE_CLUSTER_TIGHTNESS` | `balanced` | loose / balanced / tight |
| `FORGE_LSI_COUNT` | `28` | LSI keywords per cluster |
| `FORGE_WORD_COUNT` | `700` | Target blog word count |
| `FORGE_WATCH_INTERVAL` | `10` | Seconds between inbox polls |
| `FORGE_MAX_CONCURRENT` | `3` | Parallel API calls |
| `FORGE_INBOX_DIR` | `./data/inbox` | Watch folder |
| `FORGE_OUTPUT_DIR` | `./data/output` | Output folder |
| `FORGE_PROCESSED_DIR` | `./data/processed` | Archived sources |

---

## Architecture Notes

- **Stage functions are pure-ish** — `parse_file`, `cluster_keywords`, `generate_lsis`, `write_blog`, `export_run` take data + config and return data. No globals, no file I/O inside stages. Ready for Celery.
- **`anthropic_client.py` is the only file that imports `anthropic`** — swap to LiteLLM later by changing this one file.
- **Prompts are editable markdown** — `prompts/*.md`. Writer/prompt-tuning doesn't require touching Python.
- **Retry logic**: 429 and 5xx retry with exponential backoff (max 3 attempts). Other 4xx fail fast.
- **Per-cluster failures don't abort the run** — errors recorded in manifest, run continues.
- **Watcher idempotency**: only processes a file once its size has been stable for one full poll tick (avoids catching mid-upload files).

---

## Test Results (as of build)

```
12 passed — tests/test_parser.py (7) + tests/test_clusters.py (5)
ruff check . — All checks passed
forge doctor — All green (requires ANTHROPIC_API_KEY in .env)
```

---

## One-time Setup (fresh clone)

```bash
cd "/Users/mac/Documents/SEO Agent Workflow/keyword_forge"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env → set ANTHROPIC_API_KEY
forge doctor
```

---

## Future / KeyGap Integration

When lifting into the `keygap/modules/forge/` monorepo:
- Move `keyword_forge/` to `keygap/modules/forge/`
- Update imports in `cli.py`, `pipeline.py`, `watcher.py`
- Stage functions need no changes — already Celery-ready
- `Run` pydantic model serialises cleanly to Postgres `jsonb`
