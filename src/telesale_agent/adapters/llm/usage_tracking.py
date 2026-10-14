"""Per-turn LLM usage collection shared by all configured chat models."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from copy import deepcopy
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _empty_usage() -> dict[str, Any]:
    return {
        "requests": 0,
        "failed_requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "by_stage": {},
        "request_details": [],
    }


_ACTIVE_USAGE: ContextVar[dict[str, Any] | None] = ContextVar(
    "telesale_llm_usage", default=None
)
_ACTIVE_STAGE: ContextVar[str] = ContextVar(
    "telesale_llm_stage", default="unspecified"
)


@contextmanager
def usage_stage(name: str):
    """Attribute model requests and tokens to one pipeline stage."""
    token = _ACTIVE_STAGE.set(name)
    try:
        yield
    finally:
        _ACTIVE_STAGE.reset(token)


def _stage_usage(usage: dict[str, Any]) -> dict[str, int]:
    stages = usage.setdefault("by_stage", {})
    stage = _ACTIVE_STAGE.get()
    return stages.setdefault(
        stage,
        {
            "requests": 0,
            "failed_requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
    )


def begin_usage_collection() -> Token:
    """Start a fresh usage scope for the current async turn."""
    return _ACTIVE_USAGE.set(_empty_usage())


def finish_usage_collection(token: Token) -> dict[str, int]:
    """Return the current counters and restore the previous context."""
    usage = deepcopy(_ACTIVE_USAGE.get() or _empty_usage())
    _ACTIVE_USAGE.reset(token)
    if not usage["total_tokens"]:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def _token_counts(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, dict):
        return 0, 0, 0
    input_tokens = int(
        value.get("input_tokens")
        or value.get("prompt_tokens")
        or value.get("input_token_count")
        or 0
    )
    output_tokens = int(
        value.get("output_tokens")
        or value.get("completion_tokens")
        or value.get("output_token_count")
        or 0
    )
    total_tokens = int(
        value.get("total_tokens")
        or value.get("total_token_count")
        or input_tokens + output_tokens
    )
    return input_tokens, output_tokens, total_tokens


class UsageTrackingCallback(BaseCallbackHandler):
    """Collect request counts and provider-reported tokens without API calls."""

    @staticmethod
    def _increment_request() -> None:
        usage = _ACTIVE_USAGE.get()
        if usage is not None:
            usage["requests"] += 1
            _stage_usage(usage)["requests"] += 1

    def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self._increment_request()

    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self._increment_request()

    def on_llm_error(self, *args: Any, **kwargs: Any) -> None:
        usage = _ACTIVE_USAGE.get()
        if usage is not None:
            usage["failed_requests"] += 1
            stage = _stage_usage(usage)
            stage["failed_requests"] += 1
            error = args[0] if args else None
            usage["request_details"].append(
                {
                    "stage": _ACTIVE_STAGE.get(),
                    "status": "error",
                    "error_type": type(error).__name__ if error else "unknown",
                }
            )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _ACTIVE_USAGE.get()
        if usage is None:
            return

        found_message_usage = False
        request_input = request_output = request_total = 0
        finish_reason = None
        for generation_group in getattr(response, "generations", []) or []:
            for generation in generation_group or []:
                message = getattr(generation, "message", None)
                response_metadata = getattr(message, "response_metadata", None) or {}
                generation_info = getattr(generation, "generation_info", None) or {}
                if finish_reason is None:
                    finish_reason = (
                        response_metadata.get("finish_reason")
                        or response_metadata.get("stop_reason")
                        or generation_info.get("finish_reason")
                    )
                metadata = getattr(message, "usage_metadata", None)
                if not isinstance(metadata, dict):
                    continue
                input_tokens, output_tokens, total_tokens = _token_counts(metadata)
                usage["input_tokens"] += input_tokens
                usage["output_tokens"] += output_tokens
                usage["total_tokens"] += total_tokens
                request_input += input_tokens
                request_output += output_tokens
                request_total += total_tokens
                found_message_usage = True

        if not found_message_usage:
            llm_output = getattr(response, "llm_output", None) or {}
            metadata = llm_output.get("token_usage") or llm_output.get("usage") or {}
            input_tokens, output_tokens, total_tokens = _token_counts(metadata)
            usage["input_tokens"] += input_tokens
            usage["output_tokens"] += output_tokens
            usage["total_tokens"] += total_tokens
            request_input += input_tokens
            request_output += output_tokens
            request_total += total_tokens
            finish_reason = finish_reason or llm_output.get("finish_reason")

        stage = _stage_usage(usage)
        stage["input_tokens"] += request_input
        stage["output_tokens"] += request_output
        stage["total_tokens"] += request_total
        usage["request_details"].append(
            {
                "stage": _ACTIVE_STAGE.get(),
                "status": "completed",
                "finish_reason": finish_reason,
                "input_tokens": request_input,
                "output_tokens": request_output,
                "total_tokens": request_total,
            }
        )


usage_tracking_callback = UsageTrackingCallback()
