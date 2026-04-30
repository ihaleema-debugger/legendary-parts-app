#!/usr/bin/env python3
"""Translation workflow orchestrator.

Usage:
  python translation_workflow.py --resume <doc_id>
  python translation_workflow.py --validate <doc_id>
  python translation_workflow.py --dry-run --lang <lang_code> <doc_id>

The --resume flag is the primary entry point. It:
  1. Validates the doc ID and confirms Drive access
  2. Fetches the English blog from Drive
  3. Loads translation_guidelines.md (fails hard if missing/empty)
  4. Loads the product and blog URL lookup CSVs
  5. Runs 8 parallel translation tasks (ThreadPoolExecutor)
  6. Each task: translate → localize URLs → validate → save Google Doc
  7. After all complete: sends email summary
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
_ROOT = Path(__file__).parent
load_dotenv(_ROOT / ".env")

import sys
sys.path.insert(0, str(_ROOT))

from app.services import (
    drive_reader,
    translator as translator_mod,
    url_localizer,
    translation_validator,
    translation_doc_writer,
    notifier,
)
from app.services.shopify_mcp import ShopifyMCPClient
from app.services.drive_reader import get_doc_parent_folder

_TASK_TIMEOUT = 600  # 10 minutes per language

LANGUAGES = {
    "fr": "French (France)",
    "de": "German (Germany)",
    "es": "Spanish (Spain)",
    "it": "Italian (Italy)",
    "nl": "Dutch (Netherlands)",
    "pl": "Polish (Poland)",
    "sl": "Slovenian (Slovenia)",
    "pt": "Portuguese (Portugal)",
}

_DOC_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{20,60}$")


def validate_doc(doc_id: str) -> None:
    """Validate doc_id format and Drive accessibility. Exits on error."""
    if not _DOC_ID_RE.match(doc_id):
        _die(
            f"Invalid doc ID: {doc_id!r}\n"
            "Google Doc IDs are typically 20–44 alphanumeric characters (plus - and _)."
        )
    print(f"Validating access to doc {doc_id!r}...")
    try:
        title = drive_reader.get_doc_title(doc_id)
    except RuntimeError as e:
        _die(str(e))
    print(f"✓ Doc found: {title!r}")


def orchestrate(doc_id: str, dry_run: bool = False, single_lang: Optional[str] = None) -> None:
    """Run the full translation workflow for all 8 languages (or a single one in dry-run)."""
    model = os.environ.get("TRANSLATION_MODEL", "claude-sonnet-4-6")

    # ── Preflight ─────────────────────────────────────────────────────────────
    print(f"\n{'DRY RUN — ' if dry_run else ''}Fetching English blog from Drive...")
    try:
        blog = drive_reader.fetch_doc(doc_id)
    except RuntimeError as e:
        _die(str(e))

    original_slug = blog["slug"]
    print(f"  Title : {blog['title']!r}")
    print(f"  Slug  : {original_slug}")

    print("Loading translation guidelines...")
    try:
        guidelines = translator_mod.load_guidelines()
    except RuntimeError as e:
        _die(str(e))
    print(f"  Guidelines: {len(guidelines)} characters loaded")

    print("Connecting to Shopify...")
    try:
        shopify_client = ShopifyMCPClient()
        print("  ✓ Shopify client ready")
    except RuntimeError as e:
        print(f"  Warning: Shopify unavailable — {e}")
        print("  Internal links will be passed through unchanged.")
        shopify_client = None

    print("Resolving target Drive folder...")
    folder_id = get_doc_parent_folder(doc_id) or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        print("  Warning: could not determine Drive folder; translated docs will be placed in root")
    else:
        print(f"  Folder ID: {folder_id}")

    langs_to_run = {single_lang: LANGUAGES[single_lang]} if single_lang else LANGUAGES
    print(f"\nStarting translation into {len(langs_to_run)} language(s) with model {model!r}...\n")

    # ── Parallel task execution ───────────────────────────────────────────────
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(3, len(langs_to_run))) as executor:
        future_to_lang = {
            executor.submit(
                _run_language_task,
                lang_code=lang_code,
                lang_name=lang_name,
                blog=blog,
                guidelines=guidelines,
                shopify_client=shopify_client,
                source_doc_id=doc_id,
                original_slug=original_slug,
                folder_id=folder_id,
                model=model,
                dry_run=dry_run,
            ): lang_code
            for lang_code, lang_name in langs_to_run.items()
        }

        for future in as_completed(future_to_lang):
            lang_code = future_to_lang[future]
            lang_name = LANGUAGES[lang_code]
            try:
                result = future.result(timeout=_TASK_TIMEOUT)
                results.append(result)
                if result["status"] == "success":
                    flag_count = len(result.get("flags", []))
                    print(f"  ✓ {lang_name} ({lang_code.upper()}) — {flag_count} flag(s) — {result.get('doc_url', '')}")
                else:
                    print(f"  ✗ {lang_name} ({lang_code.upper()}) — FAILED: {result.get('error', '?')}")
            except FuturesTimeoutError:
                results.append({
                    "lang": lang_code,
                    "status": "failed",
                    "doc_id": None,
                    "doc_url": None,
                    "flags": [],
                    "error": f"Task timed out after {_TASK_TIMEOUT}s",
                })
                print(f"  ✗ {lang_name} ({lang_code.upper()}) — TIMEOUT")
            except Exception as e:
                results.append({
                    "lang": lang_code,
                    "status": "failed",
                    "doc_id": None,
                    "doc_url": None,
                    "flags": [],
                    "error": str(e),
                })
                print(f"  ✗ {lang_name} ({lang_code.upper()}) — ERROR: {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    successes = sum(1 for r in results if r["status"] == "success")
    print(f"\n{'─' * 60}")
    print(f"Translation complete: {successes}/{len(results)} succeeded")

    if dry_run:
        print("(Dry run — no docs saved, no email sent)")
        return

    # ── Email notification ────────────────────────────────────────────────────
    print("\nSending email summary...")
    try:
        notifier.send_summary(original_slug, doc_id, results)
        print(f"  ✓ Email sent to {os.environ.get('NOTIFY_EMAIL', '?')}")
    except RuntimeError as e:
        print(f"  Warning: email not sent — {e}")

    # ── Trello card completion update ─────────────────────────────────────────
    try:
        _update_trello_on_completion(doc_id, results)
    except Exception as e:
        print(f"  Warning: Trello update skipped — {e}")


def _update_trello_on_completion(doc_id: str, results: list) -> None:
    """Post a Trello comment with succeeded/failed language summary and conditionally move card."""
    from app.services.trello_state import TrelloState
    from app.services.trello_client import TrelloClient

    state = TrelloState()
    row = state.get_by_doc_id(doc_id)
    if not row or row["status"] != "handed_off":
        return

    done_list = os.environ.get("TRELLO_DONE_LIST_NAME", "Done")

    succeeded = [r["lang"] for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    n = len(succeeded)
    total = len(results)

    lines = [f"Translations complete: {n}/{total} succeeded\n"]

    if succeeded:
        lines.append(f"Succeeded: {', '.join(l.upper() for l in succeeded)}")

    for r in failed:
        err = r.get("error") or "unknown error"
        if len(err) > 80:
            err = err[:77] + "..."
        lines.append(f"Failed: {r['lang'].upper()} ({err})")

    if failed:
        lines.append(f"\nRe-run failed languages with: /seo-forge --resume {doc_id} --lang <code>")

    if n == 0:
        lines.append("\nAll translations failed — check logs.")

    comment = "\n".join(lines)

    client = TrelloClient()
    client.resolve_list_ids()
    client.add_comment(row["card_id"], comment)

    if n > 0:
        client.move_card_to_list(row["card_id"], done_list)
        state.mark_completed(doc_id)
        print(f"  ✓ Trello card moved to '{done_list}'")
    else:
        print("  ⚠ All translations failed — card left in Translating")


def _run_language_task(
    lang_code: str,
    lang_name: str,
    blog: dict,
    guidelines: str,
    shopify_client,
    source_doc_id: str,
    original_slug: str,
    folder_id: str,
    model: str,
    dry_run: bool,
) -> dict:
    """Translate, localize, validate, and save one language. Called in a thread."""
    print(f"  → Starting {lang_name} ({lang_code.upper()})...")

    try:
        # Step 1: Translate
        translated = translator_mod.translate_blog(
            blog=blog,
            lang_code=lang_code,
            lang_name=lang_name,
            guidelines=guidelines,
            model=model,
        )

        # Step 2: Localize URLs
        localized_body, inline_flags = url_localizer.localize_urls(
            body_markdown=translated["body_markdown"],
            lang_code=lang_code,
            shopify_client=shopify_client,
        )
        translated["body_markdown"] = localized_body

        # Step 3: Validate
        val_flags = translation_validator.validate(blog, translated, guidelines)

        all_flags = list(translated.get("flags", [])) + val_flags + inline_flags

        if dry_run:
            return {
                "lang": lang_code,
                "status": "success",
                "doc_id": None,
                "doc_url": None,
                "flags": all_flags,
                "error": None,
                "translated": translated,
            }

        # Step 4: Save to Drive
        file_meta = translation_doc_writer.save_translated_doc(
            translated=translated,
            validation_flags=val_flags,
            inline_flags=inline_flags,
            source_doc_id=source_doc_id,
            lang_code=lang_code,
            original_slug=original_slug,
            folder_id=folder_id,
            model=model,
        )

        return {
            "lang": lang_code,
            "status": "success",
            "doc_id": file_meta["id"],
            "doc_url": file_meta.get("webViewLink", ""),
            "flags": all_flags,
            "error": None,
        }

    except Exception as e:
        return {
            "lang": lang_code,
            "status": "failed",
            "doc_id": None,
            "doc_url": None,
            "flags": [],
            "error": str(e),
        }


def _die(message: str) -> None:
    print(f"\nError: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="SEO-Forge translation workflow")
    parser.add_argument("doc_id", nargs="?", help="Google Doc ID of the approved English blog")
    parser.add_argument("--resume", metavar="DOC_ID", help="Translate the approved English doc")
    parser.add_argument("--validate", metavar="DOC_ID", help="Validate doc ID and Drive access only")
    parser.add_argument("--dry-run", action="store_true", help="Translate without saving to Drive or sending email")
    parser.add_argument("--lang", metavar="LANG_CODE", help="Single language for dry-run (e.g. fr)")

    args = parser.parse_args()

    target_doc_id = args.resume or args.validate or args.doc_id
    if not target_doc_id:
        parser.print_help()
        sys.exit(1)

    if args.validate:
        validate_doc(target_doc_id)
        return

    if args.lang and args.lang not in LANGUAGES:
        _die(f"Unknown language code: {args.lang!r}. Valid codes: {', '.join(LANGUAGES)}")

    validate_doc(target_doc_id)
    orchestrate(target_doc_id, dry_run=args.dry_run, single_lang=args.lang)


if __name__ == "__main__":
    main()
