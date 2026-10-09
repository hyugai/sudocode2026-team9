import os
import json
import dataclasses
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from pathlib import Path

from telesale_agent.core.models import (
    TurnContext, TurnInput, ConversationState, TurnResult, 
    Message, Perception, ActionPlan, ActionResult, ActionStatus, Observation, AgentStep
)
from telesale_agent.core.interfaces import ASREngine
from telesale_agent.tools.registry import TOOL_REGISTRY

# Map BTC tools to LangChain tools
langchain_tools = []
for tool_name, func in TOOL_REGISTRY.items():
    safe_name = tool_name.replace(".", "_")
    langchain_tools.append(
        StructuredTool.from_function(
            func=func,
            name=safe_name,
            description=func.__doc__ or f"Execute {tool_name}"
        )
    )

class DeepAgentHarness:
    """A wrapper that uses deepagents to replace the custom pipeline loop."""
    
    def __init__(
        self, 
        asr: ASREngine = None,
        perceive=None,
        identity=None,
        crm=None,
        retrieve=None,
        call_brief=None,
        plan=None,
        guardrail=None,
        act=None,
        observe=None,
        persist=None,
    ):
        self.asr = asr
        self.perceive = perceive
        self.identity = identity
        self.crm = crm
        self.retrieve = retrieve
        self.call_brief = call_brief
        self.checkpointer = MemorySaver()
        self.exit_stack = AsyncExitStack()
        self.agent = None

    async def __aenter__(self):
        agent_dir = Path(__file__).resolve().parents[4] / "data" / "memory-root" / "agents" / "telesales_agent"
        memory_files = [
            str(agent_dir / "soul.md"),
            str(agent_dir / "agent.md"),
            str(agent_dir / "tools.md")
        ]
        skills_dirs = [
            str(agent_dir / "skills")
        ]

        server_paths = [
            Path(__file__).resolve().parents[3] / "mcp_servers" / "mcp_db.py",
            Path(__file__).resolve().parents[3] / "mcp_servers" / "mcp_memory.py",
            Path(__file__).resolve().parents[3] / "mcp_servers" / "mcp_workflow.py",
        ]

        all_mcp_tools = []
        for srv_path in server_paths:
            if srv_path.exists():
                params = StdioServerParameters(command="python", args=[str(srv_path)])
                read, write = await self.exit_stack.enter_async_context(stdio_client(params))
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools = await load_mcp_tools(session)
                all_mcp_tools.extend(tools)
                
        model_name = os.environ.get("GROQ_MODEL", "groq:llama3-8b-8192")
        from langchain_groq import ChatGroq
        try:
            model = ChatGroq(temperature=0.3, model_name="llama3-8b-8192")
        except Exception:
            model = model_name

        self.agent = create_deep_agent(
            model=model,
            tools=all_mcp_tools,
            memory=memory_files,
            skills=skills_dirs,
            checkpointer=self.checkpointer
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.exit_stack.aclose()

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
            
            if self.crm:
                context.state.customer_profile = await self.crm.retrieve_profile(context)
                context.state.past_history = await self.crm.precompute_brief(context)
        else:
            context.identity = context.state.identity
            
        # 2b. Turn-based phase (Runs every turn)
        if self.perceive:
            context.perception = await self.perceive.perceive(context)
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

        if self.call_brief:
            context.call_brief = await self.call_brief.build_call_brief(context)
            context.state.call_brief = context.call_brief

        # Inject context into the user message
        user_text = context.input.text or "[Audio]"
        enriched_user_msg = user_text
        
        # Explicitly tell the agent what user_id to use for memory tools
        if context.identity and context.identity.customer_id:
            enriched_user_msg += f"\n\n[System Note - Current User ID for Memory Tools]: {context.identity.customer_id}"
            
        if context.call_brief:
            enriched_user_msg += f"\n\n[System Note - Customer Brief]:\n{dataclasses.asdict(context.call_brief)}"
        if context.retrieved and context.retrieved.knowledge:
            enriched_user_msg += f"\n\n[System Note - Retrieved Knowledge]:\n{context.retrieved.knowledge}"

        print("\n" + "="*50)
        print(f"STARTING DEEP AGENT RUN: {user_text}")
        print("="*50)

        # 3. Invoke Deep Agent
        config = {"configurable": {"thread_id": state.conversation_id}}
        
        result = await self.agent.ainvoke(
            {"messages": [{"role": "user", "content": enriched_user_msg}]},
            config=config
        )
        
        # Extract response
        messages = result.get("messages", [])
        response_text = ""
        if messages and len(messages) > 0:
            last_msg = messages[-1]
            response_text = last_msg.content

        print(f"   -> Agent Response: {response_text}")
        print("\nDEEP AGENT RUN COMPLETED!")
        print("="*50 + "\n")
        
        # Save to state
        if response_text:
            state.messages.append(Message("agent", response_text))
            
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
            observation=Observation(summary="Deep agent executed"),
            steps=[],
            state=state,
        )
