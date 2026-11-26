"""Regression checks for corpus integrity, grading and the November pricing cases."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_corpus import HERE, reference_module, read
from validate_corpus import negative_order_probes, replay, rows_for, validate


class CorpusTests(unittest.TestCase):
    def test_scenario_exports_match_reference_naming_and_format(self):
        from build_corpus import MAIN
        expected_fields = tuple(read(MAIN / "scenarios_complete/SC-001.json"))
        call_fields = {key for path in (MAIN / "scenarios_complete").glob("*.json") for call in read(path)["calls"].values() for key in call}
        metadata = read(HERE / "scenario_metadata.json")
        evaluator = reference_module("format_probe_eval", "reference_eval.py")
        scenarios = evaluator.load_scenarios(str(HERE / "scenarios_complete"))
        self.assertEqual(len(scenarios), 156)
        self.assertEqual(set(scenarios), set(metadata))
        self.assertEqual(set(scenarios), {f"SC-{i:03d}" for i in range(121, 277)})
        self.assertFalse(set(scenarios) & {p.stem for p in (MAIN / "scenarios_complete").glob("*.json")})
        self.assertEqual(metadata["SC-121"]["source_scenario_id"], "SC-001")
        self.assertEqual(metadata["SC-121"]["source_scenario_path"], "../scenarios_complete/SC-001.json")
        for path in (HERE / "scenarios_complete").glob("*.json"):
            scenario = read(path)
            self.assertRegex(path.name, r"^SC-\d{3}\.json$")
            self.assertEqual(path.stem, scenario["scenario_id"])
            self.assertEqual(tuple(scenario), expected_fields)
            for call in scenario["calls"].values():
                self.assertLessEqual(set(call), call_fields)

    def test_persisted_corpus_meets_text_minimums(self):
        report = validate()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["text_m2_minimums_met"])
        self.assertFalse(report["audio_m2_minimums_met"])
        self.assertEqual(report["counts"]["multi_session_customers"], 78)
        self.assertEqual(report["counts"]["call_and_chat_customers"], 61)
        self.assertEqual(report["counts"]["call_and_chat_customers_within_journey"], 57)
        self.assertEqual(report["counts"]["customers_with_two_hotline_calls_in_journey"], 62)

    def test_equal_price_units_use_different_prices_in_one_order(self):
        t = read(HERE / "conversations/SC-241-call_3.json")
        order = next(tc for tc in t["private_annotations"]["reference_tool_executions"] if tc["name"] == "order.create")
        self.assertEqual(len(order["args"]["lines"]), 2)
        self.assertEqual({line["sku"] for line in order["args"]["lines"]}, {"SKU-AP-PRO"})
        self.assertEqual([line["price_vnd"] for line in order["args"]["lines"]], [7690000, 3995000])
        self.assertEqual(order["args"]["payment"], "bank")

    def test_three_machines_receive_only_one_half_price_promotion(self):
        t = read(HERE / "conversations/SC-243-call_2.json")
        quote = next(tc["result"] for tc in t["private_annotations"]["reference_tool_executions"] if tc["name"] == "pricing.quote_order")
        half_price = [u for u in quote["units"] if any(p["promo_code"] == "AIR-2ND-50" for p in u["applied_promos"])]
        self.assertEqual(len(half_price), 1)
        self.assertEqual(half_price[0]["unit"], 3)
        self.assertEqual(quote["total_vnd"], 19375000)

    def test_reference_replay_detects_falsified_price(self):
        t = read(HERE / "conversations/SC-241-call_1.json")
        tools = copy.deepcopy(t["private_annotations"]["reference_tool_executions"])
        quote = next(tc for tc in tools if tc["name"] == "pricing.quote_order")
        quote["result"]["total_vnd"] -= 1000000
        mock = reference_module("tamper_probe_tools", "mock_tools.py")
        self.assertTrue(any("differs" in error for error in replay(mock, tools)))

    def test_failed_order_and_missing_unit_are_rejected(self):
        s = read(HERE / "scenarios_complete/SC-241.json")
        t = read(HERE / "conversations/SC-241-call_3.json")
        evaluator = reference_module("negative_probe_eval", "reference_eval.py")
        self.assertTrue(evaluator.check_call(s["calls"]["call_3"], rows_for(t))[0])
        errors, n = negative_order_probes(evaluator, s["calls"]["call_3"], rows_for(t))
        self.assertEqual(errors, [])
        self.assertEqual(n, 2)

    def test_third_call_is_short_and_has_one_confirmation(self):
        t = read(HERE / "conversations/SC-161-call_3.json")
        self.assertEqual(sum(u["text"].count("?") for u in t["utterances"] if u["speaker"] == "agent"), 1)
        self.assertEqual(sum(u["speaker"] == "customer" for u in t["utterances"]), 3)

    def test_clothing_is_not_promised_manufacturer_warranty_service(self):
        t = read(HERE / "conversations/SC-141-call_1.json")
        text = " ".join(u["text"] for u in t["utterances"] if u["speaker"] == "agent")
        self.assertNotIn("trung tâm bảo hành hãng", text)
        self.assertIn("Bảng size là hướng dẫn tham khảo", text)

    def test_returning_customer_is_not_told_family_decision_is_still_pending(self):
        t = read(HERE / "conversations/SC-221-call_2.json")
        text = " ".join(u["text"] for u in t["utterances"] if u["speaker"] == "agent")
        self.assertNotIn("còn trao đổi người nhà", text)
        self.assertIn("người nhà đồng ý", text)
        self.assertIn("4.490.000", text)


if __name__ == "__main__":
    unittest.main()
