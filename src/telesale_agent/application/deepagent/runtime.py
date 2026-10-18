"""Start, prewarm, and close the DeepAgent model and MCP clients."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

from telesale_agent.adapters.llm.model_factory import (
    create_chat_model,
    model_provider_key,
    resolve_model_config,
)
from telesale_agent.application.deepagent.tools.routing import (
    IntentToolRoutingMiddleware,
    TelesaleAgentRuntimeContext,
)
from telesale_agent.application.deepagent.tools.memory_archive import build_memory_archive_tool
from telesale_agent.application.deepagent.context.prompt import positive_int_env as _positive_int_env

async def initialize_runtime(harness):
    if harness.agent is not None:
        return harness

    project_root = Path(__file__).resolve().parents[4]
    configured_agent_dir = os.environ.get("AGENT_INSTRUCTIONS_ROOT")
    agent_dir = (
        Path(configured_agent_dir)
        if configured_agent_dir
        else project_root / "data" / "memory-root" / "agents" / "telesales_agent"
    )
    missing_instructions = [
        name for name in ("soul.md", "agent.md", "tools.md")
        if not (agent_dir / name).is_file()
    ]
    if missing_instructions:
        raise FileNotFoundError(
            f"Missing DeepAgent instruction files in {agent_dir}: "
            + ", ".join(missing_instructions)
        )
    # Keep instructions as version-controlled .md files in memory-root,
    # but load them once at startup. MemoryMiddleware would append a large
    # generic harness-edit guide on every model call even though customer
    # memory is owned by the configured application persister.
    instruction_prompt = "\n\n".join(
        (agent_dir / name).read_text(encoding="utf-8").strip()
        for name in ("soul.md", "agent.md", "tools.md")
    )
    minimal_filesystem = FilesystemMiddleware(
        tools=["read_file"],
        system_prompt="",
    )

    server_paths = [
        project_root / "src" / "mcp_servers" / "mcp_db.py",
        project_root / "src" / "mcp_servers" / "mcp_knowledge.py",
        project_root / "src" / "mcp_servers" / "mcp_workflow.py",
    ]

    all_mcp_tools = []
    for srv_path in server_paths:
        if srv_path.exists():
            # Keep the parent's import path for subprocesses. This matters
            # for Windows evaluation runs where the venv launcher may fall
            # back to the base interpreter while packages remain in the
            # venv site-packages directory.
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(srv_path)],
                env=os.environ.copy(),
            )
            read, write = await harness.exit_stack.enter_async_context(stdio_client(params))
            session = await harness.exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            tools = await load_mcp_tools(session)
            all_mcp_tools.extend(tools)
    archive_tool = build_memory_archive_tool(harness.memory)
    if archive_tool is not None:
        all_mcp_tools.append(archive_tool)
    harness.mcp_tools = {
        tool.name: tool
        for tool in all_mcp_tools
        if isinstance(getattr(tool, "name", None), str)
    }
    await harness._prewarm_knowledge_mcp()
            
    model_config = resolve_model_config()
    model = create_chat_model(temperature=0.3)
    provider_key = model_provider_key(model, model_config.provider)

    # DeepAgent ships general filesystem/execution/subagent tools. This
    # telesales harness only needs the MCP business tools; hiding unused
    # schemas materially reduces every provider request while retaining the
    # DeepAgent runtime and middleware.
    register_harness_profile(
        provider_key,
        HarnessProfile(
            excluded_tools=frozenset(
                {
                    "ls",
                    "read_file",
                    "write_file",
                    "edit_file",
                    "glob",
                    "grep",
                    "execute",
                }
            ),
            general_purpose_subagent=GeneralPurposeSubagentProfile(
                enabled=False
            ),
            excluded_middleware=frozenset(
                {"SummarizationMiddleware", "PatchToolCallsMiddleware"}
            ),
        ),
    )

    harness.agent = create_deep_agent(
        model=model,
        tools=all_mcp_tools,
        system_prompt=instruction_prompt,
        middleware=[
            IntentToolRoutingMiddleware(),
            ModelCallLimitMiddleware(
                run_limit=_positive_int_env("DEEPAGENT_MAX_MODEL_CALLS", 3),
                exit_behavior="end",
            ),
            ToolCallLimitMiddleware(
                run_limit=_positive_int_env("DEEPAGENT_MAX_TOOL_CALLS", 3),
                exit_behavior="end",
            ),
            minimal_filesystem,
        ],
        context_schema=TelesaleAgentRuntimeContext,
        checkpointer=harness.checkpointer,
    )
    return harness

async def prewarm_knowledge_mcp(harness) -> None:
    """Optionally warm policy retrieval before the first live turn."""
    backend = os.environ.get("KNOWLEDGE_BACKEND", "chroma").strip().lower()
    default_enabled = "false" if backend == "pinecone" else "true"
    enabled = os.environ.get(
        "KNOWLEDGE_MCP_PREWARM", default_enabled
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not enabled:
        return
    tool = harness.mcp_tools.get("search_policy")
    if tool is None:
        print("   -> Knowledge MCP prewarm skipped: tool unavailable")
        return
    try:
        timeout = float(
            os.environ.get(
                "KNOWLEDGE_MCP_PREWARM_TIMEOUT_SECONDS", "180"
            )
        )
    except ValueError:
        timeout = 180.0
    timeout = max(timeout, 1.0)
    started = time.perf_counter()
    print(f"   -> Prewarming Knowledge MCP ({backend})...")
    try:
        result = await asyncio.wait_for(
            tool.ainvoke(
                {
                    "query": "chính sách đổi trả hiện hành",
                    "k": 1,
                }
            ),
            timeout=timeout,
        )
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result["error"]))
    except Exception as exc:
        print(f"   -> Knowledge MCP prewarm warning: {exc}")
        return
    elapsed = time.perf_counter() - started
    print(f"   -> Knowledge MCP ready in {elapsed:.1f}s")

async def close_runtime(harness, exc_type, exc_val, exc_tb):
    await harness.exit_stack.aclose()
    harness.agent = None

