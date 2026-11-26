"""Differential checks against BTC, with a disposable in-memory database."""

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mcp_servers.tools import catalog, order, workflow
from telesale_agent.adapters.db.client import PostgresClient
from telesale_agent.adapters.db.models import (
    Base, Customer, InventoryEvent, Order, Product, ProductVariant, Promotion,
)

BTC = Path(__file__).resolve().parents[1] / "dataset/organizer"
BTC_INPUT = BTC.parent / "pipeline/stage-1/input"


@compiles(JSONB, "sqlite")
def compile_jsonb_for_tests(_type, _compiler, **_kwargs):
    return "JSON"


def validate_schema(name, payload):
    schema = json.loads((BTC / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)


@pytest.fixture
def btc_db(monkeypatch):
    spec = importlib.util.spec_from_file_location("btc_reference_tools", BTC_INPUT / "eval/mock_tools.py")
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    # These contract fixtures replay BTC's reference day, not the live clock.
    class ReferenceClock:
        @staticmethod
        def now(tz=None):
            return datetime.fromisoformat(reference.REF).replace(tzinfo=tz)
    monkeypatch.setattr("telesale_agent.core.business_time.datetime", ReferenceClock)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = object.__new__(PostgresClient)
    db.SessionLocal = sessionmaker(bind=engine)
    with db.get_session() as session:
        for item in reference.PRODUCTS:
            attributes = item["attributes"]
            session.add(Product(
                sku=item["sku"], name=item["name"], category=item["category"], brand=item["brand"],
                list_price_vnd=item["list_price_vnd"], stock=item["stock"], attributes=attributes,
                is_discontinued=attributes.get("discontinued", False),
                successor_sku=attributes.get("successor_sku"),
            ))
            for variant in item["variants"]:
                session.add(ProductVariant(
                    variant_sku=variant["variant_sku"], product_sku=item["sku"],
                    size=str(variant["size"]) if variant["size"] is not None else None,
                    color=variant["color"], price_delta_vnd=variant["price_delta_vnd"],
                    stock=variant["stock"],
                ))
        for item in reference.PROMOS:
            values = {key: value for key, value in item.items() if key not in {"start", "end"}}
            session.add(Promotion(**values, start_date=date.fromisoformat(item["start"]),
                                  end_date=date.fromisoformat(item["end"])))
        for item in reference.CRM:
            values = {key: value for key, value in item.items()
                      if key in {"customer_id", "name", "honorific", "phone", "zalo_id", "fb_id", "region", "shared_phone_with"}}
            session.add(Customer(**values, attributes={"sessions": item.get("sessions", [])}))
            for previous in item.get("orders", []):
                session.add(Order(
                    order_id=previous["order_id"], customer_id=item["customer_id"], sku=previous["sku"],
                    qty=previous.get("qty", 1), price_vnd=previous.get("price_vnd"),
                    order_date=date.fromisoformat(previous["date"]), status=previous["status"],
                ))
        for item in reference.INV:
            session.add(InventoryEvent(
                sku=item["sku"], sku_type="variant" if item["sku"] in reference._VAR else "product",
                event_date=date.fromisoformat(item["date"]), qty=item["qty"], note=item.get("note"),
            ))
        session.commit()
    monkeypatch.setattr(catalog, "db_client", db)
    monkeypatch.setattr(order, "db_client", db)
    yield reference, db
    engine.dispose()


@pytest.mark.parametrize("on", ["2026-09-26", "2026-10-15", "2026-10-23", "2026-12-20"])
@pytest.mark.parametrize("address", ["Hà Nội", "Hồ Chí Minh", "Đà Nẵng"])
def test_single_quotes_match_reference(btc_db, on, address):
    reference, _ = btc_db
    for product in reference.PRODUCTS:
        for sku in [product["sku"]] + [variant["variant_sku"] for variant in product["variants"]]:
            expected = reference.pricing_get_quote(sku, on=on, address=address)
            expected.pop("_internal_price_floor_vnd")
            assert catalog.pricing_get_quote(sku, on=on, address=address) == expected, (sku, on, address)


@pytest.mark.parametrize("lines", [
    [{"sku": "SKU-AP-PRO", "qty": 2}],
    [{"sku": "SKU-AP-PRO", "qty": 3}],
    [{"sku": "SKU-SS-AX40"}, {"sku": "SKU-AP-X"}],
    [{"sku": "SKU-AP-PRO"}, {"sku": "SKU-AP-MINI"}],
    [{"sku": "SKU-FAN-TWR"}],
])
@pytest.mark.parametrize("on", ["2026-10-15", "2026-12-20"])
def test_basket_quotes_match_reference(btc_db, lines, on):
    reference, _ = btc_db
    assert catalog.pricing_quote_order(lines, on=on) == reference.pricing_quote_order(lines, on=on)


def test_trade_in_only_applies_to_one_unit(btc_db):
    reference, _ = btc_db
    customer = next(customer for customer in reference.CRM if any(
        previous["sku"] == "SKU-AP-X-2024" and previous["status"] == "delivered"
        for previous in customer.get("orders", [])
    ))
    lines = [{"sku": "SKU-AP-PRO", "qty": 3}]
    assert catalog.pricing_quote_order(lines, customer_phone=customer["phone"]) == reference.pricing_quote_order(
        lines, customer_phone=customer["phone"],
    )


def test_catalog_area_filter_and_discontinued_inventory(btc_db):
    reference, db = btc_db
    assert [item["sku"] for item in catalog.catalog_search(min_room_area_m2=50)["items"]] == [
        item["sku"] for item in reference.catalog_search(min_room_area_m2=50)["items"]
    ]
    discontinued = next(item for item in reference.PRODUCTS if item["attributes"].get("discontinued"))
    with db.get_session() as session:
        session.query(Product).filter_by(sku=discontinued["sku"]).update({"stock": 5})
        session.commit()
    assert catalog.inventory_check(discontinued["sku"]) == reference.inventory_check(discontinued["sku"])


def test_crm_identity_and_sessions(btc_db):
    reference, db = btc_db
    for customer in reference.CRM:
        actual = db.get_customer(phone=customer["phone"])
        expected = reference.crm_get_customer(phone=customer["phone"])
        if expected.get("ambiguous"):
            assert [(c["customer_id"], c["honorific"], c["sessions"]) for c in actual["candidates"]] == [
                (c["customer_id"], c["honorific"], c["sessions"]) for c in expected["candidates"]
            ]
        else:
            assert actual["identities"] == expected["identities"]
            assert actual["sessions"] == expected["sessions"]


def test_order_rejects_wrong_price_without_persisting(btc_db):
    reference, db = btc_db
    args = dict(customer_phone=reference.CRM[0]["phone"], sku="SKU-AP-X", price_vnd=1,
                payment="bank", address="100 đường Kiểm Thử, Hà Nội")
    assert order.order_create(**args) == reference.order_create(**args)
    assert db.find_orders(customer_phone=args["customer_phone"]) == []


def test_multi_line_order_round_trip_and_idempotency(btc_db):
    reference, db = btc_db
    phone = reference.CRM[0]["phone"]
    quote = reference.pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 2}])
    lines = [{"sku": unit["sku"], "qty": 1, "price_vnd": unit["final_price_vnd"]} for unit in quote["units"]]
    args = dict(customer_phone=phone, lines=lines, payment="bank", address="Hà Nội")
    expected = reference.order_create(**args)
    actual = order.order_create(**args, idempotency_key="btc-one-order")
    assert {key: value for key, value in actual.items() if key != "order_id"} == {
        key: value for key, value in expected.items() if key != "order_id"
    }
    stored = db.find_orders(order_id=actual["order_id"])[0]
    assert stored["total_vnd"] == quote["total_vnd"]
    assert len(stored["lines"]) == 2
    assert "AIR-2ND-50" in stored["promos"]
    assert order.order_create(**args, idempotency_key="btc-one-order")["idempotent_replay"]
    assert order.order_create(**{**args, "payment": "COD"}, idempotency_key="btc-one-order")["error"] == "idempotency_conflict"
    assert len(db.find_orders(customer_phone=phone)) == 1


