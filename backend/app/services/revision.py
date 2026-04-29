"""
Revision Service — targeted section editing via Claude API.

Parses Markdown content into sections by heading, applies AI-driven revisions
to individual sections, and splices the result back into the full document.
Supports single revisions and batched multi-section edits.
"""

import os
import re
import difflib
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DEFAULT_MODEL = "claude-opus-4-6"
MAX_TOKENS = 4096

# Matches Markdown headings: # through ######
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

SYSTEM_PROMPT = """You are a professional SEO content editor.
You will be given the body of a content section and a revision instruction.
Apply the revision precisely and return ONLY the revised section body text.
Do not include the section heading — it will be added back automatically.
Do not add meta-commentary, explanations, or preamble.
Output only the revised section body."""


# ─── Section parsing ──────────────────────────────────────────────────────────

def parse_sections(content: str) -> list:
    """
    Split Markdown content into sections delimited by headings.

    Returns a list of dicts, one per section:
        id            — "section_0", "section_1", ...
        heading       — heading text (None for the preamble before the first heading)
        heading_level — 1–6 (0 for the preamble)
        text          — body text of the section (heading line excluded)
        start_char    — start index in the original content string
        end_char      — end index in the original content string
    """
    sections = []
    boundaries = []

    for match in HEADING_RE.finditer(content):
        boundaries.append({
            "line_start": match.start(),
            "line_end": match.end(),
            "level": len(match.group(1)),
            "heading_text": match.group(2).strip(),
        })

    # Section 0: text before the first heading (may be empty)
    first_start = boundaries[0]["line_start"] if boundaries else len(content)
    intro_text = content[:first_start].strip()
    sections.append({
        "id": "section_0",
        "heading": None,
        "heading_level": 0,
        "text": intro_text,
        "start_char": 0,
        "end_char": first_start,
    })

    # One section per heading: text spans from end of heading line to start of next heading
    for i, boundary in enumerate(boundaries):
        next_start = boundaries[i + 1]["line_start"] if i + 1 < len(boundaries) else len(content)
        section_text = content[boundary["line_end"]:next_start].strip()
        sections.append({
            "id": f"section_{i + 1}",
            "heading": boundary["heading_text"],
            "heading_level": boundary["level"],
            "text": section_text,
            "start_char": boundary["line_start"],
            "end_char": next_start,
        })

    return sections


# ─── Diff utility ─────────────────────────────────────────────────────────────

def diff_sections(original: str, revised: str) -> dict:
    """
    Compute a word-level diff between two strings.

    Returns:
        words_added   — count of inserted words
        words_removed — count of deleted words
        changes       — list of (type, text) tuples; type is 'equal'/'insert'/'delete'
    """
    orig_words = original.split()
    rev_words = revised.split()
    matcher = difflib.SequenceMatcher(None, orig_words, rev_words, autojunk=False)

    changes = []
    words_added = 0
    words_removed = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            changes.append(("equal", " ".join(orig_words[i1:i2])))
        elif tag == "insert":
            changes.append(("insert", " ".join(rev_words[j1:j2])))
            words_added += j2 - j1
        elif tag == "delete":
            changes.append(("delete", " ".join(orig_words[i1:i2])))
            words_removed += i2 - i1
        elif tag == "replace":
            changes.append(("delete", " ".join(orig_words[i1:i2])))
            changes.append(("insert", " ".join(rev_words[j1:j2])))
            words_removed += i2 - i1
            words_added += j2 - j1

    return {
        "words_added": words_added,
        "words_removed": words_removed,
        "changes": changes,
    }


# ─── Splice helper ────────────────────────────────────────────────────────────

def _splice_section(content: str, section: dict, revised_body: str) -> str:
    """
    Replace the section's span in content with the revised body.
    Always reconstructs the heading from the original section metadata so that
    Claude's output (which contains only the body) is correctly prefixed.
    """
    before = content[: section["start_char"]]
    after = content[section["end_char"]:]

    if section["heading"]:
        heading_line = "#" * section["heading_level"] + " " + section["heading"] + "\n\n"
        new_section = heading_line + revised_body
    else:
        new_section = revised_body

    # Ensure clean separation between sections
    if after and not new_section.endswith("\n"):
        new_section += "\n"

    return before + new_section + after


# ─── Single revision ──────────────────────────────────────────────────────────

