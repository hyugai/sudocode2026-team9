"""File-based tasks for the active coding agent. No SDK, key or model launch."""
from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import venv
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from . import agent_engine as engine
from .automation_utils import api_free_environment, run_command
from .checks import validate_schema
from .common import HERE, code_hashes, encode, file_hash, files_manifest, fingerprint, new_directory, read, runtime, verify_files, write
from .planner import coverage
from .providers import ReplayProvider
from .runner import generate_run, journey_artifacts, plan_run, stamp, verify_plan, verify_run, write_dataset_card
from .selection import select_plans

REPO = HERE.parents[1]
PROFILES = {name: HERE / f"configs/hackathon_{name.lower()}.json" for name in ("M1", "M2")}
POLICY = {"estimate_safety_factor": 1.5, "checkpoint_reserve_tokens": 4000,
          "repair_allowance_tokens": 6000, "unknown_batch_journeys": 1}
FINISHED = {"completed", "partial_coverage", "quarantined"}


@contextmanager
def locked(root: Path):
    """Do not steal a lock from another agent or silently repair user files."""
    lock = root / ".agent.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def agent_info(path: Path | None = None) -> dict:
    info = read(path) if path else {}
    allowed = {"application", "version", "model"}
    if not isinstance(info, dict) or info.keys() - allowed or any(not isinstance(v, str) or not v.strip() or len(v) > 300 for v in info.values()):
        raise ValueError("agent info accepts only application/version/model strings; omit unavailable fields")
    return {key: info.get(key, "unknown") for key in sorted(allowed)}


def setup_checks(root: Path) -> dict:
    """Isolated standard-library environment; no package install or network."""
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ is required")
    environment = root / "environment"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    result = run_command([str(python), "-B", "-W", "ignore::ResourceWarning", "-m", "dataset.pipeline.testing",
                          "--report", str(root / "test_results.json")], REPO, root / "logs/tests.log",
                         env=api_free_environment(), timeout=300)
    if result.returncode or not (root / "test_results.json").is_file():
        raise RuntimeError("agent-mode regression checks failed; inspect logs/tests.log")
    tests = read(root / "test_results.json")
    if tests["status"] != "passed" or tests["tests_run"] < 1:
        raise RuntimeError("agent-mode regression checks did not pass")
    inventory = {"runtime": runtime(), "environment_python": str(python),
                 "dependencies": "Python standard library only; venv has no pip or SDK",
                 "api_calls": 0, "test_results": {k: tests[k] for k in ("tests_run", "failures", "errors", "skipped")}}
    write(root / "environment_report.json", inventory)
    return inventory


