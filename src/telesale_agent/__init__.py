"""Public API for the telesale agent harness."""

from .core.errors import AgentLoopLimitError, PipelineStageError
from .core.models import (
    CallBrief,
    Channel,
    ConversationState,
    CustomerIdentity,
    TurnInput,
    TurnResult,
)


async def build_deepagent_harness_async():
    """Build and initialize the production Deep Agent harness."""
    from .bootstrap import build_deepagent_harness_async as _build_deepagent_harness

    return await _build_deepagent_harness()

__all__ = [
    "AgentLoopLimitError",
    "CallBrief",
    "Channel",
    "ConversationState",
    "CustomerIdentity",
    "PipelineStageError",
    "TurnInput",
    "TurnResult",
    "build_deepagent_harness_async",
]
