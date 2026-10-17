"""Execute a bounded telesales turn using the initialized DeepAgent runtime."""

from __future__ import annotations

import os
import logging

from telesale_agent.core.models import (
    TurnContext,
    TurnInput,
    ConversationState,
    TurnResult,
    Message,
    ActionPlan,
    ActionResult,
    ActionStatus,
    Observation,
    Channel,
)
from telesale_agent.core.errors import ASRUnavailableError, AudioInputError
from telesale_agent.application.asr_normalization import normalize_asr_transcript
from telesale_agent.application.chat_normalization import normalize_chat_text
from telesale_agent.adapters.llm.rate_limits import is_rate_limit_error
from telesale_agent.adapters.llm.usage_tracking import (
    begin_usage_collection,
    finish_usage_collection,
    usage_stage,
)
from telesale_agent.application.deepagent.tools.routing import select_tools_for_turn
from telesale_agent.application.deepagent.tools.protocol import (
    current_turn_messages as _current_turn_messages,
    extract_tool_calls as extract_deepagent_tool_calls,
    message_text as _message_text,
    tool_calls_to_steps as _tool_calls_to_steps,
)
from telesale_agent.application.deepagent.context.callback import _callback_adjustment_note
from telesale_agent.application.deepagent.context.order import _delivery_address
from telesale_agent.application.deepagent.response import (
    _safe_fallback_response,
    ground_current_stock_claims,
    ground_unverified_unit_question,
)
from telesale_agent.application.deepagent.context.prompt import (
    DEFAULT_RECENT_MESSAGE_COUNT as _DEFAULT_RECENT_MESSAGE_COUNT,
    append_orchestration_context,
    build_base_user_message,
    positive_int_env as _positive_int_env,
)

async def run_turn(
    harness,
    turn_input: TurnInput,
    state: ConversationState | None = None,
) -> TurnResult:
    """Run one turn and always close its provider-usage scope."""
    usage_token = begin_usage_collection()
    try:
        result = await harness._run_turn_impl(turn_input, state)
    except BaseException:
        finish_usage_collection(usage_token)
        raise
    result.usage = finish_usage_collection(usage_token)
    return result

