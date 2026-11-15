"""Bounded dependency probes; no business mutations or LLM calls."""

import asyncio
from functools import lru_cache

from sqlalchemy import create_engine, text

from telesale_agent.adapters.db.client import db_client
from telesale_agent.adapters.mcp.runtime import MCP_SERVER_NAMES


@lru_cache(maxsize=1)
def _probe_engine():
    # A separate, bounded pool keeps health polling out of the business pool.
    return create_engine(db_client.engine.url, pool_size=1, max_overflow=0,
                         pool_timeout=2, pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 2})


def probe_database() -> None:
    with _probe_engine().connect() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '1000ms'"))
        connection.execute(text("SELECT 1"))


async def check_readiness(harness, *, timeout: float = 3.0) -> dict[str, str]:
    async def bounded(probe):
        try:
            await asyncio.wait_for(probe(), timeout=timeout)
            return "ok"
        except TimeoutError:
            return "timeout"
        except Exception:
            # Do not expose DB URLs, credentials, subprocess paths or errors.
            return "unavailable"

    sessions = getattr(harness, "mcp_sessions", {})

    async def ping(name):
        session = sessions.get(name)
        if session is None:
            raise RuntimeError("MCP session unavailable")
        await session.send_ping()

    names = ["database", *("mcp_" + name for name in MCP_SERVER_NAMES)]
    results = await asyncio.gather(
        bounded(lambda: asyncio.to_thread(probe_database)),
        *(bounded(lambda name=name: ping(name)) for name in MCP_SERVER_NAMES),
    )
    return {"agent": "ok" if getattr(harness, "agent", None) is not None else "unavailable",
            **dict(zip(names, results))}