@pytest.mark.parametrize("callback_at", [
    "2026-10-26T09:00", "2026-10-17T10:00", "2026-10-18T07:00",
    "2026-10-18T10:00", "2026-10-15T22:00", "2027-01-01T09:00",
])
def test_callback_matches_reference(btc_db, callback_at):
    reference, _ = btc_db
    actual = workflow.schedule_callback("0900000000", callback_at, note="Gọi lại")
    expected = reference.schedule_callback("0900000000", callback_at, note="Gọi lại")
    assert {key: value for key, value in actual.items() if key != "callback_id"} == {
        key: value for key, value in expected.items() if key != "callback_id"
    }


@pytest.mark.parametrize("action", ["exchange_size", "exchange_product", "return", "update_address", "unknown"])
def test_order_update_matches_reference(btc_db, action):
    reference, db = btc_db
    previous = {"order_id": "BTC-UPDATE", "sku": "SKU-AP-X", "price_vnd": 5_000_000,
                "customer_phone": reference.CRM[0]["phone"]}
    reference._ORDERS[previous["order_id"]] = previous
    with db.get_session() as session:
        session.add(Order(order_id=previous["order_id"], customer_id=reference.CRM[0]["customer_id"],
                          sku=previous["sku"], price_vnd=previous["price_vnd"], qty=1))
        session.commit()
    args = dict(order_id=previous["order_id"], action=action, new_variant_sku="SKU-AP-X", reason="Kiểm thử")
    assert order.order_update(**args) == reference.order_update(**args)
    if action.startswith("exchange"):
        assert order.order_update(**args) == reference.order_update(**args)