async def run_turn_impl(
    harness,
    turn_input: TurnInput,
    state: ConversationState | None = None,
) -> TurnResult:
    """Execute the initialized Deep Agent pipeline for one turn."""
    if harness.agent is None:
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
    
    # 1. Normalize input before identity, perception, and the main agent.
    if context.input.audio is not None and not context.input.text:
        if harness.asr is None:
            raise ASRUnavailableError("Chưa cấu hình ASR cho input giọng nói.")
        transcript = await harness.asr.transcribe(context)
        if not transcript or not transcript.strip():
            raise AudioInputError("Không nhận dạng được giọng nói trong ghi âm.")
        context.input.metadata["raw_asr_transcript"] = transcript.strip()
        context.input.text = normalize_asr_transcript(transcript)
    elif context.input.text and context.input.channel == Channel.CHAT:
        context.input.metadata.setdefault("raw_user_text", context.input.text)
        context.input.text = normalize_chat_text(context.input.text)

    # 2. Pre-processing Nodes
    # 2a. Initialization phase (Only runs once per conversation)
    if not context.state.identity:
        if harness.identity:
            context.identity = await harness.identity.resolve_identity(context)
            context.state.identity = context.identity
        
        if harness.customer_context:
            await harness.customer_context.hydrate(context)
    else:
        context.identity = context.state.identity
        if harness.customer_context and context.state.customer_memory is None:
            await harness.customer_context.hydrate(context)
        
    # 2b. Turn-based phase (Runs every turn)
    if harness.perceive:
        with usage_stage("perception"):
            context.perception = await harness.perceive.perceive(context)
        context.state.messages.append(
            Message("customer", context.perception.transcript)
        )
        if context.perception and context.perception.memory_deltas:
            context.state.memory_deltas.update(context.perception.memory_deltas)

    if harness.retrieve:
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
            context.retrieved = await harness.retrieve.retrieve(context)
            context.state.retrieved_data = context.retrieved

    if harness.customer_context:
        # The previous turn persists before returning. Reloading here makes
        # that canonical memory the input to this turn's new call brief.
        harness.customer_context.refresh_memory(context)

    if harness.call_brief:
        context.call_brief = await harness.call_brief.build_call_brief(context)
        context.state.call_brief = context.call_brief

    user_text, enriched_user_msg = build_base_user_message(
        context,
        prior_messages,
    )
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
    memory_facts = {}
    if context.call_brief and isinstance(
        context.call_brief.remembered_preferences, dict
    ):
        candidate_facts = context.call_brief.remembered_preferences.get("facts")
        if isinstance(candidate_facts, dict):
            memory_facts = candidate_facts
    allowed_tools = select_tools_for_turn(
        context.perception,
        context.input.text,
        memory_facts,
    )
    if (
        context.state.working_memory.get("pending_order")
        and _delivery_address(context)
    ):
        allowed_tools = frozenset(
            set(allowed_tools)
            | {"create_new_order", "check_inventory", "get_pricing_quote"}
        )
    prefetched_calls, allowed_tools = await harness._prefetch_read_tools(
        context,
        allowed_tools,
    )
    mutation_calls, allowed_tools = await harness._execute_confirmed_mutation(
        context,
        allowed_tools,
        prefetched_calls,
    )
    orchestrated_calls = [*prefetched_calls, *mutation_calls]
    enriched_user_msg = append_orchestration_context(
        context,
        enriched_user_msg,
        allowed_tools,
        mutation_calls,
        orchestrated_calls,
    )

    print(
        f"   -> Context: scope={checkpoint_scope or 'turn'}, "
        f"prompt_chars={len(enriched_user_msg)}, "
        f"recent_messages={min(len(prior_messages), _positive_int_env('DEEPAGENT_RECENT_MESSAGE_COUNT', _DEFAULT_RECENT_MESSAGE_COUNT))}, "
        f"allowed_tools={sorted(allowed_tools)}"
    )
    
    with usage_stage("main_agent"):
        try:
            result = await harness.agent.ainvoke(
                {"messages": [{"role": "user", "content": enriched_user_msg}]},
                config=config,
                context={"allowed_tools": sorted(allowed_tools)},
            )
        except Exception as exc:
            if is_rate_limit_error(exc):
                # Do not accumulate customer messages or append to a failed turn
                # checkpoint when the user sends the recording again after cooldown.
                state.messages[:] = prior_messages
                if checkpoint_scope != "conversation":
                    try:
                        await harness.checkpointer.adelete_thread(thread_id)
                    except Exception:
                        logging.getLogger(__name__).exception("Could not clear failed turn checkpoint")
            raise
    
    # Extract the current response and every tool call/result produced for
    # this turn. LangGraph returns the whole checkpoint message history.
    messages = result.get("messages", [])
    tool_calls = [
        *[call for call in orchestrated_calls if not call.get("_cached")],
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

    if not response_text.strip():
        response_text = _safe_fallback_response(context, orchestrated_calls)

    response_text = ground_unverified_unit_question(
        context, tool_calls, response_text
    )
    response_text = ground_current_stock_claims(
        context, tool_calls, response_text
    )

    callback_note = _callback_adjustment_note(tool_calls)
    if callback_note and callback_note not in response_text:
        response_text = f"{response_text.rstrip()}\n\n{callback_note}".strip()

    if harness.guardrail and response_text:
        context.plan = ActionPlan(
            action="respond_to_customer",
            rationale="DeepAgent final response safety check",
            response_text=response_text,
        )
        context.policy = await harness.guardrail.check(context)
        if context.policy.safe_plan is not None:
            response_text = context.policy.safe_plan.response_text or ""

    print(f"   -> Agent Response: {response_text}")
    print("\nDEEP AGENT RUN COMPLETED!")
    print("="*50 + "\n")
    
    # Save to state
    if response_text:
        state.messages.append(Message("agent", response_text))

    memory_writes = []
    if harness.persist:
        with usage_stage("memory_persister"):
            memory_writes = await harness.persist.persist(context) or []

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

