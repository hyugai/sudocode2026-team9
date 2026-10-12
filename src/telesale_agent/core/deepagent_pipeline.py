import os
import sys
import json
import re
from typing import Any, Optional

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.middleware.filesystem import FilesystemMiddleware
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)

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
from telesale_agent.core.tool_orchestration import (
    IntentToolRoutingMiddleware,
    TelesaleAgentRuntimeContext,
    select_tools_for_turn,
)


_BTC_TOOL_NAMES = {
    "retrieve_customer_profile": "crm.get_customer",
    "search_catalog": "catalog.search",
    "check_inventory": "inventory.check",
    "get_pricing_quote": "pricing.get_quote",
    "create_new_order": "order.create",
    "check_order_status": "order.status",
    "update_order": "order.update",
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


def _nonnegative_int_env(name: str, default: int) -> int:
    """Read a non-negative integer setting (zero disables SDK retries)."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _positive_float_env(name: str, default: float) -> float:
    """Read a positive floating-point setting."""
    try:
        value = float(os.environ.get(name, default))
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
    if isinstance(content, list):
        text_blocks = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and block.get("text")
        ]
        if len(text_blocks) == 1:
            return _decode_tool_result(text_blocks[0])
        if text_blocks:
            return [_decode_tool_result(block) for block in text_blocks]
        return content
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content


def _single_variant_sku(result: Any) -> str | None:
    """Return a SKU only when a catalog result resolves unambiguously."""
    if not isinstance(result, dict):
        return None
    variants = [
        variant.get("variant_sku")
        for item in result.get("items", [])
        if isinstance(item, dict)
        for variant in (item.get("variants") or [])
        if isinstance(variant, dict) and variant.get("variant_sku")
    ]
    unique = list(dict.fromkeys(str(sku) for sku in variants))
    return unique[0] if len(unique) == 1 else None


def _known_variant_sku(context: TurnContext) -> str | None:
    """Resolve a previously verified SKU without asking the model to infer it."""
    if context.perception and isinstance(context.perception.entities, dict):
        for key in ("variant_sku", "sku"):
            value = context.perception.entities.get(key)
            if isinstance(value, str) and value:
                return value
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            for key in ("variant_sku", "product_advised"):
                value = facts.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def _known_fact(context: TurnContext, key: str) -> Any:
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        facts = context.call_brief.remembered_preferences.get("facts") or {}
        if isinstance(facts, dict):
            return facts.get(key)
    return None


def _requested_exchange_sku(context: TurnContext) -> str | None:
    """Derive a new apparel variant only from a verified prior SKU + new size."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    explicit = entities.get("new_variant_sku")
    if isinstance(explicit, str) and explicit:
        return explicit
    requested_size = entities.get("requested_size") or entities.get("size")
    if requested_size is None:
        match = re.search(
            r"\bsize\s*(\d+|s|m|l|xl)\b",
            context.input.text or "",
            flags=re.IGNORECASE,
        )
        requested_size = match.group(1) if match else None
    current_sku = _known_variant_sku(context)
    if requested_size is None or not current_sku:
        return None
    match = re.fullmatch(
        r"(?P<product>SKU-[A-Z0-9-]+)-(?P<size>\d+|S|M|L|XL)-(?P<color>[A-Z]+)",
        current_sku,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return (
        f"{match.group('product')}-{str(requested_size).upper()}-"
        f"{match.group('color')}"
    ).upper()


def _catalog_query(context: TurnContext) -> str:
    """Build a compact catalog query while retaining requested variant data."""
    entities = (
        context.perception.entities
        if context.perception and isinstance(context.perception.entities, dict)
        else {}
    )
    product = next(
        (
            entities.get(key)
            for key in ("product_name", "product", "name", "query")
            if entities.get(key)
        ),
        None,
    )
    if not product:
        return context.input.text or ""
    parts = [str(product)]
    if entities.get("size") is not None:
        parts.append(f"size {entities['size']}")
    if entities.get("color"):
        parts.append(f"màu {entities['color']}")
    return " ".join(parts)


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
        self.mcp_tools: dict[str, Any] = {}

    async def __aenter__(self):
        if self.agent is not None:
            return self

        project_root = Path(__file__).resolve().parents[3]
        configured_agent_dir = os.environ.get("AGENT_INSTRUCTIONS_ROOT")
        agent_dir = (
            Path(configured_agent_dir)
            if configured_agent_dir
            else project_root / "data" / "memory-root" / "agents" / "telesales_agent"
        )
        missing_instructions = [
            name for name in ("soul.md", "agent.md", "tools.md")
            if not (agent_dir / name).is_file()
        ]
        if missing_instructions:
            raise FileNotFoundError(
                f"Missing DeepAgent instruction files in {agent_dir}: "
                + ", ".join(missing_instructions)
            )
        # Keep instructions as version-controlled .md files in memory-root,
        # but load them once at startup. MemoryMiddleware would append a large
        # generic self-edit guide on every model call even though customer
        # memory is owned by TurnMemoryPersister in this application.
        instruction_prompt = "\n\n".join(
            (agent_dir / name).read_text(encoding="utf-8").strip()
            for name in ("soul.md", "agent.md", "tools.md")
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
        self.mcp_tools = {
            tool.name: tool
            for tool in all_mcp_tools
            if isinstance(getattr(tool, "name", None), str)
        }
                
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
                timeout=_positive_float_env("GROQ_REQUEST_TIMEOUT_SECONDS", 30.0),
                max_retries=_nonnegative_int_env("GROQ_MAX_RETRIES", 0),
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
                excluded_middleware=frozenset(
                    {"SummarizationMiddleware", "PatchToolCallsMiddleware"}
                ),
            ),
        )

        self.agent = create_deep_agent(
            model=model,
            tools=all_mcp_tools,
            system_prompt=instruction_prompt,
            middleware=[
                IntentToolRoutingMiddleware(),
                ModelCallLimitMiddleware(
                    run_limit=_positive_int_env("DEEPAGENT_MAX_MODEL_CALLS", 4),
                    exit_behavior="end",
                ),
                ToolCallLimitMiddleware(
                    run_limit=_positive_int_env("DEEPAGENT_MAX_TOOL_CALLS", 3),
                    exit_behavior="end",
                ),
                minimal_filesystem,
            ],
            context_schema=TelesaleAgentRuntimeContext,
            checkpointer=self.checkpointer,
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

    async def _prefetch_read_tools(
        self,
        context: TurnContext,
        allowed_tools: frozenset[str],
    ) -> tuple[list[dict[str, Any]], frozenset[str]]:
        """Execute deterministic read chains without extra model round-trips.

        DeepAgent still owns the response and every mutating business action.
        The orchestrator only collapses read-only chains whose arguments can be
        derived from verified turn context. Calls remain visible in the trace
        and are fed to the normal memory persister as AgentSteps.
        """
        remaining = set(allowed_tools)
        calls: list[dict[str, Any]] = []
        call_date = context.input.metadata.get("call_date")

        async def invoke(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
            tool = self.mcp_tools.get(name)
            if tool is None:
                return None
            try:
                raw_result = await tool.ainvoke(args)
                result = _decode_tool_result(raw_result)
            except Exception as exc:
                result = {"error": str(exc)}
            record = {
                "id": f"prefetch-{len(calls) + 1}",
                "name": _canonical_tool_name(name),
                "args": _canonical_tool_args(_canonical_tool_name(name), args),
                "result": result,
            }
            calls.append(record)
            remaining.discard(name)
            return record

        # Catalog + inventory is a deterministic dependency chain when the
        # requested size/color resolves to exactly one variant. Running it here
        # replaces search->model->inventory->model with search->inventory->model.
        if {"search_catalog", "check_inventory"}.issubset(remaining):
            catalog_args: dict[str, Any] = {
                "query": _catalog_query(context),
            }
            if call_date:
                catalog_args["on"] = call_date
            catalog_call = await invoke("search_catalog", catalog_args)
            catalog_result = catalog_call.get("result") if catalog_call else None
            if not (
                isinstance(catalog_result, dict) and catalog_result.get("items")
            ):
                # Let the model retry with a different query rather than making
                # a prefetch miss terminal for this turn.
                remaining.add("search_catalog")
            variant_sku = _single_variant_sku(
                catalog_result
            )
            if variant_sku:
                inventory_args: dict[str, Any] = {"sku": variant_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)

        # On order confirmation the SKU was already established and persisted
        # by an earlier turn, so stock can be verified without asking the model
        # to repeat that choice. Exchange turns are excluded because they need
        # the newly requested variant, not the old persisted SKU.
        if "check_inventory" in remaining and "update_order" not in remaining:
            sku = _known_variant_sku(context)
            if sku:
                inventory_args = {"sku": sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)

        if "check_order_status" in remaining:
            order_id = _known_fact(context, "order_id")
            if isinstance(order_id, str) and order_id:
                await invoke("check_order_status", {"order_id": order_id})

        if "check_inventory" in remaining and "update_order" in remaining:
            exchange_sku = _requested_exchange_sku(context)
            if exchange_sku:
                inventory_args = {"sku": exchange_sku}
                if call_date:
                    inventory_args["on"] = call_date
                await invoke("check_inventory", inventory_args)

        # A price-only follow-up can reuse the variant persisted by the prior
        # catalog/inventory turn, avoiding another model call just to choose SKU.
        if "get_pricing_quote" in remaining:
            sku = _known_variant_sku(context)
            if sku:
                pricing_args: dict[str, Any] = {"sku": sku, "qty": 1}
                if call_date:
                    pricing_args["on"] = call_date
                if context.input.customer_hint:
                    pricing_args["customer_phone"] = context.input.customer_hint
                await invoke("get_pricing_quote", pricing_args)

        return calls, frozenset(remaining)

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
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": _positive_int_env("DEEPAGENT_RECURSION_LIMIT", 30),
        }
        allowed_tools = select_tools_for_turn(
            context.perception,
            context.input.text,
        )
        prefetched_calls, allowed_tools = await self._prefetch_read_tools(
            context,
            allowed_tools,
        )
        if prefetched_calls:
            verified_reads = [
                {
                    "name": call["name"],
                    "args": call["args"],
                    "result": call["result"],
                }
                for call in prefetched_calls
            ]
            enriched_user_msg += (
                "\n\n[Verified read-tool results: "
                + _clip_text(
                    json.dumps(verified_reads, ensure_ascii=False),
                    _positive_int_env("DEEPAGENT_PREFETCH_CONTEXT_CHARS", 2_400),
                )
                + "]"
            )
        allowed_tool_text = ", ".join(sorted(allowed_tools)) or "none"
        enriched_user_msg += (
            f"\n\n[System Note - Tool Budget: The complete allowlist for this "
            f"turn is: {allowed_tool_text}. Never call a tool outside this "
            "allowlist even if general instructions mention it. Do not claim "
            "price, stock, order, or address facts without corresponding verified "
            "context/tool results. If the customer did not ask about price, do "
            "not call pricing and do not state a price. Do not repeat a tool call. "
            "After the necessary allowed tools succeed, answer immediately.]"
        )

        print(
            f"   -> Context: scope={checkpoint_scope or 'turn'}, "
            f"prompt_chars={len(enriched_user_msg)}, "
            f"recent_messages={min(len(prior_messages), _positive_int_env('DEEPAGENT_RECENT_MESSAGE_COUNT', _DEFAULT_RECENT_MESSAGE_COUNT))}, "
            f"allowed_tools={sorted(allowed_tools)}"
        )
        
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": enriched_user_msg}]},
            config=config,
            context={"allowed_tools": sorted(allowed_tools)},
        )
        
        # Extract the current response and every tool call/result produced for
        # this turn. LangGraph returns the whole checkpoint message history.
        messages = result.get("messages", [])
        tool_calls = [
            *prefetched_calls,
            *extract_deepagent_tool_calls(messages),
        ]
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
