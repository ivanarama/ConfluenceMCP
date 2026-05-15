"""LLM-based query rewriting for Confluence search.

Supports OpenAI and Anthropic API formats.
Set LLM_REWRITE_PROVIDER to "openai" (default) or "anthropic".
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You expand Russian search queries into alternative phrasings for a corporate Confluence wiki.
Your main job is REPLACING KEY WORDS WITH SYNONYMS AND RELATED FORMS that employees \
actually use in documents.

Two types of replacements:
1. SYNONYMS: "директор" → "руководитель", "начальник", "управляющий"
2. RELATED WORDS (same root, different suffix): "директор" → "директорат", "дирекция"

More examples:
- "оформить" → "принять", "создать", "оформление"
- "клиент" → "заказчик", "покупатель", "абонент"
- "заявка" → "обращение", "заказ", "запрос"
- "позвонить" → "звонок", "вызов", "телефонный"

Given the user query, produce 3 to 5 alternatives. Each alternative MUST replace at least \
one key word with a synonym or related form. Do NOT just reorder or rephrase with the same words.
Return ONLY a JSON array of strings, no explanation.

User query: {query}
Alternative phrasings:"""


def _get_llm_config() -> dict[str, Any]:
    """Read LLM rewrite configuration from environment."""
    provider = os.getenv("LLM_REWRITE_PROVIDER", "openai").lower().strip()
    return {
        "provider": provider,
        "endpoint": os.getenv("LLM_REWRITE_ENDPOINT", ""),
        "model": os.getenv("LLM_REWRITE_MODEL", ""),
        "api_key": os.getenv("LLM_REWRITE_API_KEY", ""),
        "timeout": float(os.getenv("LLM_REWRITE_TIMEOUT", "5")),
    }


def is_llm_rewrite_enabled() -> bool:
    """Check if LLM rewriting is configured."""
    cfg = _get_llm_config()
    return bool(cfg["endpoint"])


def _call_openai(cfg: dict[str, Any], prompt: str) -> str:
    """Call OpenAI-compatible API and return raw content string."""
    payload: dict[str, Any] = {
        "model": cfg["model"] or "default",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 300,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    resp = requests.post(
        cfg["endpoint"],
        json=payload,
        headers=headers,
        timeout=cfg["timeout"],
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _call_anthropic(cfg: dict[str, Any], prompt: str) -> str:
    """Call Anthropic-compatible API and return raw content string."""
    endpoint = cfg["endpoint"].rstrip("/")
    # Anthropic Messages API: POST /v1/messages
    if not endpoint.endswith("/messages"):
        if endpoint.endswith("/v1"):
            endpoint += "/messages"
        elif "/v1/" not in endpoint:
            endpoint += "/v1/messages"

    payload: dict[str, Any] = {
        "model": cfg["model"] or "default",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
    }

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if cfg["api_key"]:
        headers["x-api-key"] = cfg["api_key"]

    resp = requests.post(
        endpoint,
        json=payload,
        headers=headers,
        timeout=cfg["timeout"],
    )
    resp.raise_for_status()
    data = resp.json()
    content_blocks = data.get("content", [])
    for block in content_blocks:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def _parse_alternatives(content: str) -> list[str]:
    """Extract alternative queries from LLM response content."""
    content = content.strip()

    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    alternatives: list[str] = json.loads(content)
    if not isinstance(alternatives, list):
        return []

    return [
        s.strip()
        for s in alternatives
        if isinstance(s, str) and 3 <= len(s.strip()) <= 200
    ][:5]


def rewrite_query(query: str) -> list[str]:
    """Send query to LLM and return alternative phrasings.

    Returns empty list on any failure (timeout, bad response, not configured).
    Never raises.
    """
    cfg = _get_llm_config()
    if not cfg["endpoint"]:
        return []

    prompt = _PROMPT_TEMPLATE.format(query=query)

    try:
        if cfg["provider"] == "anthropic":
            content = _call_anthropic(cfg, prompt)
        else:
            content = _call_openai(cfg, prompt)

        return _parse_alternatives(content)

    except Exception:
        log.debug("LLM rewrite failed for query: %s", query[:50], exc_info=True)
        return []
