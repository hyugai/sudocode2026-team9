"""Model selection shared by eval CLIs, separate from application defaults."""
from __future__ import annotations

import os

from telesale_agent.adapters.llm.model_factory import ModelConfig, resolve_model_config


DEFAULT_EVAL_PROVIDER = "gemini"
DEFAULT_EVAL_MODEL = "gemini-3.6-flash"
_PROVIDER_MODELS = {"gemini": DEFAULT_EVAL_MODEL, "groq": "openai/gpt-oss-20b"}


def permanent_provider_error(error: BaseException) -> bool:
    """Billing/auth/model-access errors need configuration changes, not retries."""
    current = error
    for _ in range(5):
        code = getattr(current,"status_code",None) or getattr(current,"code",None)
        if str(code) in {"401","402","403","404"}:
            return True
        current = current.__cause__ or current.__context__
        if current is None:
            break
    message = str(error).casefold()
    return any(marker in message for marker in (
        "prepayment credits are depleted", "api_key_invalid", "api key not valid",
        "api key expired", "billing account is not active",
    ))


def configure_eval_model(
    provider: str | None = None,
    model_name: str | None = None,
    *,
    request_interval: float | None = None,
) -> ModelConfig:
    """CLI > EVAL_LLM_* > Gemini 3.6 Flash; do not inherit a stale app model.

    The selected values are exported inside this process so every NLU, agent,
    memory writer, MCP child and judge uses the same provider/model. No .env
    file or application-wide default is changed.
    """
    configured_provider = os.environ.get("EVAL_LLM_PROVIDER") or DEFAULT_EVAL_PROVIDER
    chosen_provider = (provider or configured_provider).strip().lower().replace("-", "_")
    if chosen_provider in {"google", "google_genai", "google_generative_ai"}:
        chosen_provider = "gemini"
    inherited_model = os.environ.get("EVAL_LLM_MODEL") if provider is None else None
    chosen_model = model_name or inherited_model or _PROVIDER_MODELS.get(chosen_provider)
    if chosen_model is None:
        # Let the shared resolver explain unsupported providers.
        return resolve_model_config(provider=chosen_provider)
    config = resolve_model_config(provider=chosen_provider, model_name=chosen_model)
    if request_interval is not None and request_interval < 0:
        raise ValueError("request interval cannot be negative")
    interval = request_interval if request_interval is not None else (
        30.0 if config.provider == "groq" and "gpt-oss" in config.model else 0.0
    )
    os.environ.update({
        "LLM_PROVIDER": config.provider,
        "LLM_MODEL": config.model,
        "EVAL_LLM_PROVIDER": config.provider,
        "EVAL_LLM_MODEL": config.model,
        "EVAL_REQUEST_INTERVAL_SECONDS": str(interval),
    })
    return config
