# app/services/anthropic_client.py
"""Claude Code subprocess wrapper — drop-in replacement for the Anthropic SDK wrapper.

Public API (unchanged from SDK version):
    call(system, user, *, model, max_tokens, max_retries) -> str
    extract_json(text) -> Any

The `model` and `max_tokens` parameters are accepted for API compatibility but are
ignored; claude -p uses the active Claude Code session's configured model.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import time
from typing import Any

logger = logging.getLogger(__name__)

# 5 minutes — safe for sequential execution (no resource contention)
_CLAUDE_TIMEOUT = 300


def call(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 8000,
    max_retries: int = 2,
) -> str:
    """Call Claude via `claude -p`. Retries up to max_retries on failure.

    Writes the prompt to a temp file to avoid shell argument length limits.
    """
    prompt = f"{system}\n\n---\n\n{user}"
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        # Write prompt to a temp file and pipe it in to avoid ARG_MAX limits
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(prompt)
            tmp_path = f.name

        try:
            with open(tmp_path, "r", encoding="utf-8") as stdin_file:
                result = subprocess.run(
                    ["claude", "-p", "--dangerously-skip-permissions"],
                    stdin=stdin_file,
                    capture_output=True,
                    text=True,
                    timeout=_CLAUDE_TIMEOUT,
                )
            if result.returncode == 0:
                return result.stdout
            last_exc = RuntimeError(
                f"claude -p exited {result.returncode}. stderr: {(result.stderr or '')[:200]!r}"
            )
            logger.warning(
                "claude -p attempt %d/%d failed (exit %d)",
                attempt + 1, max_retries, result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            last_exc = e
            logger.warning("claude -p timed out on attempt %d/%d", attempt + 1, max_retries)
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    raise RuntimeError(f"claude -p failed after {max_retries} attempt(s)") from last_exc


def extract_json(text: str) -> Any:
    """Extract JSON from text that may contain prose or markdown fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*([\[{].*?)\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON. Preview: {text[:200]!r}")
