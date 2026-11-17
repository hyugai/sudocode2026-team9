"""Noninteractive readiness checks. Never reads or prints credential values."""
from __future__ import annotations

import importlib.metadata
import os
import sys
import tempfile
from pathlib import Path

from .common import HERE, read, write
from .domain import source_paths
from .planner import validate_config

REPO = HERE.parents[1]


def selected_models(config: dict, model: str | None, reviewer: str | None) -> tuple[str, str]:
    model = model or os.environ.get("OPENAI_MODEL") or config["generation"]["model"]
    reviewer = reviewer or os.environ.get("OPENAI_REVIEW_MODEL") or config["review"]["model"]
    return model, model if reviewer == "SAME_AS_GENERATOR" else reviewer


def check_environment(config_path: Path, output: Path, *, live: bool = False,
                      model: str | None = None, reviewer: str | None = None) -> dict:
    checks = []

    def add(name: str, status: str, detail: str):
        checks.append({"name": name, "status": status, "detail": detail})

    add("python", "passed" if sys.version_info >= (3, 11) else "blocked", sys.version.split()[0])
    add("virtual_environment", "passed" if sys.prefix != sys.base_prefix else "blocked",
        "active interpreter belongs to a virtual environment" if sys.prefix != sys.base_prefix else "run through setup_env")
    try:
        sdk = importlib.metadata.version("openai")
        add("openai_sdk", "passed" if sdk.split(".")[0] == "2" else "blocked", sdk)
    except importlib.metadata.PackageNotFoundError:
        add("openai_sdk", "blocked", "install the locked pipeline dependencies")
    try:
        with tempfile.TemporaryDirectory(dir=output):
            pass
        add("output_directory", "passed", "writable")
    except OSError:
        add("output_directory", "blocked", "directory must exist and be writable")
    config = None
    try:
        config = read(config_path)
        validate_config(config)
        root = (config_path.resolve().parent / config["domain"]["root"]).resolve()
        paths = source_paths(root, config["domain"])
        if not paths or any(not p.is_file() for p in paths):
            raise ValueError("missing source files")
        add("configuration_and_sources", "passed", f"{len(paths)} configured domain source files")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        add("configuration_and_sources", "blocked", f"invalid/missing inputs: {type(exc).__name__}")
    try:
        for name in ("response.schema.json", "transcript.schema.json", "review.schema.json"):
            if not isinstance(read(HERE / name), dict):
                raise ValueError("invalid schema")
        add("schemas", "passed", "three JSON schemas readable")
    except (OSError, ValueError):
        add("schemas", "blocked", "schema files missing or invalid")
    models = None
    if live:
        if config is not None:
            gen, rev = selected_models(config, model, reviewer)
            models = {"generation": gen, "review": rev}
            valid = all(isinstance(x, str) and x.strip() and x != "SET_OPENAI_MODEL" for x in (gen, rev))
            add("model_configuration", "passed" if valid else "blocked", "explicit models configured" if valid else "choose generation and review models")
        add("credential_presence", "passed" if os.environ.get("OPENAI_API_KEY") else "blocked",
            "configured" if os.environ.get("OPENAI_API_KEY") else "OPENAI_API_KEY is absent")
    else:
        add("model_configuration", "skipped", "API-free mode does not require model IDs")
        add("credential_presence", "skipped", "API-free mode does not require credentials")
    return {"status": "blocked" if any(c["status"] in {"blocked", "failed"} for c in checks) else "passed",
            "checks": checks, "models": models, "live_connectivity": "not_checked"}


def live_preflight(models: dict, output: Path, budget: int) -> dict:
    """One minimal Responses/schema request per distinct model, not model listing."""
    from .providers import OpenAIProvider
    from .runner import parse_response

    unique = list(dict.fromkeys(models.values()))
    if budget < len(unique):
        return {"status": "blocked", "calls": 0, "reason": "budget cannot cover model probes", "models": []}
    request = {"kind": "environment_probe", "schema_name": "environment_probe",
               "messages": [{"role": "user", "content": "Return ok=true to confirm structured output support."}],
               "schema": {"type": "object", "additionalProperties": False, "required": ["ok"],
                          "properties": {"ok": {"type": "boolean"}}}}
    results = []
    for index, model in enumerate(unique):
        try:
            provider = OpenAIProvider(model, 1024)
            response = provider.request(request)
            write(output / "live_probes" / f"{index+1:02d}.json", {"model": model, "request": request, "response": response})
            if parse_response(response) != {"ok": True}:
                raise ValueError("probe did not match schema")
            results.append({"model": model, "status": "passed", "metadata": response.get("metadata")})
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            results.append({"model": model, "status": "blocked", "error_type": type(exc).__name__})
            return {"status": "blocked", "calls": index + 1, "models": results,
                    "reason": "model probe failed; check API access, model, quota or connectivity"}
    return {"status": "passed", "calls": len(unique), "models": results}
