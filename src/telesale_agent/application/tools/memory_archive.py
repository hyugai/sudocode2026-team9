"""On-demand customer archive lookup; never expose another customer's ID."""

from __future__ import annotations

import asyncio

from langchain.tools import ToolRuntime, tool


def build_memory_archive_tool(memory):
    if not callable(getattr(memory, "search_archive", None)):
        return None

    @tool
    async def search_customer_memory_archive(
        query: str,
        runtime: ToolRuntime,
        section: str = "episodes",
        day: str = "",
    ) -> dict:
        """Search this customer's older Markdown memory only when current context lacks the answer. Sections: episodes, atomic_facts, foresights, user, behaviors, facts. An optional YYYY-MM-DD day fetches one daily file. Current facts and verified business tools take precedence over old memory."""
        context = runtime.context or {}
        customer_id = context.get("customer_id") if isinstance(context, dict) else None
        if not customer_id:
            return {"error": "Customer identity unavailable"}
        try:
            return await asyncio.to_thread(
                memory.search_archive,
                customer_id,
                query,
                section=section,
                day=day or None,
            )
        except ValueError as exc:
            return {"error": str(exc)}

    return search_customer_memory_archive
