import pytest

from telesale_agent.adapters.memory.turn_persist import _tool_memory_candidates
from telesale_agent.core.models import (
    ActionPlan,
    ActionResult,
    ActionStatus,
    AgentStep,
    CallBrief,
    ConversationState,
    CustomerIdentity,
    Message,
    Observation,
    Perception,
    PolicyDecision,
    TurnContext,
    TurnInput,
)
from telesale_agent.application.deepagent.tools.routing import select_tools_for_turn
from telesale_agent.application.deepagent.tools.routing import (
    is_explicit_callback_request,
    is_medical_handoff_request,
)
from telesale_agent.core.deepagent_pipeline import (
    DeepAgentHarness,
    _compact_orchestrated_result,
    _delivery_address,
    _recent_conversation_context,
    _requested_callback_at,
    _requested_exchange_sku,
    _safe_fallback_response,
    _single_variant_sku,
)
from mcp_servers.tools.catalog import _filter_requested_variants
from mcp_servers.tools import catalog as catalog_tools


def test_routes_exchange_turn_to_small_order_tool_set():
    perception = Perception(
        transcript="Đổi lên size 40 được không em?",
        intent="update_order",
        intents=["update_order", "ask_policy"],
    )

    tools = select_tools_for_turn(perception, perception.transcript)

    assert "update_order" not in tools
    assert "check_order_status" in tools
    assert "check_inventory" in tools
    assert "search_policy" in tools
    assert "search_catalog" not in tools
    assert "create_new_order" not in tools
    assert "mcp_schedule_callback" not in tools


def test_routes_confirmed_exchange_to_mutation_tool():
    perception = Perception(
        transcript="Ừ em làm thủ tục đổi cho anh nhé.",
        intent="update_order",
        intents=["update_order"],
    )

    tools = select_tools_for_turn(
        perception,
        perception.transcript,
        {
            "order_id": "ORD-TEST",
            "pending_variant_sku": "SKU-SN-CAS-40-DEN",
        },
    )

    assert {"check_order_status", "check_inventory", "update_order"}.issubset(
        tools
    )


def test_routes_policy_keyword_when_nlu_misses_ask_policy():
    text = (
        "Nếu mua mới hôm nay thì được đổi trong 14 ngày và mất phí "
        "20 nghìn phải không? Hình như đó là bài cũ."
    )
    perception = Perception(
        transcript=text,
        intent="complain",
        intents=["complain"],
    )

    tools = select_tools_for_turn(perception, text)

    assert "search_policy" in tools
    assert "check_order_status" not in tools
    assert "check_inventory" not in tools


@pytest.mark.asyncio
async def test_prefetches_policy_into_verified_context_without_model_tool_call():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {
                "query": args["query"],
                "chunks": [
                    {
                        "content": "Đổi trả trong 7 ngày; đổi size lần đầu miễn phí.",
                        "source_file": "chinh-sach-doi-tra.md",
                        "section": "[DT-03] Đổi size / màu",
                    }
                ],
            }

    knowledge = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"search_policy": knowledge}
    text = "Chính sách đổi size lần đầu hiện tại thế nào?"
    context = TurnContext(
        input=TurnInput(
            conversation_id="SC-031-call-2",
            text=text,
            metadata={"call_date": "2026-10-17"},
        ),
        state=ConversationState(conversation_id="SC-031-call-2"),
        perception=Perception(
            transcript=text,
            intent="ask_policy",
            intents=["ask_policy"],
        ),
    )

    calls, remaining = await harness._prefetch_read_tools(
        context, frozenset({"search_policy"})
    )

    assert "search_policy" not in remaining
    assert knowledge.calls == [
        {"query": text, "k": 3, "as_of": "2026-10-17"}
    ]
    assert calls[0]["name"] == "policy.search"
    assert "7 ngày" in calls[0]["result"]["chunks"][0]["content"]


@pytest.mark.asyncio
async def test_knowledge_mcp_prewarm_loads_tool_once(monkeypatch):
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"count": 1, "chunks": [{"content": "7 ngày"}]}

    monkeypatch.setenv("KNOWLEDGE_MCP_PREWARM", "true")
    knowledge = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"search_policy": knowledge}

    await harness._prewarm_knowledge_mcp()

    assert knowledge.calls == [
        {"query": "chính sách đổi trả hiện hành", "k": 1}
    ]


def test_routes_price_turn_without_unrelated_workflow_tools():
    perception = Perception(
        transcript="Giá bao nhiêu, có giảm gì không em?",
        intent="price_objection",
        intents=["price_objection"],
    )

    assert select_tools_for_turn(perception, perception.transcript) == frozenset(
        {"get_pricing_quote", "get_order_quote"}
    )


def test_routes_promotion_terms_to_policy_and_current_quote():
    text = "Điều kiện khuyến mãi và giá hiện tại của sản phẩm này là gì?"
    perception = Perception(
        transcript=text,
        intent="price_objection",
        intents=["price_objection"],
    )

    assert {"search_policy", "get_pricing_quote"}.issubset(
        select_tools_for_turn(perception, text)
    )


def test_future_policy_question_is_remembered_without_retrieving_early():
    text = "Chị chỉ tham khảo, chưa đặt đơn. Khi quay lại chị sẽ hỏi thêm điều kiện đổi size."
    perception = Perception(
        transcript=text,
        intent="ask_policy",
        intents=["ask_policy"],
    )

    assert "search_policy" not in select_tools_for_turn(perception, text)
    current_question = "Nếu mua hôm nay thì điều kiện đổi size thế nào?"
    assert "search_policy" in select_tools_for_turn(perception, current_question)


