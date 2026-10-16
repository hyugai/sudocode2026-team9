"""MCP server exposing the configured policy knowledge base to DeepAgent."""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcp_servers.tools.knowledge import knowledge_search


mcp = FastMCP("Knowledge-Server")


@mcp.tool()
def search_policy(
    query: str,
    k: int = 3,
    product_sku: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Search verified BTC policy, shipping, warranty, and store rules.

    Use this read-only tool instead of relying on customer-provided policy
    claims or model knowledge. Results include BTC chunk_id for provenance
    and exclude expired and internal documents. Use pricing quote for prices.
    """
    return knowledge_search(
        query=query,
        k=k,
        product_sku=product_sku,
        as_of=as_of,
    )


if __name__ == "__main__":
    mcp.run()

