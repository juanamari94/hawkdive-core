from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp.client.transports import StreamableHttpTransport
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

from hawkdive.agent.config import AgentConfig


@asynccontextmanager
async def connect_grafana(config: AgentConfig) -> AsyncIterator[list[BaseTool]]:
    transport = StreamableHttpTransport(
        config.grafana_mcp_url, auth=config.grafana_mcp_token.get_secret_value(),
    )
    async with MCPAdapter(transport) as adapter:
        tools = await adapter.list_tools()
        if not tools:
            raise RuntimeError('Grafana MCP did not advertise any tools')
        yield tools