def test_routes_natural_purchase_confirmation_to_order_tool():
    perception = Perception(
        transcript="Chị mua một chiếc, thanh toán COD nhé.",
        intent="unknown",
        intents=[],
    )

    tools = select_tools_for_turn(perception, perception.transcript)

    assert "create_new_order" in tools


def test_does_not_route_negated_order_phrase_to_order_tool():
    perception = Perception(
        transcript="Gọi lại cho chị nhé, chưa lên đơn.",
        intent="end_call",
        intents=["end_call"],
    )

    tools = select_tools_for_turn(perception, perception.transcript)

    assert "mcp_schedule_callback" in tools
    assert "create_new_order" not in tools


def test_callback_history_is_not_a_new_schedule_request():
    text = "Chị gọi lại chuyện hôm trước, người nhà đã đồng ý rồi."
    perception = Perception(transcript=text, intent="end_call", intents=["end_call"])

    assert is_explicit_callback_request(text) is False
    assert "mcp_schedule_callback" not in select_tools_for_turn(perception, text)


def test_explicit_callback_and_medical_handoff_are_narrowly_routed():
    callback_text = "Em gọi lại cho chị lúc 10 giờ ngày 2026-10-17 nhé."
    assert is_explicit_callback_request(callback_text) is True
    assert "mcp_schedule_callback" in select_tools_for_turn(
        Perception(transcript=callback_text, intent="end_call", intents=["end_call"]),
        callback_text,
    )

    generic = "Giá hotline khác giá trên fanpage, em giải thích giúp chị."
    assert is_medical_handoff_request(generic, {}) is False
    assert "mcp_escalate_to_human" not in select_tools_for_turn(
        Perception(transcript=generic, intent="complain", intents=["complain"]),
        generic,
    )

    transfer = "Nếu vượt phạm vi thì em chuyển người phụ trách giúp chị."
    facts = {"medical_question": "Dùng máy có làm thay đổi liều thuốc không?"}
    assert is_medical_handoff_request(transfer, facts) is True
    assert "mcp_escalate_to_human" in select_tools_for_turn(
        Perception(transcript=transfer, intent="complain", intents=["complain"]),
        transfer,
        facts,
    )


def test_bare_timed_callback_request_is_routed_and_parsed():
    text = "Chị còn hỏi người nhà, gọi lại lúc 10 giờ ngày 2026-10-24 nhé."
    context = TurnContext(
        input=TurnInput(conversation_id="sc-102-call-1", text=text),
        state=ConversationState(conversation_id="sc-102-call-1"),
        perception=Perception(transcript=text, intent="end_call", intents=["end_call"]),
    )

    assert is_explicit_callback_request(text) is True
    assert "mcp_schedule_callback" in select_tools_for_turn(
        context.perception, text
    )
    assert _requested_callback_at(context) == "2026-10-24T10:00"


def test_basket_swap_is_routed_to_catalog_not_order_update():
    text = (
        "Khoan, quạt Senko cơ bản quá, đổi cho anh sang "
        "Quạt đứng DC inverter Panasonic F-409 xem sao."
    )
    perception = Perception(
        transcript=text,
        intent="update_order",
        intents=["update_order"],
    )

    tools = select_tools_for_turn(
        perception,
        text,
        {"basket_skus": ["SKU-AF-6L", "SKU-FAN-SEN"]},
    )

    assert {"search_catalog", "check_inventory"}.issubset(tools)
    assert "check_order_status" not in tools
    assert "update_order" not in tools


def test_routes_terse_order_followup_from_durable_memory():
    perception = Perception(
        transcript="Ừ em làm thủ tục cho anh nhé.",
        intent="update_order",
        intents=["update_order"],
    )

    tools = select_tools_for_turn(
        perception,
        perception.transcript,
        {"order_id": "OD682761", "variant_sku": "SKU-SN-CAS-39-DEN"},
    )

    assert {"check_order_status", "update_order"}.issubset(tools)


def test_order_tool_result_becomes_cross_turn_memory():
    context = TurnContext(
        input=TurnInput(conversation_id="sample-03", text="Lên đơn"),
        state=ConversationState(conversation_id="sample-03"),
    )
    context.steps = [
        AgentStep(
            plan=ActionPlan(
                action="tool_call",
                rationale="confirmed order",
                tool_name="order.create",
                arguments={
                    "sku": "SKU-SN-CAS-39-DEN",
                    "price_vnd": 890_000,
                    "payment": "COD",
                },
            ),
            policy=PolicyDecision(allowed=True),
            action_result=ActionResult(
                status=ActionStatus.EXECUTED,
                output={"order_id": "OD682761", "status": "created"},
            ),
            observation=Observation(summary="created"),
        )
    ]

    facts = _tool_memory_candidates(context)

    assert facts["order_id"] == "OD682761"
    assert facts["product_advised"] == "SKU-SN-CAS"
    assert facts["variant_sku"] == "SKU-SN-CAS-39-DEN"
    assert facts["size"] == 39
    assert facts["color"] == "den"
    assert facts["payment"] == "COD"