def test_handoff_accepts_btc_schema_and_rejects_invalid_fields():
    brief = dict(customer_phone="0900000000", customer_name=None, escalation_reason="cau_hoi_y_te",
                 conversation_summary="Khách cần tư vấn y tế ngoài phạm vi bán hàng.", product_advised=None,
                 price_quoted_vnd=None, open_questions=["Có dùng cho bé được không?"],
                 next_action="Nhân viên tiếp nhận.", generated_at="2026-10-15T09:00:00+07:00")
    validate_schema("handoff_brief", brief)
    assert workflow.handoff_transfer(brief)["brief_ok"]
    assert workflow.handoff_transfer({key: value for key, value in brief.items() if key != "next_action"})["error"] == "brief_invalid"
    for field, value in [("open_questions", "Sai kiểu"), ("escalation_reason", "medical_advice_out_of_scope"),
                         ("customer_phone", "abc"), ("conversation_summary", "ngắn")]:
        assert workflow.handoff_transfer({**brief, field: value})["error"] == "brief_invalid"


@pytest.mark.parametrize("sku", ["SKU-AP-X", "SKU-AP-PRO"])
@pytest.mark.parametrize("address", ["Hà Nội", "Long An"])
def test_delivery_eta_matches_reference(btc_db, sku, address):
    reference, _ = btc_db
    args = dict(customer_phone=reference.CRM[0]["phone"], sku=sku, address=address,
                on="2026-10-23", payment="bank")
    assert order.order_create(**args)["estimated_delivery"] == reference.order_create(**args)["estimated_delivery"]


def test_cod_checks_basket_total_and_bank_retry(btc_db):
    reference, db = btc_db
    quote = reference.pricing_quote_order([{"sku": "SKU-AP-PRO", "qty": 3}])
    args = dict(customer_phone=reference.CRM[0]["phone"], address="Hà Nội",
                lines=[{"sku": unit["sku"], "price_vnd": unit["final_price_vnd"]} for unit in quote["units"]])
    assert order.order_create(**args) == reference.order_create(**args)
    assert db.find_orders(customer_phone=args["customer_phone"]) == []
    result = order.order_create(**args, payment="bank")
    assert result["status"] == "created"
    assert result["total_vnd"] == quote["total_vnd"]


def test_split_orders_apply_second_item_once_per_phone_day(btc_db):
    reference, _ = btc_db
    phone = reference.CRM[0]["phone"]
    first = dict(customer_phone=phone, sku="SKU-AP-PRO", price_vnd=7_690_000,
                 address="Hà Nội", payment="bank")
    assert order.order_create(**first)["total_vnd"] == reference.order_create(**first)["total_vnd"]
    second = {**first, "price_vnd": 3_995_000, "basket_skus": ["SKU-AP-PRO"]}
    assert order.order_create(**second)["total_vnd"] == reference.order_create(**second)["total_vnd"]
    assert order.order_create(**second) == reference.order_create(**second)


def test_once_per_customer_promo_persists(btc_db):
    reference, _ = btc_db
    sku, phone = "SKU-SN-RUN2-38-DEN", reference.CRM[0]["phone"]
    args = dict(sku=sku, customer_phone=phone, on="2026-10-15", address="Hà Nội")
    quote = reference.pricing_get_quote(**args)
    order.order_create(**args, price_vnd=quote["final_price_vnd"], payment="bank")
    reference.order_create(**args, price_vnd=quote["final_price_vnd"], payment="bank")
    expected = reference.pricing_get_quote(**args)
    expected.pop("_internal_price_floor_vnd")
    assert catalog.pricing_get_quote(**args) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("returning", [False, True])
async def test_call_brief_export_matches_schema_and_excludes_current_session(returning):
    from telesale_agent.application.memory.call_brief import CallBriefProjector
    from telesale_agent.core.models import ConversationState, CustomerIdentity, TurnContext, TurnInput

    state = ConversationState("btc-current")
    state.customer_profile = {"phone": "0900000000", "name": "Hoa", "sessions": []}
    state.customer_memory = {"episodes": [], "facts": {}}
    if returning:
        state.customer_profile["sessions"] = [{"session_id": "btc-old", "date": "2026-10-14",
            "channel": "hotline", "summary": "Đã tư vấn AirPure Pro.", "outcome": "hen_goi_lai"}]
        state.customer_memory = {
            "episodes": [{"conversation_id": "btc-old", "date": "2026-10-14", "summary": "Đã tư vấn AirPure Pro."},
                         {"conversation_id": "btc-current", "summary": "Phiên đang chạy."}],
            "facts": {"room_area_m2": 25, "blocker": "Chờ hỏi chồng", "product_advised": "SKU-AP-PRO"},
        }
    context = TurnContext(TurnInput("btc-current", text="Xin chào"), state,
                          identity=CustomerIdentity(customer_id="C001", phone="0900000000"))
    brief = await CallBriefProjector().build_call_brief(context)
    validate_schema("call_brief", brief.to_btc())
    assert brief.is_returning is returning
    assert brief.n_previous_sessions == int(returning)
    if returning:
        assert brief.last_session["session_id"] == "btc-old"
        assert "room_area_m2" in brief.must_not_ask
        assert brief.open_blockers == ["Chờ hỏi chồng"]
    assert "verified_customer_data" not in brief.to_btc()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_generated_trace_validates_schema_on_success_and_failure(failure):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from eval.generate_traces import run_scenario
    from eval.benchmark_support import measured_latency
    from eval.team_eval import REFERENCE
    from telesale_agent.application.memory.call_brief import CallBriefProjector
    from telesale_agent.core.models import ConversationState, CustomerIdentity, TurnContext, TurnInput

    state = ConversationState("btc-artifact")
    brief = await CallBriefProjector().build_call_brief(TurnContext(
        TurnInput("btc-artifact", text="Xin chào"), state,
        identity=CustomerIdentity(customer_id="C001", phone="0900000000"),
    ))
    result = SimpleNamespace(state=state, response_text="Xin chào chị.", call_brief=brief,
        tool_calls=[], memory_writes=[], usage={}, latency={"ttft_ms": 10.25, "total_ms": 20.75,
        "call_brief_ms": 5.5, "ttfa_ms": None, "measurement_mode": "non_streaming"})
    harness = SimpleNamespace(memory=SimpleNamespace(), reset_customer_memory=Mock(),
        run_turn=AsyncMock(side_effect=TimeoutError() if failure else None, return_value=result))
    scenario = {"scenario_id": "BTC-SCHEMA", "calls": {"call_1": {"customer_turns": ["Xin chào"]}}}
    rows = await run_scenario(scenario, harness, "full", "btc-test", max_retries=1)
    assert len(rows) == 1
    validate_schema("trace_log", rows[0])
    if failure:
        assert rows[0]["_error"] == "TimeoutError"
        assert measured_latency({("BTC-SCHEMA", "call_1"): rows}, REFERENCE, warmup=0)["n_turns"] == 0
    else:
        assert "_error" not in rows[0]
        assert rows[0]["latency"]["ttft_ms"] == 10
        assert rows[0]["latency"]["total_ms"] == 21
        assert rows[0]["call_brief_latency_ms"] == 6
        validate_schema("call_brief", rows[0]["call_brief"])


