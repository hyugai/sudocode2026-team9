"""Regression checks for SC-112/115/116/118/120 basket handling."""

import json
from pathlib import Path

import pytest

from telesale_agent.application.deepagent.context.order import (
    _current_turn_has_delivery_address,
    _delivery_address,
)
from telesale_agent.application.deepagent.context.prompt import build_base_user_message
from telesale_agent.application.deepagent.harness import DeepAgentHarness
from telesale_agent.application.deepagent.response import (
    ground_basket_recap,
    ground_multi_item_order_confirmation,
)
from telesale_agent.application.deepagent.tools.protocol import tool_calls_to_steps
from telesale_agent.application.deepagent.tools.routing import select_tools_for_turn
from telesale_agent.application.memory.turn_facts import _basket_memory_candidates, _tool_memory_candidates
from telesale_agent.core.basket import (
    declines_order_creation,
    is_multi_product_request,
    mentioned_catalog_items,
    starts_basket_checkout,
)
from telesale_agent.core.address import extract_explicit_delivery_address
from telesale_agent.adapters.llm.llm_perceive import canonicalize_memory_deltas
from telesale_agent.core.models import (
    CallBrief,
    ConversationState,
    CustomerIdentity,
    Perception,
    TurnContext,
    TurnInput,
)

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario_id,expected", [
    ("SC-112", ["SKU-MB-PUMP2", "SKU-FAN-SEN"]),
    ("SC-115", ["SKU-MB-STER", "SKU-FAN-SEN"]),
    ("SC-116", ["SKU-AP-X", "SKU-FAN-SEN"]),
    ("SC-118", ["SKU-MB-PUMP1", "SKU-FAN-SEN"]),
    ("SC-120", ["SKU-SS-AX40", "SKU-FAN-SEN"]),
])
def test_real_scenario_first_turn_resolves_only_named_catalog_items(scenario_id, expected):
    scenario_path = (
        _ROOT / "dataset" / "iterative-refinement"
        / "scenarios_complete dataset" / f"{scenario_id}.json"
    )
    catalog_path = _ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "catalog" / "products.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))["products"]
    text = scenario["calls"]["call_1"]["customer_turns"][0]

    assert is_multi_product_request(text)
    assert [item["sku"] for item in mentioned_catalog_items(text, catalog)] == expected


def test_payment_amount_never_replaces_remembered_delivery_address():
    text = "Tổng trên 10 triệu nên chị chọn chuyển khoản ngân hàng, không COD."
    context = TurnContext(
        input=TurnInput(conversation_id="sc-112", text=text),
        state=ConversationState(
            conversation_id="sc-112",
            working_memory={"pending_order": {"basket_skus": ["SKU-A", "SKU-B"]}},
        ),
        perception=Perception(transcript=text, entities={"address": text}),
        call_brief=CallBrief(
            customer_id="C001",
            remembered_preferences={
                "facts": {"delivery_address": "101 đường Kiểm Thử, Đà Nẵng"}
            },
        ),
    )
    assert not _current_turn_has_delivery_address(context, allow_bare_reply=True)
    assert _delivery_address(context) == "101 đường Kiểm Thử, Đà Nẵng"


def test_address_extraction_preserves_city_abbreviation_without_nlu_entity():
    assert extract_explicit_delivery_address(
        "Mỗi món một chiếc, giao 109 đường Kiểm Thử, TP. Hồ Chí Minh."
    ) == "109 đường Kiểm Thử, TP. Hồ Chí Minh"


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [
    "101 đường Kiểm Thử, Đà Nẵng",
    "109 đường Kiểm Thử, TP. Hồ Chí Minh",
])
async def test_multi_item_create_uses_saved_address_on_numeric_payment_turn(address):
    class CreateTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": f"ORD-{len(self.calls)}", "status": "created"}

    tool = CreateTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": tool}
    text = "Tổng trên 10 triệu nên chị chọn chuyển khoản ngân hàng, không COD."
    skus = ["SKU-MB-PUMP2", "SKU-MB-CAR"]
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-112",
            text=text,
            customer_hint="0900000000",
        ),
        state=ConversationState(
            conversation_id="sc-112",
            customer_profile={"phone": "0900000000"},
            working_memory={"pending_order": {"basket_skus": skus}},
        ),
        perception=Perception(transcript=text, entities={"address": text}),
        identity=CustomerIdentity(customer_id="C001", phone="0900000000"),
        call_brief=CallBrief(
            customer_id="C001",
            remembered_preferences={
                "facts": {"basket_skus": skus, "delivery_address": address}
            },
        ),
    )
    verified = [
        {"name": "inventory.check", "args": {"sku": sku},
         "result": {"in_stock": True, "qty": 5}}
        for sku in skus
    ] + [
        {"name": "pricing.quote_order", "args": {"lines": [{"sku": sku} for sku in skus]},
         "result": {"units": [
             {"sku": sku, "final_price_vnd": price, "applied_promos": []}
             for sku, price in zip(skus, [5_990_000, 4_990_000])
         ]}}
    ]

    await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert len(tool.calls) == 1
    assert [line["sku"] for line in tool.calls[0]["lines"]] == skus
    assert all(call["address"] == address for call in tool.calls)
    assert all(call["payment_method"] == "bank" for call in tool.calls)