def test_single_order_status_result_becomes_cross_call_memory():
    context = TurnContext(
        input=TurnInput(conversation_id="sample-03-call-2", text="Giày hơi chật"),
        state=ConversationState(conversation_id="sample-03-call-2"),
    )
    context.steps = [
        AgentStep(
            plan=ActionPlan(
                action="tool_call",
                rationale="lookup by verified phone",
                tool_name="order.status",
                arguments={"customer_phone": "0922264686"},
            ),
            policy=PolicyDecision(allowed=True),
            action_result=ActionResult(
                status=ActionStatus.EXECUTED,
                output={
                    "orders": [
                        {
                            "order_id": "OD682761",
                            "sku": "SKU-SN-CAS-39-DEN",
                            "price_vnd": 890_000,
                            "payment": "COD",
                        }
                    ]
                },
            ),
            observation=Observation(summary="found"),
        )
    ]

    facts = _tool_memory_candidates(context)

    assert facts == {
        "order_id": "OD682761",
        "order_ids_by_sku": {"SKU-SN-CAS-39-DEN": "OD682761"},
        "product_advised": "SKU-SN-CAS",
        "variant_sku": "SKU-SN-CAS-39-DEN",
        "size": 39,
        "color": "den",
        "price_quoted_vnd": 890_000,
        "payment": "COD",
    }


def test_catalog_payload_keeps_only_requested_variant():
    result = {
        "items": [
            {
                "sku": "SKU-SN-CAS",
                "variants": [
                    {"variant_sku": "SKU-SN-CAS-39-DEN", "size": "39", "color": "den"},
                    {"variant_sku": "SKU-SN-CAS-40-DEN", "size": "40", "color": "den"},
                    {"variant_sku": "SKU-SN-CAS-39-TRANG", "size": "39", "color": "trang"},
                ],
            }
        ]
    }

    filtered = _filter_requested_variants(result, "Urban Classic size 39 màu đen")

    assert filtered["items"][0]["variants"] == [
        {"variant_sku": "SKU-SN-CAS-39-DEN", "size": "39", "color": "den"}
    ]


def test_catalog_resolves_multiple_products_in_one_tool_call(monkeypatch):
    products = [
        {"sku": "SKU-AF-6L", "name": "Nồi chiên không dầu Philips 6.2L", "variants": []},
        {"sku": "SKU-FAN-DC1", "name": "Quạt đứng DC inverter Panasonic F-409", "variants": []},
        {"sku": "SKU-FAN-SEN", "name": "Quạt đứng Senko TS16", "variants": []},
    ]

    class StubDB:
        @staticmethod
        def search_products(query=None, **_kwargs):
            return {"items": [] if query else products}

    monkeypatch.setattr(catalog_tools, "db_client", StubDB())

    result = catalog_tools.catalog_search(
        "Anh đang tính Nồi chiên không dầu Philips 6.2L với "
        "Quạt đứng DC inverter Panasonic F-409"
    )

    assert [item["sku"] for item in result["items"]] == [
        "SKU-AF-6L",
        "SKU-FAN-DC1",
    ]


def test_single_variant_sku_requires_unambiguous_catalog_result():
    assert _single_variant_sku(
        {
            "items": [
                {"variants": [{"variant_sku": "SKU-SN-CAS-39-DEN"}]}
            ]
        }
    ) == "SKU-SN-CAS-39-DEN"
    assert _single_variant_sku(
        {
            "items": [
                {
                    "variants": [
                        {"variant_sku": "SKU-SN-CAS-39-DEN"},
                        {"variant_sku": "SKU-SN-CAS-40-DEN"},
                    ]
                }
            ]
        }
    ) is None
    assert _single_variant_sku(
        {"items": [{"sku": "SKU-AP-Y", "variants": []}]}
    ) == "SKU-AP-Y"


def test_compact_pricing_context_drops_unneeded_payload_fields():
    compact = _compact_orchestrated_result(
        "pricing.get_quote",
        {
            "sku": "SKU-AP-Y",
            "list_price_vnd": 5_200_000,
            "final_price_vnd": 4_800_000,
            "applied_promos": [{"promo_code": "TRADE-IN-AP"}],
            "expired_promos": ["OLD-PROMO"],
            "ineligible_promos": [{"promo_code": "X", "reason": "region"}],
            "not_applied_exclusive": ["NOISY-INTERNAL-DETAIL"],
            "freeship": True,
        },
    )

    assert compact["final_price_vnd"] == 4_800_000
    assert compact["applied_promos"] == [{"promo_code": "TRADE-IN-AP"}]
    assert "not_applied_exclusive" not in compact


def test_recent_context_defaults_to_one_customer_agent_pair(monkeypatch):
    for key in (
        "DEEPAGENT_RECENT_MESSAGE_COUNT",
        "DEEPAGENT_RECENT_MESSAGE_CHARS",
        "DEEPAGENT_RECENT_CONTEXT_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)
    messages = [
        Message("customer", "turn one customer"),
        Message("assistant", "turn one agent"),
        Message("customer", "turn two customer"),
        Message("assistant", "turn two agent"),
    ]

    compact = _recent_conversation_context(messages)

    assert "turn one" not in compact
    assert "turn two customer" in compact
    assert "turn two agent" in compact


@pytest.mark.asyncio
async def test_prefetch_collapses_catalog_inventory_model_round_trips():
    class StubTool:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return self.result

    catalog = StubTool(
        {
            "items": [
                {
                    "sku": "SKU-SN-CAS",
                    "variants": [
                        {
                            "variant_sku": "SKU-SN-CAS-39-DEN",
                            "size": "39",
                            "color": "den",
                        }
                    ],
                }
            ]
        }
    )
    inventory = StubTool({"sku": "SKU-SN-CAS-39-DEN", "in_stock": True, "qty": 9})
    harness = DeepAgentHarness()
    harness.mcp_tools = {
        "search_catalog": catalog,
        "check_inventory": inventory,
    }
    state = ConversationState(conversation_id="sample-03")
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03",
            text="Giày Urban Classic size 39 màu đen còn không?",
            metadata={"call_date": "2026-10-15"},
        ),
        state=state,
        perception=Perception(
            transcript="Giày Urban Classic size 39 màu đen còn không?",
            intent="ask_product",
            intents=["ask_product"],
        ),
    )

    calls, remaining = await harness._prefetch_read_tools(
        context,
        frozenset({"search_catalog", "check_inventory"}),
    )

    assert remaining == frozenset()
    assert [call["name"] for call in calls] == [
        "catalog.search",
        "inventory.check",
    ]
    assert inventory.calls == [
        {"sku": "SKU-SN-CAS-39-DEN", "on": "2026-10-15"}
    ]