def test_team_metrics_accept_lines_and_runtime_order_alias():
    from eval.team_eval import evaluate_team

    scenarios = {"BTC-MATCH": {"calls": {
        "call_1": {"success_if": {"tool_called": "order.create", "args_match": {"sku": "A", "price_vnd": 100},
                                 "also_ordered": ["B"], "total_match_vnd": 300}},
        "call_2": {"success_if": {"tool_called": "order.update", "args_match": {"order_id": "OD-SPEC", "action": "return"}}},
    }}}
    trace = {
        ("BTC-MATCH", "call_1"): [{"agent_text": "Đã tạo đơn.", "turn": 1, "tool_calls": [
            {"name": "order.create", "args": {"lines": [{"sku": "A", "price_vnd": 100}, {"sku": "B", "price_vnd": 200}]},
             "result": {"order_id": "ORD-RUNTIME"}}]}],
        ("BTC-MATCH", "call_2"): [{"agent_text": "Đã nhận yêu cầu trả.", "turn": 1, "tool_calls": [
            {"name": "order.update", "args": {"order_id": "ORD-RUNTIME", "action": "return"},
             "result": {"order_id": "ORD-RUNTIME", "status": "pickup_scheduled"}}]}],
    }
    for (sid, call), rows in trace.items():
        rows[0].update(scenario_id=sid, call=call)
    report = evaluate_team(scenarios, trace, pricing={})
    assert report["reference_task_success_rate"]["value"] == 100
    assert report["task_success_rate"]["value"] == 100
    assert report["tool_call_accuracy"]["value"] == 100


@pytest.mark.parametrize("text,expected", [
    ("Bên em đổi trả trong 14 ngày, phí đổi size 20.000 đồng.", {"return_days": 14, "exchange_fee_vnd": 20000}),
    ("Đổi trả trong 7 ngày, đổi size lần đầu miễn phí. Bảo hành 2 năm.", {"return_days": 7, "exchange_fee_vnd": 0, "warranty_months": 24}),
    ("Không phải đổi trả trong 14 ngày; bên em đổi trong 7 ngày.", {"return_days": 7}),
    ("Khách hỏi “đổi trả trong 14 ngày” là sai; bên em đổi trong 7 ngày.", {"return_days": 7}),
    ("Không áp dụng phí đổi size 20k; phí đổi size là 0 đồng.", {"exchange_fee_vnd": 0}),
])
def test_policy_claim_extraction(text, expected):
    from eval.trace_extractors import extract_claims
    assert {claim["field"]: claim["value"] for claim in extract_claims([], response_text=text)} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("skus,quantity", [(["SKU-AP-PRO"], 2), (["SKU-AP-PRO", "SKU-AP-MINI"], 1)])
