"""Shared MCP connection lifecycle; callers own the exit stack."""
import os
import sys
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools
from telesale_agent.application.tools.memory_archive import build_memory_archive_tool

MCP_SERVER_NAMES = ("db", "knowledge", "workflow")


async def connect_tools(exit_stack, memory, *, sessions=None):
    project_root = Path(__file__).resolve().parents[4]
    server_paths = [
        project_root / "src" / "mcp_servers" / "mcp_db.py",
        project_root / "src" / "mcp_servers" / "mcp_knowledge.py",
        project_root / "src" / "mcp_servers" / "mcp_workflow.py",
    ]

    all_mcp_tools = []
    for name, srv_path in zip(MCP_SERVER_NAMES, server_paths):
        if not srv_path.exists():
            raise FileNotFoundError(f"Missing MCP server: {name}")
        # Keep the parent's import path for subprocesses. This matters
        # for Windows evaluation runs where the venv launcher may fall
        # back to the base interpreter while packages remain in the
        # venv site-packages directory.
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(srv_path)],
            env=os.environ.copy(),
        )
        read, write = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        if sessions is not None:
            sessions[name] = session
        tools = await load_mcp_tools(session)
        all_mcp_tools.extend(tools)
    archive_tool = build_memory_archive_tool(memory)
    if archive_tool is not None:
        all_mcp_tools.append(archive_tool)
    registry = {
        tool.name: tool
        for tool in all_mcp_tools
        if isinstance(getattr(tool, "name", None), str)
    }
    return registry
