"""Compatibility import for the now-deterministic call brief projector."""

from telesale_agent.application.memory.call_brief import CallBriefProjector

LLMCallBriefBuilder = CallBriefProjector

__all__ = ["LLMCallBriefBuilder"]
