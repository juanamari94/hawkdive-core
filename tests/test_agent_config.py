import pytest

from hawkdive.agent.config import AgentConfig


def test_agent_configuration_keeps_credentials_out_of_public_data():
    config = AgentConfig(
        openrouter_api_key='model-secret', grafana_access_token='mcp-secret',
        grafana_url='https://example.grafana.net',
    )
    assert config.model == 'z-ai/glm-5.3'
    assert config.reasoning_effort == 'max'
    assert 'model-secret' not in repr(config)
    assert 'mcp-secret' not in repr(config)
    assert 'model-secret' not in config.model_dump_json()
    assert 'mcp-secret' not in config.model_dump_json()
    assert config.worker_environment()['OPENROUTER_API_KEY'] == 'model-secret'
    assert config.worker_environment()['HAWKDIVE_GRAFANA_ACCESS_TOKEN'] == 'mcp-secret'


def test_agent_configuration_requires_a_grafana_cloud_stack():
    with pytest.raises(ValueError):
        AgentConfig(openrouter_api_key='secret', grafana_access_token='secret', grafana_url='http://localhost:3000')
