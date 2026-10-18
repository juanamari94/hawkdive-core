import asyncio

from fastmcp import FastMCP
from langchain.mcp import MCPAdapter

from hawkdive.agent import grafana
from hawkdive.agent.config import AgentConfig
from hawkdive.agent.model import create_model


def configuration():
    return AgentConfig(openrouter_api_key='model-secret', grafana_access_token='mcp-secret',
                       grafana_url='https://example.grafana.net', grafana_mcp_token='caller-secret')


def test_model_uses_selected_provider_model_and_reasoning():
    model = create_model(configuration())
    assert model.model_name == 'z-ai/glm-5.3'
    assert model.reasoning == {'effort': 'max'}
    assert model.request_timeout == 60000


def test_grafana_node_receives_all_advertised_tools(monkeypatch):
    server = FastMCP('Test catalog')

    @server.tool
    def query_prometheus(expression: str) -> str:
        return expression

    @server.tool
    def update_dashboard() -> str:
        return 'available if authorized by Grafana'

    @server.tool
    def query_loki_logs(expression: str) -> str:
        return expression

    @server.tool
    def new_telemetry_tool() -> str:
        return 'new server capability'

    def connect(transport):
        assert transport.url == 'http://127.0.0.1:8001/mcp'
        assert transport.headers is None or 'X-Grafana-URL' not in transport.headers
        assert transport.auth.token.get_secret_value() == 'caller-secret'
        return MCPAdapter(server)

    monkeypatch.setattr(grafana, 'MCPAdapter', connect)

    async def run():
        async with grafana.connect_grafana(configuration()) as tools:
            assert {tool.name for tool in tools} == {
                'query_prometheus', 'query_loki_logs', 'update_dashboard', 'new_telemetry_tool',
            }

    asyncio.run(run())
