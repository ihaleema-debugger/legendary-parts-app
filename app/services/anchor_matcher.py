"""Anchor text matching for Google Docs comment resolution.

Layer 1 (implemented): normalize whitespace/NBSP/tabs, canonicalize quotes and
dashes, NFC — then retry. Handles LLM paraphrasing that changes punctuation or
whitespace encoding only.

Deferred layers (2026-05-04): Layers 2 and 3 were removed after audit showed
every documented anchor failure in production was a run-boundary structural issue
(fixed in docs_client._build_flat_text), not a character divergence. Add these
layers if/when a real paraphrasing failure occurs with a confirmed fixture:

  Layer 2 — sentence chunking: split anchor into sentences via nltk, locate
    each independently with Layer 1, verify contiguous order and gap.
  Layer 3 — fuzzy fallback: sliding window fuzz.ratio >= 95 with sentence-
    boundary guard (rapidfuzz).
"""
from __future__ import annotations

import logging
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)


def find_span(doc_text: str, anchor: str) -> Optional[tuple]:
    """Find best matching span for anchor in doc_text.

    Returns (start, end) with end exclusive, or None.
    Currently: Layer 1 only. Deferred: Layers 2 and 3 (see module docstring).
    """
    return _layer1(doc_text, anchor)


def _normalize_with_map(text: str) -> tuple:
    """Normalize text for comparison; return (normalized, orig_map).

    orig_map[i] is the index in `text` that normalized[i] was derived from.
    Rules: NFC, collapse whitespace runs (space/tab/NBSP/newline) to single
    space, curly quotes → straight, en/em-dash → hyphen.
    """
    text = unicodedata.normalize("NFC", text)
    norm_chars: list = []
    orig_positions: list = []
    i = 0
    _WS = " \t\xa0\n\r"
    while i < len(text):
        c = text[i]
        if c in _WS:
            j = i
            while j < len(text) and text[j] in _WS:
                j += 1
            norm_chars.append(" ")
            orig_positions.append(i)
            i = j
        elif c in "‘’":
            norm_chars.append("'")
            orig_positions.append(i)
            i += 1
        elif c in "“”":
            norm_chars.append('"')
            orig_positions.append(i)
            i += 1
        elif c in "–—":
            norm_chars.append("-")
            orig_positions.append(i)
            i += 1
        else:
            norm_chars.append(c)
            orig_positions.append(i)
            i += 1
    return "".join(norm_chars), orig_positions


def _layer1(doc_text: str, anchor: str) -> Optional[tuple]:
    """Layer 1: normalize both strings, find, map back to original positions."""
    norm_doc, doc_map = _normalize_with_map(doc_text)
    norm_anchor, _ = _normalize_with_map(anchor)

    idx = norm_doc.find(norm_anchor)
    if idx == -1:
        return None

    orig_start = doc_map[idx]
    orig_end = doc_map[idx + len(norm_anchor) - 1] + 1
    logger.info("Layer 1 match: span=[%d, %d], anchor=%r", orig_start, orig_end, anchor[:60])
    return orig_start, orig_end
