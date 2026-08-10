"""Provider-agnostic LLM access with schema-constrained JSON output.

One function matters: `complete_json(system, user, schema)`. Every provider
returns a dict that already conforms to `schema` — not a string we hope to
parse. Two mechanisms make that true:

  * Ollama       -> `format: <json schema>` constrains the decoder itself:
                    tokens that would break the schema cannot be sampled.
  * OpenAI-compat -> `response_format: {"type": "json_schema", ...}`.

Because both are schema-driven, an `enum` in the schema is a hard guarantee.
That is what lets the running agent pick only workout codes that exist.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.config import Settings


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]: ...


class OllamaProvider:
    """Free, local, unlimited. No API key. Data never leaves the machine."""

    name = "ollama"

    def __init__(self, settings: Settings):
        self.model = settings.model
        self._url = settings.base_url.rstrip("/") + "/api/chat"
        self._temperature = settings.temperature
        self._timeout = settings.timeout_s

    def complete_json(self, system, user, schema):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,  # <- constrained decoding
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        try:
            r = httpx.post(self._url, json=payload, timeout=self._timeout)
            r.raise_for_status()
        except httpx.ConnectError as e:
            raise LLMError(
                "Cannot reach Ollama at "
                f"{self._url}. Is `ollama serve` running?"
            ) from e
        except httpx.HTTPStatusError as e:
            raise LLMError(f"Ollama returned {e.response.status_code}: "
                           f"{e.response.text[:200]}") from e
        content = r.json()["message"]["content"]
        return _loads(content)


class OpenAICompatProvider:
    """Any OpenAI-compatible endpoint.

    Verified free options (July 2026), set via LLM_BASE_URL:
      Gemini      https://generativelanguage.googleapis.com/v1beta/openai
      Groq        https://api.groq.com/openai/v1
      OpenRouter  https://openrouter.ai/api/v1
    Paid later (Mistral, DeepSeek, OpenAI...) is the same class, different URL.
    """

    name = "openai_compat"

    def __init__(self, settings: Settings):
        self.model = settings.model
        self._url = settings.base_url.rstrip("/") + "/chat/completions"
        self._key = settings.api_key
        self._temperature = settings.temperature
        self._timeout = settings.timeout_s
        if not self._key:
            raise LLMError("LLM_API_KEY is required for the openai_compat provider.")

    def complete_json(self, system, user, schema):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        try:
            r = httpx.post(
                self._url,
                json=payload,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=self._timeout,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise LLMError(
                    "Rate limit hit. Free tiers cap requests per minute/day — "
                    "wait, or switch LLM_PROVIDER=ollama for unlimited local runs."
                ) from e
            raise LLMError(f"Provider returned {e.response.status_code}: "
                           f"{e.response.text[:200]}") from e
        content = r.json()["choices"][0]["message"]["content"]
        return _loads(content)


class MockProvider:
    """No LLM. Picks the first candidate per day.

    Keeps tests, CI and front-end work running with zero setup and zero cost.
    """

    name = "mock"
    model = "mock"

    def complete_json(self, system, user, schema):
        codes = _enum_for(schema, "workout_code") or ["UNKNOWN"]
        days = _days_from(user) or ["Mon"]
        return {
            "sessions": [
                {
                    "day": d,
                    "workout_code": codes[i % len(codes)],
                    "rationale": "Mock provider: deterministic pick, no LLM called.",
                }
                for i, d in enumerate(days)
            ]
        }


def get_provider(settings: Settings) -> LLMProvider:
    match settings.provider:
        case "ollama":
            return OllamaProvider(settings)
        case "openai_compat":
            return OpenAICompatProvider(settings)
        case "mock":
            return MockProvider()
        case other:
            raise LLMError(f"Unknown LLM_PROVIDER: {other!r}")


# --- helpers ---------------------------------------------------------------

def _loads(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Model did not return valid JSON: {content[:200]!r}") from e


def _enum_for(schema: Any, key: str) -> list[str] | None:
    """Find the enum of a named property, wherever it sits in the schema.

    Must target the property by name: a naive "first enum found" walk picks up
    the `day` enum instead, which is a different vocabulary entirely.
    """
    if isinstance(schema, dict):
        prop = schema.get("properties", {}).get(key)
        if isinstance(prop, dict) and isinstance(prop.get("enum"), list):
            return prop["enum"]
        for v in schema.values():
            if (found := _enum_for(v, key)) is not None:
                return found
    elif isinstance(schema, list):
        for v in schema:
            if (found := _enum_for(v, key)) is not None:
                return found
    return None


def _days_from(user: str) -> list[str]:
    return [d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun") if d in user]
