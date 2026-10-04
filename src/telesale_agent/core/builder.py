from __future__ import annotations
from telesale_agent.core.interfaces import (
    Perceiver, IdentityResolver, Retriever, CallBriefBuilder,
    Planner, Guardrail, Actor, Observer, Persister, CRMRetriever, ASREngine,
)
from telesale_agent.core.langgraph_pipeline import LangGraphAgentHarness

class AgentHarnessBuilder:
    """Builder pattern to construct an AgentHarness with specific adapters."""
    
    def __init__(self):
        self._asr: ASREngine | None = None
        self._perceive: Perceiver | None = None
        self._identity: IdentityResolver | None = None
        self._crm: CRMRetriever | None = None
        self._retrieve: Retriever | None = None
        self._call_brief: CallBriefBuilder | None = None
        self._plan: Planner | None = None
        self._guardrail: Guardrail | None = None
        self._act: Actor | None = None
        self._observe: Observer | None = None
        self._persist: Persister | None = None

    def with_asr(self, adapter: ASREngine) -> AgentHarnessBuilder:
        self._asr = adapter
        return self

    def with_perceiver(self, adapter: Perceiver) -> AgentHarnessBuilder:
        self._perceive = adapter
        return self

    def with_identity_resolver(self, adapter: IdentityResolver) -> AgentHarnessBuilder:
        self._identity = adapter
        return self

    def with_crm(self, adapter: 'CRMRetriever') -> AgentHarnessBuilder:
        self._crm = adapter
        return self

    def with_retriever(self, adapter: Retriever) -> AgentHarnessBuilder:
        self._retrieve = adapter
        return self

    def with_call_brief_builder(self, adapter: CallBriefBuilder) -> AgentHarnessBuilder:
        self._call_brief = adapter
        return self

    def with_planner(self, adapter: Planner) -> AgentHarnessBuilder:
        self._plan = adapter
        return self

    def with_guardrail(self, adapter: Guardrail) -> AgentHarnessBuilder:
        self._guardrail = adapter
        return self

    def with_actor(self, adapter: Actor) -> AgentHarnessBuilder:
        self._act = adapter
        return self

    def with_observer(self, adapter: Observer) -> AgentHarnessBuilder:
        self._observe = adapter
        return self

    def with_persister(self, adapter: Persister) -> AgentHarnessBuilder:
        self._persist = adapter
        return self

    def build(self) -> LangGraphAgentHarness:
        """Constructs the harness. Validates that all stages are provided."""
        
        missing = []
        if not self._asr: missing.append("asr")
        if not self._perceive: missing.append("perceive")
        if not self._identity: missing.append("identity")
        if not self._crm: missing.append("crm")
        if not self._retrieve: missing.append("retrieve")
        if not self._call_brief: missing.append("call_brief")
        if not self._plan: missing.append("plan")
        if not self._guardrail: missing.append("guardrail")
        if not self._act: missing.append("act")
        if not self._observe: missing.append("observe")
        if not self._persist: missing.append("persist")
        
        if missing:
            raise ValueError(f"Cannot build AgentHarness. Missing adapters for stages: {', '.join(missing)}")
            
        return LangGraphAgentHarness(
            asr=self._asr,
            perceive=self._perceive,
            identity=self._identity,
            crm=self._crm,
            retrieve=self._retrieve,
            call_brief=self._call_brief,
            plan=self._plan,
            guardrail=self._guardrail,
            act=self._act,
            observe=self._observe,
            persist=self._persist
        )