def test_broad_catalog_result_does_not_become_basket():
    items = [
        {"sku": f"SKU-{number}", "name": f"Máy thử nghiệm {number}"}
        for number in range(15)
    ]
    context = TurnContext(
        input=TurnInput(conversation_id="sc-116", text="Em nhắc đúng hai món cuối cùng nhé"),
        state=ConversationState(conversation_id="sc-116"),
    )
    assert mentioned_catalog_items(context.input.text, items) == []
    assert _basket_memory_candidates(context, items) == {}


@pytest.mark.asyncio
async def test_two_named_products_are_prefetched_and_saved_without_model_tools():
    class StubTool:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return self.result

    text = (
        "Shop ơi, anh mua đồ cho nhà mới, đang tính "
        "Máy hút sữa điện đôi Spectra S1 với Quạt đứng Senko TS16."
    )
    catalog = StubTool({"items": [
        {"sku": "SKU-MB-PUMP1", "name": "Máy hút sữa điện đôi Spectra S1"},
        {"sku": "SKU-FAN-SEN", "name": "Quạt đứng Senko TS16"},
    ]})
    inventory = StubTool({"in_stock": True, "qty": 5})
    harness = DeepAgentHarness()
    harness.mcp_tools = {"search_catalog": catalog, "check_inventory": inventory}
    context = TurnContext(
        input=TurnInput(conversation_id="sc-118", text=text),
        state=ConversationState(conversation_id="sc-118"),
        perception=Perception(transcript=text, intent="unknown"),
    )
    allowed = select_tools_for_turn(context.perception, text)
    assert {"search_catalog", "check_inventory"}.issubset(allowed)

    calls, remaining = await harness._prefetch_read_tools(context, allowed)

    assert catalog.calls == [{"query": text}]
    assert [call["name"] for call in calls] == [
        "catalog.search", "inventory.check", "inventory.check"
    ]
    assert remaining == frozenset()
    context.steps = tool_calls_to_steps(calls)
    assert _tool_memory_candidates(context)["basket_skus"] == [
        "SKU-MB-PUMP1", "SKU-FAN-SEN"
    ]


def test_swap_replaces_second_item_after_accent_normalization():
    text = "À đổi ý, bỏ món thứ hai vừa nói, thay bằng Máy hâm sữa Fatz 4 chức năng."
    context = TurnContext(
        input=TurnInput(conversation_id="sc-118", text=text),
        state=ConversationState(
            conversation_id="sc-118",
            customer_memory={"facts": {"basket_skus": ["SKU-MB-PUMP1", "SKU-FAN-SEN"]}},
        ),
    )
    result = _basket_memory_candidates(context, [
        {"sku": "SKU-MB-MON", "name": "Máy hâm sữa Fatz 4 chức năng"},
        {"sku": "SKU-FAN-SEN", "name": "Quạt đứng Senko TS16"},
    ])
    assert result["basket_skus"] == ["SKU-MB-PUMP1", "SKU-MB-MON"]
    assert result["removed_sku"] == "SKU-FAN-SEN"