@pytest.mark.asyncio
async def test_current_catalog_product_overrides_historical_owned_sku():
    class StubTool:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return self.result

    catalog = StubTool(
        {
            "items": [
                {
                    "sku": "SKU-AP-Y",
                    "name": "Máy lọc không khí AirPure Y",
                    "variants": [],
                }
            ]
        }
    )
    inventory = StubTool({"in_stock": True, "qty": 15})
    pricing = StubTool({"final_price_vnd": 4_800_000})
    harness = DeepAgentHarness()
    harness.mcp_tools = {
        "search_catalog": catalog,
        "check_inventory": inventory,
        "get_pricing_quote": pricing,
    }
    text = "Chị muốn đổi máy cũ sang Máy lọc không khí AirPure Y."
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-102-call-1",
            text=text,
            customer_hint="0985003703",
            metadata={"call_date": "2026-10-22"},
        ),
        state=ConversationState(conversation_id="sc-102-call-1"),
        identity=CustomerIdentity(customer_id="C031", phone="0985003703"),
        perception=Perception(
            transcript=text,
            intent="ask_product",
            intents=["ask_product", "ask_price"],
            entities={"product_name": "Máy lọc không khí AirPure Y"},
        ),
        call_brief=CallBrief(
            customer_id="C031",
            remembered_preferences={
                "facts": {"owned_sku": "SKU-AP-X-2024"}
            },
        ),
    )

    calls, remaining = await harness._prefetch_read_tools(
        context,
        frozenset({"search_catalog", "check_inventory", "get_pricing_quote"}),
    )

    assert remaining == frozenset()
    assert inventory.calls[0]["sku"] == "SKU-AP-Y"
    assert pricing.calls[0]["sku"] == "SKU-AP-Y"
    assert [call["name"] for call in calls] == [
        "catalog.search",
        "inventory.check",
        "pricing.get_quote",
    ]


@pytest.mark.asyncio
async def test_prefetch_order_status_falls_back_to_verified_phone():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"orders": []}

    status = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"check_order_status": status}
    state = ConversationState(
        conversation_id="sample-03-call-2",
        customer_profile={"phone": "0922264686"},
    )
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03-call-2",
            text="Giày hôm qua hơi chật.",
        ),
        state=state,
        identity=CustomerIdentity(customer_id="C012", phone="0922264686"),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={"facts": {}},
        ),
    )

    calls, remaining = await harness._prefetch_read_tools(
        context,
        frozenset({"check_order_status", "update_order"}),
    )

    assert status.calls == [{"customer_phone": "0922264686"}]
    assert calls[0]["name"] == "order.status"
    assert remaining == frozenset({"update_order"})


@pytest.mark.asyncio
async def test_prefetch_exploratory_exchange_checks_requested_variant_only():
    class StubTool:
        def __init__(self, result):
            self.result = result
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return self.result

    status = StubTool(
        {
            "orders": [
                {"order_id": "ORD-TEST", "sku": "SKU-SN-CAS-39-DEN"}
            ]
        }
    )
    inventory = StubTool(
        {"sku": "SKU-SN-CAS-40-DEN", "in_stock": True, "qty": 5}
    )
    text = "Đổi lên size 40 được không em? Mất phí gì không?"
    harness = DeepAgentHarness()
    harness.mcp_tools = {
        "check_order_status": status,
        "check_inventory": inventory,
    }
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03-call-2",
            text=text,
            metadata={"call_date": "2026-10-19"},
        ),
        state=ConversationState(conversation_id="sample-03-call-2"),
        perception=Perception(
            transcript=text,
            intent="update_order",
            intents=["update_order"],
            entities={"size": 40},
        ),
        call_brief=CallBrief(
            customer_id="C012",
            verified_customer_data={
                "phone": "0922264686",
                "address": "12 Nguyễn Trãi, Hà Nội",
            },
            remembered_preferences={
                "facts": {
                    "order_id": "ORD-TEST",
                    "variant_sku": "SKU-SN-CAS-39-DEN",
                }
            },
        ),
    )

    calls, remaining = await harness._prefetch_read_tools(
        context,
        frozenset({"check_order_status", "check_inventory"}),
    )

    assert remaining == frozenset()
    assert status.calls == [{"order_id": "ORD-TEST"}]
    assert inventory.calls == [
        {"sku": "SKU-SN-CAS-40-DEN", "on": "2026-10-19"}
    ]
    assert [call["name"] for call in calls] == [
        "order.status",
        "inventory.check",
    ]


def test_exchange_sku_uses_new_size_and_remembered_color():
    text = "Đổi lên size 40 được không em?"
    context = TurnContext(
        input=TurnInput(conversation_id="sample-03", text=text),
        state=ConversationState(conversation_id="sample-03"),
        perception=Perception(
            transcript=text,
            intent="update_order",
            intents=["update_order"],
            entities={"size": 40},
        ),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={
                "facts": {"variant_sku": "SKU-SN-CAS-39-DEN"}
            },
        ),
    )

    assert _requested_exchange_sku(context) == "SKU-SN-CAS-40-DEN"