def apply_revision(
    content: str,
    section_id: str,
    instruction: str,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Revise a single section of Markdown content using Claude.

    Args:
        content:     Full Markdown document
        section_id:  ID of the section to revise (e.g. "section_1")
        instruction: Plain-English instruction for the revision
        model:       Anthropic model ID (default: claude-opus-4-6)

    Returns:
        Dict with success, section_id, original_section, revised_section,
        full_content (document with revision spliced in), diff, model_used,
        tokens_used.
    """
    sections = parse_sections(content)
    target = next((s for s in sections if s["id"] == section_id), None)

    if target is None:
        return {
            "success": False,
            "error": f"Section '{section_id}' not found. "
                     f"Available: {[s['id'] for s in sections]}",
            "section_id": section_id,
        }

    # Build the full section string for the diff baseline
    if target["heading"]:
        heading_line = "#" * target["heading_level"] + " " + target["heading"] + "\n\n"
        original_full = heading_line + target["text"]
    else:
        original_full = target["text"]

    if not target["text"].strip():
        return {
            "success": False,
            "error": f"Section '{section_id}' is empty — nothing to revise.",
            "section_id": section_id,
        }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = (
        f"REVISION INSTRUCTION:\n{instruction}\n\n"
        f"SECTION BODY TO REVISE:\n{target['text']}\n\n"
        f"Output the revised section body only."
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # cache stable system prompt
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        return {"success": False, "error": str(exc), "section_id": section_id}

    revised_body = response.content[0].text.strip()

    # Reconstruct heading + revised body for the diff
    if target["heading"]:
        revised_full = heading_line + revised_body
    else:
        revised_full = revised_body

    tokens_used = response.usage.input_tokens + response.usage.output_tokens
    full_revised_content = _splice_section(content, target, revised_body)

    return {
        "success": True,
        "section_id": section_id,
        "original_section": original_full,
        "revised_section": revised_full,
        "full_content": full_revised_content,
        "diff": diff_sections(original_full, revised_full),
        "model_used": model,
        "tokens_used": tokens_used,
    }


# ─── Batch revisions ──────────────────────────────────────────────────────────

def batch_revise(content: str, revisions: list) -> dict:
    """
    Apply a sequence of revisions in order, each operating on the output of the previous.

    Args:
        content:   Full Markdown document
        revisions: List of dicts, each with keys:
                     section_id  — which section to revise
                     instruction — what to change
                     model       — (optional) model override

    Returns:
        Dict with success, final_content, revisions_applied, revisions_failed,
        results (per-revision output), total_tokens_used.
    """
    current_content = content
    results = []
    total_tokens = 0

    for rev in revisions:
        result = apply_revision(
            content=current_content,
            section_id=rev["section_id"],
            instruction=rev["instruction"],
            model=rev.get("model", DEFAULT_MODEL),
        )
        results.append(result)
        total_tokens += result.get("tokens_used", 0)

        if result["success"]:
            current_content = result["full_content"]
        # On failure: continue with remaining revisions (partial success is valid)

    revisions_applied = sum(1 for r in results if r.get("success"))
    revisions_failed = len(results) - revisions_applied

    return {
        "success": revisions_failed == 0,
        "final_content": current_content,
        "revisions_applied": revisions_applied,
        "revisions_failed": revisions_failed,
        "results": results,
        "total_tokens_used": total_tokens,
    }


# ─── CLI test block ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    sample_content = """Welcome to our store, the best place for motorcycle parts.

## Why Choose Us

We have been serving riders for over 20 years. Our team knows bikes.
We stock OEM and aftermarket parts for all major brands.

## Our Product Range

From engines to exhaust systems, we carry everything you need.
Browse by model or use our parts finder tool for fast results.

### Popular Categories

Brakes, exhausts, wheels, engine components, and accessories.

## Shipping & Returns

We ship worldwide with fast turnaround. Returns accepted within 30 days.
"""

    print("=== Revision Service CLI Test ===\n")

    # Test 1: parse_sections
    print("[1] Parsing sections...")
    sections = parse_sections(sample_content)
    for s in sections:
        heading_display = f"H{s['heading_level']}: {s['heading']}" if s["heading"] else "(preamble)"
        print(f"  {s['id']}  {heading_display:<35}  chars [{s['start_char']}:{s['end_char']}]  "
              f"words: {len(s['text'].split())}")

    # Test 2: diff_sections
    print("\n[2] Diff test...")
    orig = "We have been serving riders for over 20 years. Our team knows bikes."
    revised = "With over 20 years of experience, our expert team delivers unmatched knowledge."
    diff = diff_sections(orig, revised)
    print(f"  Words added: {diff['words_added']}  Words removed: {diff['words_removed']}")

    # Test 3: apply_revision (requires ANTHROPIC_API_KEY)
    if ANTHROPIC_API_KEY:
        print("\n[3] Applying revision to 'section_1' (Why Choose Us)...")
        result = apply_revision(
            content=sample_content,
            section_id="section_1",
            instruction=(
                "Make this section more compelling. Add a specific statistic about customer "
                "satisfaction and mention the warranty we offer. Keep it under 80 words."
            ),
        )
        if result["success"]:
            print(f"  Model: {result['model_used']}  Tokens used: {result['tokens_used']}")
            print(f"  Words added: {result['diff']['words_added']}  "
                  f"Words removed: {result['diff']['words_removed']}")
            print("\n  Original:")
            print("  " + result["original_section"].replace("\n", "\n  "))
            print("\n  Revised:")
            print("  " + result["revised_section"].replace("\n", "\n  "))
        else:
            print(f"  Error: {result['error']}")
    else:
        print("\n[3] Skipping apply_revision — ANTHROPIC_API_KEY not set")
        print("  Set ANTHROPIC_API_KEY in .env to test the Claude integration")

    print("\nFull parse_sections output:")
    print(json.dumps(sections, indent=2))