def initialize(profile: str, output: Path, *, limit: int | None = None,
               references: list[Path] | None = None, info: dict | None = None,
               policy: dict | None = None, samples: int | None = None,
               journey_ids: list[str] | None = None, archive: bool = False, generation_unit: str | None = None) -> dict:
    generation_unit = generation_unit or ("session" if archive else "journey")
    if generation_unit not in {"session", "journey"} or (archive and generation_unit != "session"):
        raise ValueError("archive replay requires session generation; choose lightweight for journey generation")
    if profile not in PROFILES:
        raise ValueError("select M1 or M2 explicitly before initializing")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be positive")
    if samples is not None and (type(samples) is not int or samples < 1):
        raise ValueError("samples must be positive")
    if sum(x is not None for x in (limit, samples, journey_ids)) > 1:
        raise ValueError("choose one selection mode")
    effective_policy = {**POLICY, **(policy or {})}
    if effective_policy.keys() != POLICY.keys():
        raise ValueError("unknown token policy field")
    for key, value in effective_policy.items():
        if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
            raise ValueError("token policy values must be positive finite numbers")
        if key != "estimate_safety_factor" and type(value) is not int:
            raise ValueError("token reserves/batch sizes must be integers")
    if effective_policy["estimate_safety_factor"] < 1:
        raise ValueError("estimate safety factor must be at least one")
    root = new_directory(output)
    with locked(root):
        try:
            setup_checks(root)
            source = PROFILES[profile]
            planned = plan_run(source, root / "generation/plan", references)
            if not planned["transcript_requirements_met"]:
                raise ValueError("source/config cannot cover the requested profile; see generation/plan/coverage_report.json")
            config = read(root / "generation/plan/config.json")
            selected = select_plans(read(root / "generation/plan/plans.json"), limit=limit, samples=samples, journey_ids=journey_ids)
            code = code_hashes()
            if archive:
                for relative in code:
                    target = root / "reproducibility/source" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(HERE / relative, target)
                for name in ("requirements.lock", "requirements.txt"):
                    shutil.copyfile(HERE / name, root / "reproducibility" / name)
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, text=True, capture_output=True, check=False)
            settings = {"format_version": 2, "archive_mode": "full" if archive else "lightweight", "generation_unit": generation_unit, "run_id": uuid4().hex, "profile": profile,
                        "source_config_sha256": file_hash(source), "limit": limit, "samples": samples,
                        "journey_ids": [p["journey_id"] for p in selected] if journey_ids is not None else None,
                        "selected_journey_ids": [p["journey_id"] for p in selected], "token_policy": effective_policy,
                        "max_model_tasks": config["generation"]["max_api_calls"],
                        "code_sha256": code, "git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
                        "created_at": stamp(), "initial_agent": info or agent_info(),
                        "review_mode": "same_agent_self_review", "api_calls": 0}
            write(root / "settings.json", settings)
            if archive:
                write(root / "reproducibility/seal.json", {"files": files_manifest(root / "reproducibility")})
            write(root / "settings.seal.json", {"settings_sha256": file_hash(root / "settings.json")})
            generation = root / "generation"
            for name in ("response.schema.json", "transcript.schema.json", "review.schema.json"):
                write(generation / "schemas" / name, read(HERE / name))
            state = engine.initial_state()
            state.update(batch_start=0, issued_task_sha256=None, generation_unit=generation_unit)
            state["sessions"].append({"at": stamp(), "agent": settings["initial_agent"]})
            save(root, state)
            config, plans, catalog, refs = inputs(root, settings)
            materialize(root, state, plans, config)
            return report(root, settings, state, plans, config, catalog)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            write(root / "initialization_error.json", {"status": "blocked", "error_type": type(exc).__name__,
                                                        "detail": str(exc)})
            raise


POLICY_UPGRADE_FILES = {"agent.py", "runner.py", "HANDS_OFF.md"}


def execution_code(root: Path, settings: dict) -> dict:
    current = code_hashes()
    if settings["code_sha256"] == current:
        return current
    path = root / "resume_policy_upgrade.json"
    if path.is_file():
        record = read(path)
        payload = {k: v for k, v in record.items() if k != "sha256"}
        changed = {k for k in set(current) | set(settings["code_sha256"])
                   if current.get(k) != settings["code_sha256"].get(k)}
        if (settings.get("archive_mode") == "lightweight" and record.get("kind") == "same_session_batch_resume_v1"
                and record.get("run_id") == settings["run_id"] and record.get("previous_code") == settings["code_sha256"]
                and record.get("execution_code") == current and fingerprint(payload) == record.get("sha256")
                and changed <= POLICY_UPGRADE_FILES):
            return current
    raise ValueError("pipeline code/prompts/guide changed; restore the frozen source version before resuming")


def upgrade_resume_policy(root: Path) -> dict:
    """Explicit opt-in upgrade. Preserve frozen settings, plan seals and submitted events."""
    with locked(root):
        settings = read(root / "settings.json")
        if (settings.get("archive_mode") != "lightweight" or (root / "final.seal.json").exists()
                or read(root / "checkpoint.json")["state"]["status"] in FINISHED):
            raise ValueError("policy upgrade is only for unfinished lightweight runs")
        if read(root / "settings.seal.json")["settings_sha256"] != file_hash(root / "settings.json"):
            raise ValueError("settings changed before policy upgrade")
        current = code_hashes()
        changed = {k for k in set(current) | set(settings["code_sha256"])
                   if current.get(k) != settings["code_sha256"].get(k)}
        if not changed or not changed <= POLICY_UPGRADE_FILES:
            raise ValueError("policy upgrade rejects unrelated code/prompt/schema changes")
        path = root / "resume_policy_upgrade.json"
        if path.exists():
            execution_code(root, settings)
            return read(path)
        payload = {"kind": "same_session_batch_resume_v1", "run_id": settings["run_id"],
                   "at": stamp(), "previous_code": settings["code_sha256"], "execution_code": current,
                   "changed_files": sorted(changed), "authorization": "explicit upgrade-resume-policy command"}
        write(path, {**payload, "sha256": fingerprint(payload)})
        try:
            load(root)  # Verify plan, settings, checkpoint, journal and materialized accepted data.
        except Exception:
            path.unlink()
            raise
        return read(path)


