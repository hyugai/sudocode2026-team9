"""Internal worker, launched with the managed environment's interpreter."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .automation_utils import api_free_environment, run_command, save_report
from .common import file_hash, read, write
from .envcheck import REPO, check_environment, live_preflight
from .providers import OpenAIProvider, ReplayProvider, RoutedProvider
from .runner import generate_run, plan_run, verify_run
from .smoke import run_smoke


def run_tests(output: Path) -> dict:
    result = run_command([sys.executable, "-B", "-W", "ignore::ResourceWarning", "-m", "dataset.pipeline.testing",
                          "--report", str(output / "test_results.json")], REPO, output / "logs/tests.log",
                         env=api_free_environment(), timeout=300)
    if not (output / "test_results.json").is_file():
        raise RuntimeError("test process did not produce test_results.json")
    report = read(output / "test_results.json")
    if result.returncode or report["status"] != "passed" or report["tests_run"] < 1:
        raise RuntimeError("regression tests failed; inspect test_results.json and logs/tests.log")
    return report


def workflow(args) -> int:
    output = args.output.resolve()
    report = read(output / "environment_report.json")

    def stage(name: str, status: str, detail):
        report["stages"].append({"name": name, "status": status, "detail": detail})
        save_report(output, report)

    try:
        live = args.mode != "offline"
        doctor = check_environment(args.config, output, live=live, model=args.model, reviewer=args.review_model)
        write(output / "readiness.json", doctor)
        stage("readiness", doctor["status"], doctor["checks"])
        if doctor["status"] != "passed":
            report["status"] = "blocked"
            save_report(output, report)
            return 2
        tests = run_tests(output)
        stage("regression_tests", "passed", {k: tests[k] for k in ("tests_run", "failures", "errors", "skipped")})
        original = read(args.config)
        effective = json.loads(json.dumps(original))
        effective["domain"]["root"] = str((args.config.resolve().parent / original["domain"]["root"]).resolve())
        models = doctor["models"]
        probes = len(set(models.values())) if live else 0
        if live and (args.max_api_calls is None or args.max_api_calls <= probes):
            raise ValueError("live budget must cover model probes plus generation/review; increase explicit --max-api-calls")
        if live:
            effective["generation"]["model"] = models["generation"]
            effective["review"]["model"] = models["review"]
            effective["generation"]["max_api_calls"] = args.max_api_calls - probes
        write(output / "effective_config.json", effective)
        planned = plan_run(output / "effective_config.json", output / "plan")
        stage("plan", "passed" if planned["transcript_requirements_met"] else "failed", planned)
        if not planned["transcript_requirements_met"]:
            report.update(status="input_coverage_gap", production_transcripts=0, dataset_requirements_met=False)
            save_report(output, report)
            return 3
        verify_run(output / "plan")
        stage("plan_verification", "passed", "frozen inputs, code and deterministic plans verified")
        smoke = run_smoke(output / "smoke_test")
        stage("offline_smoke", smoke["status"], smoke)
        if not live:
            stage("live_preflight", "skipped", "API-free mode; live readiness is not established")
            stage("production_generation", "skipped", "only explicitly labeled test fixtures were generated")
            report.update(status="offline_verified", live_ready=False, production_transcripts=0,
                          dataset_requirements_met=False, api_calls=0)
            save_report(output, report)
            return 0
        plans = read(output / "plan/plans.json")
        selected = plans if args.mode == "full" else plans[:args.limit]
        minimum = sum(len(p["sessions"]) + 1 for p in selected)
        if args.max_api_calls < probes + minimum:
            raise ValueError(f"budget cannot cover selected generation + review + probes; need at least {probes+minimum} before retries/dedup judges")
        preflight = live_preflight(models, output, args.max_api_calls)
        write(output / "live_preflight.json", preflight)
        stage("live_preflight", preflight["status"], preflight)
        report["api_calls"] = preflight["calls"]
        if preflight["status"] != "passed":
            report.update(status="blocked", live_ready=False, production_transcripts=0, dataset_requirements_met=False)
            stage("production_generation", "skipped", "model probe failed; no offline substitution")
            save_report(output, report)
            return 2
        report["live_ready"] = True
        save_report(output, report)
        provider = RoutedProvider(OpenAIProvider(models["generation"], effective["generation"]["max_output_tokens"]),
                                  OpenAIProvider(models["review"], effective["review"]["max_output_tokens"]))
        generated = generate_run(output / "plan", output / "generation", provider,
                                 limit=None if args.mode == "full" else args.limit)
        generation_code = 2 if generated["status"] in {"provider_stopped", "quarantined"} else 0 if generated["coverage"]["transcript_requirements_met"] else 3
        stage("production_generation", "failed" if generation_code == 2 else "passed",
              {**generated, "pipeline_exit_code": generation_code, "partial_coverage_expected": args.mode == "pilot"})
        verified = verify_run(output / "generation")
        stage("output_verification", "passed", verified)
        replay = generate_run(output / "generation/plan", output / "replay", ReplayProvider(output / "generation"),
                              limit=None if args.mode == "full" else args.limit)
        verify_run(output / "replay")
        first = read(output / "generation/manifest.json")
        second = read(output / "replay/manifest.json")
        if first != second or any(file_hash(output / "generation" / r["path"]) != file_hash(output / "replay" / r["path"]) for r in first):
            raise RuntimeError("replay transcripts/manifest differ from original generation")
        stage("replay", "passed", {"status": replay["status"], "byte_identical_transcripts": True})
        report.update(production_transcripts=generated["exported_transcripts"],
                      dataset_requirements_met=generated["coverage"]["transcript_requirements_met"],
                      api_calls=preflight["calls"] + generated["model_calls"])
        if generation_code == 2:
            report["status"] = "generation_incomplete"
        elif args.mode == "pilot":
            report["status"] = "pilot_verified"
        else:
            report["status"] = "full_run_verified" if generation_code == 0 else "partial_coverage"
        save_report(output, report)
        return generation_code if args.mode == "full" or generation_code == 2 else 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, ImportError) as exc:
        report.update(status="blocked", error_type=type(exc).__name__)
        stage("workflow", "blocked", str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__)
        save_report(output, report)
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("offline", "pilot", "full"), required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model")
    p.add_argument("--review-model")
    p.add_argument("--max-api-calls", type=int)
    p.add_argument("--limit", type=int, default=1)
    args = p.parse_args()
    return workflow(args)


if __name__ == "__main__":
    raise SystemExit(main())
