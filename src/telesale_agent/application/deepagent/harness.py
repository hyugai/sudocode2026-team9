"""Public DeepAgent harness: composition and compatibility facade only."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from telesale_agent.application import CustomerContextService
from telesale_agent.application.deepagent.runtime import (
    close_runtime,
    initialize_runtime,
    prewarm_knowledge_mcp,
)
from telesale_agent.application.deepagent.turn import run_turn, run_turn_impl
from telesale_agent.application.deepagent.tools.reads import ReadToolExecutor
from telesale_agent.application.deepagent.tools.mutations import MutationToolExecutor
from telesale_agent.application.deepagent.tools.protocol import (
    canonical_tool_args as _canonical_tool_args,
    compact_orchestrated_result as _compact_orchestrated_result,
    decode_tool_result as _decode_tool_result,
    extract_tool_calls as extract_deepagent_tool_calls,
    tool_calls_to_steps as _tool_calls_to_steps,
)
from telesale_agent.application.deepagent.context.order import (
    _delivery_address,
    _requested_exchange_sku,
    _single_variant_sku,
)
from telesale_agent.application.deepagent.context.callback import _requested_callback_at
from telesale_agent.application.deepagent.context.prompt import (
    recent_conversation_context as _recent_conversation_context,
)
from telesale_agent.application.deepagent.response import _safe_fallback_response
from telesale_agent.core.interfaces import ASREngine, CustomerMemoryRepository
from telesale_agent.core.models import ConversationState, TurnContext, TurnInput, TurnResult


class DeepAgentHarness:
    """Expose one stable API while runtime, turn, and tools own their logic."""

    def __init__(
        self,
        asr: ASREngine = None,
        perceive=None,
        identity=None,
        crm=None,
        memory: CustomerMemoryRepository | None = None,
        retrieve=None,
        call_brief=None,
        guardrail=None,
        persist=None,
    ):
        self.asr = asr
        self.perceive = perceive
        self.identity = identity
        self.crm = crm
        self.memory = memory
        self.customer_context = (
            CustomerContextService(crm, memory) if crm and memory else None
        )
        self.retrieve = retrieve
        self.call_brief = call_brief
        self.guardrail = guardrail
        self.persist = persist
        self.checkpointer = MemorySaver()
        self.exit_stack = AsyncExitStack()
        self.agent = None
        self.mcp_tools: dict[str, Any] = {}

    async def __aenter__(self):
        return await initialize_runtime(self)

    async def _prewarm_knowledge_mcp(self) -> None:
        await prewarm_knowledge_mcp(self)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await close_runtime(self, exc_type, exc_val, exc_tb)

    def reset_customer_memory(self) -> None:
        """Reset an isolated evaluation memory repository between scenarios."""
        reset = getattr(self.memory, "reset", None)
        if callable(reset):
            reset()

    async def _prefetch_read_tools(
        self,
        context: TurnContext,
        allowed_tools: frozenset[str],
    ) -> tuple[list[dict[str, Any]], frozenset[str]]:
        return await ReadToolExecutor(self.mcp_tools).prefetch(context, allowed_tools)

    async def _execute_confirmed_mutation(
        self,
        context: TurnContext,
        allowed_tools: frozenset[str],
        verified_calls: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], frozenset[str]]:
        return await MutationToolExecutor(self.mcp_tools).execute(
            context, allowed_tools, verified_calls
        )

    async def run_turn(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        return await run_turn(self, turn_input, state)

    async def _run_turn_impl(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        return await run_turn_impl(self, turn_input, state)
