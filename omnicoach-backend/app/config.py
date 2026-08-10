"""Application settings.

Everything about the LLM is configuration, never hard-coded. Switching from a
free local model to a paid hosted one is an .env change, not a code change.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# Load a .env file (if present) into the environment BEFORE anything reads it.
# Without this, os.getenv() only ever sees real shell variables and every
# setting silently falls back to the hard-coded defaults below.
try:
    from dotenv import load_dotenv
    # Look for a .env next to the project root (two levels up from this file),
    # then fall back to the current working directory. override=True so the
    # file wins over stale shell variables from earlier sessions.
    _root_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_root_env if _root_env.exists() else None, override=True)
except ModuleNotFoundError:
    # python-dotenv not installed: fall back to shell env only.
    pass


class Settings:
    # --- LLM ---------------------------------------------------------------
    # "ollama"        -> free, local, no API key, no rate limit
    # "openai_compat" -> any OpenAI-compatible endpoint (Gemini, Mistral,
    #                    OpenRouter, Groq, DeepSeek, OpenAI...)
    # "mock"          -> deterministic, no LLM at all (tests / CI)
    provider: str = os.getenv("LLM_PROVIDER", "ollama")
    model: str = os.getenv("LLM_MODEL", "qwen3:8b")
    base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434")
    api_key: str | None = os.getenv("LLM_API_KEY") or None
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0"))
    timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "180"))

    # --- Workout library ---------------------------------------------------
    # Path to the `converted/` folder of the canonical running library.
    # The data is NOT bundled: it is licensed "personal-use only" by its
    # provider, so it stays outside the repository.
    library_path: Path = Path(
        os.getenv("LIBRARY_PATH", "./data/converted")
    ).expanduser()


@lru_cache
def get_settings() -> Settings:
    return Settings()
