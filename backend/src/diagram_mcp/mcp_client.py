"""LangChain MCP adapter client for the headless draw.io MCP microservice.

Connects to the MCP server via Streamable HTTP transport and exposes its
tools (validate_drawio, render_drawio_png, resolve_stencil, search_stencils)
as LangChain-compatible BaseTool objects.

Usage inside an async context (tools must be used within the context manager
because the underlying HTTP session is kept alive for the duration):

    from diagram_mcp.mcp_client import mcp_tools

    async with mcp_tools() as tools:
        # tools: list[BaseTool]
        result = await tools[0].ainvoke({"xml": "<mxGraphModel>..."})

The MCP_URL env var controls which server to connect to:
  - locally (no Docker):  http://localhost:6002/mcp  (default)
  - inside Docker:        http://mcp:6002/mcp  (set via docker-compose)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

MCP_URL = os.getenv("MCP_URL", "http://localhost:6002/mcp")


@asynccontextmanager
async def mcp_tools() -> AsyncIterator[list[BaseTool]]:
    """Async context manager that yields LangChain tools from the MCP server.

    The connection is kept alive for the duration of the block; tools MUST be
    called within this block.  Yields an empty list (with a warning) if the
    server is unreachable so callers can degrade gracefully.
    """
    try:
        client = MultiServerMCPClient(
            {
                "diagram": {
                    "transport": "streamable_http",
                    "url": MCP_URL,
                }
            }
        )
        tools = await client.get_tools()
        logger.info("MCP tools loaded from %s: %s", MCP_URL, [t.name for t in tools])
        yield tools
    except Exception:
        logger.warning(
            "MCP server unreachable at %s — MCP tools unavailable. "
            "NOTE: mcp_client.py is defined but not yet integrated into the main pipeline.",
            MCP_URL,
            exc_info=True,
        )
        yield []