def test_exchange_sku_prefers_destination_in_from_to_phrase():
    text = "Chị muốn đổi từ size 38 sang 39, giữ màu cũ."
    context = TurnContext(
        input=TurnInput(conversation_id="sc-021-call-2", text=text),
        state=ConversationState(conversation_id="sc-021-call-2"),
        perception=Perception(
            transcript=text,
            intent="update_order",
            intents=["update_order"],
            entities={"size": 38},
        ),
        call_brief=CallBrief(
            customer_id="C009",
            remembered_preferences={
                "facts": {"variant_sku": "SKU-SN-CAS-38-TRANG"}
            },
        ),
    )

    assert _requested_exchange_sku(context) == "SKU-SN-CAS-39-TRANG"


def test_current_tight_size_is_not_mistaken_for_exchange_target():
    text = "Anh mới nhận giày hôm qua mà size 39 hơi chật."
    context = TurnContext(
        input=TurnInput(conversation_id="sample-03", text=text),
        state=ConversationState(conversation_id="sample-03"),
        perception=Perception(
            transcript=text,
            intent="update_order",
            intents=["update_order"],
            entities={"size": 39},
        ),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={
                "facts": {"variant_sku": "SKU-SN-CAS-39-DEN"}
            },
        ),
    )

    assert _requested_exchange_sku(context) is None


def test_pending_order_prefers_complete_address_reply_over_truncated_entity():
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03",
            text="Địa chỉ giao hàng là 12 Nguyễn Trãi, Hà Nội nhé em.",
        ),
        state=ConversationState(
            conversation_id="sample-03",
            working_memory={"pending_order": {"sku": "SKU-SN-CAS-39-DEN"}},
        ),
        perception=Perception(
            transcript="Địa chỉ giao hàng là 12 Nguyễn Trãi, Hà Nội nhé em.",
            entities={"address": "1"},
        ),
    )

    assert _delivery_address(context) == "12 Nguyễn Trãi, Hà Nội"


def test_exchange_inventory_result_is_saved_as_pending_variant():
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03", text="Đổi lên size 40 được không?"
        ),
        state=ConversationState(conversation_id="sample-03"),
        perception=Perception(
            transcript="Đổi lên size 40 được không?",
            intent="update_order",
            intents=["update_order"],
        ),
    )
    context.steps = [
        AgentStep(
            plan=ActionPlan(
                action="tool_call",
                rationale="verify exchange stock",
                tool_name="inventory.check",
                arguments={"sku": "SKU-SN-CAS-40-DEN"},
            ),
            policy=PolicyDecision(allowed=True),
            action_result=ActionResult(
                status=ActionStatus.EXECUTED,
                output={"in_stock": True, "qty": 5},
            ),
            observation=Observation(summary="available"),
        )
    ]

    assert _tool_memory_candidates(context) == {
        "pending_variant_sku": "SKU-SN-CAS-40-DEN",
        "pending_size": 40,
    }


def test_successful_exchange_promotes_and_clears_pending_variant():
    context = TurnContext(
        input=TurnInput(conversation_id="sample-03", text="Làm thủ tục đổi"),
        state=ConversationState(conversation_id="sample-03"),
    )
    context.steps = [
        AgentStep(
            plan=ActionPlan(
                action="tool_call",
                rationale="confirmed exchange",
                tool_name="order.update",
                arguments={
                    "order_id": "ORD-TEST",
                    "action": "exchange_size",
                    "new_variant_sku": "SKU-SN-CAS-40-DEN",
                },
            ),
            policy=PolicyDecision(allowed=True),
            action_result=ActionResult(
                status=ActionStatus.EXECUTED,
                output={"order_id": "ORD-TEST", "status": "exchange_size"},
            ),
            observation=Observation(summary="exchanged"),
        )
    ]

    facts = _tool_memory_candidates(context)

    assert facts["variant_sku"] == "SKU-SN-CAS-40-DEN"
    assert facts["size"] == 40
    assert facts["pending_variant_sku"] is None
    assert facts["pending_size"] is None


