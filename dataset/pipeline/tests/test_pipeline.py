import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dataset.pipeline.checks import validate_schema, validate_transcript
from dataset.pipeline.common import file_hash, files_manifest, read, write
from dataset.pipeline.duplicates import DuplicateIndex
from dataset.pipeline.providers import OpenAIProvider, ProviderFailure, ReplayProvider
from dataset.pipeline.runner import duplicate_check, generate_run, plan_run, verify_plan, verify_run
from dataset.pipeline.providers import Recorder, RoutedProvider
from dataset.pipeline.review import CRITERIA, validate_review


def fixture(root: Path, customers=1) -> Path:
    write(root / "domain/catalog.json", {"reference_date": "2026-10-15", "products": [
        {"sku": "TEST-A", "name": "Máy lọc Mẫu An", "category": "gia-dung", "price_vnd": 123000, "stock": 10}]})
    config = {"version": 1, "domain": {"kind": "json", "root": "domain", "policies": []},
              "planning": {"seed": 17, "start_date": "2026-10-15", "customers": customers,
                           "multichannel_customers": 0, "personas": ["hesitant"], "hard_cases": []},
              "generation": {"model": "fake", "max_output_tokens": 1000, "max_attempts": 3, "max_api_calls": 30},
              "review": {"model": "SAME_AS_GENERATOR", "max_output_tokens": 2000},
              "duplicates": {"review_threshold": 0.999999, "reject_threshold": 1, "judge_ambiguous": True},
              "validation": {"min_turns": 4, "max_turns": 12, "min_words": 8},
              "requirements": {"transcripts": customers * 2, "two_hotline_customers": customers,
                               "catalog_skus": 1, "required_personas": ["hesitant"]}}
    write(root / "config.json", config)
    return root / "config.json"


def candidate(session, flavor=""):
    product = session["facts"]["product"]["name"]
    price = session["facts"]["price_vnd"]
    # Mock language is only test data; it is never presented as LLM/human-reviewed output.
    return {"transcript_id": session["transcript_id"], "customer_id": session["customer_id"],
            "session_index": session["session_index"], "channel": session["channel"],
            "outcome": session["expected_outcome"], "utterances": [
                {"speaker": "customer", "text": f"Chị muốn hỏi thêm về {product}, em tư vấn nhé. {flavor}"},
                {"speaker": "agent", "text": f"Dạ giá hiện tại là {price} đồng, em kiểm tra đúng thông tin mình cần."},
                {"speaker": "customer", "text": "Để chị hỏi người nhà trước, chị chưa muốn đặt hàng ngay."},
                {"speaker": "agent", "text": "Dạ chị cứ trao đổi thêm, khi quay lại em sẽ tiếp tục nhu cầu vừa nói."}]}


def response(value):
    return {"text": json.dumps(value, ensure_ascii=False), "raw": {"test_only": True},
            "completed": True, "metadata": {"model": "fake-offline"}}


def passing_review(payload):
    transcripts = payload["transcripts"]
    evidence = [{"transcript_id": t["transcript_id"], "turn_index": 0,
                 "quote": t["utterances"][0]["text"]} for t in transcripts]
    return {"journey_id": payload["journey_plan"]["journey_id"], "checks": [
        {"criterion": key, "verdict": "pass", "reason": "Fake-provider test assertion only.",
         "evidence": evidence if key == "continuity" else evidence[:1]}
        for key in sorted(CRITERIA)]}


class FakeProvider:
    metadata = {"provider": "test_only", "model": "fake-offline"}

    def __init__(self):
        self.requests = []

    def request(self, req):
        self.requests.append(req)
        payload = json.loads(req["messages"][1]["content"])
        if req["kind"] == "duplicate":
            return response({"duplicate": False, "reason": "Chỉ cùng dữ kiện, cách triển khai khác."})
        if req["kind"] == "quality_review":
            return response(passing_review(payload))
        s = payload["session_plan"]
        # Distinct words per session exercise index commit without numeral-only variants.
        flavor = "ưu tiên phòng khách" if s["session_index"] == 1 else "tiếp tục cuộc trao đổi trước và quyết định gia đình"
        return response(candidate(s, flavor))


