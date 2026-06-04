"""DeepSeek translation client — OpenAI-compatible endpoint."""
import os
from typing import Optional

from openai import OpenAI

_MODEL = "deepseek-v4-flash"
_BASE_URL = "https://api.deepseek.com"


def _get_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set in the environment.")
    return OpenAI(api_key=api_key, base_url=_BASE_URL)


def call(system: str, user: str, *, max_tokens: int = 32000,
         temperature: float = 0.3, model: Optional[str] = None) -> str:
    """Call DeepSeek with thinking disabled and JSON output mode.

    Returns the raw JSON string from the model.
    Raises RuntimeError if DEEPSEEK_API_KEY is unset or the response is empty.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=model or _MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        response_format={"type": "json_object"},
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content
