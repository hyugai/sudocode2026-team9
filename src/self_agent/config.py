"""Configuration owned solely by the self-agent wrapper."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LearningConfig:
    enabled: bool = False
    root: Path = Path(__file__).resolve().parents[2] / "data/memory-root/agents/telesales_agent/knowledge_gap_loop"
    max_attempts: int = 3
    runtime_root: Path = Path(__file__).resolve().parents[2] / "outputs/self-agent/learning-runtime"

    @classmethod
    def from_env(cls):
        value = os.getenv("KNOWLEDGE_GAP_LOOP_ENABLED", "false").strip().lower()
        if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ValueError("Invalid KNOWLEDGE_GAP_LOOP_ENABLED boolean")
        return cls(enabled=value in {"true", "1", "yes", "on"})
