import asyncio

from telesale_agent.application import CustomerContextService
from telesale_agent.core.models import (
    ConversationState,
    CustomerIdentity,
    TurnContext,
    TurnInput,
)


class FakeCRM:
    async def retrieve_profile(self, context):
        return {"customer_id": "C031", "name": "Oanh", "phone": "0985003703"}

    async def precompute_brief(self, context):
        return {"past_orders": [{"sku": "SKU-AP-X"}]}


class FakeMemory:
    def __init__(self):
        self.fact_value = None

    def load(self, customer_id):
        assert customer_id == "C031"
        return {
            "facts": {"budget_vnd": self.fact_value} if self.fact_value else {},
            "episodes": [{"source": "episode.md", "content": "Asked about filter"}],
        }


def test_composes_crm_and_file_memory_without_merging_sources():
    state = ConversationState(conversation_id="conversation-1")
    context = TurnContext(
        input=TurnInput(conversation_id="conversation-1", text="Alo"),
        state=state,
        identity=CustomerIdentity(customer_id="C031", phone="0985003703"),
    )

    asyncio.run(CustomerContextService(FakeCRM(), FakeMemory()).hydrate(context))

    assert state.customer_profile["name"] == "Oanh"
    assert state.customer_memory["episodes"][0]["source"] == "episode.md"
    assert state.past_history["past_orders"][0]["sku"] == "SKU-AP-X"
    assert state.past_history["sessions"][0]["content"] == "Asked about filter"


def test_refresh_memory_reloads_turn_updates_without_querying_crm():
    state = ConversationState(conversation_id="conversation-1")
    context = TurnContext(
        input=TurnInput(conversation_id="conversation-1", text="Alo"),
        state=state,
        identity=CustomerIdentity(customer_id="C031"),
    )
    memory = FakeMemory()
    service = CustomerContextService(FakeCRM(), memory)
    asyncio.run(service.hydrate(context))

    memory.fact_value = 6_000_000
    asyncio.run(service.refresh_memory(context))

    assert state.customer_memory["facts"]["budget_vnd"] == 6_000_000
