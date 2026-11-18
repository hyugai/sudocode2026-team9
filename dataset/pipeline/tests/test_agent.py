import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from dataset.pipeline import agent
from dataset.pipeline.common import read, write
from dataset.pipeline.tests.test_pipeline import FakeProvider, fixture, passing_review


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = fixture(self.root)
        self.run = self.root / "run"
        self.provider = FakeProvider()

    def initialize(self, **kwargs):
        # Avoid recursively running discovery from inside discovery.
        with patch.dict(agent.PROFILES, {"M1": self.config, "M2": self.config}), \
             patch.object(agent, "setup_checks", return_value={}), patch.dict(os.environ, {}, clear=True):
            return agent.initialize(kwargs.pop("profile", "M1"), self.run, archive=kwargs.pop("archive", True), generation_unit=kwargs.pop("generation_unit", "session"), **kwargs)

    def task(self, **kwargs):
        result = agent.next_task(self.run, **kwargs)
        return read(Path(result["task_file"])) if "task_file" in result else result

    def envelope(self, task, response=None):
        value = {key: task[key] for key in ("run_id", "task_id", "task_sha256")}
        value["response"] = json.loads(self.provider.request(task["request"])["text"]) if response is None else response
        path = self.root / "response.json"
        write(path, value)
        return path

    def complete(self):
        for _ in range(80):
            task = self.task(remaining=1_000_000, source="test fixture only")
            if "request" not in task:
                return task
            agent.submit(self.run, self.envelope(task))
        self.fail("unbounded task loop")

    def test_profile_is_required_and_immutable_across_resume(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            agent.main(["init", "--output", str(self.run)])
        self.assertFalse(self.run.exists())
        self.initialize(profile="M2")
        self.assertEqual(read(self.run / "settings.json")["profile"], "M2")
        task = agent.resume(self.run)
        self.assertEqual(task["profile"], "M2")
        settings = read(self.run / "settings.json"); settings["profile"] = "M1"
        write(self.run / "settings.json", settings)
        with self.assertRaisesRegex(ValueError, "settings changed"):
            agent.inspect(self.run)

    def test_no_key_model_or_sdk_is_required_for_generation_protocol(self):
        self.initialize()
        self.assertEqual(self.complete()["status"], "ready_to_finalize")
        result = agent.finalize(self.run)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["production_transcripts"], 2)
        self.assertEqual(result["api_calls"], 0)
        self.assertEqual(result["review_mode"], "same_agent_self_review")
        self.assertTrue(result["replay"]["byte_identical_transcripts_and_manifest"])
        agent.verify_release(self.run)
        before = read(self.run / "checkpoint.json")
        self.assertEqual(agent.resume(self.run)["status"], "completed")
        self.assertEqual(before, read(self.run / "checkpoint.json"))
        self.assertEqual(agent.finalize(self.run), result)

    def test_lightweight_skips_source_archive_and_replay_but_verifies_export(self):
        from dataset.pipeline.scenario_export import export, verify_export
        self.initialize(archive=False)
        self.assertFalse((self.run / "reproducibility").exists())
        task = self.task()
        agent.submit(self.run, self.envelope(task))
        agent.pause(self.run, "usage_limit")
        agent.resume(self.run, usage_restored=True)
        self.complete()
        with patch.object(agent, "generate_run", side_effect=AssertionError("unexpected replay")):
            result = agent.finalize(self.run)
        self.assertEqual(result["replay"]["status"], "skipped")
        self.assertEqual(agent.verify_release(self.run)["status"], "verified_automated_output")
        output = self.root / "export"
        export([self.run], output)
        provenance = read(output / "manifest.json")["sources"][0]["provenance"]
        self.assertEqual(provenance["archive_mode"], "lightweight")
        self.assertEqual(provenance["profile"], "M1")
        self.assertEqual(provenance["effective_config"]["planning"]["seed"], provenance["seed"])
        verify_export(output)
        transcript = next((self.run / "generation/transcripts").glob("*.json"))
        transcript.write_text("{}")
        with self.assertRaises(ValueError):
            agent.verify_release(self.run)

    def batch_response(self, task):
        payload = json.loads(task["request"]["messages"][1]["content"])
        history = []
        for session in payload["journey_plan"]["sessions"]:
            req = agent.engine.request("generate", {"session_plan": session, "previous_sessions": history,
                                       "validation_feedback": [], "limits": payload["limits"]}, {})
            history.append(json.loads(self.provider.request(req)["text"]))
        return {"transcripts": history}

    def test_journey_duplicate_judge_resumes_pending_sessions_after_checkpoint(self):
        self.initialize(archive=False, generation_unit="journey")
        task = self.task()
        body = self.batch_response(task)
        match = {"transcript_id": "reference", "reference": body["transcripts"][0], "source": "fixture", "score": 0.7, "exact": False}
        with patch.object(agent.engine.DuplicateIndex, "compare", return_value={"decision": "review", "matches": [match]}):
            agent.submit(self.run, self.envelope(task, body))
        state = read(self.run / "checkpoint.json")["state"]
        self.assertEqual(state["phase"], "duplicate")
        self.assertEqual(len(state["pending_candidates"]), 1)
        judge = self.task()
        self.assertEqual(judge["request"]["kind"], "duplicate")
        agent.submit(self.run, self.envelope(judge, {"duplicate": False, "reason": "Fixture judge accepts distinct wording."}))
        review = self.task()
        self.assertEqual(review["request"]["kind"], "quality_review")
        agent.submit(self.run, self.envelope(review))
        self.assertEqual(agent.finalize(self.run)["model_tasks_submitted"], 3)

    def test_late_session_failure_discards_the_whole_journey_attempt(self):
        self.initialize(archive=False, generation_unit="journey")
        task = self.task()
        body = self.batch_response(task)
        body["transcripts"][-1]["customer_id"] = "wrong"
        agent.submit(self.run, self.envelope(task, body))
        state = read(self.run / "checkpoint.json")["state"]
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["history"], [])
        self.assertEqual(state["pending_candidates"], [])
        self.assertEqual(state["accepted"], [])
        self.assertIn("identity", " ".join(state["feedback"]))

    def test_duplicate_feature_cache_reuses_features_and_invalidates_changed_inputs(self):
        from dataset.pipeline.duplicates import DuplicateIndex, normalized
        transcript = {"transcript_id": "T", "utterances": [{"speaker": "customer", "text": "Xin hỏi sản phẩm mẫu."}]}
        cache = {}
        with patch("dataset.pipeline.duplicates.normalized", wraps=normalized) as normalize:
            DuplicateIndex(cache).add(transcript, ["mẫu"], "accepted")
            DuplicateIndex(cache).add(transcript, ["mẫu"], "accepted")
            self.assertEqual(normalize.call_count, 1)
            DuplicateIndex(cache).add(transcript, ["khác"], "accepted")
            transcript["utterances"][0]["text"] += " Thêm câu hỏi."
            DuplicateIndex(cache).add(transcript, ["mẫu"], "accepted")
            self.assertEqual(normalize.call_count, 3)

    def test_journey_task_commits_all_sessions_after_review_and_exports(self):
        from dataset.pipeline.scenario_export import export, verify_export
        self.initialize(archive=False, generation_unit="journey")
        task = self.task()
        self.assertEqual(task["request"]["kind"], "generate_journey")
        payload = json.loads(task["request"]["messages"][1]["content"])
        history = []
        for session in payload["journey_plan"]["sessions"]:
            req = agent.engine.request("generate", {"session_plan": session, "previous_sessions": history,
                                       "validation_feedback": [], "limits": payload["limits"]}, {})
            history.append(json.loads(self.provider.request(req)["text"]))
        agent.submit(self.run, self.envelope(task, {"transcripts": history}))
        self.assertEqual(agent.inspect(self.run)["production_transcripts"], 0)
        review = self.task()
        self.assertEqual(review["request"]["kind"], "quality_review")
        agent.submit(self.run, self.envelope(review))
        result = agent.finalize(self.run)
        self.assertEqual(result["model_tasks_submitted"], 2)
        self.assertEqual(result["production_transcripts"], 2)
        self.assertTrue(read(self.run / "checkpoint.json")["state"]["duplicate_features"])
        export([self.run], self.root / "export")
        verify_export(self.root / "export")

    def test_invalid_journey_batch_retries_without_exporting_partial_sessions(self):
        self.initialize(archive=False, generation_unit="journey")
        task = self.task()
        agent.submit(self.run, self.envelope(task, {"transcripts": []}))
        state = read(self.run / "checkpoint.json")["state"]
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["history"], [])
        self.assertEqual(state["accepted"], [])
        self.assertEqual(state["calls"], 1)
        self.assertEqual(self.task()["request"]["kind"], "generate_journey")

    def test_wrong_run_stale_and_tampered_tasks_do_not_consume_budget(self):
        self.initialize()
        task = self.task(); path = self.envelope(task)
        wrong = read(path); wrong["run_id"] = "wrong"; write(path, wrong)
        with self.assertRaisesRegex(ValueError, "wrong-run"):
            agent.submit(self.run, path)
        self.assertEqual(agent.inspect(self.run)["model_tasks_submitted"], 0)
        path = self.envelope(task); agent.submit(self.run, path)
        with self.assertRaisesRegex(ValueError, "stale"):
            agent.submit(self.run, path)
        self.assertEqual(agent.inspect(self.run)["model_tasks_submitted"], 1)
        task = self.task(); task["attempt"] = 99
        write(self.run / "tasks/000002.json", task)
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            agent.inspect(self.run)

    def test_invalid_transcripts_retry_then_quarantine_without_partial_export(self):
        self.initialize()
        for _ in range(3):
            task = self.task()
            agent.submit(self.run, self.envelope(task, {"invalid": True}))
        result = agent.inspect(self.run)
        self.assertEqual(result["status"], "ready_to_finalize")
        self.assertEqual(result["production_transcripts"], 0)
        self.assertEqual(result["model_tasks_submitted"], 3)
        final = agent.finalize(self.run)
        self.assertEqual(final["status"], "quarantined")
        self.assertFalse(final["dataset_requirements_met"])

    def test_review_uncertainty_and_false_citations_force_repair(self):
        self.initialize()
        for _ in range(2):
            task = self.task(); agent.submit(self.run, self.envelope(task))
        review = self.task()
        self.assertEqual(review["request"]["kind"], "quality_review")
        body = passing_review(json.loads(review["request"]["messages"][1]["content"]))
        body["checks"][0]["verdict"] = "uncertain"
        body["checks"][1]["evidence"][0]["quote"] = "invented citation"
        agent.submit(self.run, self.envelope(review, body))
        self.assertEqual(read(self.run / "generation/manifest.json"), [])
        repair = self.task()
        payload = json.loads(repair["request"]["messages"][1]["content"])
        self.assertTrue(any("uncertain" in e for e in payload["validation_feedback"]))
        self.complete()
        self.assertEqual(agent.finalize(self.run)["status"], "completed")

    def test_duplicate_judgments_and_retries_replay_in_the_same_order(self):
        cfg = read(self.config); cfg["duplicates"] = {"review_threshold": .05, "reject_threshold": .999999, "judge_ambiguous": True}
        write(self.config, cfg)
        self.initialize()
        saw_duplicate = False
        for _ in range(30):
            task = self.task()
            if "request" not in task: break
            if task["request"]["kind"] == "duplicate" and not saw_duplicate:
                saw_duplicate = True
                agent.submit(self.run, self.envelope(task, {"duplicate": "invalid", "reason": "test"}))
            else:
                agent.submit(self.run, self.envelope(task))
        self.assertTrue(saw_duplicate)
        self.assertEqual(agent.finalize(self.run)["status"], "completed")

    def test_committed_event_recovers_after_crash_before_checkpoint(self):
        self.initialize(); task = self.task(); path = self.envelope(task)
        with patch.object(agent, "save", side_effect=RuntimeError("simulated process failure")):
            with self.assertRaises(RuntimeError): agent.submit(self.run, path)
        self.assertTrue((self.run / "events/000001.json").is_file())
        self.assertEqual(read(self.run / "checkpoint.json")["state"]["calls"], 0)
        self.assertEqual(agent.inspect(self.run)["model_tasks_submitted"], 1)
        self.assertEqual(self.task()["sequence"], 2)
        self.complete(); agent.finalize(self.run)

    def test_low_token_budget_pauses_before_emitting_task_and_preserves_staging(self):
        self.initialize()
        result = agent.next_task(self.run, remaining=1, source="test host report")
        self.assertEqual(result["status"], "paused_token_budget")
        self.assertFalse((self.run / "tasks").exists())
        self.assertEqual(result["model_tasks_submitted"], 0)
        with self.assertRaisesRegex(ValueError, "fresh-context"):
            agent.resume(self.run)
        result = agent.resume(self.run, fresh=True)
        task = read(Path(result["task_file"]))
        agent.submit(self.run, self.envelope(task))
        agent.pause(self.run, "token_budget")
        history = read(self.run / "staging.json")["history"]
        self.assertEqual(len(history), 1)
        agent.resume(self.run, fresh=True)
        self.assertEqual(read(self.run / "staging.json")["history"], history)
        self.assertEqual(agent.inspect(self.run)["model_tasks_submitted"], 1)
        self.complete(); agent.finalize(self.run)

    def test_unknown_budget_checkpoints_one_journey_and_does_not_regenerate_it(self):
        self.config = fixture(self.root, customers=2)
        self.initialize()
        for _ in range(3):
            task = self.task(); agent.submit(self.run, self.envelope(task))
        manifest = copy.deepcopy(read(self.run / "generation/manifest.json"))
        result = self.task()
        self.assertEqual(result["status"], "paused_token_budget")
        state = read(self.run / "checkpoint.json")["state"]
        self.assertEqual(state["budget_observations"][-1]["remaining_context_tokens"], "unknown")
        resumed = agent.resume(self.run, fresh=True)
        task = read(Path(resumed["task_file"]))
        self.assertEqual(task["journey_id"], "J0002")
        self.assertEqual(read(self.run / "generation/manifest.json"), manifest)
        self.assertEqual(resumed["model_tasks_submitted"], 3)

    def test_usage_limit_needs_restoration_and_does_not_reset_attempts(self):
        self.initialize(); task = self.task()
        agent.submit(self.run, self.envelope(task, {}))
        agent.pause(self.run, "usage_limit")
        with self.assertRaisesRegex(ValueError, "restoration"):
            agent.resume(self.run)
        result = agent.resume(self.run, usage_restored=True)
        task = read(Path(result["task_file"]))
        self.assertEqual(task["attempt"], 2)
        self.assertEqual(result["model_tasks_submitted"], 1)

    def test_fresh_context_after_journey_starts_a_new_unknown_budget_batch(self):
        self.config = fixture(self.root, customers=2)
        self.initialize()
        for _ in range(3):
            task = self.task(); agent.submit(self.run, self.envelope(task))
        # Interruption can happen before next() has marked the batch pause.
        result = agent.resume(self.run, fresh=True)
        self.assertEqual(result["status"], "awaiting_task")
        self.assertEqual(read(Path(result["task_file"]))["journey_id"], "J0002")

    def test_explicit_same_session_resume_authorizes_one_more_unknown_batch(self):
        self.config = fixture(self.root, customers=2)
        self.initialize()
        for _ in range(3):
            task = self.task()
            agent.submit(self.run, self.envelope(task))
        self.assertEqual(self.task()["status"], "paused_token_budget")
        before = read(self.run / "checkpoint.json")["state"]
        result = agent.resume(self.run)
        after = read(self.run / "checkpoint.json")["state"]
        self.assertEqual(read(Path(result["task_file"]))["journey_id"], "J0002")
        self.assertEqual(before["calls"], after["calls"])
        self.assertEqual(before["accepted"], after["accepted"])
        self.assertEqual(before["attempt"], after["attempt"])
        self.assertTrue(after["sessions"][-1]["same_session_batch_authorized"])
        self.assertFalse(after["sessions"][-1]["fresh_context_attested"])
        self.assertEqual(after["sessions"][-1]["remaining_context_tokens"], "unknown")

    def test_explicit_policy_upgrade_preserves_frozen_data_and_checks_code(self):
        self.initialize(archive=False)
        settings = (self.run / "settings.json").read_bytes()
        planseal = (self.run / "generation/plan/seal.json").read_bytes()
        old = read(self.run / "settings.json")["code_sha256"]
        changed = {**old, "agent.py": "policy-update-fixture"}
        with patch.object(agent, "code_hashes", return_value=changed):
            with self.assertRaisesRegex(ValueError, "changed"):
                agent.inspect(self.run)
            receipt = agent.upgrade_resume_policy(self.run)
            self.assertEqual(receipt["previous_code"], old)
            self.assertEqual(receipt["execution_code"], changed)
            self.assertEqual(agent.inspect(self.run)["status"], "awaiting_task")
            self.assertEqual(agent.upgrade_resume_policy(self.run), receipt)
            self.complete()
            agent.finalize(self.run)
            provenance = read(self.run / "generation/provenance.json")
            self.assertEqual(provenance["execution_code_sha256"], changed)
            self.assertEqual(provenance["resume_policy_upgrade"], receipt)
            self.assertIn("resume_policy_upgrade.json", read(self.run / "final.seal.json")["files"])
            agent.verify_release(self.run)
            with patch.object(agent, "code_hashes", return_value={**changed, "planner.py": "unrelated"}):
                with self.assertRaisesRegex(ValueError, "changed"):
                    agent.inspect(self.run)
        self.assertEqual(settings, (self.run / "settings.json").read_bytes())
        self.assertEqual(planseal, (self.run / "generation/plan/seal.json").read_bytes())

    def test_policy_upgrade_rejects_other_changes_and_damaged_checkpoints(self):
        self.initialize(archive=False)
        old = read(self.run / "settings.json")["code_sha256"]
        with patch.object(agent, "code_hashes", return_value={**old, "prompts/generate.md": "changed"}):
            with self.assertRaisesRegex(ValueError, "unrelated"):
                agent.upgrade_resume_policy(self.run)
        cp = read(self.run / "checkpoint.json")
        cp["state"]["calls"] = 999
        write(self.run / "checkpoint.json", cp)
        with patch.object(agent, "code_hashes", return_value={**old, "agent.py": "policy-update-fixture"}):
            with self.assertRaisesRegex(ValueError, "checkpoint checksum"):
                agent.upgrade_resume_policy(self.run)
        self.assertFalse((self.run / "resume_policy_upgrade.json").exists())

    def test_fixed_task_budget_is_not_reset_by_resume(self):
        cfg = read(self.config); cfg["generation"]["max_api_calls"] = 1; write(self.config, cfg)
        self.initialize(); task = self.task(); agent.submit(self.run, self.envelope(task))
        self.assertEqual(self.task()["status"], "exhausted_task_budget")
        self.assertEqual(agent.resume(self.run, fresh=True)["status"], "exhausted_task_budget")
        with self.assertRaisesRegex(ValueError, "unfinished"):
            agent.finalize(self.run)

    def test_tampered_journal_and_transcript_are_detected(self):
        self.initialize(); self.complete()
        path = next((self.run / "generation/transcripts").glob("*.json"))
        original = path.read_bytes(); path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            agent.inspect(self.run)
        path.write_bytes(original)
        event = self.run / "events/000001.json"
        body = read(event); body["response"]["text"] = "{}"; write(event, body)
        with self.assertRaisesRegex(ValueError, "checksum chain|diverged"):
            agent.inspect(self.run)

    def test_changed_code_or_frozen_source_blocks_resume(self):
        self.initialize()
        with patch.object(agent, "code_hashes", return_value={}):
            with self.assertRaisesRegex(ValueError, "code/prompts/guide"):
                agent.resume(self.run)
        source = self.run / "generation/plan/snapshot/domain/catalog.json"
        body = read(source); body["products"][0]["price_vnd"] += 1; write(source, body)
        with self.assertRaisesRegex(ValueError, "checksums changed"):
            agent.inspect(self.run)

    def test_finalize_recovers_if_seal_write_was_interrupted(self):
        self.initialize(); self.complete()
        real_write = agent.write
        def fail_at_seal(path, value):
            if path.name == "final.seal.json": raise OSError("simulated interruption")
            real_write(path, value)
        with patch.object(agent, "write", side_effect=fail_at_seal):
            with self.assertRaises(OSError): agent.finalize(self.run)
        self.assertEqual(agent.finalize(self.run)["status"], "completed")
        agent.verify_release(self.run)

    def test_multiple_journeys_and_three_sessions_keep_committed_bytes(self):
        self.config = fixture(self.root, customers=2)
        config = read(self.config); config["planning"]["multichannel_customers"] = 1
        write(self.config, config)
        self.initialize()
        committed = None
        flavors = {("SYN-C0001", 1): "phòng khách", ("SYN-C0001", 2): "gian bếp",
                   ("SYN-C0001", 3): "văn phòng", ("SYN-C0002", 1): "kho chứa",
                   ("SYN-C0002", 2): "phòng ngủ"}
        for _ in range(15):
            task = self.task(remaining=1_000_000, source="test fixture only")
            if "request" not in task: break
            value = json.loads(self.provider.request(task["request"])["text"])
            if task["request"]["kind"] == "generate":
                value["utterances"][0]["text"] += " Chị đang xem cho " + flavors[(value["customer_id"], value["session_index"])] + "."
            result = agent.submit(self.run, self.envelope(task, value))
            if result["accepted_journeys"] == 1 and committed is None:
                committed = {p.name: p.read_bytes() for p in (self.run / "generation/transcripts").glob("*.json")}
        self.assertEqual(len(committed), 3)
        final = agent.finalize(self.run)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["production_transcripts"], 5)
        self.assertEqual(final["model_tasks_submitted"], 7)
        for name, content in committed.items():
            self.assertEqual((self.run / "generation/transcripts" / name).read_bytes(), content)

    def test_existing_lock_blocks_a_second_writer_without_changing_checkpoint(self):
        self.initialize()
        original = (self.run / "checkpoint.json").read_bytes()
        lock = self.run / ".agent.lock"; lock.write_text("other-process")
        with self.assertRaises(FileExistsError):
            agent.next_task(self.run)
        self.assertEqual(lock.read_text(), "other-process")
        self.assertEqual((self.run / "checkpoint.json").read_bytes(), original)

    def test_exact_five_nonprefix_samples_survive_resume_and_both_replay_paths(self):
        self.config = fixture(self.root, customers=3)
        config = read(self.config); config["planning"]["multichannel_customers"] = 2
        write(self.config, config)
        result = self.initialize(samples=5, policy={"unknown_batch_journeys": 2})
        self.assertEqual(result["selected_journey_ids"], ["J0001", "J0003"])
        self.assertEqual(agent.resume(self.run)["selected_journey_ids"], result["selected_journey_ids"])
        for _ in range(15):
            task = self.task()
            if "request" not in task: break
            value = json.loads(self.provider.request(task["request"])["text"])
            if task["request"]["kind"] == "generate":
                flavor = {1: "phòng khách", 2: "gian bếp", 3: "văn phòng"}[value["session_index"]]
                if value["customer_id"] != "SYN-C0001":
                    flavor += " và nhu cầu công việc"
                value["utterances"][0]["text"] += " Chị đang xem cho " + flavor + "."
            agent.submit(self.run, self.envelope(task, value))
        final = agent.finalize(self.run)
        self.assertTrue(final["sample_count_met"])
        self.assertEqual(final["production_transcripts"], 5)
        self.assertEqual(final["status"], "partial_coverage")
        self.assertFalse(final["dataset_requirements_met"])
        process = subprocess.run([sys.executable, "-B", "-m", "dataset.pipeline", "replay",
                                  "--run", str(self.run / "generation"), "--output", str(self.root / "cli_replay")],
                                 text=True, capture_output=True, check=False)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(read(self.root / "cli_replay/manifest.json"), read(self.run / "generation/manifest.json"))


    def test_explicit_journey_selection_survives_resume_and_replay(self):
        self.config = fixture(self.root, customers=2)
        self.initialize(journey_ids=["J0002"])
        result = agent.resume(self.run)
        self.assertEqual(result["selected_journey_ids"], ["J0002"])
        self.complete()
        final = agent.finalize(self.run)
        self.assertEqual(final["production_transcripts"], 2)
        self.assertEqual(final["status"], "partial_coverage")
        from dataset.pipeline.scenario_export import export, verify_export, migrate_export
        exported = self.root / "export"
        self.assertEqual(export([self.run], exported)["scenarios"], 1)
        self.assertFalse((exported / "seal.json").exists())
        self.assertEqual(read(exported / "manifest.json")["format_version"], 2)
        obj = read(exported / "scenarios_complete/SC-001.json")
        self.assertEqual(obj["customer_phone"], "SYN-C0002")
        self.assertEqual(len(obj["calls"]), 2)
        self.assertEqual(obj["calls"]["call_1"]["customer_turns"][0], read(self.run / "generation/transcripts/J0002-S01.json")["utterances"][0]["text"])
        original_manifest = (exported / "manifest.json").read_bytes()
        manifest = read(exported / "manifest.json"); manifest["scope"] = "changed"
        write(exported / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "manifest integrity"):
            verify_export(exported)
        (exported / "manifest.json").write_bytes(original_manifest)
        extra = exported / "unexpected.json"; extra.write_text("{}")
        with self.assertRaisesRegex(ValueError, "files/checksums"):
            verify_export(exported)
        extra.unlink()
        transcript = next((exported / "transcripts").glob("*.json")); content = transcript.read_bytes()
        transcript.unlink()
        with self.assertRaisesRegex(ValueError, "files/checksums"):
            verify_export(exported)
        transcript.write_bytes(content)
        # Recreate a genuine v1 export and exercise migration, not re-sealing bad data.
        from dataset.pipeline.common import files_manifest
        legacy = read(exported / "manifest.json"); legacy.pop("integrity"); legacy["format_version"] = 1
        write(exported / "manifest.json", legacy)
        write(exported / "seal.json", {"files": files_manifest(exported)})
        self.assertEqual(migrate_export(exported)["scenarios"], 1)
        self.assertFalse((exported / "seal.json").exists())
        self.assertEqual(migrate_export(exported)["scenarios"], 1)
        (exported / "scenarios_complete/SC-001.json").write_text("{}")
        with self.assertRaises(ValueError): verify_export(exported)

    def test_output_subfolder_is_allowed_and_excluded_from_source_hashes(self):
        from dataset.pipeline import common
        fake_code = self.root / "pipeline"; fake_code.mkdir()
        (fake_code / "code.py").write_text("# source\n")
        with patch.object(common, "HERE", fake_code):
            before = common.code_hashes()
            output = common.new_directory(fake_code / "output/run")
            write(output / "generated.json", {"test": True})
            self.assertEqual(common.code_hashes(), before)
            with self.assertRaises(ValueError): common.new_directory(fake_code / "configs/bad")
            with self.assertRaises(ValueError): common.new_directory(fake_code.parent)


if __name__ == "__main__":
    unittest.main()
