import os
from mcp.server.fastmcp import FastMCP
from typing import Any

# Import existing workflow tools
from telesale_agent.tools.workflow import schedule_callback, escalate_to_human

mcp = FastMCP("Workflow-Server")

@mcp.tool()
def mcp_schedule_callback(customer_id: str, reason: str, preferred_time: str) -> dict[str, Any]:
    """Schedule a callback for the customer."""
    return schedule_callback(customer_id=customer_id, reason=reason, preferred_time=preferred_time)

@mcp.tool()
def mcp_escalate_to_human(customer_id: str, reason: str, urgency: str) -> dict[str, Any]:
    """Escalate the conversation to a human agent."""
    return escalate_to_human(customer_id=customer_id, reason=reason, urgency=urgency)

if __name__ == "__main__":
    mcp.run()
