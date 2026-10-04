"""Shared data structures passed through the telesale pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


JsonObject = dict[str, Any]


class Channel(StrEnum):
    VOICE = "voice"
    CHAT = "chat"


class ActionStatus(StrEnum):
    EXECUTED = "executed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(slots=True)
class TurnInput:
    """One customer message received from voice or chat."""

    conversation_id: str
    text: str | None = None
    audio: bytes | None = None
    channel: Channel = Channel.CHAT
    customer_hint: str | None = None
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.conversation_id.strip():
            raise ValueError("conversation_id must not be empty")
        if self.text is None and self.audio is None:
            raise ValueError("either text or audio must be provided")


@dataclass(slots=True)
class Message:
    role: str
    content: str


@dataclass(slots=True)
class Perception:
    transcript: str
    intent: str = "unknown"
    intents: list[str] = field(default_factory=list)
    entities: JsonObject = field(default_factory=dict)
    memory_deltas: JsonObject = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(slots=True)
class CustomerIdentity:
    customer_id: str | None = None
    confidence: float = 0.0
    profile: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class RetrievedContext:
    customer_history: list[JsonObject] = field(default_factory=list)
    knowledge: list[JsonObject] = field(default_factory=list)
    active_promotions: list[JsonObject] = field(default_factory=list)


@dataclass(slots=True)
class CallBrief:
    """Compact, customer-specific context loaded into the sales agent."""

    customer_id: str | None
    customer_name: str | None = None
    summary: str = ""
    needs: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    unresolved_issues: list[str] = field(default_factory=list)
    active_promotions: list[JsonObject] = field(default_factory=list)


@dataclass(slots=True)
class ActionPlan:
    action: str
    rationale: str
    target_intent: str | None = None
    response_text: str | None = None
    tool_name: str | None = None
    arguments: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    safe_plan: ActionPlan | None = None


@dataclass(slots=True)
class ActionResult:
    status: ActionStatus
    output: JsonObject = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class Observation:
    summary: str
    should_continue: bool = False
    events: list[JsonObject] = field(default_factory=list)


@dataclass(slots=True)
class AgentStep:
    """One Plan -> Guardrail -> Act -> Observe iteration."""

    plan: ActionPlan
    policy: PolicyDecision
    action_result: ActionResult
    observation: Observation


@dataclass(slots=True)
class MemoryRecord:
    conversation_id: str
    customer_id: str | None
    kind: str
    content: JsonObject


@dataclass(slots=True)
class ConversationState:
    """State retained across all turns of one conversation."""

    conversation_id: str
    turn_number: int = 0
    identity: CustomerIdentity | None = None
    customer_profile: JsonObject | None = None
    past_history: JsonObject | None = None
    retrieved_data: RetrievedContext | None = None
    call_brief: CallBrief | None = None
    messages: list[Message] = field(default_factory=list)
    working_memory: JsonObject = field(default_factory=dict)
    memory_deltas: JsonObject = field(default_factory=dict)


@dataclass(slots=True)
class TurnContext:
    """Temporary workspace populated while one turn is processed."""

    input: TurnInput
    state: ConversationState
    perception: Perception | None = None
    identity: CustomerIdentity | None = None
    retrieved: RetrievedContext | None = None
    call_brief: CallBrief | None = None
    plan: ActionPlan | None = None
    policy: PolicyDecision | None = None
    action_result: ActionResult | None = None
    observation: Observation | None = None
    pending_intents: list[str] = field(default_factory=list)
    completed_intents: list[str] = field(default_factory=list)
    tool_results: JsonObject = field(default_factory=dict)
    steps: list[AgentStep] = field(default_factory=list)


@dataclass(slots=True)
class TurnResult:
    conversation_id: str
    turn_number: int
    response_text: str | None
    perception: Perception | None
    identity: CustomerIdentity | None
    retrieved: RetrievedContext | None
    call_brief: CallBrief
    action_result: ActionResult
    observation: Observation
    steps: list[AgentStep]
    state: ConversationState
