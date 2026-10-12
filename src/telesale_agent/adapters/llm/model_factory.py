"""Provider-neutral LangChain chat model construction.

The application selects a provider through ``LLM_PROVIDER`` while retaining
the old ``GROQ_*`` variables as backwards-compatible fallbacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


_PROVIDER_ALIASES = {
    "google": "gemini",
    "google_genai": "gemini",
    "google-generative-ai": "gemini",
    "google_generative_ai": "gemini",
}
_DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-20b",
    "gemini": "gemini-2.5-flash",
}


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _positive_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _nonnegative_int(value: str | None, default: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _positive_int(value: str | None, default: int) -> int:
    parsed = _nonnegative_int(value, default)
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)
    timeout: float = 30.0
    max_retries: int = 0
    max_output_tokens: int = 768


def resolve_model_config(
    *,
    provider: str | None = None,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> ModelConfig:
    """Resolve common settings plus provider-specific legacy fallbacks."""
    selected_provider = (
        provider or _first_env("LLM_PROVIDER") or "groq"
    ).strip().lower().replace("-", "_")
    selected_provider = _PROVIDER_ALIASES.get(selected_provider, selected_provider)

    if selected_provider not in _DEFAULT_MODELS:
        supported = ", ".join(sorted(_DEFAULT_MODELS))
        raise ValueError(
            f"Unsupported LLM_PROVIDER={selected_provider!r}. Supported: {supported}."
        )

    if selected_provider == "groq":
        provider_model_var = "GROQ_MODEL"
        provider_key_vars = ("GROQ_API_KEY",)
        provider_timeout_var = "GROQ_REQUEST_TIMEOUT_SECONDS"
        provider_retries_var = "GROQ_MAX_RETRIES"
        provider_tokens_var = "GROQ_MAX_OUTPUT_TOKENS"
    else:
        provider_model_var = "GEMINI_MODEL"
        provider_key_vars = ("GOOGLE_API_KEY", "GEMINI_API_KEY")
        provider_timeout_var = "GEMINI_REQUEST_TIMEOUT_SECONDS"
        provider_retries_var = "GEMINI_MAX_RETRIES"
        provider_tokens_var = "GEMINI_MAX_OUTPUT_TOKENS"

    selected_model = (
        (model_name.strip() if model_name else None)
        or _first_env("LLM_MODEL", provider_model_var, "MODEL_NAME")
        or _DEFAULT_MODELS[selected_provider]
    )
    api_key = _first_env(*provider_key_vars) or ""
    timeout = _positive_float(
        _first_env("LLM_REQUEST_TIMEOUT_SECONDS", provider_timeout_var), 30.0
    )
    max_retries = _nonnegative_int(
        _first_env("LLM_MAX_RETRIES", provider_retries_var), 0
    )
    token_limit = max_output_tokens or _positive_int(
        _first_env("LLM_MAX_OUTPUT_TOKENS", provider_tokens_var), 768
    )

    return ModelConfig(
        provider=selected_provider,
        model=selected_model,
        api_key=api_key,
        timeout=timeout,
        max_retries=max_retries,
        max_output_tokens=token_limit,
    )


def create_chat_model(
    *,
    temperature: float,
    provider: str | None = None,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> Any:
    """Create the configured LangChain chat model without making an API call."""
    config = resolve_model_config(
        provider=provider,
        model_name=model_name,
        max_output_tokens=max_output_tokens,
    )

    if not config.api_key:
        key_name = "GROQ_API_KEY" if config.provider == "groq" else "GOOGLE_API_KEY"
        raise ValueError(
            f"{key_name} is required when LLM_PROVIDER={config.provider}."
        )

    if config.provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            temperature=temperature,
            model_name=config.model,
            groq_api_key=config.api_key,
            max_tokens=config.max_output_tokens,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise RuntimeError(
            "Gemini requires langchain-google-genai. Install project dependencies first."
        ) from exc

    return ChatGoogleGenerativeAI(
        model=config.model,
        google_api_key=config.api_key,
        temperature=temperature,
        max_output_tokens=config.max_output_tokens,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )


def model_provider_key(model: Any, fallback: str) -> str:
    """Return the provider key used by DeepAgents harness profiles."""
    try:
        params = model._get_ls_params()
    except (AttributeError, TypeError, NotImplementedError):
        params = {}
    provider = params.get("ls_provider") if isinstance(params, dict) else None
    return provider if isinstance(provider, str) and provider else fallback
