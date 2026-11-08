"""Channel-independent customer and turn context preparation."""
import time
from telesale_agent.core.models import Message
from telesale_agent.adapters.llm.usage_tracking import usage_stage

async def prepare_context(harness, context, *, identity_started=None):
    call_brief_ms = None
    # 2a. Initialization phase (Only runs once per conversation)
    hydrated_this_turn = False
    if not context.state.identity:
        if harness.identity:
            context.identity = await harness.identity.resolve_identity(context)
            context.state.identity = context.identity
            if identity_started is None and context.identity and context.identity.phone:
                identity_started = time.perf_counter()
        
        if harness.customer_context:
            await harness.customer_context.hydrate(context)
            hydrated_this_turn = True
    else:
        context.identity = context.state.identity
        if harness.customer_context and context.state.customer_memory is None:
            await harness.customer_context.hydrate(context)
            hydrated_this_turn = True
        
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

    if harness.customer_context and not hydrated_this_turn:
        # The previous turn persists before returning. Reloading here makes
        # that canonical memory the input to this turn's new call brief.
        await harness.customer_context.refresh_memory(context)

    if harness.call_brief:
        context.call_brief = await harness.call_brief.build_call_brief(context)
        context.state.call_brief = context.call_brief
        if identity_started is not None:
            call_brief_ms = (time.perf_counter() - identity_started) * 1000

    return call_brief_ms