def inputs(root: Path, settings: dict) -> tuple:
    execution_code(root, settings)
    if settings.get("archive_mode", "full") == "full":
        verify_files(root / "reproducibility", read(root / "reproducibility/seal.json")["files"])
    config, plans, catalog = verify_plan(root / "generation/plan", rebuild=False, expected_code=settings["code_sha256"])
    plans = select_plans(plans, limit=settings["limit"], samples=settings.get("samples"), journey_ids=settings.get("journey_ids"))
    if settings.get("selected_journey_ids", [p["journey_id"] for p in plans]) != [p["journey_id"] for p in plans]:
        raise ValueError("frozen journey selection differs from the reproducible selection")
    refs = [read(p) for p in sorted((root / "generation/plan/snapshot/references").glob("*.json"))]
    return config, plans, catalog, refs


def save(root: Path, state: dict) -> None:
    write(root / "checkpoint.json", {"state": state, "state_sha256": fingerprint(state)})


def task_for(settings: dict, state: dict, plans: list[dict], config: dict) -> dict:
    req = engine.current_request(state, plans, config)
    number = state["calls"] + 1
    task = {"format_version": 1, "run_id": settings["run_id"], "profile": settings["profile"],
            "task_id": f"{settings['run_id']}-T{number:06d}", "sequence": number,
            "journey_id": plans[state["position"]]["journey_id"], "attempt": state["attempt"],
            "request_sha256": fingerprint(req), "request": req}
    task["task_sha256"] = fingerprint(task)
    return task


def load(root: Path) -> tuple:
    root = root.resolve()
    if read(root / "settings.seal.json")["settings_sha256"] != file_hash(root / "settings.json"):
        raise ValueError("profile/settings changed after initialization")
    settings = read(root / "settings.json")
    config, plans, catalog, refs = inputs(root, settings)
    checkpoint = read(root / "checkpoint.json")
    state = checkpoint["state"]
    if checkpoint["state_sha256"] != fingerprint(state):
        raise ValueError("checkpoint checksum mismatch")
    paths = sorted((root / "events").glob("*.json"))
    if len(paths) < state["calls"]:
        raise ValueError("response journal is incomplete")
    previous = None
    events = []
    for index, path in enumerate(paths, 1):
        event = read(path)
        if path.name != f"{index:06d}.json" or event["sequence"] != index or event["previous_sha256"] != previous:
            raise ValueError("response journal order/checksum chain changed")
        if event["run_id"] != settings["run_id"] or fingerprint(event["request"]) != event["request_sha256"]:
            raise ValueError("response journal request changed")
        previous = fingerprint(event)
        if index == state["calls"] and previous != state["last_event_sha256"]:
            raise ValueError("checkpoint and response journal diverged")
        events.append(event)
    # An event is durable before its checkpoint. Recover a crash in that window.
    for event in events[state["calls"]:]:
        expected = task_for(settings, state, plans, config)
        if event["task_sha256"] != expected["task_sha256"] or event["task_id"] != expected["task_id"]:
            raise ValueError("uncommitted event does not match the checkpoint task")
        state = engine.consume(state, plans, catalog, refs, config, event["request"], event["response"])
        state.update(last_event_sha256=fingerprint(event), issued_task_sha256=None)
        save(root, state)
    if state.get("issued_task_sha256") and state["status"] == "awaiting_task":
        task = task_for(settings, state, plans, config)
        if task["task_sha256"] != state["issued_task_sha256"]:
            raise ValueError("issued task differs from checkpoint")
        immutable_json(root / "tasks" / f"{task['sequence']:06d}.json", task)
    materialize(root, state, plans, config, events)
    return settings, state, config, plans, catalog, refs


def immutable_json(path: Path, value) -> None:
    if path.exists():
        if file_hash(path) != engine.json_file_hash(value):
            raise ValueError("recorded artifact changed: " + str(path.name))
    else:
        write(path, value)


