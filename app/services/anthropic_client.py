"""Anthropic SDK wrapper with retry logic for translation workflow."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

import anthropic as _anthropic
from anthropic import APIError, APIStatusError

_client: Optional[_anthropic.Anthropic] = None


def _get_client() -> _anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")
        _client = _anthropic.Anthropic(api_key=api_key)
    return _client


def call(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 8000,
    max_retries: int = 3,
) -> str:
    """Call Claude and return the text response. Retries on transient errors."""
    client = _get_client()
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
        except APIStatusError as e:
            if 400 <= e.status_code < 500 and e.status_code != 429:
                raise
            last_exc = e
        except APIError as e:
            last_exc = e
        time.sleep(2**attempt)
    raise last_exc  # type: ignore[misc]


def call_with_web_search(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int = 4096,
    max_searches: int = 3,
) -> str:
    """Call Claude with the web_search tool enabled; runs the agentic loop.

    Each individual API call is retried on transient errors (same policy as
    call()).  The loop continues until stop_reason is end_turn or until
    max_searches web searches have been used, at which point the tool is
    removed to prevent further searches.
    """
    client = _get_client()
    tools: list = [{"type": "web_search_20250305", "name": "web_search"}]
    messages: list = [{"role": "user", "content": user}]
    searches_used = 0

    while True:
        last_exc: Optional[Exception] = None
        response = None
        for attempt in range(3):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    tools=tools,
                    messages=messages,
                )
                break
            except APIStatusError as e:
                if 400 <= e.status_code < 500 and e.status_code != 429:
                    raise
                last_exc = e
            except APIError as e:
                last_exc = e
            time.sleep(2 ** attempt)
        else:
            raise last_exc  # type: ignore[misc]

        if response.stop_reason == "end_turn":
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        if response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            searches_used += len(tool_uses)

            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tu.id, "content": ""}
                    for tu in tool_uses
                ],
            })

            if searches_used >= max_searches:
                # Remove tool so the model cannot initiate another search.
                tools = []
        else:
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )


def extract_json(text: str) -> Any:
    """Extract JSON from a response that may have prose or code fences around it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"```(?:json)?\s*([\[\{].*?)\s*```", text, re.DOTALL)
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

    preview = text[:200].replace("\n", " ")
    raise ValueError(f"Could not extract JSON from response. Preview: {preview!r}")
