import copy
import io
import json
import os
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
            return agent.initialize(kwargs.pop("profile", "M1"), self.run, **kwargs)

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


if __name__ == "__main__":
    unittest.main()