class PipelineTests(unittest.TestCase):
    def test_balanced_plan_covers_persona_category_pairs_without_mutating_default(self):
        from dataset.pipeline.common import HERE
        from dataset.pipeline.domain import load_domain
        from dataset.pipeline.planner import build_plans
        config = read(HERE / "configs/hackathon_m1.json")
        config["planning"].update(customers=150, multichannel_customers=60, coverage_strategy="balanced")
        domain = load_domain((HERE / "configs" / config["domain"]["root"]).resolve(), config["domain"])
        plans = build_plans(config, domain)
        pairs = {(p["persona"], p["sessions"][0]["facts"]["product"]["category"].split("/")[0]) for p in plans}
        for persona in ("hesitant", "price_comparison"):
            self.assertEqual(len([pair for pair in pairs if pair[0] == persona]), 3)
            hard = {p["sessions"][0]["hard_case"] for p in plans if p["persona"] == persona}
            self.assertTrue(set(config["planning"]["hard_cases"]) <= hard)
        self.assertEqual(len(plans), 150)
        self.assertEqual(sum(len(p["sessions"]) for p in plans), 360)
        self.assertEqual(plans, build_plans(config, domain))
        self.assertEqual(read(HERE / "configs/hackathon_m1.json")["planning"]["customers"], 50)

    def test_plan_reproduces_without_any_m1_scenario_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = fixture(root)
            plan_run(cfg, root / "a")
            plan_run(cfg, root / "b")
            self.assertEqual(read(root / "a/plans.json"), read(root / "b/plans.json"))
            self.assertEqual(files_manifest(root / "a/snapshot"), files_manifest(root / "b/snapshot"))
            verify_plan(root / "a")
            self.assertFalse((root / "scenarios_prefilled").exists())

    def test_frozen_snapshot_survives_original_source_edits_but_detects_snapshot_tamper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_run(fixture(root), root / "plan")
            original = root / "domain/catalog.json"
            data = read(original); data["products"][0]["price_vnd"] = 999999
            write(original, data)
            _, plans, _ = verify_plan(root / "plan")
            self.assertEqual(plans[0]["sessions"][0]["facts"]["price_vnd"], 123000)
            write(root / "plan/snapshot/domain/catalog.json", data)
            with self.assertRaisesRegex(ValueError, "checksums changed"):
                verify_plan(root / "plan")

    def test_checks_reject_identity_wrong_price_missing_fact_and_fake_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan_run(fixture(root), root / "plan")
            config, plans, _ = verify_plan(root / "plan")
            s = plans[0]["sessions"][0]; good = candidate(s)
            self.assertEqual(validate_transcript(good, s, [], config["validation"]), [])
            for change in ("identity", "price", "product", "order"):
                bad = copy.deepcopy(good)
                if change == "identity": bad["customer_id"] = "OTHER"
                if change == "price": bad["utterances"][1]["text"] = "Giá 999999 đồng."
                if change == "product": bad["utterances"][0]["text"] = "Chị cần hàng."
                if change == "order": bad["utterances"][1]["text"] += " Em đã tạo đơn."
                self.assertTrue(validate_transcript(bad, s, [], config["validation"]), change)

    def test_entity_and_number_only_copies_are_duplicates(self):
        a = {"transcript_id": "A", "utterances": [{"speaker": "customer", "text": "Chị cần Mẫu An giá 123000 đồng."}]}
        b = {"transcript_id": "B", "utterances": [{"speaker": "customer", "text": "Chị cần Mẫu Bình giá 456000 đồng."}]}
        index = DuplicateIndex(); index.add(a, ["Mẫu An"], "existing")
        result = index.compare(b, ["Mẫu Bình"], {"review_threshold": .7, "reject_threshold": .9})
        self.assertEqual(result["decision"], "reject")
        self.assertTrue(result["matches"][0]["exact"])

    def test_iterative_duplicate_rejection_regenerates_with_feedback(self):
        class RetryProvider(FakeProvider):
            def __init__(self): super().__init__(); self.calls = 0
            def request(self, req):
                self.calls += 1
                result = super().request(req)
                if self.calls == 1:
                    payload = json.loads(req["messages"][1]["content"])
                    return response(candidate(payload["session_plan"], "duplicated opening"))
                return result
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cfg = fixture(root)
            plan_run(cfg, root / "initial")
            _, plans, _ = verify_plan(root / "initial")
            write(root / "refs/existing.json", candidate(plans[0]["sessions"][0], "duplicated opening"))
            plan_run(cfg, root / "plan", [root / "refs"])
            provider = RetryProvider()
            result = generate_run(root / "plan", root / "run", provider)
            self.assertEqual(result["exported_transcripts"], 2)
            self.assertEqual(result["model_calls"], 4)
            feedback = json.loads(provider.requests[1]["messages"][1]["content"])["validation_feedback"]
            self.assertIn("duplicate:", feedback[0])
            self.assertTrue(read(root / "run/duplicate_report.json")["attempts"][0]["errors"])

    def test_failed_journey_does_not_publish_partial_sessions_and_retries_are_bounded(self):
        class Failing(FakeProvider):
            def request(self, req):
                value = super().request(req)
                t = json.loads(value["text"])
                if t["session_index"] == 2:
                    t["customer_id"] = "wrong"
                return response(t)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            p = Failing(); report = generate_run(root / "plan", root / "run", p)
            self.assertEqual(report["status"], "quarantined")
            self.assertEqual(report["model_calls"], 6)
            self.assertEqual(read(root / "run/manifest.json"), [])
            self.assertFalse((root / "run/transcripts").exists())

    def test_replay_produces_byte_identical_transcripts_without_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            original = generate_run(root / "plan", root / "run", FakeProvider())
            replay = generate_run(root / "run/plan", root / "replay", ReplayProvider(root / "run"))
            self.assertEqual(original["exported_transcripts"], replay["exported_transcripts"])
            self.assertEqual(read(root / "run/manifest.json"), read(root / "replay/manifest.json"))
            for p in (root / "run/transcripts").glob("*.json"):
                self.assertEqual(file_hash(p), file_hash(root / "replay/transcripts" / p.name))
                artifact = read(p)
                schema = read(Path(__file__).resolve().parents[1] / "transcript.schema.json")
                self.assertEqual(set(artifact), set(schema["required"]))
            self.assertTrue((root / "run/DATASET_CARD.md").is_file())

    def test_automatic_review_approves_without_manual_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            result = generate_run(root / "plan", root / "run", FakeProvider())
            self.assertEqual(result["status"], "automated_release")
            self.assertEqual(result["model_calls"], 3)
            self.assertFalse((root / "run/review_template.json").exists())
            for row in read(root / "run/manifest.json"):
                artifact = read(root / "run" / row["path"])
                self.assertEqual(artifact["review_status"], "automated_approved")
                self.assertEqual(artifact["provenance"]["automated_review_sha256"], file_hash(root / "run" / row["review_path"]))
            self.assertEqual(verify_run(root / "run")["transcripts"], 2)

    def test_automatic_review_failure_regenerates_before_export(self):
        class ReviewOnceFails(FakeProvider):
            failed = False
            def request(self, req):
                value = super().request(req)
                if req["kind"] == "quality_review" and not self.failed:
                    self.failed = True
                    data = json.loads(value["text"])
                    data["checks"][0].update(verdict="fail", reason="Lời thoại chưa tự nhiên, cần sửa cách diễn đạt.")
                    return response(data)
                return value
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            provider = ReviewOnceFails()
            result = generate_run(root / "plan", root / "run", provider)
            self.assertEqual(result["status"], "automated_release")
            self.assertEqual(result["model_calls"], 6)
            self.assertEqual(read(root / "run/reviews/J0001/attempt_01.json")["status"], "rejected")
            self.assertEqual(read(root / "run/reviews/J0001/attempt_02.json")["status"], "automated_approved")
            self.assertIn("review:", json.loads(provider.requests[3]["messages"][1]["content"])["validation_feedback"][0])
            self.assertEqual(verify_run(root / "run")["transcripts"], 2)

    def test_uncertain_or_fabricated_review_evidence_is_never_approved(self):
        class Uncertain(FakeProvider):
            def request(self, req):
                value = super().request(req)
                if req["kind"] == "quality_review":
                    data = json.loads(value["text"])
                    data["checks"][0].update(verdict="uncertain", reason="Chưa đủ chứng cứ.")
                    return response(data)
                return value
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            result = generate_run(root / "plan", root / "run", Uncertain())
            self.assertEqual(result["status"], "quarantined")
            self.assertEqual(result["model_calls"], 9)
            self.assertFalse((root / "run/transcripts").exists())
            cfg, plans, _ = verify_plan(root / "plan")
            turns = [candidate(s) for s in plans[0]["sessions"]]
            decision = passing_review({"journey_plan": plans[0], "transcripts": turns})
            decision["checks"][0]["evidence"][0]["quote"] = "invented quotation"
            self.assertTrue(validate_review(decision, "J0001", turns))
            decision = passing_review({"journey_plan": plans[0], "transcripts": turns})
            decision["checks"].pop()
            self.assertTrue(validate_review(decision, "J0001", turns))

    def test_export_schema_rejects_wrong_nested_types_and_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            generate_run(root / "plan", root / "run", FakeProvider())
            path = next((root / "run/transcripts").glob("*.json"))
            artifact = read(path)
            schema = read(root / "run/schemas/transcript.schema.json")
            self.assertEqual(validate_schema(artifact, schema), [])
            for kind in ("speaker", "boolean", "date", "extra", "review_status"):
                bad = copy.deepcopy(artifact)
                if kind == "speaker": bad["utterances"][0]["speaker"] = ["customer"]
                if kind == "boolean": bad["is_actual_agent_trace"] = 0
                if kind == "date": bad["date"] = "2026-02-30"
                if kind == "extra": bad["unexpected"] = True
                if kind == "review_status": bad["review_status"] = "human_approved"
                self.assertTrue(validate_schema(bad, schema), kind)

    def test_verify_checks_format_and_session_links_beyond_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            for kind in ("schema", "link"):
                out = root / kind
                generate_run(root / "plan", out, FakeProvider())
                manifest = read(out / "manifest.json")
                row = manifest[-1]
                path = out / row["path"]
                artifact = read(path)
                if kind == "schema":
                    artifact["utterances"][0]["text"] = ["invalid nested type"]
                else:
                    artifact["previous_transcript_id"] = "wrong-session"
                write(path, artifact)
                row["sha256"] = file_hash(path)
                write(out / "manifest.json", manifest)
                write(out / "seal.json", {"files": files_manifest(out)})
                with self.assertRaisesRegex(ValueError, "schema:" if kind == "schema" else "session linkage"):
                    verify_run(out)

    def test_generation_and_review_can_use_separate_clients(self):
        class Backend:
            def __init__(self, name):
                self.metadata = {"model": name}
                self.calls = []
            def request(self, req):
                self.calls.append(req["kind"])
                return {"backend": self.metadata["model"]}
        gen, reviewer = Backend("generation-model"), Backend("review-model")
        routed = RoutedProvider(gen, reviewer)
        self.assertEqual(routed.request({"kind": "generate"})["backend"], "generation-model")
        self.assertEqual(routed.request({"kind": "quality_review"})["backend"], "review-model")
        self.assertEqual(routed.request({"kind": "duplicate"})["backend"], "review-model")
        self.assertEqual(gen.calls, ["generate"])
        self.assertEqual(reviewer.calls, ["quality_review", "duplicate"])

    def test_provider_incomplete_response_and_call_budget_never_silently_pass(self):
        class Incomplete(FakeProvider):
            def request(self, req): return {"text": "{}", "raw": {}, "completed": False, "metadata": {}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cfg = fixture(root)
            data = read(cfg); data["generation"]["max_api_calls"] = 1; write(cfg, data)
            plan_run(cfg, root / "plan")
            result = generate_run(root / "plan", root / "run", Incomplete())
            self.assertEqual(result["status"], "provider_stopped")
            self.assertEqual(result["exported_transcripts"], 0)
            self.assertEqual(result["model_calls"], 1)

    def test_openai_adapter_sends_strict_schema_and_handles_refusals(self):
        class Responses:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(output_text="", status="completed", id="test-id", model="test-model",
                                       model_dump=lambda **kw: {"output": [{"type": "refusal"}], "usage": None})
        responses = Responses()
        adapter = OpenAIProvider("test-model", 123, client=SimpleNamespace(responses=responses))
        value = adapter.request({"messages": [{"role": "user", "content": "test"}], "schema": {"type": "object"}, "schema_name": "test"})
        self.assertFalse(value["completed"])
        self.assertTrue(responses.kwargs["text"]["format"]["strict"])
        self.assertFalse(responses.kwargs["store"])
        self.assertEqual(responses.kwargs["max_output_tokens"], 123)

    def test_ambiguous_duplicates_use_judge_and_fail_closed_on_invalid_judgment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            _, plans, _ = verify_plan(root / "plan")
            s = plans[0]["sessions"][0]
            old, new = candidate(s, "phòng ngủ"), candidate(s, "phòng khách thoáng và sáng")
            index = DuplicateIndex(); index.add(old, [s["facts"]["product"]["name"]], "reference")
            score = index.compare(new, [s["facts"]["product"]["name"]], {"review_threshold": 0, "reject_threshold": 1})["matches"][0]["score"]
            self.assertTrue(0 < score < 1)
            config = {"review_threshold": score - .01, "reject_threshold": min(1, score + .01), "judge_ambiguous": True}
            # Use the same entity set as production comparison.
            p = FakeProvider(); recorder = Recorder(p, root / "calls-ok", 2)
            errors, report = duplicate_check(new, s, index, config, recorder)
            self.assertEqual(errors, [])
            self.assertEqual(p.requests[0]["kind"], "duplicate")
            class BadJudge(FakeProvider):
                def request(self, req): return response({"duplicate": "false", "reason": "invalid type"})
            errors, _ = duplicate_check(new, s, index, config, Recorder(BadJudge(), root / "bad", 2))
            self.assertTrue(errors)

    def test_provider_failure_stops_without_retrying_auth_or_inventing_output(self):
        class AuthFailure(FakeProvider):
            def request(self, req): raise ProviderFailure("test authorization failure")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            report = generate_run(root / "plan", root / "run", AuthFailure())
            self.assertEqual(report["status"], "provider_stopped")
            self.assertEqual(report["model_calls"], 1)
            self.assertEqual(read(root / "run/manifest.json"), [])

    def test_modified_archived_request_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            generate_run(root / "plan", root / "run", FakeProvider())
            call = root / "run/calls/000001.json"
            data = read(call); data["request"]["messages"][0]["content"] = "changed prompt"; write(call, data)
            report = generate_run(root / "run/plan", root / "replay", ReplayProvider(root / "run"))
            self.assertEqual(report["status"], "provider_stopped")
            self.assertEqual(report["exported_transcripts"], 0)

    def test_btc_profiles_plan_without_loading_m1_scenario_directories(self):
        folder = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            for name in ("hackathon_m1", "hackathon_m2"):
                root = Path(temp) / name
                report = plan_run(folder / "configs" / f"{name}.json", root)
                self.assertTrue(report["transcript_requirements_met"])
                self.assertEqual(report["scope"], "planned coverage; no transcripts generated")
                _, plans, _ = verify_plan(root)
                self.assertTrue(plans)
                self.assertFalse(any("scenarios_prefilled" in str(p) or "scenarios_complete" in str(p) for p in (root / "snapshot").rglob("*")))

    def test_changed_pipeline_code_invalidates_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); plan_run(fixture(root), root / "plan")
            with patch("dataset.pipeline.runner.code_hashes", return_value={"changed": "code"}):
                with self.assertRaisesRegex(ValueError, "code/prompts/schema changed"):
                    verify_plan(root / "plan")


if __name__ == "__main__":
    unittest.main()
