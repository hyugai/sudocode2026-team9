"""Backpressured answer events and timestamps at the harness output boundary."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

_RUNNING: set[asyncio.Task] = set()

_WRITE_TOOLS = frozenset({
    "create_new_order", "update_order", "mcp_schedule_callback", "mcp_escalate_to_human",
    "order.create", "order.update", "schedule.callback", "handoff.transfer",
})


def answer_can_stream(tool_names) -> bool:
    """Read-tool availability does not make customer-facing text private.

    Hold transactional confirmations while a write tool is still available.
    Reasoning and function arguments are filtered independently by chunk_text.
    """
    return not _WRITE_TOOLS.intersection(tool_names)


@dataclass
class _Emission:
    event: dict[str, Any]
    accepted: asyncio.Future


class AnswerStream:
    def __init__(self, started_at: float | None = None):
        self.started_at = started_at if started_at is not None else time.perf_counter()
        self.asr_ms = 0.0
        self.first_at = None
        self.last_at = None
        self.chunks = 0
        self.chunks_during_generation = 0
        self.text = ""
        self.detached = False
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.pending: asyncio.Future | None = None
        self.policy = "guarded_words"

    async def send(self, event: dict[str, Any]):
        if self.detached:
            return
        accepted = asyncio.get_running_loop().create_future()
        self.pending = accepted
        await self.queue.put(_Emission(event, accepted))
        if self.detached and not accepted.done():
            accepted.set_result(None)
        await accepted

    def emitted(self, event):
        # This runs immediately before yielding an answer to the caller/ASGI.
        if event["type"] in {"delta", "replace"} and event.get("text"):
            now = time.perf_counter()
            if self.first_at is None:
                self.first_at = now
            self.last_at = now
            self.chunks += 1

    async def answer(self, approved: str):
        if approved == self.text or not approved:
            return
        if approved.startswith(self.text):
            event = {"type": "delta", "text": approved[len(self.text):]}
        else:
            event = {"type": "replace", "text": approved}
        self.text = approved
        await self.send(event)

    def latency(self):
        def elapsed(at):
            return round(max(0, (at - self.started_at) * 1000 - self.asr_ms), 3) if at is not None else None
        return {"ttft_ms": elapsed(self.first_at), "total_ms": elapsed(self.last_at),
                "ttfa_ms": None, "measurement_mode": "streaming",
                "answer_chunks": self.chunks, "stream_policy": self.policy,
                "chunks_before_generation_complete": self.chunks_during_generation}

    def detach(self):
        self.detached = True
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(None)
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if not item.accepted.done():
                item.accepted.set_result(None)


async def stream_events(execute: Callable[[AnswerStream], Awaitable[Any]], *, started_at=None):
    """A disconnected consumer never cancels already-executed business actions.

    The producer owns session locks/persistence. Detaching drains output and lets
    it finish in order, rather than automatically replaying a mutation.
    """
    output = AnswerStream(started_at)

    async def produce():
        try:
            result = await execute(output)
        except Exception as exc:
            await output.send({"type": "error", "exception": exc})
        else:
            await output.send({"type": "complete", "result": result})

    task = asyncio.create_task(produce())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    try:
        while True:
            item = await output.queue.get()
            output.emitted(item.event)
            try:
                yield item.event
            finally:
                if not item.accepted.done():
                    item.accepted.set_result(None)
            if item.event["type"] in {"complete", "error"}:
                break
        await task
    finally:
        output.detach()


def chunk_text(message) -> str:
    """Never expose reasoning, tool arguments or other private content blocks."""
    if getattr(message, "tool_call_chunks", None) or getattr(message, "tool_calls", None):
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content
                       if isinstance(block, dict) and block.get("type") == "text")
    return ""


def completed_prefix(text: str) -> str:
    # Release complete words as provider chunks arrive. Keep unfinished words
    # and numeric tails so phone/account numbers split across chunks are checked
    # as a whole before any of their digits are emitted.
    boundaries = list(re.finditer(r"\s+", text))
    if not boundaries:
        return ""
    prefix = text[:boundaries[-1].end()]
    number = re.search(r"\d[\d\s.,/()+-]*$", prefix)
    return prefix[:number.start()] if number else prefix