def materialize(root: Path, state: dict, plans: list[dict], config: dict, events: list[dict] | None = None) -> None:
    """Recover missing derived files; never overwrite an existing transcript."""
    generation = root / "generation"
    if events is None:
        events = [read(p) for p in sorted((root / "events").glob("*.json"))]
    for event in events:
        immutable_json(generation / "calls" / f"{event['sequence']:06d}.json",
                       {"request_sha256": event["request_sha256"], "request": event["request"], "response": event["response"]})
    for review in state["reviews"]:
        immutable_json(generation / review["path"], review["record"])
    manifest = []
    for accepted in state["accepted"]:
        plan = plans[accepted["position"]]
        artifacts, errors = journey_artifacts(plan, accepted["history"], accepted["decisions"],
                                             accepted["review_sha256"], read(HERE / "transcript.schema.json"))
        if errors:
            raise ValueError("checkpoint contains an invalid accepted journey")
        for artifact in artifacts:
            relative = f"transcripts/{artifact['transcript_id']}.json"
            immutable_json(generation / relative, artifact)
            manifest.append({"transcript_id": artifact["transcript_id"], "customer_id": artifact["customer_id"],
                             "journey_id": artifact["journey_id"], "path": relative, "sha256": file_hash(generation / relative),
                             "audio_path": None, "review_status": "automated_approved", "review_path": accepted["review_path"]})
    existing = {str(p.relative_to(generation)) for p in (generation / "transcripts").glob("*.json")}
    if existing != {row["path"] for row in manifest}:
        raise ValueError("unexpected transcript outside the accepted manifest")
    if state["status"] not in FINISHED:
        write(generation / "manifest.json", manifest)
        write(generation / "quarantine.json", state["quarantine"])
        write(root / "staging.json", {k: state[k] for k in ("position", "attempt", "phase", "history", "candidate", "feedback")})


def estimate(state: dict, plans: list[dict], config: dict, policy: dict) -> dict:
    if state["position"] == len(plans):
        return {"required_tokens": 0, "whole_dataset_estimate_tokens": 0, "method": "no model work remaining"}
    def journey_estimate(cursor):
        req = engine.current_request(cursor, plans, config)
        sessions = len(plans[cursor["position"]]["sessions"]) - len(cursor["history"])
        if cursor["phase"] == "duplicate":
            sessions -= 1
        judges = (sessions * 3 + (len(cursor["similarity"]["matches"]) - cursor["duplicate_cursor"] if cursor["phase"] == "duplicate" else 0)) if config["duplicates"]["judge_ambiguous"] else 0
        output = sessions * config["generation"]["max_output_tokens"] + (judges + 1) * config["review"]["max_output_tokens"]
        # Character counts and reused task sizes are an explicit heuristic,
        # not a tokenizer, guaranteed upper bound, or measured host usage.
        inputs_estimate = len(encode(req)) * max(1, sessions + judges + 1)
        return math.ceil(policy["estimate_safety_factor"] * (inputs_estimate + output + policy["repair_allowance_tokens"])) + policy["checkpoint_reserve_tokens"]

    current = journey_estimate(state)
    whole = current
    for position in range(state["position"] + 1, len(plans)):
        cursor = engine.initial_state()
        cursor["position"] = position
        cursor["generation_unit"] = state.get("generation_unit", "session")
        whole += journey_estimate(cursor)
    return {"required_tokens": current, "whole_dataset_estimate_tokens": math.ceil(whole),
            "method": "heuristic: task JSON characters repeated per anticipated request, output caps, up to 3 judges/session, review, one repair allowance and reserve per journey; not measured tokens or an upper bound", "tokenizer": "unknown"}


