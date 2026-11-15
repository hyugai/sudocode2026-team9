"""Regression checks for real benchmark coverage, metrics and timing."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eval.benchmark_support import (validate_inputs,trace_health,measured_latency,compare_metrics)
from eval.team_eval import evaluate_team,REFERENCE,rag_recall
from eval.trace_extractors import extract_claims,extract_questions

PRICING = {k:None for k in ("input_per_million","output_per_million","tool_call","memory_write","storage_per_mb","fixed_call")}


def fixture():
    scenarios = {"SC-001":{"scenario_id":"SC-001","calls":{"call_1":{"customer_turns":["xin chào"],
        "success_if":{"tool_called":"order.create","args_match":{"sku":"X"}},"ground_truth_facts":{"price_vnd":1000000}}}}}
    row = {"scenario_id":"SC-001","call":"call_1","turn":1,"agent_text":"Giá là 1.000.000 đồng.",
           "tool_calls":[{"name":"order.create","args":{"sku":"X"},"result":{"order_id":"test"}}],
           "claims":[{"field":"price_vnd","value":1000000}],"latency":{"ttft_ms":10,"total_ms":10,"ttfa_ms":None,"measurement_mode":"non_streaming"}}
    return scenarios,{("SC-001","call_1"):[row]}


class CoverageTests(unittest.TestCase):
    def test_complete_trace_is_valid(self):
        self.assertTrue(trace_health(*fixture())["valid"])

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


class MetricTests(unittest.TestCase):
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
        self.assertIn({"field":"price_vnd","value":2000000},claims)
        scenarios,trace = fixture()
        trace[("SC-001","call_1")][0]["claims"] = claims
        report = evaluate_team(scenarios,trace,pricing=PRICING)
        self.assertEqual(report["hallucination_rate"]["price_only"]["value"],100)

    def test_question_does_not_inherit_preceding_product_statement(self):
        question = extract_questions("Sản phẩm này giá 1.000.000 đồng. Chị muốn lên đơn không?")[0]
        self.assertEqual(question["slot"],"other")

    def test_missing_rag_results_are_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa.json").write_text(json.dumps({"questions":[{"qid":"a","relevant_chunk_ids":["A"]},{"qid":"b","relevant_chunk_ids":["B"]}]}))
            (root / "results.json").write_text(json.dumps({"a":{"retrieved_chunk_ids":["A"]}}))
            self.assertEqual(rag_recall(root / "qa.json",root / "results.json")["recall@3"],50)

    def test_gates_use_relative_rqr_and_price_only(self):
        scenarios,trace = fixture()
        full = evaluate_team(scenarios,trace,pricing=PRICING)
        baseline = copy.deepcopy(full)
        full["repeat_question_rate"]["value"] = 20
        baseline["repeat_question_rate"]["value"] = 40
        self.assertEqual(compare_metrics(full,baseline)["status"],"pass")
        baseline["repeat_question_rate"]["value"] = 0
        self.assertEqual(compare_metrics(full,baseline)["status"],"inconclusive")
        baseline["trace_health"]["valid"] = False
        self.assertEqual(compare_metrics(full,baseline)["status"],"invalid")


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