def test_budget_is_not_overwritten_by_a_confirmed_cart_total():
    original = canonicalize_memory_deltas(
        {"budget_vnd": 2_680_000},
        "Ngân sách tổng của chị là 2.680.000 đồng.",
    )
    later = canonicalize_memory_deltas(
        {"budget_vnd": 2_380_000},
        "Tổng 2.380.000 đồng nằm trong ngân sách, giao 104 đường Kiểm Thử.",
    )
    assert original["budget_vnd"] == 2_680_000
    assert "budget_vnd" not in later


def _saved_basket_context(text, *, call_date="2026-10-21"):
    skus = ["SKU-MB-STER", "SKU-MB-MON"]
    names = {
        "SKU-MB-STER": "Máy tiệt trùng sấy khô Moaz Bebe",
        "SKU-MB-MON": "Máy hâm sữa Fatz 4 chức năng",
    }
    return TurnContext(
        input=TurnInput(
            conversation_id="sc-115-call-2", text=text,
            metadata={"call_date": call_date},
        ),
        state=ConversationState(conversation_id="sc-115-call-2"),
        call_brief=CallBrief(
            customer_id="C003",
            remembered_preferences={"facts": {
                "basket_skus": skus,
                "basket_product_names": names,
                "budget_vnd": 2_680_000,
            }},
        ),
    )


def test_catalog_names_survive_a_basket_swap():
    text = "À đổi ý, bỏ món thứ hai, thay bằng Máy hâm sữa Fatz 4 chức năng."
    context = _saved_basket_context(text)
    context.state.customer_memory = {
        "facts": {
            "basket_skus": ["SKU-MB-STER", "SKU-FAN-SEN"],
            "basket_product_names": {
                "SKU-MB-STER": "Máy tiệt trùng sấy khô Moaz Bebe",
                "SKU-FAN-SEN": "Quạt đứng Senko TS16",
            },
        }
    }
    result = _basket_memory_candidates(context, [
        {"sku": "SKU-MB-MON", "name": "Máy hâm sữa Fatz 4 chức năng"},
    ])
    assert result["basket_product_names"] == {
        "SKU-MB-STER": "Máy tiệt trùng sấy khô Moaz Bebe",
        "SKU-MB-MON": "Máy hâm sữa Fatz 4 chức năng",
    }


def test_recap_routes_current_pricing_and_prompt_contains_exact_names():
    text = "Em nhắc đúng hai món cuối cùng sau khi sửa và tổng tiền nhé."
    context = _saved_basket_context(text)
    facts = context.call_brief.remembered_preferences["facts"]
    tools = select_tools_for_turn(Perception(transcript=text), text, facts)
    _, prompt = build_base_user_message(context, [])
    assert "get_pricing_quote" in tools
    assert "Máy hâm sữa Fatz 4 chức năng" in prompt
    assert "budget_vnd" in prompt


def test_prior_consultation_does_not_hide_saved_cart_recap_or_trigger_order_lookup():
    text = (
        "Anh muốn tiếp tục phần tư vấn lần trước. "
        "Em nhắc đúng hai món cuối cùng và tổng tiền nhé."
    )
    facts = _saved_basket_context(text).call_brief.remembered_preferences["facts"]
    tools = select_tools_for_turn(
        Perception(transcript=text, intent="complain"), text, facts
    )
    assert "get_pricing_quote" in tools
    assert "check_order_status" not in tools
    assert "search_catalog" not in tools


def test_saved_cart_only_recap_does_not_lookup_order_but_explicit_order_question_does():
    facts = _saved_basket_context("x").call_brief.remembered_preferences["facts"]
    recap = "Em xác nhận lại đúng hai món sau khi sửa giúp anh."
    tools = select_tools_for_turn(
        Perception(transcript=recap, intent="complain"), recap, facts
    )
    assert "check_order_status" not in tools
    order_question = "Em nhắc hai món và kiểm tra mã đơn ORD-123 giúp anh."
    order_tools = select_tools_for_turn(
        Perception(transcript=order_question, intent="complain"),
        order_question,
        facts,
    )
    assert "check_order_status" in order_tools
    bare_id_question = "Nhắc hai món và kiểm tra ORD-123 giúp anh."
    assert "check_order_status" in select_tools_for_turn(
        Perception(transcript=bare_id_question, intent="complain"),
        bare_id_question,
        facts,
    )


