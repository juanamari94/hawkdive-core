import os
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class AgentConfig(BaseModel):
    """Application-owned configuration. Secrets never enter investigation records."""

    model_config = ConfigDict(extra='forbid')

    openrouter_api_key: SecretStr = Field(exclude=True, repr=False)
    grafana_access_token: SecretStr = Field(exclude=True, repr=False)
    grafana_url: str
    model: str = 'z-ai/glm-5.3'
    reasoning_effort: Literal['low', 'high', 'max'] = 'max'
    sandbox_image: str = 'hawkdive-sandbox:local'
    max_model_calls: int = 20
    investigation_timeout: int = 300
    command_timeout: int = 30

    @field_validator('grafana_url')
    @classmethod
    def require_cloud_stack(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or not url.hostname.endswith('.grafana.net')
                or url.username or url.password or url.query or url.fragment or url.path not in ('', '/')):
            raise ValueError('Configure the HTTPS root URL of a Grafana Cloud stack')
        return value.rstrip('/')

    @field_validator('openrouter_api_key', 'grafana_access_token')
    @classmethod
    def require_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError('Credential must not be empty')
        return value

    @field_validator('max_model_calls', 'investigation_timeout', 'command_timeout')
    @classmethod
    def require_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('Execution limits must be positive')
        return value

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> 'AgentConfig':
        environment = os.environ if environment is None else environment
        return cls(
            openrouter_api_key=environment.get('OPENROUTER_API_KEY', ''),
            grafana_access_token=environment.get('HAWKDIVE_GRAFANA_ACCESS_TOKEN', ''),
            grafana_url=environment.get('HAWKDIVE_GRAFANA_URL', ''),
            model=environment.get('HAWKDIVE_AGENT_MODEL', 'z-ai/glm-5.3'),
            reasoning_effort=environment.get('HAWKDIVE_AGENT_REASONING_EFFORT', 'max'),
            sandbox_image=environment.get('HAWKDIVE_SANDBOX_IMAGE', 'hawkdive-sandbox:local'),
            max_model_calls=int(environment.get('HAWKDIVE_AGENT_MAX_MODEL_CALLS', '20')),
            investigation_timeout=int(environment.get('HAWKDIVE_AGENT_TIMEOUT_SECONDS', '300')),
            command_timeout=int(environment.get('HAWKDIVE_SHELL_TIMEOUT_SECONDS', '30')),
        )

    def worker_environment(self) -> dict[str, str]:
        return {
            'OPENROUTER_API_KEY': self.openrouter_api_key.get_secret_value(),
            'HAWKDIVE_GRAFANA_ACCESS_TOKEN': self.grafana_access_token.get_secret_value(),
            'HAWKDIVE_GRAFANA_URL': self.grafana_url,
            'HAWKDIVE_AGENT_MODEL': self.model,
            'HAWKDIVE_AGENT_REASONING_EFFORT': self.reasoning_effort,
            'HAWKDIVE_SANDBOX_IMAGE': self.sandbox_image,
            'HAWKDIVE_AGENT_MAX_MODEL_CALLS': str(self.max_model_calls),
            'HAWKDIVE_AGENT_TIMEOUT_SECONDS': str(self.investigation_timeout),
            'HAWKDIVE_SHELL_TIMEOUT_SECONDS': str(self.command_timeout),
            # The worker retains the MCP client and model key; the sandbox receives neither.
            'LANGSMITH_TRACING': 'false',
        }
