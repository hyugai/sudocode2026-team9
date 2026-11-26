"""Application-owned session/turn identifiers; no SDK objects cross this boundary."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class SessionInit:
    conversation_id: str
    customer_hint: str | None
    text: None = None
    audio: None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class VoiceTurnRecord:
    turn_id: str = field(default_factory=lambda: uuid4().hex)
    input_text: str = ""
    input_finished: bool = False
    output_text: str = ""
    interrupted: bool = False
    model_complete: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    played_samples: int = 0
    generation: int = 0
    revision: int = 0
    prepared_revision: int = -1
    context: Any = None
    finalized: bool = False
    sequence: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transcript(self, text: str, *, finished: bool = False):
        self.input_text += text
        self.input_finished = self.input_finished or finished
        self.revision += 1