@pytest.mark.asyncio
async def test_confirmed_create_is_executed_from_verified_memory_and_reads():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-TEST", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03",
            text="Ok em lên đơn cho anh, thanh toán COD nhé.",
            customer_hint="0922264686",
            metadata={"call_date": "2026-10-15"},
        ),
        state=ConversationState(
            conversation_id="sample-03",
            customer_profile={"phone": "0922264686"},
        ),
        identity=CustomerIdentity(customer_id="C012", phone="0922264686"),
        call_brief=CallBrief(
            customer_id="C012",
            verified_customer_data={
                "phone": "0922264686",
                "address": "12 Nguyễn Trãi, Hà Nội",
            },
            remembered_preferences={
                "facts": {
                    "variant_sku": "SKU-SN-CAS-39-DEN",
                    "price_quoted_vnd": 890_000,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-SN-CAS-39-DEN"},
            "result": {"in_stock": True, "qty": 9},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-SN-CAS-39-DEN"},
            "result": {"final_price_vnd": 890_000},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert remaining == frozenset()
    assert create.calls == [
        {
            "customer_phone": "0922264686",
            "customer_id": "C012",
            "sku": "SKU-SN-CAS-39-DEN",
            "price_vnd": 890_000,
            "qty": 1,
            "payment_method": "COD",
            "address": "12 Nguyễn Trãi, Hà Nội",
            "idempotency_key": (
                "sample-03:call:create:SKU-SN-CAS-39-DEN"
            ),
            "on": "2026-10-15",
        }
    ]
    assert calls[0]["name"] == "order.create"
    assert calls[0]["args"]["payment"] == "COD"


@pytest.mark.asyncio
async def test_remembered_complete_slots_do_not_imply_purchase_consent():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-SHOULD-NOT-EXIST"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    text = "Chị gọi lại chuyện hôm trước. Mẫu, số lượng, địa chỉ và COD giữ nguyên."
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-041-call-2",
            text=text,
            customer_hint="0994893949",
            metadata={"call_date": "2026-10-17", "call_key": "call_2"},
        ),
        state=ConversationState(
            conversation_id="sc-041-call-2",
            customer_profile={"phone": "0994893949"},
        ),
        identity=CustomerIdentity(customer_id="C017", phone="0994893949"),
        perception=Perception(
            transcript=text,
            intent="create_order",
            intents=["create_order"],
        ),
        call_brief=CallBrief(
            customer_id="C017",
            remembered_preferences={
                "facts": {
                    "product_advised": "SKU-AP-X",
                    "price_quoted_vnd": 4_890_000,
                    "delivery_address": "100 đường Kiểm Thử, TP. Hồ Chí Minh",
                    "payment": "COD",
                    "quantity": 1,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-AP-X"},
            "result": {"in_stock": True, "qty": 10},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-AP-X"},
            "result": {"final_price_vnd": 4_890_000},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert calls == []
    assert remaining == frozenset()
    assert create.calls == []


@pytest.mark.asyncio
async def test_payment_can_complete_checkout_started_in_same_call():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-CHECKOUT", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    text = "Anh chọn thanh toán COD."
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-111-call-2",
            text=text,
            customer_hint="0928144976",
            metadata={"call_date": "2026-10-17", "call_key": "call_2"},
        ),
        state=ConversationState(
            conversation_id="sc-111-call-2",
            customer_profile={"phone": "0928144976"},
            working_memory={
                "pending_order": {
                    "basket_skus": ["SKU-AF-6L", "SKU-FAN-DC1"],
                    "address": "100 đường Kiểm Thử, TP. Hồ Chí Minh",
                    "payment": None,
                }
            },
        ),
        identity=CustomerIdentity(customer_id="C049", phone="0928144976"),
        call_brief=CallBrief(
            customer_id="C049",
            remembered_preferences={
                "facts": {
                    "basket_skus": ["SKU-AF-6L", "SKU-FAN-DC1"],
                    "delivery_address": "100 đường Kiểm Thử, TP. Hồ Chí Minh",
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": sku},
            "result": {"in_stock": True, "qty": 5},
        }
        for sku in ("SKU-AF-6L", "SKU-FAN-DC1")
    ] + [
        {
            "name": "pricing.quote_order",
            "args": {"lines": [{"sku": "SKU-AF-6L"}, {"sku": "SKU-FAN-DC1"}]},
            "result": {"units": [{"sku": sku, "final_price_vnd": price}
                                  for sku, price in (("SKU-AF-6L", 3_990_000), ("SKU-FAN-DC1", 2_450_000))]},
        }
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert remaining == frozenset()
    assert [line["sku"] for line in create.calls[0]["lines"]] == ["SKU-AF-6L", "SKU-FAN-DC1"]
    assert all(call["payment_method"] == "COD" for call in create.calls)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_purchase_wording_executes_create_with_call_date():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-TEST", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-001-call-2",
            text=(
                "Chị đồng ý giá hiện tại 4.890.000 đồng, mua một chiếc. "
                "Giao đến 100 đường Kiểm Thử, Hà Nội, thanh toán COD nhé."
            ),
            customer_hint="0984726714",
            metadata={"call_date": "2026-10-17", "call_key": "call_2"},
        ),
        state=ConversationState(
            conversation_id="sc-001-call-2",
            customer_profile={"phone": "0984726714"},
        ),
        identity=CustomerIdentity(customer_id="C001", phone="0984726714"),
        perception=Perception(
            transcript="mua một chiếc",
            entities={"address": "100 đường Kiểm Thử, Hà Nội"},
        ),
        call_brief=CallBrief(
            customer_id="C001",
            remembered_preferences={
                "facts": {
                    "product_advised": "SKU-AP-X",
                    "price_quoted_vnd": 4_890_000,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-AP-X", "on": "2026-10-17"},
            "result": {"in_stock": True, "qty": 40},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-AP-X", "on": "2026-10-17"},
            "result": {"final_price_vnd": 4_890_000},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert remaining == frozenset()
    assert create.calls[0]["on"] == "2026-10-17"
    assert create.calls[0]["idempotency_key"].endswith(
        ":call_2:create:SKU-AP-X"
    )
    assert calls[0]["name"] == "order.create"


@pytest.mark.asyncio
async def test_third_call_reuses_canonical_address_and_payment_without_reasking():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-THIRD", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-041-call-3",
            text="Chị gọi lần thứ ba rồi. Chốt một chiếc như đã trao đổi nhé.",
            customer_hint="0994893949",
            metadata={"call_date": "2026-10-19", "call_key": "call_3"},
        ),
        state=ConversationState(
            conversation_id="sc-041-call-3",
            customer_profile={"phone": "0994893949"},
        ),
        identity=CustomerIdentity(customer_id="C041", phone="0994893949"),
        call_brief=CallBrief(
            customer_id="C041",
            remembered_preferences={
                "facts": {
                    "product_advised": "SKU-AP-X",
                    "delivery_address": "100 đường Kiểm Thử, TP. Hồ Chí Minh",
                    "payment": "COD",
                    "quantity": 1,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-AP-X"},
            "result": {"in_stock": True, "qty": 10},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-AP-X"},
            "result": {"final_price_vnd": 4_890_000, "applied_promos": []},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert remaining == frozenset()
    assert create.calls[0]["address"] == "100 đường Kiểm Thử, TP. Hồ Chí Minh"
    assert create.calls[0]["payment_method"] == "COD"
    assert calls[0]["result"]["order_id"] == "ORD-THIRD"


@pytest.mark.asyncio
async def test_callback_is_normalized_and_orchestrated_once():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {
                "callback_id": "CB-TEST",
                "callback_at": "2026-10-19T10:00:00",
                "moved_from": "2026-10-17T10:00:00",
            }

    callback = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"mcp_schedule_callback": callback}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-001-call-1",
            text=(
                "Chị còn phải hỏi người nhà. Gọi lại cho chị lúc 10 giờ "
                "ngày 2026-10-17 nhé, chưa lên đơn."
            ),
            metadata={"call_date": "2026-10-15"},
        ),
        state=ConversationState(
            conversation_id="sc-001-call-1",
            customer_profile={"phone": "0984726714"},
        ),
        identity=CustomerIdentity(customer_id="C001", phone="0984726714"),
    )

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"mcp_schedule_callback"}), []
    )

    assert remaining == frozenset()
    assert callback.calls == [
        {
            "customer_phone": "0984726714",
            "callback_at": "2026-10-17T10:00",
            "note": context.input.text,
            "on": "2026-10-15",
        }
    ]
    assert calls[0]["name"] == "schedule.callback"


@pytest.mark.asyncio
async def test_confirmed_create_waits_for_required_delivery_address():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-SHOULD-NOT-EXIST"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03",
            text="Ok em lên đơn cho anh, thanh toán COD nhé.",
            customer_hint="0922264686",
        ),
        state=ConversationState(
            conversation_id="sample-03",
            customer_profile={"phone": "0922264686", "address": None},
        ),
        identity=CustomerIdentity(customer_id="C012", phone="0922264686"),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={
                "facts": {
                    "variant_sku": "SKU-SN-CAS-39-DEN",
                    "price_quoted_vnd": 890_000,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-SN-CAS-39-DEN"},
            "result": {"in_stock": True, "qty": 9},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-SN-CAS-39-DEN"},
            "result": {"final_price_vnd": 890_000},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert calls == []
    assert remaining == frozenset()
    assert create.calls == []
    assert context.state.working_memory["pending_order"] == {
        "sku": "SKU-SN-CAS-39-DEN",
        "price_vnd": 890_000,
        "payment": "COD",
    }


@pytest.mark.asyncio
async def test_create_is_hidden_when_customer_identity_is_ambiguous():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-SHOULD-NOT-EXIST"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="shared-phone-call",
            text=(
                "Chị đồng ý mua một chiếc, giao 100 đường Kiểm Thử, "
                "TP. Hồ Chí Minh, COD."
            ),
            customer_hint="0958421083",
        ),
        state=ConversationState(
            conversation_id="shared-phone-call",
            customer_profile={"phone": "0958421083"},
        ),
        identity=CustomerIdentity(
            customer_id=None,
            phone="0958421083",
            confidence=0.0,
            profile={"is_ambiguous": True},
        ),
        perception=Perception(
            transcript="mua một chiếc",
            entities={"address": "100 đường Kiểm Thử, TP. Hồ Chí Minh"},
        ),
        call_brief=CallBrief(
            customer_id=None,
            remembered_preferences={
                "facts": {
                    "product_advised": "SKU-AP-X",
                    "price_quoted_vnd": 4_890_000,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-AP-X"},
            "result": {"in_stock": True, "qty": 40},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-AP-X"},
            "result": {"final_price_vnd": 4_890_000},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert calls == []
    assert remaining == frozenset()
    assert create.calls == []


@pytest.mark.asyncio
async def test_confirmed_exchange_uses_pending_variant_from_file_memory():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "ORD-TEST", "status": "exchange_size"}

    update = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"update_order": update}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03-call-2",
            text="Ừ em làm thủ tục đổi cho anh nhé.",
            metadata={"call_date": "2026-10-19"},
        ),
        state=ConversationState(conversation_id="sample-03-call-2"),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={
                "facts": {
                    "order_id": "ORD-TEST",
                    "variant_sku": "SKU-SN-CAS-39-DEN",
                    "pending_variant_sku": "SKU-SN-CAS-40-DEN",
                }
            },
        ),
    )
    verified = [
        {
            "name": "order.status",
            "args": {"order_id": "ORD-TEST"},
            "result": {
                "orders": [
                    {"order_id": "ORD-TEST", "sku": "SKU-SN-CAS-39-DEN"}
                ]
            },
        },
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-SN-CAS-40-DEN"},
            "result": {"in_stock": True, "qty": 5},
        },
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"update_order"}), verified
    )

    assert remaining == frozenset()
    assert update.calls[0]["order_id"] == "ORD-TEST"
    assert update.calls[0]["new_variant_sku"] == "SKU-SN-CAS-40-DEN"
    assert update.calls[0]["action"] == "exchange_size"
    assert calls[0]["name"] == "order.update"


