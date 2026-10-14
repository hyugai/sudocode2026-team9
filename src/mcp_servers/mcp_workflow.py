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
def mcp_escalate_to_human(
    reason: str,
    customer_id: str,
    summary: str,
    customer_phone: str | None = None,
    customer_name: str | None = None,
    escalation_reason: str | None = None,
    conversation_summary: str | None = None,
    product_advised: str | None = None,
    price_quoted_vnd: int | None = None,
    open_questions: str | None = None,
    next_action: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Escalate the conversation to a human agent."""
    return handoff_transfer(
        brief={
            "reason": reason,
            "customer_id": customer_id,
            "summary": summary,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "escalation_reason": escalation_reason or reason,
            "conversation_summary": conversation_summary or summary,
            "product_advised": product_advised,
            "price_quoted_vnd": price_quoted_vnd,
            "open_questions": open_questions,
            "next_action": next_action,
            "generated_at": generated_at,
        }
    )

if __name__ == "__main__":
    mcp.run()
