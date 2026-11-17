import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from dataset.pipeline import automation, envcheck, setup_env
from dataset.pipeline.automation_utils import api_free_environment, redact, save_report
from dataset.pipeline.common import read, write
from dataset.pipeline.providers import OpenAIProvider
from dataset.pipeline.smoke import SmokeProvider
from dataset.pipeline.tests.test_pipeline import fixture


def make_managed(root):
    env = root / "managed"
    setup_env.python_path(env).parent.mkdir(parents=True)
    setup_env.python_path(env).touch()
    lock = root / "requirements.lock"
    lock.write_text("openai==2.54.0\n")
    from dataset.pipeline.common import file_hash
    marker = {"managed_by": "dataset.pipeline.setup_env", "format_version": 1,
              "python": list(sys.version_info[:2]), "platform": setup_env.platform.system(),
              "lock_sha256": file_hash(lock), "status": "ready"}
    write(env / setup_env.MARKER, marker)
    inventory = {"python": list(sys.version_info[:2]), "prefix": str(env),
                 "packages": {"openai": "2.54.0", "pip": "1"}}
    return env, lock, inventory


class SetupTests(unittest.TestCase):
    def test_existing_unmanaged_environment_is_never_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "existing").mkdir(); (root / "lock").write_text("openai==2.54.0\n")
            sentinel = root / "existing/user_file"; sentinel.write_text("keep")
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                setup_env.ensure_environment(root / "existing", root / "lock", root / "report")
            self.assertEqual(sentinel.read_text(), "keep")

    def test_compatible_environment_is_reused_without_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); env, lock, inventory = make_managed(root)
            out = root / "report"; out.mkdir()
            with patch.object(setup_env, "inspect_environment", return_value=inventory), \
                 patch.object(setup_env, "run_command", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                result = setup_env.ensure_environment(env, lock, out)
            self.assertTrue(result["reused"])
            self.assertEqual(run.call_count, 1)
            self.assertIn("check", run.call_args.args[0])
            self.assertTrue((out / "requirements.lock").is_file())

    def test_drift_is_blocked_instead_of_silently_upgrading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); env, lock, inventory = make_managed(root)
            inventory["packages"]["openai"] = "wrong"
            with patch.object(setup_env, "inspect_environment", return_value=inventory):
                with self.assertRaisesRegex(ValueError, "dependency drift"):
                    setup_env.ensure_environment(env, lock, root / "report")

    def test_install_failure_is_actionable_and_retriable_in_owned_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); env, lock, inventory = make_managed(root)
            marker = read(env / setup_env.MARKER); marker["status"] = "installing"; write(env / setup_env.MARKER, marker)
            out = root / "report"; out.mkdir()
            with patch.object(setup_env, "run_command", return_value=subprocess.CompletedProcess([], 1, "", "network unavailable")):
                with self.assertRaisesRegex(RuntimeError, "installation failed"):
                    setup_env.ensure_environment(env, lock, out)
            self.assertEqual(read(env / setup_env.MARKER)["status"], "installing")
            with patch.object(setup_env, "inspect_environment", return_value=inventory), \
                 patch.object(setup_env, "run_command", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
                result = setup_env.ensure_environment(env, lock, out, root / "wheels")
            install = run.call_args_list[0].args[0]
            self.assertIn("--no-index", install)
            self.assertIn("--no-input", install)
            self.assertTrue(result["status"] == "passed")

    def test_lock_rejects_options_and_unpinned_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lock"
            for text in ("openai>=2\n", "--index-url https://example.invalid\n", "openai==2\nOpenAI==2\n"):
                path.write_text(text)
                with self.assertRaises(ValueError): setup_env.parse_lock(path)

    def test_credentials_are_removed_from_offline_children_and_redacted(self):
        secret = 'SETUP_SECRET_"quoted"\nDO_NOT_LOG'
        with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False):
            self.assertNotIn("OPENAI_API_KEY", api_free_environment())
            self.assertNotIn(secret, redact(f"failed {secret}"))
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                save_report(root, {"mode": "offline", "status": "blocked", "stages": [
                    {"name": "error", "status": "blocked", "detail": secret}]})
                self.assertEqual(read(root / "environment_report.json")["stages"][0]["detail"], "[REDACTED]")
                self.assertNotIn(secret, (root / "environment_report.md").read_text())
        self.assertNotIn("password", redact("https://user:password@registry.example/simple"))

    def test_missing_live_credentials_block_before_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root)
            with patch.dict(os.environ, {}, clear=True):
                report = envcheck.check_environment(config, root, live=True, model="example-model", reviewer=None)
            check = next(c for c in report["checks"] if c["name"] == "credential_presence")
            self.assertEqual(check["status"], "blocked")
            self.assertEqual(report["live_connectivity"], "not_checked")

    def test_offline_workflow_retains_fixture_label_and_never_calls_api(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root); out = root / "run"; out.mkdir()
            save_report(out, {"mode": "offline", "status": "running", "stages": [], "live_ready": False})
            args = Namespace(mode="offline", config=config, output=out, model=None, review_model=None, max_api_calls=None, limit=1)
            doctor = {"status": "passed", "checks": [], "models": None}
            with patch.object(automation, "check_environment", return_value=doctor), \
                 patch.object(automation, "run_tests", return_value={"tests_run": 1, "failures": 0, "errors": 0, "skipped": 0}), \
                 patch.object(automation, "live_preflight", side_effect=AssertionError("unexpected API probe")), \
                 patch.object(automation, "OpenAIProvider", side_effect=AssertionError("unexpected live provider")):
                self.assertEqual(automation.workflow(args), 0)
            report = read(out / "environment_report.json")
            self.assertEqual(report["status"], "offline_verified")
            self.assertEqual(report["production_transcripts"], 0)
            self.assertEqual(report["api_calls"], 0)
            self.assertFalse(report["live_ready"])
            self.assertEqual(read(out / "smoke_test/smoke_report.json")["mode"], "OFFLINE_TEST_FIXTURE_ONLY")

    def test_pilot_accepts_partial_coverage_but_does_not_claim_full_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root, customers=2); out = root / "run"; out.mkdir()
            save_report(out, {"mode": "pilot", "status": "running", "stages": [], "live_ready": False})
            args = Namespace(mode="pilot", config=config, output=out, model="fake", review_model="fake", max_api_calls=10, limit=1)
            doctor = {"status": "passed", "checks": [], "models": {"generation": "fake", "review": "fake"}}
            with patch.object(automation, "check_environment", return_value=doctor), \
                 patch.object(automation, "run_tests", return_value={"tests_run": 1, "failures": 0, "errors": 0, "skipped": 0}), \
                 patch.object(automation, "live_preflight", return_value={"status": "passed", "calls": 1}), \
                 patch.object(automation, "OpenAIProvider", return_value=SmokeProvider()):
                self.assertEqual(automation.workflow(args), 0)
            report = read(out / "environment_report.json")
            self.assertEqual(report["status"], "pilot_verified")
            self.assertFalse(report["dataset_requirements_met"])
            self.assertLessEqual(report["api_calls"], 10)

    def test_live_probe_failure_never_falls_back_to_fake_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); config = fixture(root); out = root / "run"; out.mkdir()
            save_report(out, {"mode": "pilot", "status": "running", "stages": [], "live_ready": False})
            args = Namespace(mode="pilot", config=config, output=out, model="fake", review_model=None, max_api_calls=10, limit=1)
            with patch.object(automation, "check_environment", return_value={"status": "passed", "checks": [], "models": {"generation": "fake", "review": "fake"}}), \
                 patch.object(automation, "run_tests", return_value={"tests_run": 1, "failures": 0, "errors": 0, "skipped": 0}), \
                 patch.object(automation, "live_preflight", return_value={"status": "blocked", "calls": 1}), \
                 patch.object(automation, "OpenAIProvider", side_effect=AssertionError("must not construct generator")):
                self.assertEqual(automation.workflow(args), 2)
            report = read(out / "environment_report.json")
            self.assertEqual(report["status"], "blocked")
            self.assertFalse((out / "generation").exists())

    def test_live_mode_requires_budget_and_protects_existing_output(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            setup_env.main(["--mode", "full"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); out = root / "existing"; out.mkdir(); sentinel = out / "keep"; sentinel.write_text("unchanged")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(setup_env.main(["--output", str(out), "--venv", str(root / 'env')]), 2)
            self.assertEqual(sentinel.read_text(), "unchanged")

    @unittest.skipUnless(importlib.util.find_spec("openai") and importlib.util.find_spec("httpx"), "SDK integration runs in the managed environment")
    def test_installed_sdk_roundtrip_uses_mock_http_without_network(self):
        import httpx
        from openai import OpenAI
        captured = []
        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "resp_fixture", "object": "response", "created_at": 0,
                "status": "completed", "model": "fixture-model", "parallel_tool_calls": False,
                "tool_choice": "auto", "tools": [], "output": [{"id": "msg_fixture", "type": "message",
                "status": "completed", "role": "assistant", "content": [{"type": "output_text",
                "text": '{"ok":true}', "annotations": []}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}})
        with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
            client = OpenAI(api_key="FAKE_SDK_TEST_KEY", http_client=transport)
            provider = OpenAIProvider("fixture-model", 64, client=client)
            result = provider.request({"kind": "probe", "schema_name": "probe", "schema": {"type": "object"},
                                       "messages": [{"role": "user", "content": "test"}]})
        self.assertTrue(result["completed"])
        self.assertEqual(json.loads(result["text"]), {"ok": True})
        self.assertTrue(captured[0]["text"]["format"]["strict"])


if __name__ == "__main__":
    unittest.main()