def report(root: Path, settings: dict, state: dict, plans: list[dict], config: dict, catalog: list[dict]) -> dict:
    counts = coverage([plans[a["position"]] for a in state["accepted"]], catalog, config["requirements"])
    result = {"run_id": settings["run_id"], "profile": settings["profile"], "status": state["status"],
              "requested_samples": settings.get("samples"),
              "sample_count_met": counts["counts"]["transcripts"] == settings["samples"] if settings.get("samples") is not None else None,
              "selected_journey_ids": [p["journey_id"] for p in plans],
              "api_calls": 0, "model_tasks_submitted": state["calls"], "max_model_tasks": settings["max_model_tasks"],
              "api_calls_scope": "direct pipeline API calls only; active-agent host usage is not measured",
              "accepted_journeys": len(state["accepted"]), "production_transcripts": counts["counts"]["transcripts"],
              "dataset_requirements_met": counts["transcript_requirements_met"], "coverage": counts,
              "review_mode": "same_agent_self_review", "pause_reason": state.get("pause_reason"),
              "token_estimate": estimate(state, plans, config, settings["token_policy"]), "run": str(root.resolve())}
    write(root / "agent_report.json", result)
    command = shlex.join(["python3", "-B", "-m", "dataset.pipeline.agent", "resume", "--run", str(root.resolve())])
    (root / "RESUME.md").write_text(
        "# Tiếp tục pipeline transcript\n\n"
        f"Run: `{settings['run_id']}`; profile: `{settings['profile']}`; trạng thái: `{state['status']}`.\n\n"
        f"Đã nhận {state['calls']} response, chấp nhận {len(state['accepted'])} hành trình. "
        "Đọc HANDS_OFF.md của phiên bản mã đã đóng băng và agent_report.json. Không đổi profile hoặc reset retry/budget.\n\n"
        f"```bash\n{command}\n```\n\n"
        "Nếu chỉ dừng do hết batch với context unknown, lệnh resume cho phép batch tiếp trong cùng session; không tự động lặp resume nếu người dùng chưa yêu cầu. "
        "Nếu thực sự bắt đầu context mới, thêm `--fresh-context`. Nếu host cung cấp số token còn lại, "
        "thêm `--remaining-context-tokens <số thực tế> --context-source <nguồn đo>`; nếu không, để unknown. "
        "Nếu dừng vì quota, chỉ thêm `--usage-restored` khi host đã cho phép tiếp tục. "
        "Sau resume chạy `next --run <đường dẫn run>` và submit task được trả về. "
        "Nếu ready_to_finalize, chạy finalize thay vì next. Không ghi đè transcript đã chấp nhận.\n\n"
        "Checkpoint: `checkpoint.json`; journal: `events/`; config/nguồn: `generation/plan/`; "
        "hash mã/guide: `settings.json`; bản sao nguồn chỉ có khi init với `--archive`. "
        "Lightweight không tự khôi phục mã cũ; giữ checkout tương ứng để resume. Checksum nằm trong checkpoint và các seal. "
        "Không tự sửa checksum để bỏ qua lỗi; không tự đổi model khi hết quota.\n", encoding="utf-8")
    return result


def next_task(root: Path, *, remaining: int | None = None, source: str | None = None) -> dict:
    with locked(root):
        settings, state, config, plans, catalog, _ = load(root)
        if state["status"] in FINISHED or state["status"] in {"ready_to_finalize", "paused_token_budget", "paused_usage_limit", "exhausted_task_budget"}:
            return report(root, settings, state, plans, config, catalog)
        if remaining is not None and (type(remaining) is not int or remaining < 0 or not source or not source.strip()):
            raise ValueError("remaining context requires a nonnegative integer and an explicit measurement source")
        observation = {"at": stamp(), "remaining_context_tokens": remaining if remaining is not None else "unknown",
                       "source": source if remaining is not None else "not_available", "before_task": state["calls"] + 1}
        state["budget_observations"].append(observation)
        budget = estimate(state, plans, config, settings["token_policy"])
        if state["calls"] >= settings["max_model_tasks"]:
            state.update(status="exhausted_task_budget", pause_reason="fixed model-task limit reached; retries are not reset")
        elif remaining is not None and remaining < budget["required_tokens"]:
            state.update(status="paused_token_budget", pause_reason="insufficient reported context for remaining journey work and checkpoint reserve")
        elif remaining is None and state["position"] - state["batch_start"] >= settings["token_policy"]["unknown_batch_journeys"]:
            state.update(status="paused_token_budget", pause_reason="unknown context budget: batch complete; explicitly resume to authorize another batch")
        else:
            task = task_for(settings, state, plans, config)
            path = root / "tasks" / f"{task['sequence']:06d}.json"
            immutable_json(path, task)
            state["issued_task_sha256"] = task["task_sha256"]
            save(root, state)
            result = report(root, settings, state, plans, config, catalog)
            return {**result, "task_file": str(path.resolve()), "response_schema": str((HERE / "agent_response.schema.json").resolve()),
                    "submission_template": {"run_id": task["run_id"], "task_id": task["task_id"], "task_sha256": task["task_sha256"],
                                            "response": "Replace this string with JSON matching task.request.schema"}}
        save(root, state)
        return report(root, settings, state, plans, config, catalog)


