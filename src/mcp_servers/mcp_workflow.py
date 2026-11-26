import os
from mcp.server.fastmcp import FastMCP
from typing import Any
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import existing workflow tools
from mcp_servers.tools.workflow import schedule_callback, handoff_transfer

mcp = FastMCP("Workflow-Server")

@mcp.tool()
def mcp_schedule_callback(
    customer_phone: str,
    callback_at: str,
    note: str | None = None,
    on: str | None = None,
) -> dict[str, Any]:
    """Schedule a callback for the customer."""
    return schedule_callback(
        customer_phone=customer_phone,
        callback_at=callback_at,
        note=note,
        on=on,
    )

@mcp.tool()
def mcp_escalate_to_human(brief: dict[str, Any]) -> dict[str, Any]:
    """Transfer a BTC HandoffBrief to a human agent."""
    return handoff_transfer(brief=brief)

if __name__ == "__main__":
    mcp.run()
