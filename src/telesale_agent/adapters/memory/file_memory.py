from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


_SAFE_CUSTOMER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_FACT_LINE = re.compile(r"^- ([A-Za-z0-9_.-]+):\s*(.*)$")
_LOCKS_GUARD = threading.Lock()
_CUSTOMER_LOCKS: dict[str, threading.RLock] = {}


def _customer_lock(root: Path, customer_id: str) -> threading.RLock:
    key = str((root / customer_id).resolve())
    with _LOCKS_GUARD:
        return _CUSTOMER_LOCKS.setdefault(key, threading.RLock())


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace a file atomically without exposing partially written markdown."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class FileCustomerMemoryRepository:
    """Store customer memory as .md files outside the CRM database.

    Existing .mmd files are readable for backward compatibility. New writes
    always target .md files so callers do not need to know file layout.
    """

    def __init__(self, root: str | Path | None = None):
        project_root = Path(__file__).resolve().parents[4]
        configured_root = root or os.environ.get("CUSTOMER_MEMORY_ROOT")
        self._base_root = (
            Path(configured_root)
            if configured_root
            else project_root / "data" / "memory-root" / "users"
        )
        self.root = self._base_root

    def select_namespace(self, namespace: str) -> Path:
        """Select an isolated child root without deleting durable memory.

        Evaluation scenarios are independent experiments even when their CRM
        phone numbers overlap.  Keeping the immutable base root separately
        prevents repeated calls from nesting namespaces (SC-002/SC-003/...).
        Production callers never invoke this method and therefore keep the
        normal customer-id layout under ``_base_root``.
        """
        if not namespace or not _SAFE_CUSTOMER_ID.fullmatch(namespace):
            raise ValueError("memory namespace contains unsupported characters")
        base = self._base_root.resolve()
        selected = (base / namespace).resolve()
        if selected.parent != base:
            raise ValueError("memory namespace resolves outside the base root")
        selected.mkdir(parents=True, exist_ok=True)
        self.root = selected
        return selected

    def _user_dir(self, customer_id: str, *, create: bool = False) -> Path:
        if not customer_id or not _SAFE_CUSTOMER_ID.fullmatch(customer_id):
            raise ValueError("customer_id contains unsupported path characters")

        root = self.root.resolve()
        user_dir = (root / customer_id).resolve()
        if user_dir.parent != root:
            raise ValueError("customer_id resolves outside the memory root")

        if create:
            user_dir.mkdir(parents=True, exist_ok=True)
            for name in ("episodes", "atomic_facts", "foresights"):
                (user_dir / name).mkdir(exist_ok=True)
        return user_dir

    @staticmethod
    def _read_primary_or_legacy(primary: Path, legacy: Path) -> str:
        path = primary if primary.exists() else legacy
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @staticmethod
    def _read_collection(directory: Path) -> list[dict[str, str]]:
        if not directory.exists():
            return []

        # Prefer canonical .md if both extensions exist for the same logical file.
        selected: dict[str, Path] = {}
        for path in sorted(directory.glob("*.mmd")):
            selected[path.stem] = path
        for path in sorted(directory.glob("*.md")):
            selected[path.stem] = path

        return [
            {"source": path.name, "content": path.read_text(encoding="utf-8")}
            for path in sorted(selected.values(), key=lambda item: item.name)
        ]

    @staticmethod
    def _parse_facts(content: str) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        for raw_line in content.splitlines():
            match = _FACT_LINE.match(raw_line.strip())
            if not match:
                continue
            key, raw_value = match.groups()
            try:
                facts[key] = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                facts[key] = raw_value
        return facts

    def _load_facts(self, user_dir: Path) -> dict[str, Any]:
        facts_path = user_dir / "facts.md"
        legacy_path = user_dir / "facts.mmd"
        content = self._read_primary_or_legacy(facts_path, legacy_path)
        if content:
            return self._parse_facts(content)

        # Older memories stored `key: value` entries in dated atomic-fact
        # files. Fold them into one latest-value view until facts.md is written.
        facts: dict[str, Any] = {}
        for item in self._read_collection(user_dir / "atomic_facts"):
            facts.update(self._parse_facts(item["content"]))
        return facts

    def load(self, customer_id: str) -> dict[str, Any]:
        with _customer_lock(self.root, customer_id):
            user_dir = self._user_dir(customer_id)
            if not user_dir.exists():
                return {
                    "customer_id": customer_id,
                    "profile": "",
                    "behaviors": "",
                    "facts": {},
                    "atomic_facts": [],
                    "episodes": [],
                    "foresights": [],
                }

            return {
                "customer_id": customer_id,
                "profile": self._read_primary_or_legacy(
                    user_dir / "user.md", user_dir / "user.mmd"
                ),
                "behaviors": self._read_primary_or_legacy(
                    user_dir / "behaviors.md", user_dir / "behaviors.mmd"
                ),
                "facts": self._load_facts(user_dir),
                "atomic_facts": self._read_collection(user_dir / "atomic_facts"),
                "episodes": self._read_collection(user_dir / "episodes"),
                "foresights": self._read_collection(user_dir / "foresights"),
            }

    @staticmethod
    def _ensure_primary(primary: Path, legacy: Path, heading: str) -> None:
        if primary.exists():
            return
        if legacy.exists():
            _atomic_write_text(primary, legacy.read_text(encoding="utf-8"))
        else:
            _atomic_write_text(primary, f"# {heading}\n\n")

    @staticmethod
    def _append_line(path: Path, value: str) -> None:
        normalized = " ".join(value.strip().splitlines())
        if not normalized:
            raise ValueError("memory value must not be empty")
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        _atomic_write_text(path, existing + f"- {normalized}\n")

    def update_profile(self, customer_id: str, fact: str) -> dict[str, Any]:
        with _customer_lock(self.root, customer_id):
            user_dir = self._user_dir(customer_id, create=True)
            path = user_dir / "user.md"
            self._ensure_primary(path, user_dir / "user.mmd", "User Profile")
            self._append_line(path, fact)
        return {"status": "success", "file": "user.md", "action": "updated"}

    def update_behaviors(self, customer_id: str, pattern: str) -> dict[str, Any]:
        with _customer_lock(self.root, customer_id):
            user_dir = self._user_dir(customer_id, create=True)
            path = user_dir / "behaviors.md"
            self._ensure_primary(path, user_dir / "behaviors.mmd", "Behavioral Patterns")
            self._append_line(path, pattern)
        return {"status": "success", "file": "behaviors.md", "action": "updated"}

    def latest_fact(self, customer_id: str, key: str) -> Any:
        return self.load(customer_id).get("facts", {}).get(key)

    def upsert_fact(
        self, customer_id: str, key: str, value: Any
    ) -> dict[str, Any]:
        if not key or not re.fullmatch(r"[A-Za-z0-9_.-]+", key):
            raise ValueError("memory fact key contains unsupported characters")

        with _customer_lock(self.root, customer_id):
            user_dir = self._user_dir(customer_id, create=True)
            facts = self._load_facts(user_dir)
            action = "updated" if key in facts else "created"
            facts[key] = value
            lines = ["# Customer Facts", ""]
            lines.extend(
                f"- {fact_key}: {json.dumps(fact_value, ensure_ascii=False)}"
                for fact_key, fact_value in facts.items()
            )
            path = user_dir / "facts.md"
            _atomic_write_text(path, "\n".join(lines) + "\n")
        return {"status": "success", "file": "facts.md", "action": action}

    def _daily_path(
        self,
        customer_id: str,
        directory: str,
        prefix: str,
        date_value: str | None = None,
    ) -> Path:
        user_dir = self._user_dir(customer_id, create=True)
        date_value = date_value or datetime.now().strftime("%Y-%m-%d")
        path = user_dir / directory / f"{prefix}-{date_value}.md"
        legacy = path.with_suffix(".mmd")
        if not path.exists() and legacy.exists():
            _atomic_write_text(path, legacy.read_text(encoding="utf-8"))
        return path

    def record_atomic_fact(self, customer_id: str, fact: str) -> dict[str, Any]:
        with _customer_lock(self.root, customer_id):
            path = self._daily_path(customer_id, "atomic_facts", "fact")
            self._append_line(path, fact)
        return {"status": "success", "file": f"atomic_facts/{path.name}"}

    def record_foresight(self, customer_id: str, foresight: str) -> dict[str, Any]:
        normalized = " ".join(foresight.split()).strip()
        if not normalized:
            raise ValueError("foresight must not be empty")
        with _customer_lock(self.root, customer_id):
            path = self._daily_path(customer_id, "foresights", "foresight")
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            existing_lines = {
                " ".join(line.removeprefix("- ").split()).casefold()
                for line in existing.splitlines()
                if line.strip()
            }
            if normalized.casefold() in existing_lines:
                return {
                    "status": "success",
                    "file": f"foresights/{path.name}",
                    "action": "skipped",
                }
            self._append_line(path, normalized)
        return {
            "status": "success",
            "file": f"foresights/{path.name}",
            "action": "created",
        }

    def record_episode(
        self,
        customer_id: str,
        summary: str,
        *,
        occurred_on: str | None = None,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = summary.strip()
        if not normalized:
            raise ValueError("episode summary must not be empty")
        with _customer_lock(self.root, customer_id):
            path = self._daily_path(customer_id, "episodes", "episode", occurred_on)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            marker = f"<!-- source_id:{source_id} -->" if source_id else ""
            if marker and marker in existing:
                return {"status": "success", "file": f"episodes/{path.name}", "action": "skipped"}

            timestamp = datetime.now().strftime("%H:%M:%S")
            addition = f"{marker}\n" if marker else ""
            addition += f"### Session at {timestamp}\n{normalized}\n\n"
            _atomic_write_text(path, existing + addition)
        return {"status": "success", "file": f"episodes/{path.name}", "action": "created"}