async def test_agent_checkout_uses_btc_units_then_one_persisted_order(btc_db, skus, quantity):
    from mcp_servers import mcp_db
    from telesale_agent.application.tools.reads import ReadToolExecutor
    from telesale_agent.application.tools.mutations import MutationToolExecutor
    from telesale_agent.application.tools.protocol import tool_calls_to_steps
    from telesale_agent.application.memory.turn_facts import _tool_memory_candidates
    from telesale_agent.application.deepagent.response import ground_multi_item_order_confirmation
    from telesale_agent.core.models import CallBrief, ConversationState, CustomerIdentity, Perception, TurnContext, TurnInput

    reference, db = btc_db
    customer = reference.CRM[0]
    text = f"Chốt đơn {quantity} máy, giao 100 đường Kiểm Thử, Hà Nội, chuyển khoản ngân hàng."
    facts = {"product_advised": skus[0], "delivery_address": "100 đường Kiểm Thử, Hà Nội", "quantity": quantity}
    if len(skus) > 1:
        facts["basket_skus"] = skus
    context = TurnContext(
        TurnInput("btc-checkout", text=text, customer_hint=customer["phone"], metadata={"call_date": "2026-10-15"}),
        ConversationState("btc-checkout", customer_profile={"phone": customer["phone"]}),
        identity=CustomerIdentity(customer_id=customer["customer_id"], phone=customer["phone"]),
        perception=Perception(transcript=text, intent="create_order", entities={"quantity": quantity}),
        call_brief=CallBrief(customer_id=customer["customer_id"], remembered_preferences={"facts": facts}),
    )

    class LocalTool:
        def __init__(self, function):
            self.function = function

        async def ainvoke(self, args):
            return self.function(**args)

    tools = {name: LocalTool(getattr(mcp_db, name)) for name in (
        "check_inventory", "get_pricing_quote", "get_order_quote", "create_new_order",
    )}
    reads, remaining = await ReadToolExecutor(tools).prefetch(context, frozenset(tools))
    writes, _ = await MutationToolExecutor(tools).execute(context, remaining, reads)
    assert [call["name"] for call in writes] == ["order.create"]
    quote = next(call["result"] for call in reads if call["name"] == "pricing.quote_order")
    assert quote == reference.pricing_quote_order([{"sku": sku, "qty": quantity} for sku in skus],
        customer_phone=customer["phone"], address=facts["delivery_address"])
    assert writes[0]["result"]["total_vnd"] == quote["total_vnd"]
    assert len(db.find_orders(customer_phone=customer["phone"])) == 1
    response = ground_multi_item_order_confirmation(context, writes, "Đã tạo hai đơn.")
    assert response.count(writes[0]["result"]["order_id"]) == 1
    assert "Đã tạo hai đơn" not in response
    context.steps = tool_calls_to_steps(reads + writes)
    memory = _tool_memory_candidates(context)
    assert memory["order_ids_by_sku"] == {sku: writes[0]["result"]["order_id"] for sku in skus}
    assert [unit["price_quoted_vnd"] for unit in memory["basket_unit_quotes"]] == [
        unit["final_price_vnd"] for unit in quote["units"]
    ]


@pytest.mark.asyncio
async def test_mcp_exposes_btc_order_and_handoff_inputs():
    from mcp_servers import mcp_db, mcp_workflow
    db_tools = {tool.name: tool.inputSchema for tool in await mcp_db.mcp.list_tools()}
    workflow_tools = {tool.name: tool.inputSchema for tool in await mcp_workflow.mcp.list_tools()}
    assert "lines" in db_tools["get_order_quote"]["required"]
    assert "lines" in db_tools["create_new_order"]["properties"]
    assert "min_room_area_m2" in db_tools["search_catalog"]["properties"]
    assert workflow_tools["mcp_escalate_to_human"]["required"] == ["brief"]


def test_idempotency_accepts_same_server_priced_request(btc_db):
    reference, db = btc_db
    args = dict(customer_phone=reference.CRM[0]["phone"], sku="SKU-AP-X", qty=2,
                address="Hà Nội", payment="bank", idempotency_key="server-priced")
    first = order.order_create(**args)
    assert order.order_create(**args)["order_id"] == first["order_id"]
    assert len(db.find_orders(customer_phone=args["customer_phone"])) == 1


def test_unapplied_client_promo_does_not_consume_once_per_customer(btc_db):
    reference, db = btc_db
    args = dict(customer_phone=reference.CRM[0]["phone"], sku="SKU-AP-X", promo_code="RUN-10",
                address="Hà Nội", payment="bank")
    created = order.order_create(**args)
    assert "RUN-10" not in db.find_orders(order_id=created["order_id"])[0]["promos"]


@pytest.mark.asyncio
async def test_expired_brief_promo_and_latency_survive_local_refresh(btc_db):
    from telesale_agent.application.memory.call_brief import CallBriefProjector, FreshCallBrief
    from telesale_agent.core.models import ConversationState, CustomerIdentity, TurnContext, TurnInput

    reference, db = btc_db
    customer = reference.CRM[0]
    state = ConversationState("btc-stale", customer_profile={"phone": customer["phone"], "region": "bac"},
        customer_memory={"facts": {"product_advised": "SKU-AP-X", "promo_code": "GIFT-FILTER",
                                    "price_quoted_vnd": 4_890_000}})
    context = TurnContext(TurnInput("btc-stale", text="Giá cũ?", metadata={"call_date": "2026-10-31"}),
                          state, identity=CustomerIdentity(customer_id=customer["customer_id"], phone=customer["phone"]))
    brief = await FreshCallBrief(CallBriefProjector(), db).build_call_brief(context)
    brief.latency_ms = 1234
    state.call_brief = brief
    assert brief.products_advised[0]["promo_still_active"] is False
    assert brief.stale_warnings
    refreshed = await CallBriefProjector().build_call_brief(context)
    assert refreshed.products_advised[0]["promo_still_active"] is False
    assert refreshed.latency_ms == 1234
    validate_schema("call_brief", refreshed.to_btc())


