"""Customer wording to use when matching literal product names and models."""

from __future__ import annotations

from telesale_agent.core.models import TurnContext, TurnInput


def literal_customer_text(turn_input: TurnInput) -> str:
    """Prefer original input over normalized text for catalog-name matching.

    Normalization helps intent extraction but may expand an abbreviation that
    is actually part of a brand, product name, or model identifier.
    """
    for key in ("raw_user_text", "raw_asr_transcript"):
        value = turn_input.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return turn_input.text or ""


def is_closing_turn(context: TurnContext) -> bool:
    """Return True for the post-call agent closing turn with empty customer text."""
    if context.input.metadata.get("closing_turn"):
        return True
    return (
        context.input.audio is None
        and (context.input.text or "").strip() == ""
        and context.state.turn_number > 0
    )
