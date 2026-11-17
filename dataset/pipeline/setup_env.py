"""One-command managed environment setup and end-to-end execution.

Default is API-free verification. --mode pilot/full explicitly enables live API
calls, requires a call budget, and never substitutes an offline provider.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .automation_utils import api_free_environment, redact, run_command, save_report
from .common import HERE, file_hash, new_directory, read, write

REPO = HERE.parents[1]
MARKER = ".dataset-pipeline-env.json"


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
        if not match or normalized(match[1]) in pins:
            raise ValueError("lock must contain distinct exact name==version pins, without executable pip options")
        pins[normalized(match[1])] = match[2]
    if "openai" not in pins:
        raise ValueError("lock must pin the OpenAI SDK")
    return pins


def python_path(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def inspect_environment(python: Path, output: Path) -> dict:
    code = ("import sys,json,importlib.metadata as m; "
            "print(json.dumps({'python':list(sys.version_info[:2]),'prefix':sys.prefix,"
            "'packages':{d.metadata['Name']:d.version for d in m.distributions() if d.metadata['Name']}}))")
    result = run_command([str(python), "-c", code], REPO, output / "logs/environment_inventory.log",
                         env=api_free_environment())
    if result.returncode:
        raise RuntimeError("managed environment interpreter is not usable; choose a fresh --venv path")
    return json.loads(result.stdout)


def dependency_errors(inventory: dict, pins: dict) -> list[str]:
    installed = {normalized(k): v for k, v in inventory["packages"].items()}
    errors = [f"{name}: expected {version}, found {installed.get(name, 'missing')}"
              for name, version in pins.items() if installed.get(name) != version]
    extra = installed.keys() - pins.keys() - {"pip", "setuptools", "wheel"}
    if extra:
        errors.append("unexpected packages: " + ", ".join(sorted(extra)))
    return errors


def ensure_environment(environment: Path, lock: Path, output: Path, wheelhouse: Path | None = None) -> dict:
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11+ is required")
    pins = parse_lock(lock)
    environment = environment.resolve()
    if environment == REPO or REPO.is_relative_to(environment) or environment.is_relative_to(HERE):
        raise ValueError("venv must be outside code and must not contain the repository")
    expected = {"managed_by": "dataset.pipeline.setup_env", "format_version": 1,
                "python": list(sys.version_info[:2]), "platform": platform.system(),
                "lock_sha256": file_hash(lock)}
    marker = environment / MARKER
    existed = environment.exists()
    if existed:
        if not marker.is_file():
            raise ValueError("refusing to modify an unmanaged environment; use a new --venv path")
        actual = read(marker)
        if not isinstance(actual, dict):
            raise ValueError("managed environment marker is invalid; use a fresh --venv path")
        if any(actual.get(k) != v for k, v in expected.items()):
            raise ValueError("environment Python/platform/lock changed; choose a new --venv path")
    else:
        venv.EnvBuilder(with_pip=True).create(environment)
        write(marker, {**expected, "status": "installing"})
        actual = {"status": "installing"}
    python = python_path(environment)
    if not python.is_file():
        raise RuntimeError("managed environment has no interpreter; use a fresh --venv path")
    if actual.get("status") != "ready":
        command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
                   "--retries", "0", "--timeout", "20", "-r", str(lock.resolve())]
        if wheelhouse:
            command += ["--no-index", "--find-links", str(wheelhouse.resolve())]
        result = run_command(command, REPO, output / "logs/install.log", env=api_free_environment(), timeout=300)
        if result.returncode:
            raise RuntimeError("dependency installation failed; inspect logs/install.log; retry with a new output directory, or provide --wheelhouse")
    inventory = inspect_environment(python, output)
    if inventory["python"] != expected["python"] or Path(inventory["prefix"]).resolve() != environment:
        raise ValueError("environment interpreter identity differs from its marker")
    errors = dependency_errors(inventory, pins)
    if errors:
        raise ValueError("environment dependency drift; use a fresh --venv path: " + "; ".join(errors))
    result = run_command([str(python), "-m", "pip", "check"], REPO, output / "logs/pip_check.log",
                         env=api_free_environment())
    if result.returncode:
        raise RuntimeError("pip check failed; inspect logs/pip_check.log")
    write(marker, {**expected, "status": "ready"})
    write(output / "environment_inventory.json", inventory)
    shutil.copyfile(lock, output / "requirements.lock")
    return {"status": "passed", "reused": existed and actual.get("status") == "ready",
            "python": str(python), "environment": str(environment), "lock_sha256": expected["lock_sha256"]}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("offline", "pilot", "full"), default="offline")
    p.add_argument("--config", type=Path, default=HERE / "configs/hackathon_m1.json")
    p.add_argument("--output", type=Path, help="new directory; default creates a timestamped run")
    p.add_argument("--venv", type=Path, default=REPO / "outputs/benchmark/dataset-managed-venv")
    p.add_argument("--lock", type=Path, default=HERE / "requirements.lock")
    p.add_argument("--wheelhouse", type=Path, help="install from local wheels without contacting a registry")
    p.add_argument("--model")
    p.add_argument("--review-model")
    p.add_argument("--max-api-calls", type=int, help="required live budget, including environment probes and review")
    p.add_argument("--limit", type=int, default=1, help="pilot journeys; full uses all")
    return p


def main(argv=None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.mode != "offline" and (args.max_api_calls is None or args.max_api_calls < 1):
        p.error("live modes require explicit positive --max-api-calls")
    if args.limit < 1:
        p.error("--limit must be positive")
    output = args.output or REPO / "outputs/benchmark" / ("dataset_automation_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:8])
    try:
        environment = args.venv.resolve()
        if environment == REPO or REPO.is_relative_to(environment) or environment.is_relative_to(HERE):
            raise ValueError("venv must be outside code and must not contain the repository")
        if output.resolve().is_relative_to(environment) or environment.is_relative_to(output.resolve()):
            raise ValueError("output and venv directories must be separate")
        output = new_directory(output)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__,
                          "detail": "choose a fresh output and a separate managed venv outside code"}))
        return 2
    report = {"format_version": 1, "mode": args.mode, "status": "running", "live_ready": False,
              "created_at": datetime.now(timezone.utc).isoformat(), "stages": []}
    save_report(output, report)
    lockfile = args.venv.resolve().parent / (args.venv.name + ".setup.lock")
    locked = False
    try:
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        with lockfile.open("x", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        locked = True
        setup = ensure_environment(args.venv, args.lock, output, args.wheelhouse)
        report["stages"].append({"name": "environment_setup", "status": "passed", "detail": setup})
        save_report(output, report)
        worker = [setup["python"], "-B", "-W", "ignore::ResourceWarning", "-m", "dataset.pipeline.automation",
                  "--mode", args.mode, "--config", str(args.config.resolve()), "--output", str(output), "--limit", str(args.limit)]
        if args.model:
            worker += ["--model", args.model]
        if args.review_model:
            worker += ["--review-model", args.review_model]
        if args.max_api_calls is not None:
            worker += ["--max-api-calls", str(args.max_api_calls)]
        env = api_free_environment() if args.mode == "offline" else dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = run_command(worker, REPO, output / "logs/workflow.log", env=env,
                             timeout=max(600, (args.max_api_calls or 0) * 75 + 600))
        report = read(output / "environment_report.json")
        if report["status"] == "running":
            raise RuntimeError("workflow ended without a final report")
        print(json.dumps({"status": report["status"], "mode": args.mode, "report": str(output / 'environment_report.md')}, ensure_ascii=False))
        return result.returncode
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        report = read(output / "environment_report.json")
        report.update(status="blocked", error_type=type(exc).__name__)
        report["stages"].append({"name": "setup_or_workflow", "status": "blocked", "detail": redact(str(exc))})
        save_report(output, report)
        print(json.dumps({"status": "blocked", "report": str(output / 'environment_report.md')}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        report = read(output / "environment_report.json")
        report.update(status="interrupted")
        save_report(output, report)
        return 130
    finally:
        if locked:
            lockfile.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
