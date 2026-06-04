# Legendary Parts — seo-forge

Multilingual SEO content pipeline for Legendary Parts. Generates keyword-clustered,
SEO-optimized Harley-Davidson blog posts, translates them into eight European
languages, and publishes them to Shopify as hidden drafts — driven end-to-end by a
Trello-based poller.

## What it does

1. Cluster keywords and build a content brief for a topic.
2. Write a structured, source-backed blog post (FR is the source locale).
3. Publish the source to Google Drive and open a Trello card.
4. On validation, translate into 8 locales and publish all of them to Shopify.

Source locale: **fr**. Translations: **en, de, es, it, nl, pl, pt, sl**
(English uses a rename trick — the finished English original is renamed with an
`--en` suffix and published without AI translation).

## Pipeline stages

The pipeline is **poller-driven**, not a single script. `trello_poller.py` watches
Trello cards and advances them stage by stage.

| Stage | What happens | Trigger |
|-------|--------------|---------|
| 8  | Publish source blog to Google Drive + open a Trello card | manual / on completion of writing |
| 9  | Comment resolution | fires when both Trello validation boxes are ticked |
| 10 | Translation (`translation_workflow.py --resume`) — runs detached | fires after Stage 9 |
| 11 | Shopify publish + `translationsRegister` | auto-wired inline at the end of Stage 10's success path |

### Failure handling

Stage 10 runs as a detached subprocess, so the poller can't watch it directly.
Instead the workflow reports its own outcome:

- On a crash it moves its Trello card to the **"Failed translation"** list and marks
  it `failed_error` in `trello_state.db`.
- This is distinct from `failed_stale`, the 14-day staleness timeout.
- `cmd_retry` treats both the same — a failed card moves back to "Blog drafts",
  validation boxes are unchecked, and the staleness clock resets.

Run a retry with:

```bash
python3 trello_gate.py retry <doc_id>
```

## Running it

The pipeline is invoked from Claude Code via the `/seo-forge` command
(`.claude/commands/seo-forge.md`) or natural-language triggers. VS Code must be
opened from the **project root** or the slash command won't resolve.

To run the poller directly:

```bash
# from project root, using the project venv
keyword_forge/.venv/bin/python trello_poller.py --interval <seconds>
```

> Translation (Stage 10) requires the venv interpreter at
> `keyword_forge/.venv/bin/python` — system Python lacks the translation
> dependencies, and the workflow will fail fast if the venv is missing.

## Environment variables

Set in `.env` (gitignored).

| Variable | Purpose |
|----------|---------|
| `SHOPIFY_CLIENT_ID` | Shopify client-credentials auth |
| `SHOPIFY_CLIENT_SECRET` | Shopify client-credentials auth (→ 24hr token) |
| `SHOPIFY_BLOG_ID` | Target blog (`98568634712`) |
| `SHOPIFY_API_VERSION` | Shopify API version (`2026-04`) |
| `TRANSLATIONS_FOLDER_ID` | Google Drive folder holding translated docs |
| `DEEPSEEK_API_KEY` | Translation engine (DeepSeek, via openai>=1.0 client) |
| `TRELLO_API_KEY` / `TRELLO_API_TOKEN` | Trello board access |

Google Drive access uses a service-account JSON (path referenced in config, never
committed) with `supportsAllDrives=True` for Shared Drive items.

## Project layout

```
translation_workflow.py         # Stage 10 entrypoint
trello_poller.py                # poller loop
trello_gate.py                  # stage gating + retry (cmd_retry lives here)
app/services/
  translation_doc_writer.py     # final HTML write (strips [EN:] locale annotations)
  drive_reader.py               # Drive-native blog reading
  url_localizer.py              # internal-link localization
workflows/Publishers/
  shopify_publisher.py          # Stage 11 publish
  drive_fetcher.py              # Drive file fetch helpers
trello_state.db                 # live poller state (SQLite, gitignored)
.claude/commands/seo-forge.md   # /seo-forge command
```

## Notes

- `trello_state.db` is live state and should stay gitignored — it churns on every
  poller tick.
- Translation engine is DeepSeek as of the May–June 2026 migration. (The
  `TRANSLATION_MODEL` footer on translated docs may still show the old model name —
  cosmetic, fix pending.)