@pytest.mark.asyncio
async def test_confirmed_exchange_hides_mutation_when_order_lookup_misses():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"status": "should_not_run"}

    update = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"update_order": update}
    context = TurnContext(
        input=TurnInput(
            conversation_id="sample-03-call-2",
            text="Ừ em làm thủ tục đổi cho anh nhé.",
        ),
        state=ConversationState(conversation_id="sample-03-call-2"),
        call_brief=CallBrief(
            customer_id="C012",
            remembered_preferences={
                "facts": {"pending_variant_sku": "SKU-SN-CAS-40-DEN"}
            },
        ),
    )

    calls, remaining = await harness._execute_confirmed_mutation(
        context,
        frozenset({"update_order"}),
        [{"name": "order.status", "args": {}, "result": {"orders": []}}],
    )

    assert calls == []
    assert remaining == frozenset()
    assert update.calls == []
    assert context.state.working_memory["order_update_blocker"] == (
        "order_not_found"
    )


@pytest.mark.asyncio
async def test_read_prefetch_reuses_successful_result_within_call():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"final_price_vnd": 4_890_000, "applied_promos": []}

    pricing = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"get_pricing_quote": pricing}
    state = ConversationState(conversation_id="same-call")
    context = TurnContext(
        input=TurnInput(
            conversation_id="same-call",
            text="Giá hiện tại bao nhiêu?",
            customer_hint="0984726714",
            metadata={"call_date": "2026-10-17"},
        ),
        state=state,
        identity=CustomerIdentity(customer_id="C001", phone="0984726714"),
        call_brief=CallBrief(
            customer_id="C001",
            remembered_preferences={"facts": {"product_advised": "SKU-AP-X"}},
        ),
    )

    first, _ = await harness._prefetch_read_tools(
        context, frozenset({"get_pricing_quote"})
    )
    second, _ = await harness._prefetch_read_tools(
        context, frozenset({"get_pricing_quote"})
    )

    assert len(pricing.calls) == 1
    assert first[0].get("_cached") is None
    assert second[0]["_cached"] is True


