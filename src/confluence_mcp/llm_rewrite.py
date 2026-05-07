"""LLM-based query rewriting for Confluence search."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a search query rewriter for a Russian-language corporate Confluence wiki.
Given the user's search query, produce 3 to 5 alternative phrasings that might match
the same documents. Use synonyms, paraphrases, and different word forms.
Return ONLY a JSON array of strings, no explanation.

User query: {query}
Alternative phrasings:"""


def _get_llm_config() -> dict[str, Any]:
    """Read LLM rewrite configuration from environment."""
    return {
        "endpoint": os.getenv("LLM_REWRITE_ENDPOINT", ""),
        "model": os.getenv("LLM_REWRITE_MODEL", ""),
        "api_key": os.getenv("LLM_REWRITE_API_KEY", ""),
        "timeout": float(os.getenv("LLM_REWRITE_TIMEOUT", "5")),
    }


def is_llm_rewrite_enabled() -> bool:
    """Check if LLM rewriting is configured."""
    cfg = _get_llm_config()
    return bool(cfg["endpoint"])


def rewrite_query(query: str) -> list[str]:
    """Send query to LLM and return alternative phrasings.

    Returns empty list on any failure (timeout, bad response, not configured).
    Never raises.
    """
    cfg = _get_llm_config()
    if not cfg["endpoint"]:
        return []

    prompt = _PROMPT_TEMPLATE.format(query=query)

    payload: dict[str, Any] = {
        "model": cfg["model"] or "default",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 300,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    try:
        resp = requests.post(
            cfg["endpoint"],
            json=payload,
            headers=headers,
            timeout=cfg["timeout"],
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = content.strip()

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

    except Exception:
        log.debug("LLM rewrite failed for query: %s", query[:50], exc_info=True)
        return []
