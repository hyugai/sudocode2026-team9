"""Execute a bounded telesales turn using the initialized DeepAgent runtime."""

from __future__ import annotations

import os
import logging
import time
from telesale_agent.application.deepagent.streaming import answer_can_stream, chunk_text, completed_prefix

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
from telesale_agent.application.conversation.prepare import prepare_context
from telesale_agent.application.memory.coordinator import persist_shared
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
    ground_basket_recap,
    ground_multi_item_order_confirmation,
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
    *, response_stream=None,
) -> TurnResult:
    """Run one turn and always close its provider-usage scope."""
    usage_token = begin_usage_collection()
    try:
        if response_stream is None:
            result = await harness._run_turn_impl(turn_input, state)
        else:
            result = await harness._run_turn_impl(turn_input, state, response_stream=response_stream)
    except BaseException as exc:
        usage = finish_usage_collection(usage_token)
        exc.telesale_usage = usage
        raise
    result.usage = finish_usage_collection(usage_token)
    return result

async def run_turn_impl(
    harness,
    turn_input: TurnInput,
    state: ConversationState | None = None,
    *, response_stream=None,
) -> TurnResult:
    """Execute the initialized Deep Agent pipeline for one turn."""
    if harness.agent is None:
        raise RuntimeError(
            "DeepAgentHarness is not initialized; use "
            "build_deepagent_harness_async() or 'async with build_deepagent_harness()'."
        )

    backend_started = (response_stream.started_at if response_stream is not None
                       else turn_input.metadata.get("_latency_started_at", time.perf_counter()))
    state = state or ConversationState(conversation_id=turn_input.conversation_id)
    if state.conversation_id != turn_input.conversation_id:
        raise ValueError("state and input must belong to the same conversation")

    context = TurnContext(input=turn_input, state=state)
    asr_ms = None
    new_call = not context.state.identity
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
        asr_started = time.perf_counter()
        transcript = await harness.asr.transcribe(context)
        asr_ms = (time.perf_counter() - asr_started) * 1000
        if not transcript or not transcript.strip():
            raise AudioInputError("Không nhận dạng được giọng nói trong ghi âm.")
        context.input.metadata["raw_asr_transcript"] = transcript.strip()
        context.input.text = normalize_asr_transcript(transcript)
    elif context.input.text and context.input.channel == Channel.CHAT:
        context.input.metadata.setdefault("raw_user_text", context.input.text)
        context.input.text = normalize_chat_text(context.input.text)

    # Offline file ASR is excluded from M1 response latency (BTC guidance).
    if response_stream is not None:
        response_stream.asr_ms = asr_ms or 0
        await response_stream.send({"type": "input", "transcript": context.input.text,
                                    "normalized_message": context.input.text})
    response_started = backend_started + (asr_ms or 0) / 1000
    identity_started = response_started if new_call else None
    call_brief_ms = None
    call_brief_ms = await prepare_context(harness, context, identity_started=identity_started)

    precomputed_parts = ["persisted_" + key for key in ("facts", "episodes", "atomic_facts", "foresights")
                         if (context.state.customer_memory or {}).get(key)]

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
            payload = {"messages": [{"role": "user", "content": enriched_user_msg}]}
            runtime_context = {"allowed_tools": sorted(allowed_tools),
                               "customer_id": context.identity.customer_id if context.identity else None}
            if response_stream is not None and callable(getattr(harness.agent, "astream", None)):
                # Stream public model text even while read tools are available.
                # Pending write tools keep their confirmations buffered.
                registered_tools = getattr(harness, "mcp_tools", None)
                effective_tools = allowed_tools if registered_tools is None else set(allowed_tools).intersection(registered_tools)
                incremental = answer_can_stream(effective_tools)
                response_stream.policy = "guarded_words" if incremental else "buffered_tool_turn"
                raw_text = ""
                checked_prefix = ""
                stream_evidence = list(orchestrated_calls)
                result = {}
                async for mode, part in harness.agent.astream(
                    payload, config=config, context=runtime_context,
                    stream_mode=["messages", "values", "custom"], version="v1",
                ):
                    if mode == "values":
                        result = part
                        stream_evidence = [*orchestrated_calls, *extract_deepagent_tool_calls(part.get("messages", []))]
                    elif mode == "custom" and isinstance(part, dict) and part.get("type") == "answer_stream_gate":
                        incremental = bool(part.get("can_stream"))
                        raw_text = ""
                        checked_prefix = ""
                        if incremental:
                            response_stream.policy = "guarded_words"
                    elif mode == "messages" and incremental:
                        message, metadata = part
                        if metadata.get("langgraph_node") == "model":
                            raw_text += chunk_text(message)
                            prefix = completed_prefix(raw_text)
                            if prefix and prefix != checked_prefix:
                                checked_prefix = prefix
                                approved = await prepare_response(harness, context, stream_evidence, prefix)
                                previous_chunks = response_stream.chunks
                                await response_stream.answer(approved)
                                response_stream.chunks_during_generation += response_stream.chunks - previous_chunks
            else:
                if response_stream is not None:
                    response_stream.policy = "buffered_runtime"
                result = await harness.agent.ainvoke(payload, config=config, context=runtime_context)
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

    response_text = await prepare_response(harness, context, tool_calls, response_text,
                                           basket_evidence=[*orchestrated_calls, *tool_calls])

    response_ready = time.perf_counter()
    if response_stream is not None:
        await response_stream.answer(response_text)
        await response_stream.send({"type": "response_complete", "latency": response_stream.latency()})

    print(f"   -> Agent Response: {response_text}")
    if response_text:
        state.messages.append(Message("agent", response_text))
    memory_writes = []
    persist_started = time.perf_counter()
    if harness.persist:
        with usage_stage("memory_persister"):
            memory_writes = await persist_shared(harness, context)
    persist_finished = time.perf_counter()
    state.turn_number += 1
    completed_ms = (persist_finished - response_started) * 1000
    latency = {
        "ttft_ms": round(completed_ms, 3), "total_ms": round(completed_ms, 3),
        "ttfa_ms": None, "measurement_mode": "non_streaming",
        "asr_ms": round(asr_ms, 3) if asr_ms is not None else None,
        "call_brief_ms": round(call_brief_ms, 3) if call_brief_ms is not None else None,
        "response_ready_ms": round((response_ready - response_started) * 1000, 3),
        "persistence_ms": round((persist_finished - persist_started) * 1000, 3),
        "request_complete_ms": round(completed_ms, 3),
        "backend_total_ms": round((persist_finished - backend_started) * 1000, 3),
        "precomputed_parts": precomputed_parts,
    }
    if response_stream is not None:
        latency.update(response_stream.latency())
    print("\nDEEP AGENT RUN COMPLETED!\n" + "="*50 + "\n")
    return TurnResult(
        conversation_id=state.conversation_id, turn_number=state.turn_number,
        response_text=response_text, perception=context.perception, identity=context.identity,
        retrieved=context.retrieved, call_brief=context.call_brief,
        action_result=ActionResult(status=ActionStatus.EXECUTED, output={"message": "Handled by Deep Agent"}),
        observation=Observation(summary="Deep agent executed", events=[{"tool_calls": len(tool_calls)}]),
        steps=steps, state=state, tool_calls=tool_calls, memory_writes=memory_writes, latency=latency,
    )


async def prepare_response(harness, context, tool_calls, response_text, *, basket_evidence=None):
    """Apply identical grounding and guardrails to emitted and final answers."""
    response_text = ground_unverified_unit_question(
        context, tool_calls, response_text
    )
    response_text = ground_current_stock_claims(
        context, tool_calls, response_text
    )
    response_text = ground_basket_recap(
        context, basket_evidence if basket_evidence is not None else tool_calls, response_text
    )
    response_text = ground_multi_item_order_confirmation(
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

    return response_text

