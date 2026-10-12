"""Create the production Deep Agent harness."""

import os
from typing import Literal

from dotenv import load_dotenv

from telesale_agent.adapters.mock.asr import MockASREngine
from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
from telesale_agent.adapters.mock.identity import HintIdentityResolver
from telesale_agent.adapters.vector_db.retrieve import VectorDBRetriever
from telesale_agent.adapters.llm.llm_call_brief import LLMCallBriefBuilder
from telesale_agent.adapters.crm import PostgresCRMRetriever
from telesale_agent.adapters.memory import (
    FileCustomerMemoryRepository,
    InMemoryCustomerMemoryRepository,
    TurnMemoryPersister,
)
from telesale_agent.adapters.llm.llm_persist import LLMPersister

MemoryMode = Literal["durable", "evaluation", "disabled"]


def build_deepagent_harness(memory_mode: MemoryMode = "durable"):
    """Configure an unstarted Deep Agent harness for use with ``async with``."""
    load_dotenv()
    from telesale_agent.core.deepagent_pipeline import DeepAgentHarness

    durable_memory = FileCustomerMemoryRepository()
    if memory_mode == "durable":
        memory = durable_memory
        persister_mode = os.environ.get(
            "MEMORY_PERSISTER_MODE", "deterministic"
        ).strip().lower()
        persist = (
            LLMPersister(memory)
            if persister_mode == "llm_episode"
            else TurnMemoryPersister(memory)
        )
    elif memory_mode == "evaluation":
        memory = InMemoryCustomerMemoryRepository(seed=durable_memory)
        persist = TurnMemoryPersister(memory)
    elif memory_mode == "disabled":
        memory = InMemoryCustomerMemoryRepository()
        persist = None
    else:
        raise ValueError(f"Unsupported memory_mode: {memory_mode}")

    return DeepAgentHarness(
        asr=MockASREngine(),
        perceive=LLMPerceiver(),
        identity=HintIdentityResolver(),
        crm=PostgresCRMRetriever(),
        memory=memory,
        retrieve=VectorDBRetriever(),
        call_brief=LLMCallBriefBuilder(),
        persist=persist,
    )

async def build_deepagent_harness_async(memory_mode: MemoryMode = "durable"):
    """Build and initialize a harness that uses MCP Clients."""
    harness = build_deepagent_harness(memory_mode=memory_mode)
    await harness.__aenter__()
    return harness
