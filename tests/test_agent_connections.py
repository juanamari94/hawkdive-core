import asyncio

from fastmcp import FastMCP
from langchain.mcp import MCPAdapter

from hawkdive.agent import grafana
from hawkdive.agent.config import AgentConfig
from hawkdive.agent.model import create_model


def configuration():
    return AgentConfig(openrouter_api_key='model-secret', grafana_access_token='mcp-secret',
                       grafana_url='https://example.grafana.net')


def test_model_uses_selected_provider_model_and_reasoning():
    model = create_model(configuration())
    assert model.model_name == 'z-ai/glm-5.3'
    assert model.reasoning == {'effort': 'max'}
    assert model.request_timeout == 60000


def test_grafana_node_only_receives_supported_read_tools(monkeypatch):
    server = FastMCP('Test catalog')

    @server.tool
    def query_prometheus(expression: str) -> str:
        return expression

    @server.tool
    def update_dashboard() -> str:
        return 'must not be exposed'

    monkeypatch.setattr(grafana, 'MCPAdapter', lambda transport: MCPAdapter(server))

    async def run():
        async with grafana.connect_grafana(configuration()) as tools:
            assert [tool.name for tool in tools] == ['query_prometheus']

    asyncio.run(run())
