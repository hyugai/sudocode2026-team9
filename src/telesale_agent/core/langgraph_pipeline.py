"""LangGraph orchestrator replacing the custom PipelineStages loop."""

from typing import TypedDict
from langgraph.graph import StateGraph, START, END

from pydantic import TypeAdapter
from telesale_agent.core.models import (
    TurnContext, AgentStep, TurnInput, ConversationState, TurnResult, Message
)
from telesale_agent.core.interfaces import (
    ASREngine, Perceiver, IdentityResolver, Retriever, CallBriefBuilder,
    Planner, Guardrail, Actor, Observer, Persister, CRMRetriever
)

class AgentState(TypedDict):
    context: TurnContext

ctx_adapter = TypeAdapter(TurnContext)

def _get_ctx(state: AgentState) -> TurnContext:
    raw_ctx = state["context"]
    if isinstance(raw_ctx, dict):
        return ctx_adapter.validate_python(raw_ctx)
    return raw_ctx

class LangGraphAgentHarness:
    """A wrapper that compiles and runs a LangGraph instead of a custom for-loop."""
    
    def __init__(self,
                 asr: ASREngine,
                 perceive: Perceiver,
                 identity: IdentityResolver,
                 crm: CRMRetriever,
                 retrieve: Retriever,
                 call_brief: CallBriefBuilder,
                 plan: Planner,
                 guardrail: Guardrail,
                 act: Actor,
                 observe: Observer,
                 persist: Persister,
                 max_steps: int = 5):
        
        self.asr = asr
        self.perceive = perceive
        self.identity = identity
        self.crm = crm
        self.retrieve = retrieve
        self.call_brief = call_brief
        self.plan = plan
        self.guardrail = guardrail
        self.act = act
        self.observe = observe
        self.persist = persist
        self.max_steps = max_steps
        
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        
        # Define Nodes
        async def node_asr(state: AgentState):
            ctx = _get_ctx(state)
            # Run ASR only if there's audio and no text yet
            if self.asr and ctx.input.audio and not ctx.input.text:
                transcript = await self.asr.transcribe(ctx)
                if transcript:
                    ctx.input.text = transcript
            return {"context": ctx}

        async def node_perceive(state: AgentState):
            ctx = _get_ctx(state)
            ctx.perception = await self.perceive.perceive(ctx)
            ctx.state.messages.append(Message("customer", ctx.perception.transcript))
            if ctx.perception.memory_deltas:
                ctx.state.memory_deltas.update(ctx.perception.memory_deltas)
            return {"context": ctx}

        async def node_identity(state: AgentState):
            ctx = _get_ctx(state)
            ctx.identity = await self.identity.resolve_identity(ctx)
            ctx.state.identity = ctx.identity
            return {"context": ctx}

        async def node_crm_profile(state: AgentState):
            ctx = _get_ctx(state)
            profile = await self.crm.retrieve_profile(ctx)
            ctx.state.customer_profile = profile
            return {"context": ctx}

        async def node_precompute_brief(state: AgentState):
            ctx = _get_ctx(state)
            history = await self.crm.precompute_brief(ctx)
            ctx.state.past_history = history
            return {"context": ctx}

        async def node_retrieve(state: AgentState):
            ctx = _get_ctx(state)
            # Example caching logic to avoid re-querying VectorDB
            # If intent hasn't changed, we could reuse state.retrieved_data here
            ctx.retrieved = await self.retrieve.retrieve(ctx)
            ctx.state.retrieved_data = ctx.retrieved
            return {"context": ctx}

        async def node_call_brief(state: AgentState):
            ctx = _get_ctx(state)
            ctx.call_brief = await self.call_brief.build_call_brief(ctx)
            ctx.state.call_brief = ctx.call_brief
            return {"context": ctx}

        async def node_plan(state: AgentState):
            ctx = _get_ctx(state)
            ctx.plan = await self.plan.plan(ctx)
            return {"context": ctx}

        async def node_guardrail(state: AgentState):
            ctx = _get_ctx(state)
            ctx.policy = await self.guardrail.check(ctx)
            if ctx.policy.safe_plan is not None:
                ctx.plan = ctx.policy.safe_plan
            return {"context": ctx}

        async def node_act(state: AgentState):
            ctx = _get_ctx(state)
            if ctx.policy.allowed:
                ctx.action_result = await self.act.act(ctx)
            return {"context": ctx}

        async def node_observe(state: AgentState):
            ctx = _get_ctx(state)
            if ctx.policy.allowed:
                ctx.observation = await self.observe.observe(ctx)
            
            # Save the step to context history
            if ctx.plan and ctx.policy and ctx.action_result and ctx.observation:
                ctx.steps.append(
                    AgentStep(
                        plan=ctx.plan,
                        policy=ctx.policy,
                        action_result=ctx.action_result,
                        observation=ctx.observation,
                    )
                )
            return {"context": ctx}

        async def node_persist(state: AgentState):
            ctx = _get_ctx(state)
            if ctx.plan and ctx.plan.response_text:
                ctx.state.messages.append(Message("agent", ctx.plan.response_text))
            await self.persist.persist(ctx)
            return {"context": ctx}

        # Add Nodes to Graph
        workflow.add_node("asr", node_asr)
        workflow.add_node("perceive", node_perceive)
        workflow.add_node("identity", node_identity)
        workflow.add_node("crm_profile", node_crm_profile)
        workflow.add_node("precompute_brief", node_precompute_brief)
        workflow.add_node("retrieve", node_retrieve)
        workflow.add_node("call_brief", node_call_brief)
        workflow.add_node("plan", node_plan)
        workflow.add_node("guardrail", node_guardrail)
        workflow.add_node("act", node_act)
        workflow.add_node("observe", node_observe)
        workflow.add_node("persist", node_persist)

        # Edges
        # Conditional start: If identity is missing, do initialization first
        def route_start(state: AgentState) -> str:
            ctx = _get_ctx(state)
            if not ctx.state.identity:
                return "identity"
            return "asr"
            
        workflow.add_conditional_edges(
            START,
            route_start,
            {"identity": "identity", "asr": "asr"}
        )

        # Initialization phase (Static Block)
        workflow.add_edge("identity", "crm_profile")
        workflow.add_edge("crm_profile", "precompute_brief")
        workflow.add_edge("precompute_brief", "asr")
        
        # Turn loop phase
        workflow.add_edge("asr", "perceive")
        workflow.add_edge("perceive", "retrieve")
        workflow.add_edge("retrieve", "call_brief")
        workflow.add_edge("call_brief", "plan")
        
        workflow.add_edge("plan", "guardrail")
        workflow.add_edge("guardrail", "act")
        workflow.add_edge("act", "observe")

        # Conditional Edge after observe
        def should_continue(state: AgentState) -> str:
            ctx = _get_ctx(state)
            if not ctx.policy.allowed:
                return "persist"
            # To prevent infinite loops
            if len(ctx.steps) >= self.max_steps:
                return "persist"
            if ctx.observation and ctx.observation.should_continue:
                return "plan"
            return "persist"

        workflow.add_conditional_edges(
            "observe",
            should_continue,
            {"plan": "plan", "persist": "persist"}
        )
        
        workflow.add_edge("persist", END)

        return workflow.compile()
        
    async def run_turn(
        self,
        turn_input: TurnInput,
        state: ConversationState | None = None,
    ) -> TurnResult:
        """Run the graph asynchronously."""
        state = state or ConversationState(conversation_id=turn_input.conversation_id)
        if state.conversation_id != turn_input.conversation_id:
            raise ValueError("state and input must belong to the same conversation")

        context = TurnContext(input=turn_input, state=state)
        
        # Load initialization data into TurnContext if it exists
        if state.identity:
            context.identity = state.identity
        if state.retrieved_data:
            context.retrieved = state.retrieved_data
            
        initial_state = {"context": context}
        
        print("\n" + "="*50)
        print(f"STARTING GRAPH RUN: {turn_input.text or '[Audio]'}")
        print("="*50)
        
        ctx = context
        async for event in self.graph.astream(initial_state):
            for node_name, node_state in event.items():
                print(f"\n🟢 NODE EXECUTED: [{node_name.upper()}]")
                ctx = _get_ctx(node_state)
                
                # Print specific outputs based on node
                if node_name == "perceive" and ctx.perception:
                    print(f"   -> Intent: {ctx.perception.intent}")
                    print(f"   -> Entities: {ctx.perception.entities}")
                    if ctx.perception.memory_deltas:
                        print(f"   -> Memory Deltas: {ctx.perception.memory_deltas}")
                elif node_name == "identity" and ctx.identity:
                    print(f"   -> Customer ID: {ctx.identity.customer_id}")
                elif node_name == "crm_profile":
                    print(f"   -> CRM Profile: {ctx.state.customer_profile.get('name') if ctx.state.customer_profile else 'None'} | Phone: {ctx.state.customer_profile.get('phone') if ctx.state.customer_profile else 'None'}")
                elif node_name == "precompute_brief":
                    print(f"   -> Past History: {len(ctx.state.past_history.get('sessions', []))} sessions, {len(ctx.state.past_history.get('past_orders', []))} orders")
                elif node_name == "retrieve" and ctx.retrieved:
                    print(f"   -> Retrieved items: {len(ctx.retrieved.knowledge)}")
                elif node_name == "call_brief" and ctx.call_brief:
                    print(f"   -> Needs: {ctx.call_brief.needs}")
                    print(f"   -> Brief Summary: {ctx.call_brief.summary}")
                elif node_name == "plan" and ctx.plan:
                    print(f"   -> Action: {ctx.plan.action}")
                    print(f"   -> Rationale: {ctx.plan.rationale}")
                    if ctx.plan.tool_name:
                        print(f"   -> Tool: {ctx.plan.tool_name} with args {ctx.plan.arguments}")
                    if ctx.plan.response_text:
                        print(f"   -> Text Response: {ctx.plan.response_text}")
                elif node_name == "guardrail" and ctx.policy:
                    print(f"   -> Allowed: {ctx.policy.allowed} (Reason: {ctx.policy.reason})")
                elif node_name == "act" and ctx.action_result:
                    print(f"   -> Result Status: {ctx.action_result.status}")
                    print(f"   -> Output: {ctx.action_result.output}")
        
        print("\nGRAPH RUN COMPLETED!")
        print("="*50 + "\n")
        
        state.turn_number += 1
        return TurnResult(
            conversation_id=state.conversation_id,
            turn_number=state.turn_number,
            response_text=ctx.plan.response_text if ctx.plan else None,
            perception=ctx.perception,
            identity=ctx.identity,
            retrieved=ctx.retrieved,
            call_brief=ctx.call_brief,
            action_result=ctx.action_result,
            observation=ctx.observation,
            steps=ctx.steps,
            state=state,
        )
