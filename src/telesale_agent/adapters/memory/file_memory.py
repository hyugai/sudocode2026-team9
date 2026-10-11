from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


_SAFE_CUSTOMER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_FACT_LINE = re.compile(r"^- ([A-Za-z0-9_.-]+):\s*(.*)$")


class FileCustomerMemoryRepository:
    """Store customer memory as .md files outside the CRM database.

    Existing .mmd files are readable for backward compatibility. New writes
    always target .md files so callers do not need to know file layout.
    """

    def __init__(self, root: str | Path | None = None):
        project_root = Path(__file__).resolve().parents[4]
        self.root = Path(root) if root else project_root / "data" / "memory-root" / "users"

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
            primary.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            primary.write_text(f"# {heading}\n\n", encoding="utf-8")

    @staticmethod
    def _append_line(path: Path, value: str) -> None:
        normalized = " ".join(value.strip().splitlines())
        if not normalized:
            raise ValueError("memory value must not be empty")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {normalized}\n")

    def update_profile(self, customer_id: str, fact: str) -> dict[str, Any]:
        user_dir = self._user_dir(customer_id, create=True)
        path = user_dir / "user.md"
        self._ensure_primary(path, user_dir / "user.mmd", "User Profile")
        self._append_line(path, fact)
        return {"status": "success", "file": "user.md", "action": "updated"}

    def update_behaviors(self, customer_id: str, pattern: str) -> dict[str, Any]:
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
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
            path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        return path

    def record_atomic_fact(self, customer_id: str, fact: str) -> dict[str, Any]:
        path = self._daily_path(customer_id, "atomic_facts", "fact")
        self._append_line(path, fact)
        return {"status": "success", "file": f"atomic_facts/{path.name}"}

    def record_foresight(self, customer_id: str, foresight: str) -> dict[str, Any]:
        path = self._daily_path(customer_id, "foresights", "foresight")
        self._append_line(path, foresight)
        return {"status": "success", "file": f"foresights/{path.name}"}

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
        path = self._daily_path(customer_id, "episodes", "episode", occurred_on)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        marker = f"<!-- source_id:{source_id} -->" if source_id else ""
        if marker and marker in existing:
            return {"status": "success", "file": f"episodes/{path.name}", "action": "skipped"}

        timestamp = datetime.now().strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            if marker:
                handle.write(f"{marker}\n")
            handle.write(f"### Session at {timestamp}\n{normalized}\n\n")
        return {"status": "success", "file": f"episodes/{path.name}", "action": "created"}
