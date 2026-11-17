"""Meaningful guard checks without credentials, dependencies or model calls."""
import argparse
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import naturalize_transcripts as pipeline


def echo(request):
    return {"scenario_id": request["scenario_id"], "sessions": [
        {"transcript_id": s["transcript_id"], "utterances": [
            {"speaker": u["speaker"], "text": u["text"]} for u in s["utterances"]]}
        for s in request["sessions"]]}


def arguments(output, **kwargs):
    args = argparse.Namespace(output=output, scenario=["SC-121"], generate=False,
                              responses=None, provider=None, model=None,
                              temperature=0.5, max_output_tokens=8192, thinking_level=None)
    for key, value in kwargs.items():
        setattr(args, key, value)
    return args


class NaturalizeTests(unittest.TestCase):
    def test_original_dialogue_is_preserved_in_requests_and_candidates(self):
        request, protected, scenario, transcripts = pipeline.prepare("SC-241")
        serialized = json.dumps(request, ensure_ascii=False)
        self.assertIn(scenario["customer_phone"], serialized)
        self.assertIn(scenario["customer_name"], serialized)
        address = scenario["calls"]["call_1"]["facts_established"]["delivery_address"]
        self.assertIn(address, serialized)
        _, restored = pipeline.materialize(request, echo(request), protected, scenario, transcripts)
        for a, b in zip(restored, transcripts):
            self.assertEqual(a["utterances"], b["utterances"])

    def test_changed_price_and_product_are_rejected_without_masking(self):
        request, protected, _, _ = pipeline.prepare("SC-121")
        source = request["sessions"][0]["utterances"][1]["text"]
        price = pipeline.NUMBER.findall(source)[0]
        for text in (source + " Giá mới 1 đồng.", source.replace(price, "", 1),
                     source.replace("AirPure X", "AirPure Y")):
            response = echo(request)
            response["sessions"][0]["utterances"][1]["text"] = text
            self.assertTrue(pipeline.validate_response(request, response, protected))

    def test_numeric_order_is_preserved_without_tokenization(self):
        request, protected, _, _ = pipeline.prepare("SC-121")
        response = echo(request)
        for original, rewritten in zip(request["sessions"], response["sessions"]):
            for old, new in zip(original["utterances"], rewritten["utterances"]):
                numbers = pipeline.NUMBER.findall(old["text"])
                if len(numbers) >= 2 and numbers[0] != numbers[1]:
                    new["text"] = old["text"].replace(numbers[0], "TEMP_VALUE", 1).replace(numbers[1], numbers[0], 1).replace("TEMP_VALUE", numbers[1])
                    self.assertTrue(pipeline.validate_response(request, response, protected))
                    return
        self.fail("no utterance with two distinct numeric values found")

    def test_turn_structure_metadata_and_session_order_cannot_be_changed(self):
        request, protected, _, _ = pipeline.prepare("SC-121")
        response = echo(request)
        response["sessions"].reverse()
        self.assertTrue(pipeline.validate_response(request, response, protected))
        response = echo(request)
        response["sessions"][0]["utterances"].pop()
        self.assertTrue(pipeline.validate_response(request, response, protected))
        response = echo(request)
        response["sessions"][0]["utterances"][0]["speaker"] = "agent"
        self.assertTrue(pipeline.validate_response(request, response, protected))
        response = echo(request)
        response["sessions"][0]["utterances"][0]["tool_refs"] = [0]
        self.assertTrue(pipeline.validate_response(request, response, protected))

    def test_noisy_customer_turns_are_frozen(self):
        sid = next(p.stem for p in sorted((pipeline.HERE / "scenarios_complete").glob("*.json"))
                   if any("customer_turns_asr" in c for c in pipeline.read(p)["calls"].values()))
        request, protected, _, _ = pipeline.prepare(sid)
        response = echo(request)
        for s, r in zip(request["sessions"], response["sessions"]):
            for old, new in zip(s["utterances"], r["utterances"]):
                if old["locked"]:
                    new["text"] += " nhé"
                    self.assertTrue(pipeline.validate_response(request, response, protected))
                    return
        self.fail("no locked noisy input found")

    def test_business_checks_reject_failed_order_even_with_unchanged_dialogue(self):
        request, protected, scenario, transcripts = pipeline.prepare("SC-241")
        scenario, candidates = pipeline.materialize(request, echo(request), protected, scenario, transcripts)
        self.assertEqual(pipeline.check_business(scenario, candidates), [])
        altered = copy.deepcopy(candidates)
        order = next(tc for t in altered for tc in t["private_annotations"]["reference_tool_executions"]
                     if tc["name"] == "order.create")
        order["result"] = {"error": "price_mismatch"}
        self.assertTrue(pipeline.check_business(scenario, altered))

    def test_prepare_is_offline_and_archives_exact_original_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "prepared"
            with patch.object(pipeline, "model_client", side_effect=AssertionError("unexpected model call")), redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.run(arguments(output)), 0)
            metadata = pipeline.read(output / "run.json")
            self.assertEqual(metadata["status"], "prepared")
            self.assertIsNone(metadata["model"])
            self.assertEqual(metadata["input_text_handling"], "original_dialogue_without_masking")
            self.assertFalse((output / "private_token_maps").exists())
            messages = pipeline.read(output / "messages/SC-121.json")
            self.assertEqual(json.loads(messages[1]["content"]), pipeline.read(output / "requests/SC-121.json"))
            self.assertEqual(messages[0]["content"], (output / "system_prompt.md").read_text())
            with self.assertRaises(FileExistsError), redirect_stdout(io.StringIO()):
                pipeline.run(arguments(output))

    def test_offline_replay_is_repeatable_and_does_not_modify_baseline(self):
        request, _, _, transcripts = pipeline.prepare("SC-121")
        original_hashes = {t["transcript_id"]: pipeline.digest(pipeline.HERE / "conversations" / f"{t['transcript_id']}.json") for t in transcripts}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            responses = root / "external_responses"
            response = echo(request)
            response["sessions"][0]["utterances"][1]["text"] = "Vâng, " + response["sessions"][0]["utterances"][1]["text"]
            pipeline.write(responses / "SC-121.json", response)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.run(arguments(root / "first", responses=responses)), 0)
                self.assertEqual(pipeline.run(arguments(root / "second", responses=root / "first/raw_responses")), 0)
            for tid, original in original_hashes.items():
                self.assertEqual(pipeline.digest(pipeline.HERE / "conversations" / f"{tid}.json"), original)
                self.assertEqual(pipeline.read(root / f"first/candidates/conversations/{tid}.json"),
                                 pipeline.read(root / f"second/candidates/conversations/{tid}.json"))
            report = pipeline.read(root / "second/validation_report.json")
            self.assertEqual(report["status"], "candidate_pending_human_review")
            self.assertEqual(pipeline.read(root / "second/run.json")["response_source"]["status"], "archived_inputs_verified")
            # A changed prompt invalidates the claim of identical replay.
            pipeline.write(root / "first/messages/SC-121.json", [])
            with self.assertRaisesRegex(ValueError, "archived prompt differs"), redirect_stdout(io.StringIO()):
                pipeline.run(arguments(root / "third", responses=root / "first/raw_responses"))

    def test_invalid_response_is_archived_but_never_published_as_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "responses").mkdir()
            (root / "responses/SC-121.json").write_text("not JSON")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.run(arguments(root / "run", responses=root / "responses")), 2)
            self.assertEqual((root / "run/raw_responses/SC-121.json").read_text(), "not JSON")
            self.assertFalse((root / "run/candidates").exists())
            self.assertEqual(pipeline.read(root / "run/validation_report.json")["status"], "rejected")

    def test_live_adapter_archives_messages_and_rejects_provider_fact_changes(self):
        class FakeMessage:
            response_metadata = {"model_name": "fake-test-model"}
            usage_metadata = {"input_tokens": 1, "output_tokens": 1}

            def __init__(self, text):
                self.content = [{"type": "text", "text": text}]

        class FakeClient:
            def invoke(self, messages):
                self.messages = messages
                response = echo(json.loads(messages[1][1]))
                response["sessions"][0]["utterances"][1]["text"] += " Giá 999 đồng."
                return FakeMessage(json.dumps(response, ensure_ascii=False))

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "run"
            client = FakeClient()
            with patch.object(pipeline, "model_client", return_value=(client, {"requested_model": "fake-test-model"})), redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.run(arguments(output, generate=True)), 2)
            messages = pipeline.read(output / "messages/SC-121.json")
            self.assertEqual(client.messages, [("system", messages[0]["content"]), ("human", messages[1]["content"])])
            self.assertEqual(pipeline.read(output / "run.json")["model"]["requested_model"], "fake-test-model")
            self.assertTrue((output / "raw_responses/SC-121.json").is_file())
            self.assertFalse((output / "candidates").exists())


if __name__ == "__main__":
    unittest.main()
