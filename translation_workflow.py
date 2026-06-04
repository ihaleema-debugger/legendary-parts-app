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
  5. Runs 8 translation tasks sequentially (FR→DE→ES→IT→NL→PL→SL→PT)
  6. Each task: translate → localize URLs → validate → save Google Doc
  7. Failed languages get one automatic retry before being reported
  8. After all complete: sends email summary and updates Trello card
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
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
        # Raise so the main() except-Exception handler can call _report_failure_to_trello.
        # _die(sys.exit) would bypass that handler since SystemExit is not an Exception.
        raise
    print(f"✓ Doc found: {title!r}")


def orchestrate(doc_id: str, dry_run: bool = False, single_lang: Optional[str] = None, langs_subset: Optional[list] = None) -> int:
    """Run the full translation workflow for all 8 languages (or a filtered subset)."""
    model = os.environ.get("TRANSLATION_MODEL", "deepseek-v4-flash")

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
    folder_id = os.environ.get("TRANSLATIONS_FOLDER_ID", "")
    if not folder_id:
        raise RuntimeError(
            "TRANSLATIONS_FOLDER_ID is not set. Add it to .env to specify "
            "the Drive folder where translated docs should be saved."
        )
    print(f"  Folder ID: {folder_id}")

    if single_lang:
        langs_to_run = {single_lang: LANGUAGES[single_lang]}
    elif langs_subset:
        langs_to_run = {code: LANGUAGES[code] for code in langs_subset}
    else:
        langs_to_run = LANGUAGES

    n_running = len(langs_to_run)
    n_total = len(LANGUAGES)
    if n_running < n_total:
        print(f"\nTranslating into: {', '.join(langs_to_run.keys())} ({n_running} of {n_total})")
    print(f"\nStarting translation into {n_running} language(s) with model {model!r}...\n")

    # ── Parallel task execution ───────────────────────────────────────────────
    result_objects: list[dict] = []
    succeeded: list[str] = []
    failed: list[dict] = []  # {"lang": str, "error": str}

    with ThreadPoolExecutor(max_workers=len(langs_to_run)) as executor:
        futures = {
            executor.submit(
                _run_language_task,
                lang_code=code,
                lang_name=name,
                blog=blog,
                guidelines=guidelines,
                shopify_client=shopify_client,
                source_doc_id=doc_id,
                original_slug=original_slug,
                folder_id=folder_id,
                model=model,
                dry_run=dry_run,
            ): code
            for code, name in langs_to_run.items()
        }
        for future in as_completed(futures):
            lang_code = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = {
                    "lang": lang_code, "status": "failed",
                    "doc_id": None, "doc_url": None, "flags": [], "error": str(e),
                }
            result_objects.append(result)
            if result["status"] == "success":
                succeeded.append(lang_code)
                flag_count = len(result.get("flags", []))
                print(f"  ✓ [{lang_code.upper()}] {flag_count} flag(s) — {result.get('doc_url', '')}")
            else:
                failed.append({"lang": lang_code, "error": result.get("error", "unknown error")})
                print(f"  ✗ [{lang_code.upper()}] FAILED: {result.get('error', '?')}")

    # ── Retry pass (one attempt for each failed language, also in parallel) ────
    if failed:
        retry_codes = [f["lang"] for f in failed]
        print(f"\n  First pass complete. Retrying {len(failed)} failed language(s): {retry_codes}")
        still_failed: list[dict] = []
        retry_langs = {code: LANGUAGES[code] for code in retry_codes}

        with ThreadPoolExecutor(max_workers=len(retry_langs)) as executor:
            retry_futures = {
                executor.submit(
                    _run_language_task,
                    lang_code=code,
                    lang_name=name,
                    blog=blog,
                    guidelines=guidelines,
                    shopify_client=shopify_client,
                    source_doc_id=doc_id,
                    original_slug=original_slug,
                    folder_id=folder_id,
                    model=model,
                    dry_run=dry_run,
                ): code
                for code, name in retry_langs.items()
            }
            for future in as_completed(retry_futures):
                lang_code = retry_futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        "lang": lang_code, "status": "failed",
                        "doc_id": None, "doc_url": None, "flags": [], "error": str(e),
                    }
                result_objects = [r for r in result_objects if r.get("lang") != lang_code]
                result_objects.append(result)
                if result["status"] == "success":
                    succeeded.append(lang_code)
                    flag_count = len(result.get("flags", []))
                    print(f"  ✓ [{lang_code.upper()}] retry succeeded — {flag_count} flag(s)")
                else:
                    still_failed.append({"lang": lang_code, "error": result.get("error", "unknown error")})
                    print(f"  ✗ [{lang_code.upper()}] retry failed: {result.get('error', '?')}")
        failed = still_failed

    results = result_objects  # alias used by summary/email/Trello below

    # ── Summary table (always prints before any exit) ─────────────────────────
    successes = sum(1 for r in results if r["status"] == "success")
    n_failed = len(results) - successes
    print(f"\n{'─' * 60}")
    print(f"Translation complete: {successes}/{len(results)} succeeded")
    _print_result_summary(results)

    if n_failed > 0 and successes == 0:
        print("\nALL TRANSLATIONS FAILED — see summary above", file=sys.stderr, flush=True)

    if dry_run:
        print("(Dry run — no docs saved, no email sent)", flush=True)
        return n_failed

    # ── Email notification ────────────────────────────────────────────────────
    print("\nSending email summary...")
    try:
        notifier.send_summary(original_slug, doc_id, results)
        print(f"  ✓ Email sent to {os.environ.get('NOTIFY_EMAIL', '?')}")
    except RuntimeError as e:
        print(f"  Warning: email not sent — {e}")

    # Stage 11 — Shopify publish + translation registration
    if successes > 0:
        _pub_dir = str(_ROOT / "workflows" / "Publishers")
        if _pub_dir not in sys.path:
            sys.path.insert(0, _pub_dir)
        _stage = "shopify_publish"
        try:
            from shopify_publisher import publish_blog_post
            from translation_publisher import publish_translations

            fr_result = next(
                (r for r in results if r["lang"] == "fr" and r["status"] == "success"),
                None,
            )
            if fr_result is None:
                raise RuntimeError(
                    "[Stage 11] French translation did not succeed — cannot publish to "
                    "Shopify without the FR source doc. Resolve the FR translation "
                    "failure first."
                )
            _article, _source_locale = publish_blog_post(fr_result["doc_id"])
            _source_article_id = _article["id"]
            _blog_stem = original_slug

            _stage = "translations_register"
            _trans_result = publish_translations(
                source_article_id=_source_article_id,
                blog_stem=_blog_stem,
            )
            _ok_count = sum(1 for v in _trans_result.values() if v.get("status") == "ok")
            print(
                f"[Stage 11] Shopify draft published (article_id={_source_article_id}), "
                f"{_ok_count} locales registered for doc_id={doc_id}"
            )
        except Exception as _e:
            print(
                f"[Stage 11] FAILED at {_stage} for doc_id={doc_id}: {_e}",
                file=sys.stderr,
            )
            raise
    else:
        print("[Stage 11] Skipped — no successful translations.")

    # ── Trello card completion update ─────────────────────────────────────────
    try:
        _update_trello_on_completion(doc_id, results)
    except Exception as e:
        print(f"  Warning: Trello update skipped — {e}")

    return n_failed



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

        # Compute word counts for result summary
        _src_raw = blog.get("body_html", "") or blog.get("body_markdown", "")
        _src_wc = len(re.sub(r"<[^>]+>", " ", _src_raw).split())
        _tgt_wc = len(translated["body_markdown"].split())
        _expansion = round((_tgt_wc / _src_wc - 1) * 100, 1) if _src_wc else 0.0

        if dry_run:
            return {
                "lang": lang_code,
                "status": "success",
                "doc_id": None,
                "doc_url": None,
                "flags": all_flags,
                "error": None,
                "word_count": _tgt_wc,
                "source_word_count": _src_wc,
                "expansion_pct": _expansion,
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
            "word_count": _tgt_wc,
            "source_word_count": _src_wc,
            "expansion_pct": _expansion,
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


def _print_result_summary(results: list) -> None:
    """Print a per-language result table to stdout. Always called before sys.exit()."""
    header = f"{'LANG':<6} {'STATUS':<10} {'WORDS':<7} {'EXPAN%':<8} {'ERR':<5} {'WARN':<5} {'INFO':<5} DETAIL"
    divider = "─" * 90
    print(f"\n{divider}", flush=True)
    print(header, flush=True)
    print(divider, flush=True)
    for r in results:
        lang = (r.get("lang") or "?").upper()
        status = r.get("status", "?")
        flags = r.get("flags") or []
        n_err = sum(1 for f in flags if f.get("severity") == "error")
        n_warn = sum(1 for f in flags if f.get("severity") == "warning")
        n_info = sum(1 for f in flags if f.get("severity") == "info")
        if status == "success":
            wc = r.get("word_count")
            exp = r.get("expansion_pct")
            wc_str = str(wc) if wc is not None else "-"
            exp_str = (f"+{exp}%" if exp >= 0 else f"{exp}%") if exp is not None else "-"
            detail = (r.get("doc_url") or "-")[:60]
            status_str = "SUCCESS"
        else:
            wc_str = "-"
            exp_str = "-"
            err_msg = (r.get("error") or "unknown error")
            detail = err_msg[:60]
            status_str = "FAILED"
        print(
            f"{lang:<6} {status_str:<10} {wc_str:<7} {exp_str:<8} {n_err:<5} {n_warn:<5} {n_info:<5} {detail}",
            flush=True,
        )
    print(divider, flush=True)


def _die(message: str) -> None:
    print(f"\nError: {message}", file=sys.stderr)
    sys.exit(1)


def _report_failure_to_trello(doc_id: str, exc: BaseException) -> None:
    """Best-effort: move card to Failed list and write failed_error to DB. Never raises."""
    import logging
    _log = logging.getLogger(__name__)
    failed_list = os.environ.get("TRELLO_FAILED_LIST_NAME", "Failed translation")
    try:
        from app.services.trello_state import TrelloState
        from app.services.trello_client import TrelloClient
        state = TrelloState()
        row = state.get_by_doc_id(doc_id)
        if row is None:
            _log.error("[failure-routing] No DB row for doc_id=%r — cannot report to Trello", doc_id)
            return
        card_id = row["card_id"]
        try:
            client = TrelloClient()
            client.ensure_list_id(failed_list)
            client.move_card_to_list(card_id, failed_list)
            client.add_comment(
                card_id,
                f"❌ Translation crashed — {type(exc).__name__}: {exc}\n"
                f"Re-run with `python3 trello_gate.py retry {doc_id}`",
            )
        except Exception as trello_err:
            _log.error(
                "[failure-routing] Trello update failed for doc_id=%r: %s", doc_id, trello_err
            )
        try:
            state.mark_failed_error(doc_id, reason=str(exc))
        except Exception as db_err:
            _log.error(
                "[failure-routing] DB write failed for doc_id=%r: %s", doc_id, db_err
            )
    except Exception as handler_err:
        _log.error(
            "[failure-routing] Unexpected error in failure handler for doc_id=%r: %s",
            doc_id, handler_err,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="SEO-Forge translation workflow")
    parser.add_argument("doc_id", nargs="?", help="Google Doc ID of the approved English blog")
    parser.add_argument("--resume", metavar="DOC_ID", help="Translate the approved English doc")
    parser.add_argument("--validate", metavar="DOC_ID", help="Validate doc ID and Drive access only")
    parser.add_argument("--dry-run", action="store_true", help="Translate without saving to Drive or sending email")
    lang_group = parser.add_mutually_exclusive_group()
    lang_group.add_argument("--lang", metavar="LANG_CODE", help="Single language for dry-run (e.g. fr)")
    lang_group.add_argument("--langs", metavar="LANG_CODES", help="Comma-separated language codes to translate, e.g. it,nl,pl,sl,pt. Subset of the 8 supported languages.")

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

    langs_subset = None
    if args.langs:
        requested = [c.strip() for c in args.langs.split(",") if c.strip()]
        unknown = [c for c in requested if c not in LANGUAGES]
        if unknown:
            _die(
                f"Unknown language code(s): {', '.join(repr(c) for c in unknown)}.\n"
                f"Valid codes: {', '.join(LANGUAGES)}"
            )
        langs_subset = requested

    try:
        validate_doc(target_doc_id)
        n_failed = orchestrate(target_doc_id, dry_run=args.dry_run, single_lang=args.lang, langs_subset=langs_subset)
        if n_failed > 0:
            raise RuntimeError(f"{n_failed} language(s) failed to translate — see logs/translation.log")
    except Exception as exc:
        _report_failure_to_trello(target_doc_id, exc)
        raise


if __name__ == "__main__":
    main()