@pytest.mark.asyncio
async def test_recap_prefetches_one_current_basket_quote():
    class QuoteTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"units": [{"sku": line["sku"], "final_price_vnd": 490_000}
                              for line in args["lines"]], "total_vnd": 980_000}

    text = "Em nhắc đúng hai món cuối cùng sau khi sửa và tổng tiền nhé."
    context = _saved_basket_context(text)
    quote = QuoteTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"get_order_quote": quote}
    allowed = select_tools_for_turn(
        Perception(transcript=text), text,
        context.call_brief.remembered_preferences["facts"],
    )

    calls, remaining = await harness._prefetch_read_tools(context, allowed)

    assert len(calls) == 1
    assert [line["sku"] for line in calls[0]["args"]["lines"]] == [
        "SKU-MB-STER", "SKU-MB-MON"
    ]
    assert all(call["args"]["on"] == "2026-10-21" for call in calls)
    assert "get_pricing_quote" not in remaining
    assert "get_order_quote" not in remaining


def test_recap_uses_both_current_quotes_and_exact_catalog_names():
    context = _saved_basket_context(
        "Em nhắc đúng hai món cuối cùng sau khi sửa và tổng tiền nhé."
    )
    quotes = [
        {"name": "pricing.get_quote", "args": {"sku": sku, "qty": 1, "on": "2026-10-21"},
         "result": {"final_price_vnd": price}}
        for sku, price in [("SKU-MB-STER", 1_890_000), ("SKU-MB-MON", 490_000)]
    ]
    recap = ground_basket_recap(context, quotes, "Em chưa thể báo tổng tiền ạ.")
    assert "Máy hâm sữa Fatz 4 chức năng" in recap
    assert "Máy theo dõi" not in recap
    assert "2.380.000 đồng" in recap
    incomplete = ground_basket_recap(context, quotes[:1], "Tổng cũ 2.380.000 đồng")
    assert "chưa xác minh đủ giá hiện tại" in incomplete
    assert "2.380.000" not in incomplete
    stale = [dict(call, args=dict(call["args"], on="2026-10-19")) for call in quotes]
    assert "chưa xác minh đủ giá hiện tại" in ground_basket_recap(
        context, stale, "Tổng cũ 2.380.000 đồng"
    )


def test_recap_uses_changed_current_call_prices_not_previous_call_quotes():
    context = _saved_basket_context(
        "Em nhắc hai món và tổng tiền nhé.", call_date="2026-10-21"
    )
    quotes = [
        {
            "name": "pricing.get_quote",
            "args": {"sku": sku, "qty": 1, "on": day},
            "result": {"final_price_vnd": price},
        }
        for day, prices in (
            ("2026-10-19", (1_890_000, 490_000)),
            ("2026-10-21", (2_090_000, 490_000)),
        )
        for sku, price in zip(("SKU-MB-STER", "SKU-MB-MON"), prices)
    ]
    answer = ground_basket_recap(context, quotes, "Tổng cũ 2.380.000 đồng")
    assert "2.580.000 đồng" in answer
    assert "2.380.000" not in answer


def test_checkout_progress_requires_new_consent_and_explicit_delivery_details():
    accepted = (
        "Tổng 2.380.000 đồng nằm trong ngân sách, "
        "mỗi món một chiếc, giao 104 đường Kiểm Thử, Hà Nội."
    )
    assert starts_basket_checkout(accepted)
    assert not starts_basket_checkout("Anh chọn thanh toán COD.")
    assert not starts_basket_checkout(
        "Tổng này nằm trong ngân sách, mỗi món một chiếc nhưng chưa đặt hàng. "
        "Địa chỉ là 104 đường Kiểm Thử, Hà Nội."
    )
    assert declines_order_creation("Chưa đặt hàng nhé.")
    assert not starts_basket_checkout(
        "Tổng này nằm trong ngân sách, mỗi món một chiếc, "
        "giao 104 đường Kiểm Thử, Hà Nội, nhưng hôm nay chưa mua."
    )


