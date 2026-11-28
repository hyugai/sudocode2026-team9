"""Business-flow, trace and evaluator regressions for BTC multi-line orders."""

import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from telesale_agent.core.models import TurnContext, TurnInput, ConversationState, CustomerIdentity, CallBrief, Perception
from telesale_agent.core.basket import product_lines, mentioned_catalog_items
from telesale_agent.application.tools.reads import ReadToolExecutor
from telesale_agent.application.tools.mutations import MutationToolExecutor
from telesale_agent.application.tools.protocol import canonical_tool_name, compact_orchestrated_result, tool_calls_to_steps
from telesale_agent.application.deepagent.context.order import _basket_lines, _requested_order_id
from telesale_agent.application.deepagent.response import ground_basket_recap, ground_multi_item_order_confirmation
from telesale_agent.application.memory.turn_facts import _tool_memory_candidates
from telesale_agent.application.conversation.tool_policy import select_tools_for_turn
from datetime import date
from mcp_servers.tools.pricing import PricingCalculator
from test_btc_pricing import FixtureDB
from eval.team_eval import evaluate_team, REFERENCE

DATA = ROOT / "dataset/transcript/src/stage-1/input/catalog"
PRODUCTS = json.loads((DATA / "products.json").read_text(encoding="utf-8"))["products"]
PROMOS = json.loads((DATA / "promotions.json").read_text(encoding="utf-8"))["promotions"]
PRICING = {k: None for k in ("input_per_million", "output_per_million", "tool_call", "memory_write", "storage_per_mb", "fixed_call")}


def context(qty=2, text="Chị chốt 2 máy AirPure Pro, chuyển khoản."):
    facts = {"basket_skus": ["SKU-AP-PRO"], "basket_lines": [{"sku": "SKU-AP-PRO", "qty": qty}],
             "basket_product_names": {"SKU-AP-PRO": "Máy lọc không khí AirPure Pro"},
             "product_advised": "SKU-AP-PRO", "delivery_address": "12 Nguyễn Trãi, Hà Nội", "payment": "bank"}
    state = ConversationState("test-basket", turn_number=1, customer_profile={"phone": "0900000000"}, customer_memory={"facts": facts})
    return TurnContext(input=TurnInput("test-basket", text=text, customer_hint="0900000000", metadata={"call_date": "2026-10-15"}),
                       state=state, identity=CustomerIdentity(customer_id="C-test", phone="0900000000"),
                       call_brief=CallBrief(customer_id="C-test", remembered_preferences={"facts": facts}),
                       perception=Perception(transcript=text, intent="create_order"))


def evidence(qty=2):
    lines = [{"sku": "SKU-AP-PRO", "qty": qty}]
    quote = PricingCalculator(FixtureDB(), date(2026, 10, 15)).quote_order(lines)
    return [
        {"name": "inventory.check", "args": {"sku": "SKU-AP-PRO"}, "result": {"in_stock": True, "qty": 100}},
        {"name": "pricing.quote_order", "args": {"lines": lines, "on": "2026-10-15"}, "result": quote},
    ]


