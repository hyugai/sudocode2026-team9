"""Shared business services; the text harness continues owning the MCP lifecycle."""
from dataclasses import dataclass
from typing import Any


@dataclass
class ConversationServices:
    identity: Any
    customer_context: Any
    perceive: Any
    retrieve: Any
    call_brief: Any
    guardrail: Any
    persist: Any
    memory: Any
    mcp_tools: dict

    @classmethod
    def from_harness(cls, harness):
        return cls(**{name: getattr(harness, name, None) for name in cls.__dataclass_fields__})
