import os
import sys
import json
from typing import Any, Optional

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import FilesystemBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.memory import MemoryMiddleware
from langgraph.checkpoint.memory import MemorySaver

from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from pathlib import Path

from telesale_agent.core.models import (
    TurnContext, TurnInput, ConversationState, TurnResult, 
    Message, Perception, ActionPlan, ActionResult, ActionStatus, Observation,
    AgentStep, PolicyDecision,
)
from telesale_agent.core.interfaces import ASREngine, CustomerMemoryRepository
from telesale_agent.application import CustomerContextService


_BTC_TOOL_NAMES = {
    "retrieve_customer_profile": "crm.get_customer",
    "search_catalog": "catalog.search",
    "check_inventory": "inventory.check",
    "get_pricing_quote": "pricing.get_quote",
    "create_new_order": "order.create",
    "check_order_status": "order.status",
    "mcp_schedule_callback": "schedule.callback",
    "mcp_escalate_to_human": "handoff.transfer",
}

_DEFAULT_RECENT_MESSAGE_COUNT = 4
_DEFAULT_RECENT_MESSAGE_CHARS = 450
_DEFAULT_RECENT_CONTEXT_CHARS = 1_600


def _positive_int_env(name: str, default: int) -> int:
    """Read a positive integer limit without making startup fragile."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _recent_conversation_context(messages: list[Message]) -> str:
    """Format a small application-owned history for a fresh agent turn."""
    count = _positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_COUNT", _DEFAULT_RECENT_MESSAGE_COUNT
    )
    per_message = _positive_int_env(
        "DEEPAGENT_RECENT_MESSAGE_CHARS", _DEFAULT_RECENT_MESSAGE_CHARS
    )
    total_limit = _positive_int_env(
        "DEEPAGENT_RECENT_CONTEXT_CHARS", _DEFAULT_RECENT_CONTEXT_CHARS
    )
    lines = [
        f"{message.role}: {_clip_text(message.content, per_message)}"
        for message in messages[-count:]
        if message.content
    ]
    return _clip_text("\n".join(lines), total_limit)


def _canonical_tool_name(name: str | None) -> str:
    if not name:
        return "unknown"
    return _BTC_TOOL_NAMES.get(name, name.replace("_", "."))


def _canonical_tool_args(name: str, args: Any) -> dict[str, Any]:
    normalized = dict(args) if isinstance(args, dict) else {}
    if name == "order.create" and "payment_method" in normalized:
        normalized["payment"] = normalized.pop("payment_method")
    elif name == "handoff.transfer" and "brief" not in normalized:
        normalized = {
            "brief": {
                key: normalized[key]
                for key in ("reason", "customer_id", "summary")
                if key in normalized
            }
        }
    return normalized


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _decode_tool_result(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


def _current_turn_messages(messages: list[Any]) -> list[Any]:
    """Return messages produced after the most recent user message."""
    start = 0
    for index, message in enumerate(messages):
        if getattr(message, "type", None) in {"human", "user"}:
            start = index + 1
    return messages[start:]


def extract_deepagent_tool_calls(messages: list[Any]) -> list[dict[str, Any]]:
    """Pair DeepAgent AI tool calls with ToolMessage results for one turn."""
    pending: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []

    for message in _current_turn_messages(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue
            call_id = str(raw_call.get("id") or f"tool-{len(ordered) + 1}")
            canonical_name = _canonical_tool_name(raw_call.get("name"))
            record = {
                "id": call_id,
                "name": canonical_name,
                "args": _canonical_tool_args(
                    canonical_name, raw_call.get("args") or {}
                ),
                "result": None,
            }
            pending[call_id] = record
            ordered.append(record)

        if getattr(message, "type", None) == "tool":
            call_id = str(getattr(message, "tool_call_id", "") or "")
            if call_id in pending:
                pending[call_id]["result"] = _decode_tool_result(
                    getattr(message, "content", "")
                )

    return ordered


def _tool_calls_to_steps(tool_calls: list[dict[str, Any]]) -> list[AgentStep]:
    steps = []
    for call in tool_calls:
        result = call.get("result")
        output = result if isinstance(result, dict) else {"value": result}
        error = output.get("error") if isinstance(output, dict) else None
        status = ActionStatus.FAILED if error else ActionStatus.EXECUTED
        plan = ActionPlan(
            action="tool_call",
            rationale="Tool selected by DeepAgent",
            tool_name=call["name"],
            arguments=call.get("args") or {},
        )
        policy = PolicyDecision(allowed=True, reason="Executed by DeepAgent")
        action_result = ActionResult(status=status, output=output, error=error)
        observation = Observation(
            summary=f"{call['name']} {'failed' if error else 'executed'}",
            events=[{"tool_call_id": call.get("id")}],
        )
        steps.append(
            AgentStep(
                plan=plan,
                policy=policy,
                action_result=action_result,
                observation=observation,
            )
        )
    return steps

class DeepAgentHarness:
    """A wrapper that uses deepagents to replace the custom pipeline loop."""
    
    def __init__(
        self, 
        asr: ASREngine = None,
        perceive=None,
        identity=None,
        crm=None,
        memory: CustomerMemoryRepository | None = None,
        retrieve=None,
        call_brief=None,
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
        self.persist = persist
        self.checkpointer = MemorySaver()
        self.exit_stack = AsyncExitStack()
        self.agent = None

    async def __aenter__(self):
        if self.agent is not None:
            return self

        project_root = Path(__file__).resolve().parents[3]
        agent_dir = project_root / "data" / "memory-root" / "agents" / "telesales_agent"
        instruction_files = ["/soul.md", "/agent.md", "/tools.md"]
        instruction_memory = MemoryMiddleware(
            backend=FilesystemBackend(root_dir=agent_dir, virtual_mode=True),
            sources=instruction_files,
        )
        minimal_filesystem = FilesystemMiddleware(
            tools=["read_file"],
            system_prompt="",
        )

        server_paths = [
            project_root / "src" / "mcp_servers" / "mcp_db.py",
            project_root / "src" / "mcp_servers" / "mcp_workflow.py",
        ]

        all_mcp_tools = []
        for srv_path in server_paths:
            if srv_path.exists():
                # Keep the parent's import path for subprocesses. This matters
                # for Windows evaluation runs where the venv launcher may fall
                # back to the base interpreter while packages remain in the
                # venv site-packages directory.
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(srv_path)],
                    env=os.environ.copy(),
                )
                read, write = await self.exit_stack.enter_async_context(stdio_client(params))
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools = await load_mcp_tools(session)
                all_mcp_tools.extend(tools)
                
        model_name = (
            os.environ.get("GROQ_MODEL")
            or os.environ.get("MODEL_NAME")
            or "openai/gpt-oss-20b"
        )
        from langchain_groq import ChatGroq
        max_output_tokens = _positive_int_env("GROQ_MAX_OUTPUT_TOKENS", 768)
        try:
            model = ChatGroq(
                temperature=0.3,
                model_name=model_name,
                max_tokens=max_output_tokens,
            )
        except Exception:
            model = f"groq:{model_name}"

        # DeepAgent ships general filesystem/execution/subagent tools. This
        # telesales harness only needs the MCP business tools; hiding unused
        # schemas materially reduces every Groq request while retaining the
        # DeepAgent runtime and middleware.
        register_harness_profile(
            "groq",
            HarnessProfile(
                excluded_tools=frozenset(
                    {
                        "ls",
                        "read_file",
                        "write_file",
                        "edit_file",
                        "glob",
                        "grep",
                        "execute",
                    }
                ),
                general_purpose_subagent=GeneralPurposeSubagentProfile(
                    enabled=False
                ),
            ),
        )

        self.agent = create_deep_agent(
            model=model,
            tools=all_mcp_tools,
            middleware=[minimal_filesystem, instruction_memory],
            checkpointer=self.checkpointer
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.exit_stack.aclose()
        self.agent = None

    def reset_customer_memory(self) -> None:
        """Reset an isolated evaluation memory repository between scenarios."""
        reset = getattr(self.memory, "reset", None)
        if callable(reset):
            reset()

    async def run_turn(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        """Run one turn through the initialized Deep Agent."""
        if self.agent is None:
            raise RuntimeError(
                "DeepAgentHarness is not initialized; use "
                "build_deepagent_harness_async() or 'async with build_deepagent_harness()'."
            )

        state = state or ConversationState(conversation_id=turn_input.conversation_id)
        if state.conversation_id != turn_input.conversation_id:
            raise ValueError("state and input must belong to the same conversation")

        context = TurnContext(input=turn_input, state=state)
        # ConversationState is the canonical application history. Keep a copy
        # from before this turn so a fresh DeepAgent checkpoint can receive a
        # bounded amount of recent dialogue instead of its entire raw history.
        prior_messages = list(state.messages)
        if state.retrieved_data:
            context.retrieved = state.retrieved_data
        
        # 1. ASR
        if self.asr and context.input.audio and not context.input.text:
            transcript = await self.asr.transcribe(context)
            if transcript:
                context.input.text = transcript

        # 2. Pre-processing Nodes
        # 2a. Initialization phase (Only runs once per conversation)
        if not context.state.identity:
            if self.identity:
                context.identity = await self.identity.resolve_identity(context)
                context.state.identity = context.identity
            
            if self.customer_context:
                await self.customer_context.hydrate(context)
        else:
            context.identity = context.state.identity
            if self.customer_context and context.state.customer_memory is None:
                await self.customer_context.hydrate(context)
            
        # 2b. Turn-based phase (Runs every turn)
        if self.perceive:
            context.perception = await self.perceive.perceive(context)
            context.state.messages.append(
                Message("customer", context.perception.transcript)
            )
            if context.perception and context.perception.memory_deltas:
                context.state.memory_deltas.update(context.perception.memory_deltas)

        if self.retrieve:
            from telesale_agent.config.intent_taxonomy import SKIP_RETRIEVAL_INTENTS
            # Skip retrieval if the intent is explicitly marked as not needing knowledge
            should_retrieve = True
            if context.perception:
                # If ALL intents detected are in SKIP_RETRIEVAL_INTENTS, skip the VectorDB search
                if context.perception.intents and all(i in SKIP_RETRIEVAL_INTENTS for i in context.perception.intents):
                    should_retrieve = False
                elif context.perception.intent in SKIP_RETRIEVAL_INTENTS and not context.perception.intents:
                    should_retrieve = False
                    
            if should_retrieve:
                context.retrieved = await self.retrieve.retrieve(context)
                context.state.retrieved_data = context.retrieved

        if self.customer_context:
            # The previous turn persists before returning. Reloading here makes
            # that canonical memory the input to this turn's new call brief.
            self.customer_context.refresh_memory(context)

        if self.call_brief:
            context.call_brief = await self.call_brief.build_call_brief(context)
            context.state.call_brief = context.call_brief

        # Inject compact, relevant context into the user message
        user_text = context.input.text or "[Audio]"
        notes = []
        if context.identity and context.identity.customer_id:
            notes.append(f"Customer ID: {context.identity.customer_id}")
        call_date = context.input.metadata.get("call_date")
        if call_date:
            notes.append(f"Current Call Date: {call_date}")

        recent_context = _recent_conversation_context(prior_messages)
        if recent_context:
            notes.append("Recent Conversation:\n" + recent_context)

        if context.perception:
            turn_delta = []
            if context.perception.intent and context.perception.intent != "unknown":
                turn_delta.append(f"intent={context.perception.intent}")
            if context.perception.entities:
                turn_delta.append(
                    "entities=" + _clip_text(context.perception.entities, 500)
                )
            if turn_delta:
                notes.append("Current Turn: " + " | ".join(turn_delta))

        # The brief is rebuilt from canonical memory each turn. Keep the
        # projection compact so its size is bounded as the call gets longer.
        if context.call_brief:
            cb = context.call_brief
            brief_parts = []
            if cb.customer_name:
                brief_parts.append(f"Name: {cb.customer_name}")
            if cb.summary:
                brief_parts.append(f"Past Summary: {cb.summary}")
            if cb.needs:
                brief_parts.append(f"Needs: {'; '.join(str(n) for n in cb.needs[:3])}")
            addr = cb.verified_customer_data.get("address") if isinstance(cb.verified_customer_data, dict) else None
            if addr:
                brief_parts.append(f"Saved Address: {addr}")
            phone = cb.verified_customer_data.get("phone") if isinstance(cb.verified_customer_data, dict) else None
            if phone:
                brief_parts.append(f"Phone: {phone}")
            if cb.remembered_preferences and isinstance(cb.remembered_preferences, dict):
                facts = cb.remembered_preferences.get("facts") or {}
                if isinstance(facts, dict) and facts:
                    fact_items = [
                        f"{key}: {_clip_text(value, 160)}"
                        for key, value in list(facts.items())[-8:]
                    ]
                    brief_parts.append(f"Known Facts: {', '.join(fact_items)}")
                else:
                    atomic = cb.remembered_preferences.get("atomic_facts") or []
                    if isinstance(atomic, list) and atomic:
                        legacy = [
                            _clip_text(f.get("content", ""), 180)
                            for f in atomic[-5:]
                            if isinstance(f, dict) and f.get("content")
                        ]
                        if legacy:
                            brief_parts.append(f"Known Facts: {', '.join(legacy)}")
            if brief_parts:
                notes.append("Customer Brief: " + " | ".join(brief_parts))

        # Only inject compact knowledge hints if turn 1 (state.turn_number == 0) to avoid bloat
        if state.turn_number == 0 and context.retrieved and context.retrieved.knowledge:
            items = []
            for item in context.retrieved.knowledge[:3]:
                if isinstance(item, dict):
                    if "sku" in item:
                        items.append(f"{item.get('sku')}: {item.get('name')} ({item.get('list_price_vnd')}đ)")
                    elif "policy_chunk" in item:
                        items.append(str(item["policy_chunk"])[:120])
                elif isinstance(item, str):
                    items.append(item[:120])
            if items:
                notes.append("Catalog/Policy Hints: " + " ; ".join(items))

        if notes:
            enriched_user_msg = f"{user_text}\n\n[System Context: {' // '.join(notes)}]"
        else:
            enriched_user_msg = user_text

        print("\n" + "="*50)
        print(f"STARTING DEEP AGENT RUN: {user_text}")
        print("="*50)

        # 3. Invoke Deep Agent. The default turn scope prevents the graph
        # checkpointer from replaying an ever-growing raw message/tool history.
        # The application-owned ConversationState supplies bounded continuity.
        checkpoint_scope = os.environ.get(
            "DEEPAGENT_CHECKPOINT_SCOPE", "turn"
        ).strip().lower()
        if checkpoint_scope == "conversation":
            thread_id = state.conversation_id
        else:
            thread_id = f"{state.conversation_id}__turn_{state.turn_number + 1}"
        config = {"configurable": {"thread_id": thread_id}}

        print(
            f"   -> Context: scope={checkpoint_scope or 'turn'}, "
            f"prompt_chars={len(enriched_user_msg)}, "
            f"recent_messages={min(len(prior_messages), _positive_int_env('DEEPAGENT_RECENT_MESSAGE_COUNT', _DEFAULT_RECENT_MESSAGE_COUNT))}"
        )
        
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": enriched_user_msg}]},
            config=config
        )
        
        # Extract the current response and every tool call/result produced for
        # this turn. LangGraph returns the whole checkpoint message history.
        messages = result.get("messages", [])
        tool_calls = extract_deepagent_tool_calls(messages)
        steps = _tool_calls_to_steps(tool_calls)
        context.steps = steps
        context.tool_results = {
            str(call.get("id")): call.get("result") for call in tool_calls
        }
        response_text = ""
        for message in reversed(_current_turn_messages(messages)):
            if getattr(message, "type", None) in {"ai", "assistant"}:
                response_text = _message_text(message)
                if response_text:
                    break

        print(f"   -> Agent Response: {response_text}")
        print("\nDEEP AGENT RUN COMPLETED!")
        print("="*50 + "\n")
        
        # Save to state
        if response_text:
            state.messages.append(Message("agent", response_text))

        memory_writes = []
        if self.persist:
            memory_writes = await self.persist.persist(context) or []
            
        state.turn_number += 1
        
        return TurnResult(
            conversation_id=state.conversation_id,
            turn_number=state.turn_number,
            response_text=response_text,
            perception=context.perception,
            identity=context.identity,
            retrieved=context.retrieved,
            call_brief=context.call_brief,
            action_result=ActionResult(status=ActionStatus.EXECUTED, output={"message": "Handled by Deep Agent"}),
            observation=Observation(
                summary="Deep agent executed",
                events=[{"tool_calls": len(tool_calls)}],
            ),
            steps=steps,
            state=state,
            tool_calls=tool_calls,
            memory_writes=memory_writes,
        )