@pytest.mark.asyncio
async def test_confirmed_multi_item_basket_creates_one_order_for_all_verified_units():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": f"ORD-{len(self.calls)}", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    context = TurnContext(
        input=TurnInput(
            conversation_id="basket-call",
            text="Em lên đơn đúng giỏ cuối cùng nhé.",
            customer_hint="0928144976",
            metadata={"call_date": "2026-10-17", "call_key": "call_2"},
        ),
        state=ConversationState(
            conversation_id="basket-call",
            customer_profile={"phone": "0928144976"},
        ),
        identity=CustomerIdentity(customer_id="C111", phone="0928144976"),
        call_brief=CallBrief(
            customer_id="C111",
            verified_customer_data={"phone": "0928144976"},
            remembered_preferences={
                "facts": {
                    "basket_skus": ["SKU-AF-6L", "SKU-FAN-DC1"],
                    "delivery_address": "100 đường Kiểm Thử, TP. Hồ Chí Minh",
                    "payment": "COD",
                    "quantity_each": 1,
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": sku},
            "result": {"in_stock": True, "qty": 5},
        }
        for sku in ("SKU-AF-6L", "SKU-FAN-DC1")
    ] + [
        {
            "name": "pricing.quote_order",
            "args": {"lines": [{"sku": "SKU-AF-6L"}, {"sku": "SKU-FAN-DC1"}]},
            "result": {"units": [{"sku": sku, "final_price_vnd": price}
                                  for sku, price in (("SKU-AF-6L", 3_990_000), ("SKU-FAN-DC1", 2_450_000))]},
        }
    ]

    calls, remaining = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert remaining == frozenset()
    assert [line["sku"] for line in create.calls[0]["lines"]] == ["SKU-AF-6L", "SKU-FAN-DC1"]
    assert [line["price_vnd"] for line in create.calls[0]["lines"]] == [3_990_000, 2_450_000]
    assert len([call for call in calls if call["name"] == "order.create"]) == 1


@pytest.mark.asyncio
async def test_same_call_create_confirmation_does_not_create_duplicate_order():
    class StubTool:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return {"order_id": "OD600001", "status": "created"}

    create = StubTool()
    harness = DeepAgentHarness()
    harness.mcp_tools = {"create_new_order": create}
    state = ConversationState(
        conversation_id="sc-021-call-1",
        customer_profile={"phone": "0992298369"},
    )
    context = TurnContext(
        input=TurnInput(
            conversation_id="sc-021-call-1",
            text="Chị đồng ý, tạo đơn giúp chị nhé.",
            metadata={"call_date": "2026-10-02", "call_key": "call_1"},
        ),
        state=state,
        identity=CustomerIdentity(customer_id="C009", phone="0992298369"),
        call_brief=CallBrief(
            customer_id="C009",
            verified_customer_data={"address": "100 đường Kiểm Thử, Đà Nẵng"},
            remembered_preferences={
                "facts": {
                    "variant_sku": "SKU-SN-CAS-38-TRANG",
                    "payment": "COD",
                }
            },
        ),
    )
    verified = [
        {
            "name": "inventory.check",
            "args": {"sku": "SKU-SN-CAS-38-TRANG"},
            "result": {"in_stock": True, "qty": 5},
        },
        {
            "name": "pricing.get_quote",
            "args": {"sku": "SKU-SN-CAS-38-TRANG"},
            "result": {"final_price_vnd": 890_000, "applied_promos": []},
        },
    ]

    first, _ = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )
    state.turn_number += 1
    context.input.text = "Em tạo đơn giúp chị và đọc mã đơn để chị lưu nhé."
    second, _ = await harness._execute_confirmed_mutation(
        context, frozenset({"create_new_order"}), verified
    )

    assert len(create.calls) == 1
    assert first[0]["result"]["order_id"] == "OD600001"
    assert second == []
    assert state.working_memory["order_create_duplicate_prevented"] == {
        "SKU-SN-CAS-38-TRANG": "OD600001"
    }


def test_empty_model_response_uses_verified_tool_fallback():
    context = TurnContext(
        input=TurnInput(conversation_id="fallback", text="Giá bao nhiêu?"),
        state=ConversationState(conversation_id="fallback"),
    )

    response = _safe_fallback_response(
        context,
        [
            {
                "name": "pricing.get_quote",
                "args": {"sku": "SKU-AP-X"},
                "result": {"final_price_vnd": 4_890_000},
            }
        ],
    )

    assert "4.890.000 đồng" in response