@pytest.mark.asyncio
async def test_agent_handoff_sends_valid_btc_brief():
    from mcp_servers.mcp_workflow import mcp_escalate_to_human
    from telesale_agent.application.tools.mutations import MutationToolExecutor
    from telesale_agent.core.models import CallBrief, ConversationState, CustomerIdentity, TurnContext, TurnInput

    class HandoffTool:
        async def ainvoke(self, args):
            return mcp_escalate_to_human(**args)

    context = TurnContext(
        TurnInput("btc-handoff", text="Chuyển cho nhân viên tư vấn y tế giúp chị.", metadata={"call_date": "2026-10-15"}),
        ConversationState("btc-handoff"), identity=CustomerIdentity(customer_id="C001", phone="0900000000"),
        call_brief=CallBrief(customer_id="C001", summary="Đã tư vấn sản phẩm cho bé.",
            remembered_preferences={"facts": {"medical_question": "Có điều trị được bệnh không?"}}),
    )
    calls, remaining = await MutationToolExecutor({"mcp_escalate_to_human": HandoffTool()}).execute(
        context, frozenset({"mcp_escalate_to_human"}), [],
    )
    assert remaining == frozenset()
    validate_schema("handoff_brief", calls[0]["args"]["brief"])
    assert calls[0]["result"]["brief_ok"]