class BasketTests(unittest.TestCase):
    def test_per_product_quantities_and_short_catalog_names(self):
        items = [p for p in PRODUCTS if p["sku"] in {"SKU-AP-PRO", "SKU-AP-X"}]
        text = "Chị mua 2 máy AirPure Pro và 1 máy AirPure X."
        selected = mentioned_catalog_items(text, items)
        self.assertEqual([p["sku"] for p in selected], ["SKU-AP-PRO", "SKU-AP-X"])
        self.assertEqual(product_lines(text, selected), [{"sku": "SKU-AP-PRO", "qty": 2}, {"sku": "SKU-AP-X", "qty": 1}])

    def test_quantity_survives_payment_only_followup(self):
        item = context(text="Chị chọn chuyển khoản.")
        self.assertEqual(_basket_lines(item), [{"sku": "SKU-AP-PRO", "qty": 2}])

    def test_order_mapping_supports_multiple_skus_in_one_order(self):
        item = context(text="Kiểm tra đơn của chị.")
        item.call_brief.remembered_preferences["facts"]["order_ids_by_sku"] = {"A": "NEW-1", "B": "NEW-1"}
        self.assertEqual(_requested_order_id(item), "NEW-1")

    def test_new_tool_is_routed_and_keeps_required_output_fields(self):
        item = context()
        self.assertIn("get_order_quote", select_tools_for_turn(item.perception, item.input.text))
        self.assertEqual(canonical_tool_name("get_order_quote"), "pricing.quote_order")
        self.assertEqual(canonical_tool_name("pricing.quote_order"), "pricing.quote_order")
        error = {"error": "price_mismatch", "expected_units": [{"sku": "A", "price_vnd": 100}]}
        self.assertEqual(compact_orchestrated_result("order.create", error), error)
        result = {"order_id": "NEW-1", "total_vnd": 300, "needs_confirmation_call": True}
        self.assertEqual(compact_orchestrated_result("order.create", result), result)


class OrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_publishes_new_quote_and_optional_legacy_order_inputs(self):
        from mcp_servers.mcp_db import mcp
        tools = {tool.name: tool.inputSchema for tool in await mcp.list_tools()}
        self.assertIn("get_order_quote", tools)
        self.assertEqual(tools["get_order_quote"]["required"], ["lines"])
        self.assertIn("lines", tools["create_new_order"]["properties"])
        self.assertNotIn("sku", tools["create_new_order"]["required"])

    async def test_realtime_quote_binds_identity_and_validates_nested_lines(self):
        from telesale_agent.application.realtime.tool_dispatch import dispatch
        from telesale_agent.config.realtime import RealtimeSettings
        item = context(text="Báo giá 2 máy AirPure Pro.")
        item.state.identity = item.identity
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value=evidence()[1]["result"]))
        services = SimpleNamespace(mcp_tools={"get_order_quote": tool})
        result, logged = await dispatch(services, RealtimeSettings(), item.state, item, "get_order_quote",
                                       {"lines": [{"sku": "SKU-AP-PRO", "qty": 2}]}, "voice-quote")
        self.assertEqual(result["total_vnd"], 11_685_000)
        self.assertEqual(logged["name"], "pricing.quote_order")
        self.assertEqual(tool.ainvoke.call_args.args[0]["customer_id"], "C-test")
        self.assertEqual(tool.ainvoke.call_args.args[0]["address"], "12 Nguyễn Trãi, Hà Nội")
        for lines in ([], [{"sku": "A", "qty": True}], [{"sku": "A", "qty": 1, "customer_id": "other"}]):
            result, _ = await dispatch(services, RealtimeSettings(), item.state, item, "get_order_quote", {"lines": lines}, "bad")
            self.assertEqual(result["error"], "invalid_arguments")
        tool.ainvoke.assert_awaited_once()

    async def test_prefetch_uses_one_basket_quote_with_date_identity_and_address(self):
        item = context()
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value=evidence()[1]["result"]))
        old = SimpleNamespace(ainvoke=AsyncMock())
        reads = ReadToolExecutor({"get_order_quote": tool, "get_pricing_quote": old})
        calls, remaining = await reads.prefetch(item, frozenset({"get_pricing_quote", "get_order_quote"}))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "pricing.quote_order")
        self.assertEqual(tool.ainvoke.call_args.args[0], {"lines": [{"sku": "SKU-AP-PRO", "qty": 2}],
            "on": "2026-10-15", "customer_phone": "0900000000", "customer_id": "C-test", "address": "12 Nguyễn Trãi, Hà Nội"})
        old.ainvoke.assert_not_awaited()
        self.assertFalse(remaining)

    async def test_legacy_single_unit_prefetch_still_uses_get_quote(self):
        item = context(1, "Báo giá AirPure Pro.")
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value={"sku": "SKU-AP-PRO", "final_price_vnd": 7_690_000}))
        basket = SimpleNamespace(ainvoke=AsyncMock())
        calls, _ = await ReadToolExecutor({"get_pricing_quote": tool, "get_order_quote": basket}).prefetch(item, frozenset({"get_pricing_quote", "get_order_quote"}))
        self.assertEqual(calls[0]["name"], "pricing.get_quote")
        basket.ainvoke.assert_not_awaited()

    async def test_empty_lines_prefetch_preserves_get_order_quote(self):
        item = TurnContext(
            input=TurnInput("test-empty", text="Báo giá hai máy lọc không khí giúp chị.", customer_hint="0900000000", metadata={"call_date": "2026-10-15"}),
            state=ConversationState("test-empty", turn_number=0, customer_profile={"phone": "0900000000"}),
            identity=CustomerIdentity(customer_id="C-test", phone="0900000000"),
            perception=Perception(transcript="Báo giá hai máy lọc không khí giúp chị.", intent="ask_product"),
        )
        quote_order = SimpleNamespace(ainvoke=AsyncMock())
        get_quote = SimpleNamespace(ainvoke=AsyncMock())
        calls, remaining = await ReadToolExecutor(
            {"get_order_quote": quote_order, "get_pricing_quote": get_quote}
        ).prefetch(item, frozenset({"get_pricing_quote", "get_order_quote"}))
        self.assertEqual(calls, [])
        self.assertIn("get_order_quote", remaining)
        self.assertIn("get_pricing_quote", remaining)

    async def test_closing_turn_executes_confirmed_pending_multiline_order_and_reads_back(self):
        from langchain_core.messages import AIMessage
        from telesale_agent.application.deepagent.turn import run_turn_impl

        lines = [{"sku": "SKU-AP-PRO", "qty": 2}]
        quote = PricingCalculator(FixtureDB(), date(2026, 10, 15)).quote_order(lines)
        inventory = SimpleNamespace(ainvoke=AsyncMock(return_value={"in_stock": True, "qty": 10}))
        quote_order = SimpleNamespace(ainvoke=AsyncMock(return_value=quote))
        get_quote = SimpleNamespace(ainvoke=AsyncMock())
        create_order = SimpleNamespace(
            ainvoke=AsyncMock(return_value={"order_id": "ORD-CLOSE-1", "status": "created", "total_vnd": 11_685_000, "estimated_delivery": "2026-10-17"})
        )
        mcp_tools = {
            "check_inventory": inventory,
            "get_order_quote": quote_order,
            "get_pricing_quote": get_quote,
            "create_new_order": create_order,
        }
        reads = ReadToolExecutor(mcp_tools)
        mutations = MutationToolExecutor(mcp_tools)
        seen_runtime_contexts = []

        async def fake_agent(payload, config=None, context=None):
            seen_runtime_contexts.append(context)
            return {"messages": [AIMessage(content="Dạ em đã lên đơn xong ạ.")]}

        perceive = SimpleNamespace(perceive=AsyncMock())
        state = ConversationState(
            "conv-close",
            turn_number=2,
            identity=CustomerIdentity(customer_id="C-test", phone="0900000000"),
            customer_profile={"phone": "0900000000"},
            customer_memory={"facts": {
                "basket_product_names": {"SKU-AP-PRO": "Máy lọc không khí AirPure Pro"},
            }},
            working_memory={
                "pending_order": {
                    "lines": lines,
                    "address": "12 Nguyễn Trãi, Hà Nội",
                    "payment": "bank",
                    "checkout_confirmed": True,
                }
            },
        )
        brief = CallBrief(
            customer_id="C-test",
            remembered_preferences={"facts": {"basket_product_names": {"SKU-AP-PRO": "Máy lọc không khí AirPure Pro"}}},
        )
        harness = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=fake_agent),
            asr=None,
            identity=None,
            customer_context=None,
            perceive=perceive,
            retrieve=None,
            call_brief=SimpleNamespace(build_call_brief=AsyncMock(return_value=brief)),
            persist=None,
            guardrail=None,
            _prefetch_read_tools=reads.prefetch,
            _execute_confirmed_mutation=mutations.execute,
        )
        turn_input = TurnInput(
            conversation_id="conv-close",
            text="",
            customer_hint="0900000000",
            metadata={"call_date": "2026-10-15", "call_key": "call_1", "closing_turn": True},
        )
        result = await run_turn_impl(harness, turn_input, state)
        perceive.perceive.assert_not_awaited()
        get_quote.ainvoke.assert_not_awaited()
        quote_order.ainvoke.assert_awaited_once()
        create_order.ainvoke.assert_awaited_once()
        self.assertEqual(
            create_order.ainvoke.call_args.args[0]["lines"],
            [
                {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000},
            ],
        )
        self.assertEqual(seen_runtime_contexts[0]["allowed_tools"], [])
        self.assertIn("ORD-CLOSE-1", result.response_text)
        self.assertIn("11.685.000", result.response_text)
        self.assertNotIn("pending_order", state.working_memory)
        self.assertEqual(state.working_memory["last_created_order"]["order_id"], "ORD-CLOSE-1")

    async def test_closing_turn_without_confirmed_pending_order_never_creates_order(self):
        from langchain_core.messages import AIMessage
        from telesale_agent.application.deepagent.turn import run_turn_impl

        create_order = SimpleNamespace(ainvoke=AsyncMock())
        reads = ReadToolExecutor({"create_new_order": create_order})
        mutations = MutationToolExecutor({"create_new_order": create_order})
        seen_contexts = []

        async def fake_agent(payload, config=None, context=None):
            seen_contexts.append((payload, context))
            return {"messages": [AIMessage(content="Dạ cảm ơn anh chị đã liên hệ ạ.")]}

        state = ConversationState(
            "conv-no-order",
            turn_number=1,
            identity=CustomerIdentity(customer_id="C-test", phone="0900000000"),
            customer_profile={"phone": "0900000000"},
        )
        harness = SimpleNamespace(
            agent=SimpleNamespace(ainvoke=fake_agent),
            asr=None,
            identity=None,
            customer_context=None,
            perceive=SimpleNamespace(perceive=AsyncMock()),
            retrieve=None,
            call_brief=None,
            persist=None,
            guardrail=None,
            _prefetch_read_tools=reads.prefetch,
            _execute_confirmed_mutation=mutations.execute,
        )
        result = await run_turn_impl(
            harness,
            TurnInput(conversation_id="conv-no-order", text="", metadata={"call_date": "2026-10-15", "closing_turn": True}),
            state,
        )
        create_order.ainvoke.assert_not_awaited()
        self.assertEqual(result.tool_calls, [])
        self.assertEqual(seen_contexts[0][1]["allowed_tools"], [])
        self.assertIn("Closing turn", seen_contexts[0][0]["messages"][0]["content"])

    async def test_prompt_uses_quote_order_guidance_and_closing_readback_for_existing_order(self):
        from telesale_agent.application.deepagent.context.prompt import append_orchestration_context, build_base_user_message

        item = context(text="")
        item.input.metadata["closing_turn"] = True
        item.state.working_memory["last_created_order"] = {"order_id": "ORD-99", "total_vnd": 11_685_000}
        user_text, base = build_base_user_message(item, [])
        prompt = append_orchestration_context(item, base, frozenset(), [], [])
        self.assertIn("Closing turn", user_text)
        self.assertIn("pricing.quote_order", prompt)
        self.assertNotIn("pricing.get_quote for every basket item", prompt)
        self.assertIn("ORD-99", prompt)

    async def test_one_order_keeps_distinct_unit_prices_and_prevents_duplicate(self):
        item = context()
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value={"order_id": "NEW-1", "total_vnd": 11_685_000}))
        executor = MutationToolExecutor({"create_new_order": tool})
        item.state.working_memory["read_tool_cache"] = {"stale": True}
        calls, _ = await executor.execute(item, frozenset({"create_new_order"}), evidence())
        args = tool.ainvoke.call_args.args[0]
        self.assertEqual(args["lines"], [{"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                                        {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000}])
        self.assertNotIn("read_tool_cache", item.state.working_memory)
        again, _ = await executor.execute(item, frozenset({"create_new_order"}), evidence())
        self.assertFalse(again)
        tool.ainvoke.assert_awaited_once()
        item.steps = tool_calls_to_steps(evidence() + calls)
        facts = _tool_memory_candidates(item)
        self.assertEqual(facts["order_ids_by_sku"]["SKU-AP-PRO"], "NEW-1")
        self.assertEqual(facts["order_total_vnd"], 11_685_000)
        self.assertEqual(len(facts["order_lines"]), 2)
        reply = ground_multi_item_order_confirmation(item, calls, "")
        self.assertEqual(reply.count("NEW-1"), 1)
        self.assertIn("11.685.000", reply)

    async def test_changed_quantity_can_create_a_new_checkout(self):
        item = context()
        tool = SimpleNamespace(ainvoke=AsyncMock(return_value={"order_id": "NEW-1"}))
        executor = MutationToolExecutor({"create_new_order": tool})
        await executor.execute(item, frozenset({"create_new_order"}), evidence())
        item.input.text = "Chị chốt 3 máy AirPure Pro, chuyển khoản."
        await executor.execute(item, frozenset({"create_new_order"}), evidence(3))
        self.assertEqual(tool.ainvoke.await_count, 2)
        self.assertEqual(len(tool.ainvoke.call_args.args[0]["lines"]), 3)

    async def test_failed_cod_preserves_cart_for_payment_retry(self):
        item = context(text="Chị chốt 2 máy AirPure Pro, COD.")
        tool = SimpleNamespace(ainvoke=AsyncMock(side_effect=[{"error": "cod_limit_exceeded"}, {"order_id": "NEW-1"}]))
        executor = MutationToolExecutor({"create_new_order": tool})
        await executor.execute(item, frozenset({"create_new_order"}), evidence())
        self.assertEqual(item.state.working_memory["pending_order"]["lines"], [{"sku": "SKU-AP-PRO", "qty": 2}])
        item.input.text = "Chị chọn chuyển khoản."
        await executor.execute(item, frozenset({"create_new_order"}), evidence())
        self.assertEqual(tool.ainvoke.await_count, 2)
        self.assertNotIn("pending_order", item.state.working_memory)
        self.assertEqual(tool.ainvoke.call_args.args[0]["payment_method"], "bank")

    async def test_exploratory_or_declined_order_never_creates(self):
        for text in ("Hai máy giá bao nhiêu?", "Chị chưa chốt đơn."):
            item = context(text=text)
            tool = SimpleNamespace(ainvoke=AsyncMock())
            await MutationToolExecutor({"create_new_order": tool}).execute(item, frozenset({"create_new_order"}), evidence())
            tool.ainvoke.assert_not_awaited()

    async def test_recap_uses_quote_total_for_same_sku_different_prices(self):
        item = context(text="Nhắc lại giỏ hàng và tổng tiền cho chị.")
        reply = ground_basket_recap(item, evidence(), "")
        self.assertIn("11.685.000", reply)
        self.assertIn("7.690.000", reply)
        self.assertIn("3.995.000", reply)

    async def test_first_turn_confirmation_uses_current_catalog_names(self):
        item = context()
        item.call_brief.remembered_preferences["facts"].pop("basket_product_names")
        calls = [{"name": "catalog.search", "result": {"items": [{"sku": "SKU-AP-PRO", "name": "Máy lọc không khí AirPure Pro"}]}},
                 {"name": "order.create", "args": {"lines": [{"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 7_690_000},
                    {"sku": "SKU-AP-PRO", "qty": 1, "price_vnd": 3_995_000}]}, "result": {"order_id": "NEW-1", "total_vnd": 11_685_000}}]
        reply = ground_multi_item_order_confirmation(item, calls, "")
        self.assertIn("Máy lọc không khí AirPure Pro", reply)
        self.assertNotIn("SKU-AP-PRO", reply)


class EvaluatorTests(unittest.TestCase):
    def evaluate(self, scenario, rows):
        return evaluate_team({"S": {"scenario_id": "S", "calls": scenario}},
                             {("S", key): [{"scenario_id": "S", "call": key, **value}] for key, value in rows.items()}, pricing=PRICING, warmup_turns=0)

    def row(self, calls):
        return {"turn": 1, "agent_text": "Đã thực hiện.", "tool_calls": calls, "claims": [], "latency": {}}

    def test_multiline_order_counts_for_tool_accuracy_and_total(self):
        spec = {"call_1": {"customer_turns": ["Tạo đơn"], "success_if": {"tool_called": "order.create",
                "args_match": {"sku": "A", "price_vnd": 100}, "also_ordered": ["B"], "total_match_vnd": 300}}}
        result = self.evaluate(spec, {"call_1": self.row([{"name": "order.create", "args": {"lines": [
            {"sku": "A", "qty": 1, "price_vnd": 100}, {"sku": "B", "qty": 1, "price_vnd": 200}]}, "result": {"order_id": "REAL"}}])})
        for metric in ("task_success_rate", "reference_task_success_rate", "tool_call_accuracy"):
            self.assertEqual(result[metric]["value"], 100)

    def test_previous_real_order_id_is_accepted_by_all_team_metrics(self):
        spec = {"call_1": {"customer_turns": ["Tạo đơn"], "success_if": {"tool_called": "order.create", "args_match": {"sku": "A"}}},
                "call_2": {"customer_turns": ["Cập nhật đơn"], "success_if": {"tool_called": "order.update", "args_match": {"order_id": "SCRIPT-ID", "action": "update_address"}}}}
        rows = {"call_1": self.row([{"name": "order.create", "args": {"sku": "A"}, "result": {"order_id": "REAL"}}]),
                "call_2": self.row([{"name": "order.update", "args": {"order_id": "REAL", "action": "update_address"}, "result": {"order_id": "REAL"}}])}
        result = self.evaluate(spec, rows)
        for metric in ("task_success_rate", "reference_task_success_rate", "tool_call_accuracy"):
            self.assertEqual(result[metric]["value"], 100)
        rows["call_1"]["tool_calls"][0]["result"] = {"error": "failed", "order_id": "REAL"}
        self.assertEqual(self.evaluate(spec, rows)["task_success_rate"]["value"], 0)

    def test_failed_cod_attempt_is_not_double_counted(self):
        spec = {"call_1": {"customer_turns": ["Tạo đơn"], "success_if": {"tool_called": "order.create", "args_match": {"sku": "A"}, "total_match_vnd": 100}}}
        calls = [{"name": "order.create", "args": {"sku": "A", "price_vnd": 100}, "result": {"error": "cod_limit_exceeded"}},
                 {"name": "order.create", "args": {"sku": "A", "price_vnd": 100}, "result": {"order_id": "REAL"}}]
        result = self.evaluate(spec, {"call_1": self.row(calls)})
        self.assertEqual(result["task_success_rate"]["value"], 100)
        self.assertEqual(result["tool_call_accuracy"]["value"], 100)

    def test_asr_new_entity_metrics_accept_aliases_and_score_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            gt = {"dialogues": [{"id": "D", "full_text": "hai máy", "entities": {"quantity": [1, 2]},
                                 "turns": [{"idx": 1, "entities": {"quantity": 2}}]}]}
            hy = {"D": {"text": "hai máy", "entities": {"quantity": 2}, "turns": [{"idx": 1, "entities": {"quantity": 2}}]}}
            (path / "ground_truth.json").write_text(json.dumps(gt), encoding="utf-8")
            (path / "hypotheses.json").write_text(json.dumps(hy), encoding="utf-8")
            report = REFERENCE.wer_cer(directory)
            self.assertEqual(report["entity_accuracy"], 100)
            self.assertEqual(report["entity_accuracy_per_turn"], 100)


if __name__ == "__main__":
    unittest.main()