def submit(root: Path, response_file: Path) -> dict:
    # Validate the transport envelope before changing the run or its budget.
    envelope = read(response_file)
    errors = validate_schema(envelope, read(HERE / "agent_response.schema.json"))
    if errors:
        raise ValueError("invalid submission envelope: " + "; ".join(errors))
    with locked(root):
        settings, state, config, plans, catalog, refs = load(root)
        if state["status"] != "awaiting_task" or state["calls"] >= settings["max_model_tasks"]:
            raise ValueError("run is paused, finished or out of task budget; inspect status")
        task = task_for(settings, state, plans, config)
        if any(envelope[k] != task[k] for k in ("run_id", "task_id", "task_sha256")) or state["issued_task_sha256"] != task["task_sha256"]:
            raise ValueError("stale, unissued, wrong-run or mismatched task response")
        response = {"completed": True, "text": json.dumps(envelope["response"], ensure_ascii=False, allow_nan=False),
                    "raw": {"source": "active_agent_file_submission"},
                    "metadata": {"model": state["sessions"][-1]["agent"]["model"],
                                 "review_mode": "same_agent_self_review", "session": len(state["sessions"])}}
        event = {"sequence": task["sequence"], "run_id": settings["run_id"], "task_id": task["task_id"],
                 "task_sha256": task["task_sha256"], "request_sha256": task["request_sha256"],
                 "previous_sha256": state["last_event_sha256"], "request": task["request"], "response": response}
        updated = engine.consume(state, plans, catalog, refs, config, task["request"], response)
        immutable_json(root / "events" / f"{task['sequence']:06d}.json", event)
        updated.update(last_event_sha256=fingerprint(event), issued_task_sha256=None)
        save(root, updated)
        materialize(root, updated, plans, config)
        return report(root, settings, updated, plans, config, catalog)


def resume(root: Path, *, fresh: bool = False, usage_restored: bool = False, info: dict | None = None,
           remaining: int | None = None, source: str | None = None) -> dict:
    if remaining is not None and (type(remaining) is not int or remaining < 0 or not source or not source.strip()):
        raise ValueError("remaining context requires a nonnegative integer and an explicit measurement source")
    with locked(root):
        settings, state, config, plans, catalog, _ = load(root)
        if state["status"] in FINISHED:
            verify_release(root)
            return read(root / "final_report.json")
        if state["status"] in {"ready_to_finalize", "exhausted_task_budget"}:
            return report(root, settings, state, plans, config, catalog)
        if state["status"] == "paused_usage_limit" and not usage_restored:
            raise ValueError("usage limit is still pending; confirm actual restoration with --usage-restored")
        same_session_batch = (state["status"] == "paused_token_budget"
                              and (state.get("pause_reason") or "").startswith("unknown context budget: batch complete")
                              and not fresh and remaining is None)
        if state["status"] == "paused_token_budget" and not fresh and remaining is None and not same_session_batch:
            raise ValueError("token pause requires --fresh-context or a new host-reported remaining budget")
        if fresh or same_session_batch:
            state["batch_start"] = state["position"]
        if state["status"] in {"paused_usage_limit", "paused_token_budget"}:
            if remaining is not None:
                state["batch_start"] = state["position"]
            state.update(status="awaiting_task", pause_reason=None, issued_task_sha256=None)
        state["sessions"].append({"at": stamp(), "agent": info or agent_info(), "fresh_context_attested": fresh,
                                  "same_session_batch_authorized": same_session_batch,
                                  "remaining_context_tokens": remaining if remaining is not None else "unknown"})
        save(root, state)
    return next_task(root, remaining=remaining, source=source)


def pause(root: Path, reason: str) -> dict:
    if reason not in {"token_budget", "usage_limit"}:
        raise ValueError("pause reason must be token_budget or usage_limit")
    with locked(root):
        settings, state, config, plans, catalog, _ = load(root)
        if state["status"] == "awaiting_task":
            state.update(status="paused_" + reason, pause_reason="agent reported " + reason, issued_task_sha256=None)
            save(root, state)
        return report(root, settings, state, plans, config, catalog)


def inspect(root: Path) -> dict:
    with locked(root):
        settings, state, config, plans, catalog, _ = load(root)
        if state["status"] in FINISHED:
            verify_release(root)
        return report(root, settings, state, plans, config, catalog)


