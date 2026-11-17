from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from .common import write


def secret_name(name: str) -> bool:
    return any(word in name.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))


def redact(text: str, environ: dict | None = None) -> str:
    env = os.environ if environ is None else environ
    for key, value in env.items():
        if value and secret_name(key):
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)


def api_free_environment() -> dict:
    env = {k: v for k, v in os.environ.items() if not secret_name(k)}
    env.update(PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_CACHE_DIR="1",
               PYTHONDONTWRITEBYTECODE="1")
    return env


def run_command(command: list[str], cwd: Path, log: Path, *, env: dict | None = None,
                timeout: int = 300) -> subprocess.CompletedProcess:
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8",
                                errors="replace", capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
        log.write_text(redact(f"TIMEOUT\n{stdout}\n{stderr}"), encoding="utf-8")
        raise RuntimeError("command timed out; inspect the sanitized log") from None
    log.write_text(redact(f"$ {shlex.join(command)}\nexit_code={result.returncode}\n{result.stdout}\n{result.stderr}"), encoding="utf-8")
    return result


def save_report(output: Path, report: dict) -> None:
    # Sanitize even structured error details before writing either representation.
    def sanitize(value):
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, dict):
            return {redact(str(k)): sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [sanitize(v) for v in value]
        return value

    safe = sanitize(report)
    write(output / "environment_report.json", safe)
    rows = ["# Báo cáo tự động môi trường và pipeline", "",
            f"- Chế độ: `{safe['mode']}`", f"- Trạng thái: `{safe['status']}`",
            f"- Live ready: `{safe.get('live_ready', False)}`", "",
            "| Bước | Trạng thái | Chi tiết |", "| --- | --- | --- |"]
    for stage in safe.get("stages", []):
        detail = str(stage.get("detail", "")).replace("|", "/").replace("\n", " ")
        rows.append(f"| {stage['name']} | {stage['status']} | {detail} |")
    rows += ["", "Chi tiết: `environment_report.json`, `test_results.json`, `logs/`.",
             "Test fixture không phải transcript thật do LLM sinh; skipped live không chứng minh live readiness."]
    (output / "environment_report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
