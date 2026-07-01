"""Post-translation validation checks.

Five check types:
  1. Numerical fidelity   — numbers, year ranges, OEM codes match source
  2. Structural fidelity  — paragraph/sentence counts roughly match
  3. Protected tokens     — brand names and terms from Section 3 present verbatim
  4. Link integrity       — every source link has a counterpart (or explicit flag) in target
  5. Character limits     — title ≤ 60, meta description ≤ 155
"""
from __future__ import annotations

import re
from typing import Optional


def validate(source: dict, translated: dict, guidelines: str) -> list[dict]:
    """Run all five checks and return a flat list of flag dicts.

    Each flag: {"type": str, "severity": str, "message": str, "location": str}
    """
    flags: list[dict] = []

    source_body = source.get("body_html", "") or source.get("body_markdown", "")
    target_body = translated.get("body_markdown", "")
    source_title = source.get("title", "")
    source_meta = source.get("meta_description") or ""

    flags.extend(check_numerical_fidelity(source_body, target_body))
    flags.extend(check_structural_fidelity(source_body, target_body))
    flags.extend(check_protected_tokens(source_body, target_body, guidelines))
    flags.extend(check_link_integrity(source_body, target_body))
    flags.extend(check_char_limits(translated.get("title", ""), translated.get("meta_description", "")))

    return flags


# ── 1. Numerical fidelity ─────────────────────────────────────────────────────

_NUMBER_RE = re.compile(r"\b\d{1,3}(?:[,.\s]\d{3})*(?:[.,]\d+)?\b|\b\d+\b")
_YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}[–—-](19|20)\d{2}\b")
_OEM_RE = re.compile(r"\b[A-Z0-9]{3,}-[A-Z0-9]{2,}[A-Z]?\b")


def _normalize_number(num_str: str) -> str:
    """Return digit-only form for locale-agnostic number comparison.

    Strips thousands separators (comma, period, space, NBSP, NNBSP) and decimal
    separators so that "3,000", "3 000", and "3.000" all compare equal.
    """
    return re.sub(r"[^\d]", "", num_str)


def check_numerical_fidelity(source_text: str, target_text: str) -> list[dict]:
    """Flag numbers, year ranges, and OEM codes present in source but absent in target."""
    flags: list[dict] = []

    src_numbers_raw = _NUMBER_RE.findall(_strip_html(source_text))
    tgt_numbers_raw = _NUMBER_RE.findall(target_text)

    # Normalize both sides to digit-only so locale-specific thousands separators
    # (3,000 vs 3 000 vs 3.000) don't produce false positives.
    src_norm_to_original: dict[str, str] = {}
    for n in src_numbers_raw:
        src_norm_to_original.setdefault(_normalize_number(n), n)
    tgt_normalized = {_normalize_number(n) for n in tgt_numbers_raw}

    for norm, original in src_norm_to_original.items():
        if norm not in tgt_normalized:
            flags.append(_flag(
                "numerical_fidelity", "error",
                f"Number '{original}' found in source but missing in translation",
                "body",
            ))

    src_years = set(_YEAR_RANGE_RE.findall(source_text))
    tgt_years = set(_YEAR_RANGE_RE.findall(target_text))
    for yr in src_years - tgt_years:
        flags.append(_flag(
            "numerical_fidelity", "error",
            f"Year range '{yr}' found in source but missing in translation",
            "body",
        ))

    src_oems = set(_OEM_RE.findall(_strip_html(source_text)))
    tgt_oems = set(_OEM_RE.findall(target_text))
    for oem in src_oems - tgt_oems:
        flags.append(_flag(
            "numerical_fidelity", "warning",
            f"OEM code '{oem}' found in source but missing in translation",
            "body",
        ))

    return flags


# ── 2. Structural fidelity ────────────────────────────────────────────────────