def finalize(root: Path) -> dict:
    with locked(root):
        settings, state, config, plans, catalog, _ = load(root)
        if state["status"] in FINISHED and (root / "final.seal.json").is_file():
            verify_release(root)
            return read(root / "final_report.json")
        if state["status"] != "ready_to_finalize" and state["status"] not in FINISHED:
            raise ValueError("run has unfinished tasks; resume/checkpoint instead of claiming completion")
        generation = root / "generation"
        verify_plan(generation / "plan", expected_code=settings["code_sha256"])
        counts = coverage([plans[a["position"]] for a in state["accepted"]], catalog, config["requirements"])
        counts["scope"] = "active coding agent responses passing checks and same-agent self-review"
        status = "quarantined" if state["quarantine"] else "automated_release" if counts["transcript_requirements_met"] else "automated_partial_coverage"
        manifest = read(generation / "manifest.json")
        provider = {"provider": "active_coding_agent", "review_mode": "same_agent_self_review", "sessions": state["sessions"]}
        write(generation / "run.json", {"kind": "generation", "created_at": settings["created_at"], "status": status,
                                       "runtime": runtime(), "provider": provider, "code_sha256": settings["code_sha256"],
                                       "plan_seal_sha256": file_hash(generation / "plan/seal.json"), "selected_journeys": len(plans),
                                       "limit": settings["limit"], "samples": settings.get("samples"),
                                       "journey_ids": settings.get("journey_ids"),
                                       "model_calls": state["calls"], "stop_reason": None,
                                       "review_mode": "same_agent_self_review", "audio_generated": False})
        write(generation / "coverage_report.json", counts)
        write(generation / "validation_report.json", {"status": status, "exported_transcripts": len(manifest),
                                                      "accepted_journeys": len(state["accepted"]), "quarantined": state["quarantine"],
                                                      "review_mode": "same_agent_self_review", "semantic_equivalence_proven": False})
        write(generation / "automated_review_report.json", {"mode": "same_agent_self_review", "reviews": state["reviews"],
                                                            "limitation": "same agent supplies generation and review; not independent evaluation"})
        write(generation / "duplicate_report.json", {"thresholds": config["duplicates"], "attempts": state["audit"],
                                                     "limitation": "heuristics and self-judgment may miss semantic duplicates"})
        write_dataset_card(generation, counts, status, provider)
        with (generation / "DATASET_CARD.md").open("a", encoding="utf-8") as stream:
            stream.write("\nReview: `same_agent_self_review`; không phải đánh giá độc lập. Model không xác định được ghi unknown.\n")
        write(generation / "provenance.json", {
            "format_version": 1, "profile": settings["profile"],
            "archive_mode": settings.get("archive_mode", "full"),
            "seed": config["planning"]["seed"], "effective_config": config,
            "code_prompt_schema_sha256": settings["code_sha256"],
            "source_sha256": read(generation / "plan/seal.json")["files"],
            "execution_code_sha256": execution_code(root, settings),
            "resume_policy_upgrade": read(root / "resume_policy_upgrade.json") if (root / "resume_policy_upgrade.json").exists() else None,
            "generation": provider, "validation": read(generation / "validation_report.json"),
            "coverage": counts,
            "limitation": "Hashes identify inputs but cannot restore missing content; model output is not deterministic."
        })
        write(generation / "seal.json", {"files": files_manifest(generation)})
        verified = verify_run(generation)
        replay_result = {"status": "skipped", "reason": "lightweight mode: replay is optional",
                         "api_calls": 0}
        if settings.get("archive_mode", "full") == "full":
            # Reuse the original synchronous engine as an independent execution path.
            # A temporary directory makes an interrupted finalize safely retryable.
            with tempfile.TemporaryDirectory(prefix="replay-", dir=root) as temp:
                replay_root = Path(temp) / "generation"
                replay = generate_run(generation / "plan", replay_root, ReplayProvider(generation), limit=settings["limit"],
                                      samples=settings.get("samples"), journey_ids=settings.get("journey_ids"))
                verify_run(replay_root)
                if read(replay_root / "manifest.json") != manifest or any(file_hash(replay_root / row["path"]) != row["sha256"] for row in manifest):
                    raise ValueError("recorded-response replay differs from accepted agent transcripts")
                if replay["model_calls"] != state["calls"] or replay["status"] != status:
                    raise ValueError("agent transitions diverged from recorded-response replay")
            replay_result = {"status": "passed", "byte_identical_transcripts_and_manifest": True, "api_calls": 0}
        state["status"] = "quarantined" if state["quarantine"] else "completed" if counts["transcript_requirements_met"] else "partial_coverage"
        save(root, state)
        result = report(root, settings, state, plans, config, catalog)
        result.update(output_verification=verified, replay=replay_result)
        write(root / "final_report.json", result)
        # Mutable reports, lock and the interpreter installation are not release artifacts.
        release = {str(p.relative_to(root)): file_hash(p) for prefix in ("generation", "events", "tasks", "reproducibility")
                   for p in (root / prefix).rglob("*") if p.is_file() and p.suffix != ".partial"}
        for name in ("settings.json", "settings.seal.json", "checkpoint.json", "final_report.json") + (("resume_policy_upgrade.json",) if (root / "resume_policy_upgrade.json").exists() else ()):
            release[name] = file_hash(root / name)
        write(root / "final.seal.json", {"files": release})
        return result


