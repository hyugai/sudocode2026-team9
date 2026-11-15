from datetime import date

import pytest

from mcp_servers.tools import catalog
from telesale_agent.adapters.llm.llm_call_brief import LLMCallBriefBuilder
from telesale_agent.adapters.memory import (
    FileCustomerMemoryRepository,
    TurnMemoryPersister,
)
from telesale_agent.core.deepagent_pipeline import DeepAgentHarness
from telesale_agent.application.deepagent.context.prompt import build_base_user_message
from telesale_agent.application.deepagent.tools.protocol import tool_calls_to_steps
from telesale_agent.core.models import (
    CallBrief,
    ConversationState,
    CustomerIdentity,
    Perception,
    TurnContext,
    TurnInput,
)
from telesale_agent.application.deepagent.tools.routing import select_tools_for_turn


class RunLitePricingDB:
    def search_products(self, sku=None, **_):
        runlite = {
            "sku": "SKU-SN-RUN2",
            "name": "RunLite 2 Pro",
            "category": "thoi-trang/giay",
            "list_price_vnd": 1_690_000,
            "variants": [
                {"variant_sku": "SKU-SN-RUN2-38-DEN", "size": 38, "price_delta": 0},
                {"variant_sku": "SKU-SN-RUN2-43-DEN", "size": 43, "price_delta": 100_000},
            ],
        }
        other = {
            "sku": "SKU-AP-X",
            "name": "AirPure X",
            "category": "gia-dung/may-loc-khong-khi",
            "list_price_vnd": 4_890_000,
            "variants": [],
        }
        if sku == runlite["sku"] or sku in {
            item["variant_sku"] for item in runlite["variants"]
        }:
            return {"items": [runlite]}
        return {"items": [other] if sku == other["sku"] else []}

    def get_pricing_customer_context(self, **_):
        return {"region": "bac", "owned_skus": [], "used_promos": []}

    def get_promotions(self):
        return [
            {
                "promo_code": "COD-0", "type": "freecod", "applies_to": ["*"],
                "start_date": date(2026, 1, 1), "end_date": date(2026, 12, 31),
                "stackable": True, "conditions": {},
            },
            {
                "promo_code": "RUN2-SALE", "type": "percent",
                "applies_to": ["SKU-SN-RUN2"], "discount_percent": 20,
                "start_date": date(2026, 9, 5), "end_date": date(2026, 10, 7),
                "stackable": False, "conditions": {},
            },
            {
                "promo_code": "RUN-10", "type": "percent",
                "applies_to": ["SKU-SN-RUN2"], "discount_percent": 10,
                "start_date": date(2026, 10, 12), "end_date": date(2026, 10, 25),
                "stackable": False,
                "conditions": {"exclude_variant_size": [43]},
            },
        ]


def test_variant_inherits_base_promotion_by_date(monkeypatch):
    monkeypatch.setattr(catalog, "db_client", RunLitePricingDB())

    old = catalog.pricing_get_quote("SKU-SN-RUN2-38-DEN", on="2026-09-26")
    current = catalog.pricing_get_quote("SKU-SN-RUN2-38-DEN", on="2026-10-15")

    assert old["final_price_vnd"] == 1_352_000
    assert [p["promo_code"] for p in old["applied_promos"]] == [
        "COD-0", "RUN2-SALE"
    ]
    assert current["final_price_vnd"] == 1_521_000
    assert [p["promo_code"] for p in current["applied_promos"]] == [
        "COD-0", "RUN-10"
    ]
    assert "RUN2-SALE" in current["expired_promos"]