@pytest.mark.asyncio
async def test_voice_initialization_measures_btc_brief_latency(monkeypatch):
    from types import SimpleNamespace
    from telesale_agent.application.realtime import controller
    from telesale_agent.application.memory.call_brief import CallBriefProjector
    from telesale_agent.core.models import CustomerIdentity

    clock = [0.0]

    async def identity(context):
        clock[0] += .02
        return CustomerIdentity(customer_id="C001", phone="0900000000")

    async def hydrate(context):
        clock[0] += .03
        context.state.customer_profile = {"phone": "0900000000"}

    async def build(context):
        clock[0] += .04
        return await CallBriefProjector().build_call_brief(context)

    services = SimpleNamespace(identity=SimpleNamespace(resolve_identity=identity),
        customer_context=SimpleNamespace(hydrate=hydrate), call_brief=SimpleNamespace(build_call_brief=build))
    monkeypatch.setattr(controller, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    state, _ = await controller.initialize_customer(services, "btc-voice", "0900000000")
    assert state.call_brief.latency_ms == 90
    validate_schema("call_brief", state.call_brief.to_btc())


def checkout_context(reference, skus, text, quantity=1, saved_lines=None):
    from telesale_agent.core.models import CallBrief, ConversationState, CustomerIdentity, Perception, TurnContext, TurnInput
    customer = reference.CRM[0]
    names = {p["sku"]: p["name"] for p in reference.PRODUCTS}
    facts = {"product_advised": skus[0], "variant_sku": skus[0], "basket_skus": skus,
             "basket_product_names": {sku: names.get(sku, sku) for sku in skus},
             "quantity": quantity, "payment": "bank", "delivery_address": "100 đường Kiểm Thử, Hà Nội"}
    if saved_lines is not None:
        facts["basket_lines"] = saved_lines
    state = ConversationState("btc-regression", customer_profile={"phone": customer["phone"]}, customer_memory={"facts": facts})
    identity = CustomerIdentity(customer_id=customer["customer_id"], phone=customer["phone"])
    state.identity = identity
    return TurnContext(TurnInput("btc-regression", text=text, customer_hint=customer["phone"], metadata={"call_date": "2026-10-15"}),
        state, identity=identity, perception=Perception(transcript=text, intent="create_order", entities={"quantity": quantity}),
        call_brief=CallBrief(customer_id=customer["customer_id"], remembered_preferences={"facts": facts}))


def checkout_tools():
    from mcp_servers import mcp_db

    class LocalTool:
        def __init__(self, function):
            self.function = function
            self.calls = []

        async def ainvoke(self, args):
            self.calls.append(args)
            return self.function(**args)

    return {name: LocalTool(getattr(mcp_db, name)) for name in (
        "check_inventory", "get_pricing_quote", "get_order_quote", "create_new_order", "update_order")}


@pytest.mark.asyncio
@pytest.mark.parametrize("quantities,description", [
    ((2, 1), "2 máy AirPure Pro và 1 máy AirPure Mini"),
    ((1, 3), "1 máy AirPure Pro và 3 máy AirPure Mini"),
    ((2, 1), "hai máy AirPure Pro và một máy AirPure Mini"),
    ((2, 1), "AirPure Pro 2 máy và AirPure Mini 1 máy"),
])
async def test_checkout_preserves_each_product_quantity(btc_db, quantities, description):
    from collections import Counter
    from telesale_agent.application.tools.reads import ReadToolExecutor
    from telesale_agent.application.tools.mutations import MutationToolExecutor
    reference, db = btc_db
    skus = ["SKU-AP-PRO", "SKU-AP-MINI"]
    ctx = checkout_context(reference, skus, f"Chốt đơn {description}, chuyển khoản.", quantities[0])
    tools = checkout_tools()
    reads, remaining = await ReadToolExecutor(tools).prefetch(ctx, frozenset(tools))
    writes, _ = await MutationToolExecutor(tools).execute(ctx, remaining, reads)
    lines = [{"sku": sku, "qty": qty} for sku, qty in zip(skus, quantities)]
    expected = reference.pricing_quote_order(lines, customer_phone=reference.CRM[0]["phone"], address="Hà Nội")
    quote_call = next(c for c in reads if c["name"] == "pricing.quote_order")
    assert quote_call["args"]["lines"] == lines
    assert quote_call["result"] == expected
    assert len(writes) == 1
    assert writes[0]["result"]["total_vnd"] == expected["total_vnd"]
    saved = db.find_orders(order_id=writes[0]["result"]["order_id"])[0]
    assert Counter(l["sku"] for l in saved["lines"]) == dict(zip(skus, quantities))


@pytest.mark.asyncio
async def test_per_item_counts_survive_payment_only_followup(btc_db):
    from telesale_agent.application.tools.reads import ReadToolExecutor
    from telesale_agent.application.tools.mutations import MutationToolExecutor
    reference, _ = btc_db
    lines = [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]
    ctx = checkout_context(reference, [l["sku"] for l in lines], "Chốt đơn, chị chọn chuyển khoản.", 2, lines)
    tools = checkout_tools()
    reads, remaining = await ReadToolExecutor(tools).prefetch(ctx, frozenset(tools))
    writes, _ = await MutationToolExecutor(tools).execute(ctx, remaining, reads)
    assert next(c for c in reads if c["name"] == "pricing.quote_order")["args"]["lines"] == lines
    assert len(writes[0]["args"]["lines"]) == 3


@pytest.mark.asyncio
async def test_successful_create_invalidates_once_per_customer_quote_cache(btc_db):
    from telesale_agent.application.tools.reads import ReadToolExecutor
    from telesale_agent.application.tools.mutations import MutationToolExecutor
    reference, _ = btc_db
    sku = "SKU-SN-RUN2-38-DEN"
    ctx = checkout_context(reference, [sku], "Chốt đơn 1 đôi, chuyển khoản.")
    tools = checkout_tools()
    executor = ReadToolExecutor(tools)
    reads, remaining = await executor.prefetch(ctx, frozenset(tools))
    initial = next(c for c in reads if c["name"] == "pricing.get_quote")["result"]["final_price_vnd"]
    writes, _ = await MutationToolExecutor(tools).execute(ctx, remaining, reads)
    assert writes[0]["result"].get("order_id")
    assert "read_tool_cache" not in ctx.state.working_memory
    ctx.input.text = "Giá hiện tại của đôi giày này là bao nhiêu?"
    later, _ = await executor.prefetch(ctx, frozenset({"get_pricing_quote", "get_order_quote"}))
    quote = next(c for c in later if c["name"] == "pricing.get_quote")
    assert not quote.get("_cached")
    fresh = catalog.pricing_get_quote(sku, customer_phone=reference.CRM[0]["phone"], address="Hà Nội")
    assert initial == 1_521_000
    assert quote["result"]["final_price_vnd"] == fresh["final_price_vnd"] == 1_690_000


@pytest.mark.parametrize("legacy", [False, True])
def test_exchange_keeps_header_and_lines_consistent(btc_db, legacy):
    reference, db = btc_db
    customer = reference.CRM[0]
    if legacy:
        with db.get_session() as session:
            session.add(Order(order_id="OLD-EXCHANGE", customer_id=customer["customer_id"],
                              sku="SKU-AP-X", qty=1, price_vnd=4_890_000))
            session.commit()
        oid = "OLD-EXCHANGE"
    else:
        oid = order.order_create(customer["phone"], sku="SKU-AP-X", payment="bank", address="Hà Nội")["order_id"]
    actual = order.order_update(oid, "exchange_product", new_variant_sku="SKU-AP-Y")
    assert actual["status"] == "pickup_scheduled"
    saved = db.find_orders(order_id=oid)[0]
    assert saved["sku"] == saved["lines"][0]["sku"] == "SKU-AP-Y"
    assert saved["total_vnd"] == sum(l["price_vnd"] * l.get("qty", 1) for l in saved["lines"])
    assert saved["exchange_count"] == 1


def test_exchange_without_line_selector_cannot_rewrite_multi_line_order(btc_db):
    reference, db = btc_db
    created = order.order_create(reference.CRM[0]["phone"], lines=[{"sku": "SKU-AP-PRO", "qty": 2}], payment="bank", address="Hà Nội")
    before = db.find_orders(order_id=created["order_id"])[0]
    result = order.order_update(created["order_id"], "exchange_product", new_variant_sku="SKU-AP-Y")
    assert result["error"] == "ambiguous_order_line"
    assert db.find_orders(order_id=created["order_id"])[0] == before


@pytest.mark.parametrize("lines", [
    [{"sku": "SKU-AP-PRO", "qty": 1}, {"sku": "SKU-AP-PRO", "qty": 1}],
    [{"sku": "SKU-AP-PRO", "qty": 2}],
])
def test_stock_is_checked_for_total_units_per_sku(btc_db, monkeypatch, lines):
    reference, db = btc_db
    monkeypatch.setattr(order, "inventory_check", lambda sku, on: {"sku": sku, "in_stock": True, "qty": 1})
    result = order.order_create(reference.CRM[0]["phone"], lines=lines, payment="bank", address="Hà Nội")
    assert result["error"] == "out_of_stock"
    assert db.find_orders(customer_phone=reference.CRM[0]["phone"]) == []


def test_order_lines_migration_is_repeatable_and_preserves_old_rows(btc_db):
    from sqlalchemy import inspect, text
    reference, db = btc_db
    engine = db.SessionLocal.kw["bind"]
    with engine.begin() as conn:
        before = conn.execute(text("SELECT order_id, sku, qty, price_vnd FROM orders ORDER BY order_id")).all()
        conn.execute(text("ALTER TABLE orders DROP COLUMN lines"))
    module_spec = importlib.util.spec_from_file_location("order_lines_migration", BTC.parents[1] / "scripts/migrate_order_lines.py")
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    assert migration.migrate_order_lines(engine) is True
    assert migration.migrate_order_lines(engine) is False
    assert next(c for c in inspect(engine).get_columns("orders") if c["name"] == "lines")["nullable"]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT order_id, sku, qty, price_vnd FROM orders ORDER BY order_id")).all() == before
    existing = next(o for c in reference.CRM for o in c.get("orders", []))
    saved = db.find_orders(order_id=existing["order_id"])[0]
    assert saved["lines"][0]["sku"] == existing["sku"]


@pytest.mark.asyncio
async def test_realtime_basket_quote_matches_btc_and_binds_private_arguments(btc_db, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from telesale_agent.application.realtime import tool_dispatch
    from telesale_agent.application.realtime.context import tool_declarations
    from telesale_agent.config.realtime import RealtimeSettings
    reference, db = btc_db
    ctx = checkout_context(reference, ["SKU-AP-PRO", "SKU-AP-MINI"], "Báo giá 2 máy Pro và 1 máy Mini.")

    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 15, 9, tzinfo=tz)

    monkeypatch.setattr("telesale_agent.core.business_time.datetime", Clock)
    tools = checkout_tools()
    services = SimpleNamespace(mcp_tools=tools)
    settings = RealtimeSettings()
    lines = [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]
    result, evidence = await tool_dispatch.dispatch(services, settings, ctx.state, ctx, "get_order_quote", {"lines": lines}, "quote")
    expected = reference.pricing_quote_order(lines, customer_phone=reference.CRM[0]["phone"], address="Hà Nội")
    assert result == expected
    assert evidence["name"] == "pricing.quote_order"
    args = tools["get_order_quote"].calls[0]
    assert args["customer_id"] == reference.CRM[0]["customer_id"]
    assert args["on"] == "2026-10-15"
    assert args["address"] == "100 đường Kiểm Thử, Hà Nội"
    assert "create_new_order" not in {d["name"] for d in tool_declarations(tools, "read_only")}
    for invalid in ([], [{"sku": "A", "qty": True}], [{"sku": "A", "qty": 1, "customer_id": "other"}]):
        rejected, _ = await tool_dispatch.dispatch(services, settings, ctx.state, ctx, "get_order_quote", {"lines": invalid}, "bad")
        assert rejected["error"] == "invalid_arguments"
    assert len(tools["get_order_quote"].calls) == 1
    assert db.find_orders(customer_phone=reference.CRM[0]["phone"]) == []


@pytest.mark.parametrize("failed_order", [False, True])
def test_first_quote_grounds_unit_prices_without_hiding_order_errors(btc_db, failed_order):
    from telesale_agent.application.deepagent.response import ground_basket_recap
    reference, _ = btc_db
    ctx = checkout_context(reference, ["SKU-AP-PRO", "SKU-AP-MINI"],
        "Báo giá từng máy và tổng tiền cho 2 AirPure Pro và 1 AirPure Mini, chưa tạo đơn.", 2)
    ctx.call_brief.remembered_preferences = {"facts": {}}
    ctx.state.customer_memory = {"facts": {}}
    ctx.input.metadata.pop("call_date")
    lines = [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-MINI", "qty": 1}]
    quote = catalog.pricing_quote_order(lines)
    calls = [
        {"name": "catalog.search", "result": {"items": [p for p in reference.PRODUCTS if p["sku"] in {"SKU-AP-PRO", "SKU-AP-MINI"}]}},
        {"name": "pricing.quote_order", "args": {"lines": lines}, "result": quote},
    ]
    if failed_order:
        calls.append({"name": "order.create", "result": {"error": "cod_limit_exceeded"}})
        response = "Đơn vượt giới hạn COD 10 triệu, chưa tạo đơn."
        assert ground_basket_recap(ctx, calls, response) == response
    else:
        wrong = "Pro 7.990.000đ/máy; Mini 495.000đ; tổng 16.475.000đ."
        response = ground_basket_recap(ctx, calls, wrong)
        assert response.count("7.690.000") == 2
        assert "1.095.000" in response
        assert "16.475.000" in response
        assert "7.990.000" not in response
        assert "495.000" not in response
