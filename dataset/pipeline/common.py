from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".partial")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def new_directory(path: Path) -> Path:
    path = path.resolve()
    if HERE.is_relative_to(path) or (path.is_relative_to(HERE) and not path.is_relative_to(HERE / "output")):
        raise ValueError("output must be outside pipeline code or inside pipeline/output, and must not contain code")
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    (path / ".gitignore").write_text("*\n", encoding="utf-8")
    return path


def code_hashes() -> dict[str, str]:
    return {str(p.relative_to(HERE)): file_hash(p) for p in sorted(HERE.rglob("*"))
            if p.is_file() and p.suffix in {".py", ".md", ".json"}
            and not p.is_relative_to(HERE / "output")
            and "tests" not in p.parts and "configs" not in p.parts}


def files_manifest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): file_hash(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name not in {".gitignore", "seal.json"} and p.suffix != ".partial"}


def verify_files(root: Path, expected: dict[str, str]) -> None:
    if files_manifest(root) != expected:
        raise ValueError(f"snapshot contents/checksums changed: {root.name}")


def runtime() -> dict:
    return {"python": platform.python_version(), "implementation": platform.python_implementation()}