def test_size_exclusion_and_unrelated_basket_promo(monkeypatch):
    monkeypatch.setattr(catalog, "db_client", RunLitePricingDB())

    size_43 = catalog.pricing_get_quote("SKU-SN-RUN2-43-DEN", on="2026-10-15")
    unrelated = catalog.pricing_get_quote(
        "SKU-AP-X",
        on="2026-10-15",
        basket_skus=["SKU-SN-RUN2-38-DEN"],
    )

    assert size_43["final_price_vnd"] == 1_790_000
    assert {p["promo_code"]: p["reason"] for p in size_43["ineligible_promos"]}[
        "RUN-10"
    ] == "exclude_variant_size"
    assert unrelated["final_price_vnd"] == 4_890_000
    assert "RUN-10" not in [p["promo_code"] for p in unrelated["applied_promos"]]


@pytest.mark.parametrize("price_text", ["1.352.000 đồng", "1352000₫"])
def test_explicit_amount_routes_pricing_without_the_word_gia(price_text):
    text = f"Đôi giày size 38 màu đen còn {price_text} đúng không?"
    perception = Perception(transcript=text, intent="ask_product", intents=["ask_product"])

    assert "get_pricing_quote" in select_tools_for_turn(perception, text)


def test_address_number_alone_does_not_route_pricing():
    text = "Giao đến 100 đường Kiểm Thử, Hà Nội nhé."
    perception = Perception(transcript=text, intent="provide_info", intents=["provide_info"])

    assert "get_pricing_quote" not in select_tools_for_turn(perception, text)


@pytest.mark.asyncio
async def test_first_call_price_request_prefetches_verified_variant_quote():
    class Tool:
        def __init__(self, name, result, calls):
            self.name = name
            self.result = result
            self.calls = calls

        async def ainvoke(self, args):
            self.calls.append((self.name, args))
            return self.result

    text = (
        "Giày chạy bộ RunLite 2 Pro size 38 màu đen còn "
        "1.352.000 đồng theo RUN2-SALE đúng không?"
    )
    perception = Perception(transcript=text, intent="ask_product", intents=["ask_product"])
    allowed = select_tools_for_turn(perception, text)
    assert {"search_catalog", "check_inventory", "get_pricing_quote"}.issubset(allowed)

    calls = []
    harness = DeepAgentHarness()
    harness.mcp_tools = {
        "search_catalog": Tool("catalog", {"items": [{
            "sku": "SKU-SN-RUN2",
            "variants": [{"variant_sku": "SKU-SN-RUN2-38-DEN"}],
        }]}, calls),
        "check_inventory": Tool("inventory", {
            "sku": "SKU-SN-RUN2-38-DEN", "in_stock": True, "qty": 5,
        }, calls),
        "get_pricing_quote": Tool("pricing", {
            "final_price_vnd": 1_352_000,
            "applied_promos": [{"promo_code": "RUN2-SALE", "discount_vnd": 338_000}],
        }, calls),
    }
    context = TurnContext(
        input=TurnInput(
            conversation_id="SC-081-call-1",
            text=text,
            metadata={"call_date": "2026-09-26"},
        ),
        state=ConversationState(conversation_id="SC-081-call-1"),
        perception=perception,
    )

    verified, _ = await harness._prefetch_read_tools(context, allowed)

    assert [name for name, _ in calls] == ["catalog", "inventory", "pricing"]
    assert calls[-1][1]["sku"] == "SKU-SN-RUN2-38-DEN"
    assert calls[-1][1]["on"] == "2026-09-26"
    assert verified[-1]["result"]["final_price_vnd"] == 1_352_000


