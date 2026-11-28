"""Regression checks for real benchmark coverage, metrics and timing."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.benchmark_support import (validate_inputs,trace_health,measured_latency,compare_metrics)
from eval.team_eval import btc_v2_report, evaluate_team, REFERENCE, REFERENCE_EVAL, rag_recall
from eval.trace_extractors import extract_claims,extract_facts_used,extract_questions

PRICING = {k:None for k in ("input_per_million","output_per_million","tool_call","memory_write","storage_per_mb","fixed_call")}


def fixture():
    scenarios = {"SC-001":{"scenario_id":"SC-001","calls":{"call_1":{"customer_turns":["xin chào"],
        "success_if":{"tool_called":"order.create","args_match":{"sku":"X"}},"ground_truth_facts":{"price_vnd":1000000}}}}}
    row = {"scenario_id":"SC-001","call":"call_1","turn":1,"agent_text":"Giá là 1.000.000 đồng.",
           "tool_calls":[{"name":"order.create","args":{"sku":"X"},"result":{"order_id":"test"}}],
           "claims":[{"field":"price_vnd","value":1000000}],"latency":{"ttft_ms":10,"total_ms":10,"ttfa_ms":None,"measurement_mode":"non_streaming"}}
    return scenarios,{("SC-001","call_1"):[row]}


class CoverageTests(unittest.TestCase):
    def test_submission_runner_visits_all_41_ids_in_both_configs(self):
        from eval import generate_traces
        from telesale_agent import bootstrap

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scenarios = root / "inputs"
            scenarios.mkdir()
            for index in range(1, 42):
                sid = f"CASE-{index:02}"
                data = {"scenario_id": sid, "calls": {"call_1": {"customer_turns": ["Xin chào"]}}}
                (scenarios / f"file-{index:02}.json").write_text(json.dumps(data), encoding="utf-8")
            harness = SimpleNamespace(__aexit__=AsyncMock())

            async def replay(scenario, harness, config, run_id, **kwargs):
                return [{"scenario_id": scenario["scenario_id"], "call": "call_1", "turn": 1, "config": config}]

            with patch.object(bootstrap, "build_deepagent_harness_async", AsyncMock(return_value=harness)), \
                 patch.object(generate_traces, "run_scenario", replay), \
                 patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key", "EVAL_LLM_PROVIDER": "gemini"}):
                for config in ("full", "baseline_no_memory"):
                    output = root / f"{config}.jsonl"
                    with patch.object(sys, "argv", ["run_eval.py", "--scenarios", str(scenarios),
                                                   "--config", config, "--out", str(output)]):
                        self.assertEqual(asyncio.run(generate_traces.main(submission=True)), 0)
                    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                    self.assertEqual([row["scenario_id"] for row in rows], [f"CASE-{i:02}" for i in range(1, 42)])
                    self.assertEqual(sum(row["latency_warmup"] for row in rows), 3)
                    self.assertTrue(json.loads(output.with_suffix(".metadata.json").read_bytes())["trace_health"]["valid"])

    def test_complete_trace_is_valid(self):
        self.assertTrue(trace_health(*fixture())["valid"])

    def test_trace_health_supports_and_validates_closing_turns(self):
        from eval.benchmark_support import turn_keys

        scenarios = {
            "SC-001": {
                "scenario_id": "SC-001",
                "calls": {
                    "call_1": {"customer_turns": ["xin chào"]},
                    "call_2": {"customer_turns": ["tôi chốt đơn"]},
                },
            }
        }
        self.assertEqual(len(turn_keys(scenarios)), 2)
        self.assertEqual(len(turn_keys(scenarios, include_closing_turn=True)), 4)

        complete = {
            ("SC-001", "call_1"): [
                {"scenario_id": "SC-001", "call": "call_1", "turn": 1, "customer_text": "xin chào"},
                {"scenario_id": "SC-001", "call": "call_1", "turn": 2, "customer_text": ""},
            ],
            ("SC-001", "call_2"): [
                {"scenario_id": "SC-001", "call": "call_2", "turn": 1, "customer_text": "tôi chốt đơn"},
                {"scenario_id": "SC-001", "call": "call_2", "turn": 2, "customer_text": ""},
            ],
        }
        health = trace_health(scenarios, complete)
        self.assertTrue(health["valid"])
        self.assertEqual(health["closing_turns"], 2)
        self.assertEqual(health["expected_turns"], 4)

        # Missing closing turn on one call must fail when closing turns are present.
        partial = copy.deepcopy(complete)
        partial[("SC-001", "call_2")].pop()
        partial_health = trace_health(scenarios, partial)
        self.assertFalse(partial_health["valid"])
        self.assertEqual(partial_health["missing_turns"], [("SC-001", "call_2", 2)])

        # Non-empty customer_text on a closing turn must fail validation.
        nonempty = copy.deepcopy(complete)
        nonempty[("SC-001", "call_1")][1]["customer_text"] = "không rỗng"
        nonempty_health = trace_health(scenarios, nonempty)
        self.assertFalse(nonempty_health["valid"])
        self.assertEqual(nonempty_health["invalid_closing_turns"], [("SC-001", "call_1", 2)])

    def test_run_scenario_appends_closing_turn_with_empty_customer_text(self):
        from eval.generate_traces import run_scenario

        scenarios, _ = fixture()
        seen_inputs = []
        state = SimpleNamespace()

        async def fake_run_turn(turn_input, conv_state):
            seen_inputs.append(turn_input)
            return SimpleNamespace(
                state=state,
                response_text="Em xác nhận đơn và chào anh chị ạ.",
                tool_calls=[],
                memory_writes=[],
                usage={"requests": 1, "failed_requests": 0, "input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                call_brief=None,
                latency={"ttft_ms": 10, "total_ms": 10, "ttfa_ms": None, "measurement_mode": "non_streaming"},
            )

        harness = SimpleNamespace(
            memory=SimpleNamespace(),
            reset_customer_memory=Mock(),
            run_turn=fake_run_turn,
        )
        rows = asyncio.run(run_scenario(scenarios["SC-001"], harness, "full", "test", max_retries=1))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["turn"], 1)
        self.assertEqual(rows[0]["customer_text"], "xin chào")
        self.assertEqual(rows[1]["turn"], 2)
        self.assertEqual(rows[1]["customer_text"], "")
        self.assertEqual(rows[1]["reference_customer_text"], "")
        self.assertEqual(rows[1]["normalized_customer_text"], "")
        self.assertTrue(seen_inputs[1].metadata.get("closing_turn"))
        self.assertEqual(seen_inputs[1].text, "")
        self.assertTrue(trace_health(scenarios, {("SC-001", "call_1"): rows}, include_closing_turn=True)["valid"])

    def test_empty_trace_is_invalid(self):
        scenarios,_ = fixture()
        self.assertFalse(trace_health(scenarios,{})["valid"])

    def test_blank_error_marker_is_invalid_and_excluded_from_latency(self):
        scenarios,trace = fixture()
        trace[("SC-001","call_1")][0]["_error"] = ""
        self.assertEqual(trace_health(scenarios,trace)["error_turns"],1)
        self.assertFalse(trace_health(scenarios,trace)["valid"])
        self.assertEqual(measured_latency(trace,REFERENCE,warmup=0)["n_turns"],0)

    def test_duplicates_and_internal_request_errors_are_invalid(self):
        scenarios,trace = fixture()
        row = trace[("SC-001","call_1")][0]
        row["usage"] = {"failed_requests":1}
        self.assertFalse(trace_health(scenarios,trace)["valid"])
        row.pop("usage")
        trace[("SC-001","call_1")].append(copy.deepcopy(row))
        self.assertEqual(trace_health(scenarios,trace)["duplicate_turns"],1)

    def test_audio_requires_manifest_checksum_and_matching_text(self):
        scenarios,_ = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path = root / "audio/SC-001/call_1/SC-001_call_1_turn_001.wav"
            wav_path.parent.mkdir(parents=True)
            with wave.open(str(wav_path),"wb") as wav:
                wav.setparams((1,2,16000,0,"NONE","not compressed"))
                wav.writeframes(b"\0\0"*160)
            row = {"scenario_id":"SC-001","call_id":"call_1","turn_number":1,"status":"generated",
                   "text_original":"xin chào","output_sha256":hashlib.sha256(wav_path.read_bytes()).hexdigest()}
            manifest = root / "manifest.jsonl"
            manifest.write_text(json.dumps(row),encoding="utf-8")
            self.assertEqual(validate_inputs(scenarios,root / "audio")["audio_files"],1)
            row["text_original"] = "different text"
            manifest.write_text(json.dumps(row),encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_inputs(scenarios,root / "audio")
            row["text_original"] = "xin chào"
            row["output_sha256"] = "wrong"
            manifest.write_text(json.dumps(row),encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_inputs(scenarios,root / "audio")


class DialogueASRTests(unittest.TestCase):
    def test_btc_asr_counts_empty_hypothesis_and_rejects_missing_id(self):
        from eval.run_asr import run_dialogue_asr, validate_btc_asr

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = root / "reference.json"
            truth.write_text(json.dumps({"dialogues": [
                {"id": "A", "full_text": "size bốn mươi", "entities": {"size_old": 40}},
                {"id": "B", "full_text": "còn hàng", "entities": {"in_stock": True}},
            ]}), encoding="utf-8")
            for sid in ("A", "B"):
                with wave.open(str(root / f"{sid}.wav"), "wb") as out:
                    out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    out.writeframes(b"\0\0" * 100)
            engine = SimpleNamespace(transcribe=AsyncMock(side_effect=["size bốn mươi", ""]))
            output = root / "output"
            self.assertEqual(asyncio.run(run_dialogue_asr(truth, root, output, engine, {})), 0)
            hypotheses = json.loads((output / "hypotheses.json").read_bytes())
            self.assertEqual(hypotheses["A"]["entities"], {"size_old": 40})
            self.assertEqual(hypotheses["B"], {"text": "", "entities": {}})
            report = json.loads((output / "report.json").read_bytes())
            self.assertEqual(report["asr"]["n_entities"], 2)
            self.assertEqual(report["asr"]["WER"], 40.0)
            self.assertEqual(report["asr"]["entity_accuracy"], 50.0)
            del hypotheses["B"]
            (output / "hypotheses.json").write_text(json.dumps(hypotheses), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"missing=\['B'\]"):
                validate_btc_asr(output)


class MetricTests(unittest.TestCase):
    def test_reference_json_matches_direct_cli_on_original_scenarios(self):
        scenarios, trace = fixture()
        row = trace[("SC-001", "call_1")][0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "original.json").write_text(json.dumps(scenarios["SC-001"]), encoding="utf-8")
            full, baseline = root / "full.jsonl", root / "base.jsonl"
            for path in (full, baseline):
                path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            direct = root / "external.json"
            subprocess.run(
                [sys.executable, "-X", "utf8", str(REFERENCE_EVAL), "--scenarios", str(inputs),
                 "--trace", str(full), "--baseline", str(baseline), "--out", str(direct)],
                check=True, capture_output=True,
            )
            self.assertEqual(btc_v2_report(scenarios, full, baseline, scenarios_path=inputs),
                             json.loads(direct.read_bytes()))

    def test_failed_order_is_not_a_success_or_close(self):
        scenarios,trace = fixture()
        trace[("SC-001","call_1")][0]["tool_calls"][0]["result"] = {"error":"out_of_stock"}
        result = evaluate_team(scenarios,trace,pricing=PRICING)
        self.assertEqual(result["reference_task_success_rate"]["value"],0)
        self.assertEqual(result["task_success_rate"]["value"],0)
        self.assertEqual(result["calls_to_close"]["n_closed"],0)

    def test_no_action_scenario_still_requires_observed_turns(self):
        scenarios,_ = fixture()
        scenarios["SC-001"]["calls"]["call_1"]["success_if"] = {"tool_called":None}
        result = evaluate_team(scenarios,{},pricing=PRICING)
        self.assertEqual(result["task_success_rate"]["value"],0)

    def test_wrong_spoken_price_is_counted(self):
        claims = extract_claims([],response_text="Giá hiện tại là 2.000.000 đồng.")
        self.assertEqual(claims[0], {
            "field": "price_vnd", "value": 2000000, "text": "Giá hiện tại là 2.000.000 đồng.",
        })
        scenarios,trace = fixture()
        trace[("SC-001","call_1")][0]["claims"] = claims
        report = evaluate_team(scenarios,trace,pricing=PRICING)
        self.assertEqual(report["hallucination_rate"]["price_only"]["value"],100)

    def test_promo_expiry_scores_only_spoken_codes(self):
        scenarios, trace = fixture()
        facts = scenarios["SC-001"]["calls"]["call_1"]["ground_truth_facts"]
        facts["promo_expiry_dates"] = {"MOM-FREESHIP": "2026-11-29", "COD-0": "2026-12-14"}
        row = trace[("SC-001", "call_1")][0]
        for spoken, expected in (("29/11", 0.0), ("01/01/2030", 100.0)):
            with self.subTest(expiry=spoken):
                row["claims"] = extract_claims(
                    [], call_date="2026-11-26",
                    response_text=f"Mã **MOM-FREESHIP** còn hiệu lực đến hết ngày {spoken} ạ.",
                )
                report = evaluate_team(scenarios, trace, pricing=PRICING)
                self.assertEqual(
                    report["hallucination_rate"]["price_promo_only"],
                    {"value": expected, "wrong": int(expected > 0), "total": 1},
                )
                self.assertIsNone(report["hallucination_rate"]["price_only"]["value"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            btc = btc_v2_report(scenarios, path)
        self.assertIsNone(btc["system"]["hallucination_rate"]["price_promo_only"]["value"])
        self.assertNotIn("promo_expiry_MOM-FREESHIP", facts)

    def test_promo_questions_and_tool_status_do_not_replace_spoken_claims(self):
        self.assertEqual(extract_claims(
            [], response_text="Mã AIR-OCT hết hạn ngày 31/02/2026. Mã COD-0 hết hạn ngày 14/12/2026 đúng không?"
        ), [])
        tool_calls = [{
            "name": "pricing.get_quote",
            "result": {"expired_promos": [{"promo_code": "AIR-OCT"}]},
        }]
        claims = extract_claims(tool_calls, response_text="Mã AIR-OCT vẫn áp dụng cho mình ạ.")
        self.assertEqual(claims, [{
            "field": "promo_AIR-OCT_active", "value": True, "text": "AIR-OCT vẫn áp dụng",
        }])

    def test_btc_report_surfaces_reference_error_when_full_rqr_has_no_sample(self):
        scenarios, trace = fixture()
        scenarios["SC-001"]["calls"]["call_1"]["must_not_ask"] = ["product_advised"]
        row = trace[("SC-001", "call_1")][0]
        baseline_row = {**row, "questions": [{"type": "open", "slot": "product_advised"}]}
        with tempfile.TemporaryDirectory() as directory:
            full = Path(directory) / "full.jsonl"
            baseline = Path(directory) / "baseline.jsonl"
            full.write_text(json.dumps(row) + "\n", encoding="utf-8")
            baseline.write_text(json.dumps(baseline_row) + "\n", encoding="utf-8")
            report = btc_v2_report(scenarios, full, baseline)
        self.assertIn("TypeError", report["error"])
        self.assertNotEqual(report["exit_code"], 0)

    def test_suite_keeps_turn_asr_as_an_internal_diagnostic(self):
        from eval import run_suite

        scenarios, trace = fixture()
        row = trace[("SC-001", "call_1")][0]
        row["customer_text"] = "xin chào"

        async def run_arm(args, selected, kind, config, run_dir):
            arm_dir = run_dir / kind / config
            arm_dir.mkdir(parents=True)
            (arm_dir / "trace.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            system = evaluate_team(selected, trace, pricing=PRICING)
            if kind == "audio":
                system["asr"] = run_suite.asr_report(selected, trace, arm_dir / "asr")
            return {"system": system, "error": None}

        with tempfile.TemporaryDirectory() as directory, patch.object(run_suite, "run_arm", run_arm):
            run_dir = Path(directory)
            args = SimpleNamespace(input_kinds=["text", "audio"])
            with self.assertRaises(StopIteration):
                run_suite.run(args, scenarios, run_dir, {}).send(None)
            report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        self.assertNotIn("asr", report["btc_v2"]["text"])
        self.assertNotIn("asr", report["btc_v2"]["audio"])
        team_asr = report["reports"]["audio"]["full"]["system"]["asr"]
        self.assertEqual(team_asr["WER"], 0.0)
        self.assertEqual(team_asr["coverage"], {"expected": 1, "observed": 1})

    def test_question_does_not_inherit_preceding_product_statement(self):
        question = extract_questions("Sản phẩm này giá 1.000.000 đồng. Chị muốn lên đơn không?")[0]
        self.assertEqual(question["slot"],"other")

    def test_missing_rag_results_are_misses_and_include_by_type_recall(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa.json").write_text(json.dumps({"questions":[
                {"qid":"a","type":"single","relevant_chunk_ids":["A"]},
                {"qid":"b","type":"numeric","relevant_chunk_ids":["B"]},
            ]}))
            (root / "results.json").write_text(json.dumps({"a":{"retrieved_chunk_ids":["A"]}}))
            report = rag_recall(root / "qa.json",root / "results.json")
            self.assertEqual(report["recall@3"],50)
            self.assertEqual(report["by_type_recall@5"]["single"],100.0)
            self.assertEqual(report["by_type_recall@5"]["numeric"],0.0)
            self.assertIn("note",report)

    def test_gates_follow_btc_rqr_zero_and_price_promo_hr(self):
        scenarios,trace = fixture()
        full = evaluate_team(scenarios,trace,pricing=PRICING)
        baseline = copy.deepcopy(full)
        full["repeat_question_rate"]["value"] = 20
        baseline["repeat_question_rate"]["value"] = 40
        passed = compare_metrics(full,baseline)
        self.assertEqual(passed["status"],"pass")
        self.assertTrue(passed["meets_rqr_threshold_40pct"])
        self.assertTrue(passed["meets_tsr_70pct"])
        self.assertTrue(passed["meets_hr_price_5pct"])

        # Promo hallucination must fail the BTC HR gate even when price_only is 0.
        promo_fail = copy.deepcopy(full)
        promo_fail["hallucination_rate"]["price_only"]["value"] = 0.0
        promo_fail["hallucination_rate"]["price_promo_only"]["value"] = 25.0
        failed_hr = compare_metrics(promo_fail,baseline)
        self.assertEqual(failed_hr["status"],"fail")
        self.assertFalse(failed_hr["meets_hr_price_5pct"])

        # BTC rule for baseline RQR = 0: system RQR = 0 -> None/inconclusive; system RQR > 0 -> False/fail.
        baseline["repeat_question_rate"]["value"] = 0
        full["repeat_question_rate"]["value"] = 20
        failed_rqr = compare_metrics(full,baseline)
        self.assertEqual(failed_rqr["status"],"fail")
        self.assertIs(failed_rqr["meets_rqr_threshold_40pct"],False)
        self.assertIsNotNone(failed_rqr["rqr_note"])

        full["repeat_question_rate"]["value"] = 0
        inconclusive = compare_metrics(full,baseline)
        self.assertEqual(inconclusive["status"],"inconclusive")
        self.assertIsNone(inconclusive["meets_rqr_threshold_40pct"])
        self.assertIsNotNone(inconclusive["rqr_note"])

        baseline["trace_health"]["valid"] = False
        self.assertEqual(compare_metrics(full,baseline)["status"],"invalid")

    def test_extractors_support_multiline_orders_and_order_promos(self):
        brief = {
            "product_advised": "SKU-SN-RUN2-38-DEN",
            "variant_sku": "SKU-SN-RUN2-38-DEN",
            "price_quoted_vnd": 1521000,
            "size": 38,
            "color": "den",
            "promo_code": "RUN-10",
        }
        tool_calls = [{
            "name": "order.create",
            "args": {
                "lines": [{"sku": "SKU-SN-RUN2-38-DEN", "qty": 1, "price_vnd": 1521000}],
                "promo_code": "RUN-10",
            },
            "result": {"order_id": "ORD-1"},
        }]
        used = extract_facts_used("Em đã lên đơn xong ạ.", tool_calls, brief)
        self.assertTrue({"product_advised", "variant_sku", "price_quoted_vnd", "size", "color", "promo_code"} <= set(used))

        quote_calls = [{
            "name": "pricing.quote_order",
            "args": {"lines": [{"sku": "SKU-AP-PRO", "qty": 2}]},
            "result": {
                "units": [
                    {"sku": "SKU-AP-PRO", "list_price_vnd": 7990000, "final_price_vnd": 7690000,
                     "applied_promos": [{"promo_code": "AIR-OCT"}]},
                    {"sku": "SKU-AP-PRO", "list_price_vnd": 7990000, "final_price_vnd": 3995000,
                     "applied_promos": [{"promo_code": "AIR-2ND-50"}]},
                ],
                "order_promos": [{"promo_code": "NAM-SHIP0"}],
                "total_vnd": 11685000,
            },
        }]
        claims = extract_claims(
            quote_calls,
            response_text="Giá niêm yết 7.990.000đ, máy 1 còn 7.690.000đ (AIR-OCT), máy 2 còn 3.995.000đ (AIR-2ND-50), tổng 11.685.000đ, freeship NAM-SHIP0.",
        )
        values = {(claim["field"], claim["value"]) for claim in claims}
        self.assertIn(("list_price_vnd", 7990000), values)
        self.assertIn(("promo_NAM-SHIP0_active", True), values)

    def test_free_text_evidence_does_not_depend_on_tool_truth(self):
        questions = extract_questions("Chị cho em xin diện tích phòng với ạ. Phòng vẫn 25 m² đúng không chị?")
        self.assertEqual([(q["slot"], q["type"]) for q in questions],
                         [("room_area_m2", "open"), ("room_area_m2", "confirm")])
        claims = extract_claims(
            [], response_text="AirPure Pro còn bảy triệu sáu trăm chín mươi nghìn đồng. "
                              "Máy này hết hàng rồi ạ. Tổng là 17.990.000đ. Em giao sau 5 ngày ạ.",
        )
        self.assertEqual({c["field"]: c["value"] for c in claims}, {
            "price_vnd": 7_690_000, "in_stock": False, "total_vnd": 17_990_000, "delivery_days": 5,
        })

    def test_fact_carryover_checks_prior_value_and_current_brief(self):
        prior = {"room_area_m2": 25}
        self.assertEqual(extract_facts_used("Phòng chị rộng 25 m².", [], prior), ["room_area_m2"])
        self.assertEqual(extract_facts_used("Phòng chị rộng 35 m².", [], prior), [])
        changed = SimpleNamespace(remembered_preferences={"facts": {"room_area_m2": 35}})
        self.assertEqual(extract_facts_used("Phòng chị rộng 25 m².", [], prior, current_brief=changed), [])

    def test_asr_turns_default_customer_input_mode_to_asr_transcript(self):
        from eval.generate_traces import run_scenario
        from unittest.mock import AsyncMock
        scenarios, _ = fixture()
        scenarios["SC-001"]["calls"]["call_1"]["customer_turns_asr"] = ["xin chao"]
        state = SimpleNamespace()
        turn_result = SimpleNamespace(
            state=state,
            response_text="Chào anh chị ạ.",
            tool_calls=[],
            memory_writes=[],
            usage={},
            call_brief=None,
            latency={"ttft_ms": 10, "total_ms": 10, "ttfa_ms": None, "measurement_mode": "non_streaming"},
        )
        harness = SimpleNamespace(
            memory=SimpleNamespace(),
            reset_customer_memory=Mock(),
            run_turn=AsyncMock(return_value=turn_result),
        )
        coroutine = run_scenario(scenarios["SC-001"], harness, "full", "test", max_retries=1)
        try:
            coroutine.send(None)
        except StopIteration as stopped:
            rows = stopped.value
        else:
            self.fail("Pure async fakes should complete without external IO")
        self.assertEqual(rows[0]["customer_input_mode"], "asr_transcript")

    def test_team_failures_include_hard_case_field(self):
        scenarios, trace = fixture()
        scenarios["SC-001"]["hard_case"] = True
        trace[("SC-001", "call_1")][0]["tool_calls"][0]["result"] = {"error": "out_of_stock"}
        report = evaluate_team(scenarios, trace, pricing=PRICING)
        self.assertTrue(report["task_success_rate"]["failures"][0]["hard_case"])


class LatencyTests(unittest.TestCase):
    def test_nonstreamed_answer_latency_excludes_asr_and_persistence(self):
        from langchain_core.messages import AIMessage
        from telesale_agent.application.deepagent.turn import run_turn_impl
        from telesale_agent.core.models import TurnInput,CustomerIdentity,CallBrief
        clock = [0.0]
        async def asr(context):
            clock[0] += 0.5
            return "xin chào"
        async def identity(context):
            clock[0] += 0.003
            return CustomerIdentity(customer_id="C-test")
        async def brief(context):
            clock[0] += 0.004
            return CallBrief(customer_id="C-test")
        async def agent(*args,**kwargs):
            clock[0] += 0.020
            return {"messages":[AIMessage(content="Xin chào chị.")]}
        async def persist(context):
            clock[0] += 1
            return []
        async def reads(*args):
            return [],frozenset()
        async def mutations(*args):
            return [],frozenset()
        harness = SimpleNamespace(agent=SimpleNamespace(ainvoke=agent),asr=SimpleNamespace(transcribe=asr),
                                  identity=SimpleNamespace(resolve_identity=identity),customer_context=None,
                                  perceive=None,retrieve=None,call_brief=SimpleNamespace(build_call_brief=brief),
                                  persist=SimpleNamespace(persist=persist),guardrail=None,
                                  _prefetch_read_tools=reads,_execute_confirmed_mutation=mutations)
        with patch("telesale_agent.application.deepagent.turn.time",SimpleNamespace(perf_counter=lambda:clock[0])), patch("telesale_agent.application.conversation.prepare.time",SimpleNamespace(perf_counter=lambda:clock[0])):
            coroutine = run_turn_impl(harness,TurnInput(conversation_id="test",audio=b"fake-audio",customer_hint="0901234567"))
            import asyncio
            result = asyncio.run(coroutine)
        self.assertEqual(result.latency["asr_ms"],500)
        self.assertEqual(result.latency["call_brief_ms"],507)
        self.assertEqual(result.latency["response_ready_ms"],27)
        self.assertEqual(result.latency["persistence_ms"],1000)
        self.assertEqual(result.latency["total_ms"],27)
        self.assertEqual(result.latency["ttft_ms"],27)
        self.assertEqual(result.latency["request_complete_ms"],1027)
        self.assertEqual(result.latency["backend_total_ms"],1527)
        self.assertIsNone(result.latency["ttfa_ms"])

    def test_report_keeps_answer_persistence_and_request_completion_separate(self):
        _, trace = fixture()
        trace[("SC-001", "call_1")][0]["latency"].update(
            ttft_ms=27, total_ms=27, response_ready_ms=27,
            persistence_ms=1000, request_complete_ms=1027)
        result = measured_latency(trace, REFERENCE, warmup=0)
        self.assertEqual(result["ttft"]["p95_ms"], 27)
        self.assertEqual(result["total"]["p95_ms"], 27)
        self.assertEqual(result["persistence"]["p95_ms"], 1000)
        self.assertEqual(result["request_complete"]["p95_ms"], 1027)

    def test_three_warmups_are_excluded_using_official_percentile(self):
        rows = [{"latency":{"ttft_ms":i,"total_ms":i,"ttfa_ms":None,"measurement_mode":"non_streaming"}} for i in range(1,104)]
        result = measured_latency({("s","c"):rows},REFERENCE)
        self.assertEqual(result["n_turns"],100)
        self.assertEqual(result["total"]["p95_ms"],99)
        self.assertEqual(result["ttft"],result["total"])
        self.assertIsNone(result["ttfa"])
        self.assertTrue(result["thresholds"]["sufficient_sample"])

    def test_legacy_estimated_latency_is_not_reported_as_measured(self):
        result = measured_latency({("s","c"):[{"latency":{"total_ms":100,"ttft_ms":33}}]},REFERENCE,0)
        self.assertIsNone(result["ttft"])
        self.assertFalse(result["thresholds"]["sufficient_sample"])


class ModelCompatibilityTests(unittest.TestCase):
    def test_generator_records_timeout_without_message(self):
        from eval.generate_traces import run_scenario
        from unittest.mock import AsyncMock
        scenarios,_ = fixture()
        harness = SimpleNamespace(memory=SimpleNamespace(),reset_customer_memory=Mock(),
                                  run_turn=AsyncMock(side_effect=TimeoutError()))
        coroutine = run_scenario(scenarios["SC-001"],harness,"full","test",max_retries=1)
        try:
            coroutine.send(None)
        except StopIteration as stopped:
            rows = stopped.value
        else:
            self.fail("Pure async fakes should complete without external IO")
        self.assertEqual(rows[0]["_error"],"TimeoutError")

    def test_provider_billing_error_is_permanent_but_429_is_not(self):
        from eval.model_config import permanent_provider_error
        self.assertTrue(permanent_provider_error(Exception("Your prepayment credits are depleted")))
        self.assertFalse(permanent_provider_error(Exception("429 rate limit reached; try again in 5s")))
        error = RuntimeError("model access failed")
        error.status_code = 404
        self.assertTrue(permanent_provider_error(error))

    def test_generator_stops_after_first_permanent_provider_failure(self):
        from eval.generate_traces import run_scenario
        from unittest.mock import AsyncMock
        scenarios,_ = fixture()
        scenarios["SC-001"]["calls"]["call_1"]["customer_turns"] = ["one","two","three"]
        error = RuntimeError("Your prepayment credits are depleted")
        harness = SimpleNamespace(memory=SimpleNamespace(),reset_customer_memory=Mock(),
                                  run_turn=AsyncMock(side_effect=error))
        coroutine = run_scenario(scenarios["SC-001"],harness,"full","test")
        try:
            coroutine.send(None)
        except StopIteration as stopped:
            rows = stopped.value
        else:
            self.fail("Pure async fakes should complete without external IO")
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]["_fatal_provider_error"])
        self.assertEqual(harness.run_turn.await_count,1)

    def test_suite_skips_remaining_arms_when_provider_billing_is_blocked(self):
        from eval.run_suite import run
        from unittest.mock import AsyncMock
        scenarios,_ = fixture()
        failed = {"system":evaluate_team(scenarios,{},pricing=PRICING),
                  "error":"prepayment credits are depleted","fatal_provider_error":True}
        args = SimpleNamespace(input_kinds=["text","audio"],pricing=PRICING)
        with tempfile.TemporaryDirectory() as directory, patch("eval.run_suite.run_arm",AsyncMock(return_value=failed)) as arm, patch("builtins.print"):
            root = Path(directory)
            coroutine = run(args,scenarios,root,{})
            try:
                coroutine.send(None)
            except StopIteration as stopped:
                code = stopped.value
            else:
                self.fail("Pure async fakes should complete without external IO")
            self.assertEqual(code,2)
            self.assertEqual(arm.await_count,1)
            report = json.loads((root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"],"blocked_provider")
            self.assertTrue(report["reports"]["text"]["full"]["skipped"])
            self.assertTrue(report["reports"]["audio"]["baseline_no_memory"]["skipped"])
            self.assertTrue(report["reports"]["audio"]["full"]["skipped"])

    def test_eval_defaults_to_gemini_despite_old_groq_environment(self):
        from eval.model_config import configure_eval_model
        with patch.dict("os.environ",{"LLM_PROVIDER":"groq","LLM_MODEL":"openai/gpt-oss-20b",
                                      "EVAL_REQUEST_INTERVAL_SECONDS":"30","GOOGLE_API_KEY":"test-key"},clear=True):
            config = configure_eval_model()
            self.assertEqual((config.provider,config.model),("gemini","gemini-3.6-flash"))
            import os
            self.assertEqual(float(os.environ["EVAL_REQUEST_INTERVAL_SECONDS"]),0)
            self.assertEqual(os.environ["LLM_MODEL"],"gemini-3.6-flash")

    def test_explicit_provider_does_not_inherit_another_provider_model(self):
        from eval.model_config import configure_eval_model
        with patch.dict("os.environ",{"EVAL_LLM_PROVIDER":"gemini","EVAL_LLM_MODEL":"gemini-3.6-flash"},clear=True):
            config = configure_eval_model("groq")
            self.assertEqual((config.provider,config.model),("groq","openai/gpt-oss-20b"))

    def test_eval_override_is_exported_for_child_runners(self):
        from eval.model_config import configure_eval_model
        with patch.dict("os.environ",{"EVAL_LLM_PROVIDER":"gemini","EVAL_LLM_MODEL":"gemini-custom"},clear=True):
            config = configure_eval_model(request_interval=0.5)
            import os
            self.assertEqual(config.model,"gemini-custom")
            self.assertEqual(os.environ["EVAL_LLM_MODEL"],"gemini-custom")
            self.assertEqual(float(os.environ["EVAL_REQUEST_INTERVAL_SECONDS"]),0.5)

    def test_gemini_36_omits_unsupported_temperature_and_groq_limiter(self):
        from eval.model_config import configure_eval_model
        from telesale_agent.adapters.llm.model_factory import create_chat_model
        constructor = Mock(return_value="gemini-model")
        with patch.dict("os.environ",{"GOOGLE_API_KEY":"test-key"},clear=True), patch.dict(
                "sys.modules",{"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            configure_eval_model()
            self.assertEqual(create_chat_model(temperature=0.3),"gemini-model")
        kwargs = constructor.call_args.kwargs
        self.assertEqual(kwargs["model"],"gemini-3.6-flash")
        self.assertNotIn("temperature",kwargs)
        self.assertIsNone(kwargs["rate_limiter"])

    def test_gpt_oss_uses_native_json_schema(self):
        from telesale_agent.adapters.llm.model_factory import structured_output
        class FakeModel:
            model_name = "openai/gpt-oss-20b"
            with_structured_output = Mock(return_value="structured")
        FakeModel.__module__ = "langchain_groq.chat_models"
        model = FakeModel()
        self.assertEqual(structured_output(model,dict),"structured")
        model.with_structured_output.assert_called_once_with(dict,method="json_schema",strict=False)

    def test_benchmark_limiter_is_shared_across_models(self):
        from telesale_agent.adapters.llm.model_factory import _benchmark_rate_limiter
        with patch.dict("os.environ",{"EVAL_REQUEST_INTERVAL_SECONDS":"17"}):
            self.assertIs(_benchmark_rate_limiter(),_benchmark_rate_limiter())


class NLUThinkingTests(unittest.TestCase):
    def gemini_constructor(self):
        return Mock(side_effect=lambda **kwargs: SimpleNamespace(
            options=kwargs, with_structured_output=Mock(return_value="structured")))

    def test_nlu_override_does_not_change_agent_or_persister_thinking(self):
        import os
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        from telesale_agent.adapters.llm.model_factory import create_chat_model
        constructor = self.gemini_constructor()
        with patch.dict(os.environ, {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                "GOOGLE_API_KEY":"test-key", "LLM_THINKING_LEVEL":"high",
                "NLU_THINKING_LEVEL":"minimal"}, clear=True), patch.dict(sys.modules,
                {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            nlu = LLMPerceiver()
            agent = create_chat_model(temperature=0)
            persister = create_chat_model(temperature=0)
            self.assertEqual(nlu.llm.options["thinking_level"], "minimal")
            self.assertEqual(agent.options["thinking_level"], "high")
            self.assertEqual(persister.options["thinking_level"], "high")
            self.assertEqual(os.environ["LLM_THINKING_LEVEL"], "high")

    def test_unset_nlu_thinking_preserves_shared_or_provider_default(self):
        import os
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        constructor = self.gemini_constructor()
        for shared in (None, "low"):
            env = {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash", "GOOGLE_API_KEY":"test-key"}
            if shared:
                env["LLM_THINKING_LEVEL"] = shared
            with self.subTest(shared=shared), patch.dict(os.environ, env, clear=True), patch.dict(
                    sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
                self.assertEqual(LLMPerceiver().llm.options.get("thinking_level"), shared)

    def test_explicit_nlu_level_overrides_nlu_environment(self):
        import os
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        constructor = self.gemini_constructor()
        with patch.dict(os.environ, {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                "GOOGLE_API_KEY":"test-key", "NLU_THINKING_LEVEL":"minimal"}, clear=True), patch.dict(
                sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            self.assertEqual(LLMPerceiver(thinking_level=" LOW ").llm.options["thinking_level"], "low")

    def test_invalid_nlu_level_fails_before_constructing_model(self):
        import os
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        constructor = self.gemini_constructor()
        with patch.dict(os.environ, {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                "GOOGLE_API_KEY":"test-key", "NLU_THINKING_LEVEL":"minimall"}, clear=True), patch.dict(
                sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            with self.assertRaisesRegex(ValueError, "thinking level"):
                LLMPerceiver()
            constructor.assert_not_called()


class DeepAgentThinkingTests(unittest.TestCase):
    def gemini_constructor(self):
        return Mock(side_effect=lambda **kwargs: SimpleNamespace(
            options=kwargs, with_structured_output=Mock(return_value="structured")))

    def test_agent_and_nlu_overrides_leave_actual_persister_on_shared_level(self):
        import os
        from telesale_agent.application.deepagent.runtime import create_deepagent_model
        from telesale_agent.adapters.llm.llm_perceive import LLMPerceiver
        from telesale_agent.adapters.llm.llm_persist import LLMPersister
        constructor = self.gemini_constructor()
        with patch.dict(os.environ, {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                "GOOGLE_API_KEY":"test-key", "LLM_THINKING_LEVEL":"high",
                "NLU_THINKING_LEVEL":"minimal", "DEEPAGENT_THINKING_LEVEL":" MINIMAL "}, clear=True), patch.dict(
                sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            self.assertEqual(create_deepagent_model().options["thinking_level"], "minimal")
            self.assertEqual(LLMPerceiver().llm.options["thinking_level"], "minimal")
            self.assertEqual(LLMPersister(object()).llm.options["thinking_level"], "high")
            self.assertEqual(os.environ["LLM_THINKING_LEVEL"], "high")

    def test_unset_agent_level_inherits_shared_setting_not_nlu(self):
        import os
        from telesale_agent.application.deepagent.runtime import create_deepagent_model
        constructor = self.gemini_constructor()
        for shared in (None, "low"):
            env = {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                   "GOOGLE_API_KEY":"test-key", "NLU_THINKING_LEVEL":"minimal"}
            if shared:
                env["LLM_THINKING_LEVEL"] = shared
            with self.subTest(shared=shared), patch.dict(os.environ, env, clear=True), patch.dict(
                    sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
                self.assertEqual(create_deepagent_model().options.get("thinking_level"), shared)

    def test_invalid_agent_level_is_rejected_before_model_construction(self):
        import os
        from telesale_agent.application.deepagent.runtime import create_deepagent_model
        constructor = self.gemini_constructor()
        with patch.dict(os.environ, {"LLM_PROVIDER":"gemini", "LLM_MODEL":"gemini-3.6-flash",
                "GOOGLE_API_KEY":"test-key", "DEEPAGENT_THINKING_LEVEL":"minimall"}, clear=True), patch.dict(
                sys.modules, {"langchain_google_genai":SimpleNamespace(ChatGoogleGenerativeAI=constructor)}):
            with self.assertRaisesRegex(ValueError, "thinking level"):
                create_deepagent_model()
            constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
