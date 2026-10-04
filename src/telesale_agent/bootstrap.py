"""Create a runnable harness by choosing one implementation for each stage."""

import os
from dotenv import load_dotenv

from telesale_agent.core.langgraph_pipeline import LangGraphAgentHarness
from telesale_agent.core.builder import AgentHarnessBuilder

from telesale_agent.adapters.mock.asr import MockASREngine
from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
from telesale_agent.adapters.mock.identity import HintIdentityResolver
from telesale_agent.adapters.vector_db.retrieve import VectorDBRetriever
from telesale_agent.adapters.llm.llm_call_brief import LLMCallBriefBuilder
from telesale_agent.adapters.llm.llm_planner import LLMPlanner
from telesale_agent.adapters.rules.pii_guardrail import PIIGuardrail
from telesale_agent.adapters.crm import SupabaseCRMRetriever

from telesale_agent.adapters.mock.act import LocalActor
from telesale_agent.adapters.mock.observe import BasicObserver
from telesale_agent.adapters.llm.llm_persist import LLMPersister

def build_default_harness() -> LangGraphAgentHarness:
    """Build a dependency-free harness for local development and tests using Builder."""
    load_dotenv()
    
    return (AgentHarnessBuilder()
        .with_asr(MockASREngine())
        .with_perceiver(LLMPerceiver())
        .with_identity_resolver(HintIdentityResolver())
        .with_crm(SupabaseCRMRetriever())
        .with_retriever(VectorDBRetriever())
        .with_call_brief_builder(LLMCallBriefBuilder())
        .with_planner(LLMPlanner())
        .with_guardrail(PIIGuardrail())
        .with_actor(LocalActor())
        .with_observer(BasicObserver())
        .with_persister(LLMPersister())
        .build())