@pytest.mark.asyncio
async def test_first_verified_quote_survives_price_change_in_file_memory(tmp_path):
    memory = FileCustomerMemoryRepository(tmp_path)
    persister = TurnMemoryPersister(memory)
    customer_id = "C001"

    def quote_context(call_key, call_date, result):
        state = ConversationState(conversation_id=f"SC-081-{call_key}")
        context = TurnContext(
            input=TurnInput(
                conversation_id=state.conversation_id,
                text="Báo giá đôi giày size 38 màu đen giúp chị.",
                metadata={"call_key": call_key, "call_date": call_date},
            ),
            state=state,
            identity=CustomerIdentity(customer_id=customer_id),
            perception=Perception(transcript="Báo giá đôi giày size 38 màu đen giúp chị."),
        )
        context.steps = tool_calls_to_steps([{
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-SN-RUN2-38-DEN", "on": call_date},
            "result": result,
        }])
        return context

    old = quote_context("call_1", "2026-09-26", {
        "final_price_vnd": 1_352_000,
        "applied_promos": [{"promo_code": "RUN2-SALE", "discount_vnd": 338_000}],
    })
    await persister.persist(old)
    assert memory.latest_fact(customer_id, "price_quoted_vnd") == 1_352_000
    assert memory.latest_fact(customer_id, "promo_code") == "RUN2-SALE"

    current = quote_context("call_2", "2026-10-15", {
        "final_price_vnd": 1_521_000,
        "applied_promos": [{"promo_code": "RUN-10", "discount_vnd": 169_000}],
    })
    current.state.customer_memory = memory.load(customer_id)
    await persister.persist(current)

    facts = memory.load(customer_id)["facts"]
    assert facts["price_quoted_vnd"] == 1_521_000
    assert facts["promo_code"] == "RUN-10"
    assert facts["previous_price_quoted_vnd"] == 1_352_000
    assert facts["previous_promo_code"] == "RUN2-SALE"
    next_context = TurnContext(
        input=TurnInput(conversation_id="SC-081-call-2-next", text="Giá cũ sao khác?"),
        state=ConversationState(
            conversation_id="SC-081-call-2-next",
            customer_memory=memory.load(customer_id),
        ),
        identity=current.identity,
        perception=Perception(transcript="Giá cũ sao khác?", intent="price_objection"),
    )
    next_context.call_brief = await LLMCallBriefBuilder().build_call_brief(next_context)
    _, prompt = build_base_user_message(next_context, [])
    assert "previous_price_quoted_vnd: 1352000" in prompt
    assert "previous_promo_code: RUN2-SALE" in prompt


@pytest.mark.asyncio
async def test_order_uses_current_variant_quote_not_historical_memory():
    class CreateTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-TEST", "status": "created"}

    create = CreateTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    text = (
        "Chị đồng ý lấy một đôi. Địa chỉ giao hàng là "
        "100 đường Kiểm Thử, Hà Nội. Thanh toán COD."
    )
    state = ConversationState(conversation_id="SC-081-call-2")
    context = TurnContext(
        input=TurnInput(
            conversation_id=state.conversation_id,
            text=text,
            customer_hint="0984726714",
            metadata={"call_date": "2026-10-15", "call_key": "call_2"},
        ),
        state=state,
        identity=CustomerIdentity(customer_id="C038", phone="0984726714"),
        perception=Perception(
            transcript=text,
            intent="create_order",
            intents=["create_order"],
            entities={"delivery_address": "100 đường Kiểm Thử, Hà Nội"},
        ),
        call_brief=CallBrief(
            customer_id="C038",
            remembered_preferences={"facts": {
                "variant_sku": "SKU-SN-RUN2-38-DEN",
                "price_quoted_vnd": 1_352_000,
                "promo_code": "RUN2-SALE",
            }},
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-SN-RUN2-38-DEN", "on": "2026-10-15"},
            "result": {"in_stock": True, "qty": 5},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-SN-RUN2-38-DEN", "on": "2026-10-15"},
            "result": {
                "final_price_vnd": 1_521_000,
                "applied_promos": [
                    {"promo_code": "COD-0", "discount_vnd": 0},
                    {"promo_code": "RUN-10", "discount_vnd": 169_000},
                ],
            },
        },
    ]

    calls, _ = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert len(calls) == 1
    assert create.calls[0]["sku"] == "SKU-SN-RUN2-38-DEN"
    assert create.calls[0]["price_vnd"] == 1_521_000
    assert create.calls[0]["promo_code"] == "RUN-10"