@pytest.mark.asyncio
async def test_accepted_cart_creates_once_when_payment_completes_checkout():
    class ReadTool:
        def __init__(self, result):
            self.result = result

        async def ainvoke(self, args):
            if "lines" in args:
                return {"units": [{"sku": line["sku"], "final_price_vnd": 1_190_000}
                                  for line in args["lines"]], "total_vnd": 2_380_000}
            return {**self.result, "sku": args["sku"]}

    class CreateTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": f"ORD-{len(self.calls)}", "status": "created"}

    harness = DeepAgentHarness()
    create = CreateTool()
    harness.mcp_tools = {
        "check_inventory": ReadTool({"in_stock": True, "qty": 5}),
        "get_pricing_quote": ReadTool({"final_price_vnd": 1_190_000}),
        "get_order_quote": ReadTool({}),
        "create_new_order": create,
    }
    state = ConversationState(
        conversation_id="basket-checkout",
        customer_profile={"phone": "0900000000"},
    )
    facts = {
        "basket_skus": ["SKU-A", "SKU-B"],
        "basket_product_names": {"SKU-A": "Món A", "SKU-B": "Món B"},
    }
    brief = CallBrief(customer_id="C001", remembered_preferences={"facts": facts})
    identity = CustomerIdentity(customer_id="C001", phone="0900000000")

    async def run_turn(text):
        context = TurnContext(
            input=TurnInput(
                conversation_id="basket-checkout",
                text=text,
                customer_hint="0900000000",
                metadata={"call_date": "2026-10-21", "call_key": "call_2"},
            ),
            state=state,
            identity=identity,
            perception=Perception(transcript=text),
            call_brief=brief,
        )
        allowed = set(select_tools_for_turn(context.perception, text, facts))
        if state.working_memory.get("pending_order") and _delivery_address(context):
            allowed.update({"create_new_order", "check_inventory", "get_pricing_quote"})
        reads, remaining = await harness._prefetch_read_tools(
            context, frozenset(allowed)
        )
        writes, _ = await harness._execute_confirmed_mutation(
            context, remaining, reads
        )
        return writes

    first = await run_turn(
        "Tổng 2.380.000 đồng nằm trong ngân sách, mỗi món một chiếc, "
        "giao 104 đường Kiểm Thử, Hà Nội."
    )
    assert first == []
    assert state.working_memory["pending_order"]["checkout_confirmed"] is True
    assert state.working_memory["pending_order"]["address"] == (
        "104 đường Kiểm Thử, Hà Nội"
    )

    second = await run_turn("Anh chọn thanh toán COD.")
    assert [call["name"] for call in second] == ["order.create"]
    assert [line["sku"] for line in create.calls[0]["lines"]] == ["SKU-A", "SKU-B"]
    assert all(call["payment_method"] == "COD" for call in create.calls)
    assert all(call["address"] == "104 đường Kiểm Thử, Hà Nội" for call in create.calls)
    assert "pending_order" not in state.working_memory


@pytest.mark.asyncio
async def test_customer_can_cancel_pending_checkout_before_payment():
    harness = DeepAgentHarness()
    context = _saved_basket_context("Chưa đặt hàng nhé, tôi chỉ chọn COD để tham khảo.")
    context.state.working_memory["pending_order"] = {
        "basket_skus": ["SKU-MB-STER", "SKU-MB-MON"],
        "address": "104 đường Kiểm Thử, Hà Nội",
        "checkout_confirmed": True,
    }
    calls, _ = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), []
    )
    assert calls == []
    assert "pending_order" not in context.state.working_memory


def test_order_confirmation_pairs_each_name_with_its_verified_order_id():
    context = _saved_basket_context("Chị chọn thanh toán COD.")
    created = [
        {"name": "order.create", "args": {"sku": sku, "address": "104 đường Kiểm Thử", "payment": "COD"},
         "result": {"order_id": order_id}}
        for sku, order_id in [
            ("SKU-MB-STER", "ORD-FIRST"), ("SKU-MB-MON", "ORD-SECOND")
        ]
    ]
    answer = ground_multi_item_order_confirmation(
        context, created, "Em đã tạo đơn cho máy theo dõi em bé."
    )
    assert "Máy hâm sữa Fatz 4 chức năng — mã đơn ORD-SECOND" in answer
    assert "Máy tiệt trùng sấy khô Moaz Bebe — mã đơn ORD-FIRST" in answer
    assert "Máy theo dõi" not in answer
