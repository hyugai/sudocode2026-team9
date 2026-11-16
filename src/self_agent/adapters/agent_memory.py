"""Only approved Markdown lessons are durable agent memory; diagnostics live in outputs."""
import json
import os
import tempfile
from pathlib import Path


class AgentMemory:
    def write_lesson(self, lesson):
        from self_agent.lessons import markdown
        key = lesson['id']
        if not key or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid lesson ID')
        target = self.root / 'lessons/approved' / (key + '.md')
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, suffix='.tmp')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as output:
                output.write(markdown(lesson))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return str(target.relative_to(self.root))

    def __init__(self, root, *, runtime_root=None):
        self.root = Path(root)
        self.runtime_root = Path(runtime_root) if runtime_root is not None else Path(__file__).resolve().parents[3] / "outputs/self-agent/learning-runtime"

    def directory(self, group):
        if group not in {"jobs", "gaps", "knowledge", "patterns", "regression_cases", "reports", "releases"}:
            raise ValueError("Unknown artifact group")
        return self.runtime_root / group

    def write(self, group, key, value):
        if group not in {"jobs", "gaps", "knowledge", "patterns", "regression_cases", "reports", "releases"}:
            raise ValueError("Unknown artifact group")
        if not key or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Artifact key must be a hex digest")
        target = self.directory(group) / (key + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read(self, group, key):
        if not key or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Artifact key must be a hex digest")
        return json.loads((self.directory(group) / (key + ".json")).read_text(encoding="utf-8"))

    def records(self, group):
        return [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(self.directory(group).glob("*.json"))]
