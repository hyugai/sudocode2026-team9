"""
Tool Registry — aggregates all domain tools into a single lookup dict.

To add a new tool: create a function in the appropriate domain file
(crm.py / catalog.py / order.py / workflow.py), add it to that file's
TOOLS dict, and it will automatically appear here.

To swap mock → real implementation: replace the import source for that
domain's TOOLS dict without touching anything else.
"""

from __future__ import annotations

from typing import Any

from telesale_agent.tools.crm import TOOLS as _CRM
from telesale_agent.tools.catalog import TOOLS as _CATALOG
from telesale_agent.tools.order import TOOLS as _ORDER
from telesale_agent.tools.workflow import TOOLS as _WORKFLOW

# Master registry — BTC tool name → callable
TOOL_REGISTRY: dict[str, Any] = {
    **_CRM,
    **_CATALOG,
    **_ORDER,
    **_WORKFLOW,
}


def dispatch_tool(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call by BTC-standard name.

    Returns a dict; always includes 'error' key on failure.
    """
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"unknown_tool: {tool_name}"}
    try:
        return fn(**tool_args)
    except TypeError as e:
        return {"error": f"bad_args: {e}"}
    except Exception as e:
        return {"error": str(e)}