def verify_release(root: Path) -> dict:
    expected = read(root / "final.seal.json")["files"]
    actual = {str(p.relative_to(root)): file_hash(p) for prefix in ("generation", "events", "tasks", "reproducibility")
              for p in (root / prefix).rglob("*") if p.is_file() and p.suffix != ".partial"}
    for name in ("settings.json", "settings.seal.json", "checkpoint.json", "final_report.json") + (("resume_policy_upgrade.json",) if (root / "resume_policy_upgrade.json").exists() else ()):
        actual[name] = file_hash(root / name)
    if actual != expected:
        raise ValueError("final agent release checksum changed")
    return verify_run(root / "generation")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="check environment and freeze an explicit M1/M2 profile")
    init.add_argument("--profile", choices=tuple(PROFILES), required=True)
    init.add_argument("--output", type=Path, required=True)
    size = init.add_mutually_exclusive_group()
    size.add_argument("--limit", type=int, help="pilot journeys; default processes the whole profile")
    size.add_argument("--samples", type=int, help="exact transcript count, selecting only complete journeys")
    size.add_argument("--journey-ids", nargs="+", help="specific complete journeys, retained in frozen plan order")
    init.add_argument("--reference-dir", type=Path, action="append", default=[])
    init.add_argument("--generation-unit", choices=("journey", "session"), help="default: journey; archive defaults to session")
    init.add_argument("--archive", action="store_true", help="archive source code and require recorded-response replay at finalize")
    init.add_argument("--agent-info", type=Path)
    init.add_argument("--token-policy", type=Path, help="JSON overrides for frozen token reserves/batch policy")
    upgrade = sub.add_parser("upgrade-resume-policy", help="explicitly adopt same-session batch resume for an unfinished lightweight run")
    upgrade.add_argument("--run", type=Path, required=True)
    for command in ("next", "submit", "status", "resume", "pause", "finalize", "verify"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--run", type=Path, required=True)
        if command in {"next", "resume"}:
            cmd.add_argument("--remaining-context-tokens", type=int)
            cmd.add_argument("--context-source")
        if command == "submit":
            cmd.add_argument("--response", type=Path, required=True)
        if command == "resume":
            cmd.add_argument("--fresh-context", action="store_true")
            cmd.add_argument("--usage-restored", action="store_true")
            cmd.add_argument("--agent-info", type=Path)
        if command == "pause":
            cmd.add_argument("--reason", choices=("token_budget", "usage_limit"), required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.profile, args.output.resolve(), limit=args.limit,
                                references=args.reference_dir, info=agent_info(args.agent_info),
                                policy=read(args.token_policy) if args.token_policy else None, samples=args.samples,
                                journey_ids=args.journey_ids, archive=args.archive, generation_unit=args.generation_unit)
        else:
            root = args.run.resolve()
            if args.command == "upgrade-resume-policy":
                receipt = upgrade_resume_policy(root)
                result = {"status": "policy_upgraded", "receipt": receipt}
            elif args.command == "next":
                result = next_task(root, remaining=args.remaining_context_tokens, source=args.context_source)
            elif args.command == "submit":
                result = submit(root, args.response)
            elif args.command == "resume":
                result = resume(root, fresh=args.fresh_context, usage_restored=args.usage_restored,
                                info=agent_info(args.agent_info), remaining=args.remaining_context_tokens, source=args.context_source)
            elif args.command == "pause":
                result = pause(root, args.reason)
            elif args.command == "finalize":
                result = finalize(root)
            elif args.command == "verify":
                result = verify_release(root)
            else:
                result = inspect(root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3 if result["status"] == "partial_coverage" else 2 if result["status"] in {"quarantined", "exhausted_task_budget"} else 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, IndexError) as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
