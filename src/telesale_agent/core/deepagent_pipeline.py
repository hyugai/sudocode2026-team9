"""Backward-compatible imports while DeepAgent lives under application/."""

from telesale_agent.application.deepagent.harness import (
    DeepAgentHarness,
    _canonical_tool_args,
    _compact_orchestrated_result,
    _decode_tool_result,
    _delivery_address,
    _recent_conversation_context,
    _requested_callback_at,
    _requested_exchange_sku,
    _safe_fallback_response,
    _single_variant_sku,
    _tool_calls_to_steps,
    extract_deepagent_tool_calls,
)

__all__ = ["DeepAgentHarness", "extract_deepagent_tool_calls"]
