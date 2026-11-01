"""Create the production Deep Agent harness."""

import os
from typing import Literal

from dotenv import load_dotenv

from telesale_agent.adapters.asr import ZipformerASREngine
from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
from telesale_agent.adapters.mock.identity import HintIdentityResolver
from telesale_agent.adapters.vector_db.retrieve import VectorDBRetriever
from telesale_agent.application.memory.call_brief import CallBriefProjector, FreshCallBrief
from telesale_agent.adapters.db.client import db_client
from telesale_agent.adapters.crm import PostgresCRMRetriever
from telesale_agent.adapters.memory import (
    FileCustomerMemoryRepository,
    InMemoryCustomerMemoryRepository,
    ObjectStorageCustomerMemoryRepository,
    TurnMemoryPersister,
)
from telesale_agent.adapters.llm.llm_persist import LLMPersister
from telesale_agent.adapters.rules.pii_guardrail import PIIGuardrail

MemoryMode = Literal["durable", "evaluation", "disabled"]


def build_deepagent_harness(memory_mode: MemoryMode = "durable"):
    """Configure an unstarted Deep Agent harness for use with ``async with``."""
    load_dotenv()
    from telesale_agent.application.deepagent.harness import DeepAgentHarness

    local_memory = FileCustomerMemoryRepository()
    if memory_mode == "durable":
        memory_backend = os.environ.get("CUSTOMER_MEMORY_BACKEND", "file").strip().lower()
        if memory_backend == "file":
            memory = local_memory
        elif memory_backend in {"object_storage", "s3"}:
            memory = ObjectStorageCustomerMemoryRepository()
        else:
            raise ValueError(f"Unsupported CUSTOMER_MEMORY_BACKEND: {memory_backend}")
        persister_mode = os.environ.get(
            "MEMORY_PERSISTER_MODE", "llm_learning"
        ).strip().lower()
        persist = (
            LLMPersister(memory)
            if persister_mode in {"llm_episode", "llm_learning"}
            else TurnMemoryPersister(memory)
        )
    elif memory_mode == "evaluation":
        memory = InMemoryCustomerMemoryRepository(seed=local_memory)
        persist = TurnMemoryPersister(memory)
    elif memory_mode == "disabled":
        memory = InMemoryCustomerMemoryRepository()
        persist = None
    else:
        raise ValueError(f"Unsupported memory_mode: {memory_mode}")

    return DeepAgentHarness(
        asr=ZipformerASREngine(),
        perceive=LLMPerceiver(),
        identity=HintIdentityResolver(),
        crm=PostgresCRMRetriever(),
        memory=memory,
        retrieve=VectorDBRetriever(),
        call_brief=FreshCallBrief(CallBriefProjector(), db_client),
        guardrail=PIIGuardrail(),
        persist=persist,
    )

async def build_deepagent_harness_async(memory_mode: MemoryMode = "durable"):
    """Build and initialize a harness that uses MCP Clients."""
    harness = build_deepagent_harness(memory_mode=memory_mode)
    await harness.__aenter__()
    return harness