def check_structural_fidelity(source_body: str, target_body: str) -> list[dict]:
    """Flag paragraph count mismatches and per-paragraph sentence deviations > ±1."""
    flags: list[dict] = []

    # Source arrives as HTML; use block-tag-aware splitting so each <p>…</p>
    # becomes its own paragraph rather than one collapsed blob.
    src_paras = _split_html_paragraphs(source_body)
    tgt_paras = _split_paragraphs(target_body)

    if len(src_paras) != len(tgt_paras):
        print(
            f"[structural_fidelity] paragraph count: source={len(src_paras)}, translation={len(tgt_paras)}",
            flush=True,
        )
        flags.append(_flag(
            "structural_fidelity", "warning",
            f"Paragraph count mismatch: source has {len(src_paras)}, translation has {len(tgt_paras)}",
            "body",
        ))
        return flags  # can't do per-paragraph check if counts differ

    for i, (sp, tp) in enumerate(zip(src_paras, tgt_paras)):
        sc = _sentence_count(sp)
        tc = _sentence_count(tp)
        if abs(sc - tc) > 1:
            flags.append(_flag(
                "structural_fidelity", "info",
                f"Paragraph {i + 1}: source has {sc} sentence(s), translation has {tc} (deviation > ±1)",
                f"body paragraph {i + 1}",
            ))

    return flags


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _split_html_paragraphs(html: str) -> list[str]:
    """Split HTML source into paragraphs using block-level tag boundaries.

    Converts closing block tags to double newlines before stripping HTML so that
    <p>Para 1</p><p>Para 2</p> doesn't collapse into a single paragraph.
    Falls back to double-newline splitting if the input contains no HTML tags.
    """
    if "<" not in html:
        return _split_paragraphs(html)
    # Insert paragraph break at each closing block tag
    text = re.sub(
        r"</(?:p|div|li|h[1-6]|blockquote|pre|tr)>",
        "\n\n",
        html,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def _sentence_count(text: str) -> int:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return max(1, len([s for s in sentences if s.strip()]))


# ── 3. Protected tokens ───────────────────────────────────────────────────────

def check_protected_tokens(source_text: str, target_text: str, guidelines: str) -> list[dict]:
    """Flag protected tokens from Section 3 of guidelines that are missing or modified."""
    tokens = _extract_protected_tokens(guidelines)
    if not tokens:
        return []

    flags: list[dict] = []
    src_clean = _strip_html(source_text)
    tgt_clean = target_text

    for token in tokens:
        if token.lower() in src_clean.lower() and token not in tgt_clean:
            flags.append(_flag(
                "protected_token", "error",
                f"Protected token '{token}' appears in source but not verbatim in translation",
                "body",
            ))

    return flags


def _extract_protected_tokens(guidelines: str) -> list[str]:
    """Extract bullet-listed tokens from '## Section 3' block in guidelines."""
    section_match = re.search(
        r"##\s*(?:section\s*3|3\.)[^\n]*\n(.*?)(?:##|\Z)",
        guidelines,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []

    section_text = section_match.group(1)
    tokens = re.findall(r"^[-*]\s+(.+)$", section_text, re.MULTILINE)
    return [t.strip() for t in tokens if t.strip()]


# ── 4. Link integrity ─────────────────────────────────────────────────────────

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\)]+)\)")
_HTML_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_REVIEW_FLAG_RE = re.compile(r"\[REVIEW:")
_LANG_SEGMENT_RE = re.compile(
    r"^(https?://[^/]+)/(?:en|fr|de|es|it|pl|sl|nl|pt)(/.*)$"
)


def _normalize_url_lang(url: str) -> str:
    """Strip the language-code path segment so /en/… and /fr/… compare equal."""
    m = _LANG_SEGMENT_RE.match(url)
    if m:
        return m.group(1) + m.group(2)
    return url


def check_link_integrity(source_body: str, target_body: str) -> list[dict]:
    """Flag source links that are missing from the translated body without a [REVIEW:] annotation.

    A removed hyperlink accompanied by a [REVIEW:...] inline flag is NOT counted
    as a missing link — it was intentionally flagged by url_localizer.
    Localized URL paths (/en/… vs /fr/…) are treated as matching counterparts.
    """
    flags: list[dict] = []

    src_urls = set(_HTML_LINK_RE.findall(source_body)) | set(
        m.group(2) for m in _MD_LINK_RE.finditer(source_body)
    )
    tgt_urls = set(m.group(2) for m in _MD_LINK_RE.finditer(target_body))
    tgt_urls_normalized = {_normalize_url_lang(u) for u in tgt_urls}

    for url in src_urls:
        if url in tgt_urls:
            continue
        # Accept a locale-swapped version of the same path as a valid counterpart
        if _normalize_url_lang(url) in tgt_urls_normalized:
            continue
        # Check if this was intentionally removed with a [REVIEW:] annotation
        if not _has_review_annotation_for_url(url, target_body):
            flags.append(_flag(
                "link_integrity", "warning",
                f"Source link '{url[:80]}' has no counterpart in translation and no [REVIEW:] annotation",
                "body",
            ))

    return flags


def _has_review_annotation_for_url(url: str, target_body: str) -> bool:
    """A [REVIEW:...] annotation near an OEM or slug extracted from the URL counts as handled."""
    oem_match = re.search(r"-oem-([a-z0-9-]+)", url.lower())
    if oem_match:
        oem = oem_match.group(1)
        return bool(re.search(re.escape(oem), target_body, re.IGNORECASE) and
                    _REVIEW_FLAG_RE.search(target_body))

    slug_match = re.search(r"/blogs/[^/]+/([^/?#]+)", url)
    if slug_match:
        slug = slug_match.group(1)
        return bool(re.search(re.escape(slug), target_body, re.IGNORECASE) and
                    _REVIEW_FLAG_RE.search(target_body))

    return bool(_REVIEW_FLAG_RE.search(target_body))


# ── 5. Character limits ───────────────────────────────────────────────────────

def check_char_limits(title: str, meta_description: str) -> list[dict]:
    """Flag title > 60 chars and meta description > 155 chars."""
    flags: list[dict] = []

    if len(title) > 60:
        flags.append(_flag(
            "char_limit", "warning",
            f"Title is {len(title)} characters (limit: 60). Shorten if possible.",
            "title",
        ))

    if meta_description and len(meta_description) > 155:
        flags.append(_flag(
            "char_limit", "warning",
            f"Meta description is {len(meta_description)} characters (limit: 155). Shorten if possible.",
            "meta_description",
        ))

    return flags


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flag(flag_type: str, severity: str, message: str, location: str) -> dict:
    return {"type": flag_type, "severity": severity, "message": message, "location": location}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)
