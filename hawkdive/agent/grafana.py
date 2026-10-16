from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp.client.transports import StreamableHttpTransport
from langchain.mcp import MCPAdapter
from langchain_core.tools import BaseTool

from hawkdive.agent.config import AgentConfig

READ_TOOLS = frozenset({
    'list_datasources', 'get_datasource', 'search_dashboards', 'get_dashboard_by_uid',
    'get_dashboard_summary', 'get_dashboard_panel_queries', 'query_prometheus',
    'list_prometheus_metric_names', 'list_prometheus_metric_metadata',
    'list_prometheus_label_names', 'list_prometheus_label_values', 'get_annotations', 'get_annotation_tags',
})


@asynccontextmanager
async def connect_grafana(config: AgentConfig) -> AsyncIterator[list[BaseTool]]:
    transport = StreamableHttpTransport(
        'https://mcp.grafana.com/mcp', headers={'X-Grafana-URL': config.grafana_url},
        auth=config.grafana_access_token.get_secret_value(),
    )
    async with MCPAdapter(transport) as adapter:
        tools = [tool for tool in await adapter.list_tools() if tool.name in READ_TOOLS]
        if not tools:
            raise RuntimeError('Grafana Cloud MCP did not advertise any supported read tools')
        yield tools
