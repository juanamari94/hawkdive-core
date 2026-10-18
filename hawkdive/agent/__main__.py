"""Run one investigation. Stdout is reserved for validated worker records."""

import asyncio
import logging
import sys

from hawkdive.agent.config import AgentConfig
from hawkdive.agent.grafana import connect_grafana
from hawkdive.agent.graph import InvestigationAgent
from hawkdive.agent.model import create_model
from hawkdive.agent.shell import DockerSandbox
from hawkdive.investigations import WorkerInput, WorkerOutput

logger = logging.getLogger(__name__)


def emit(output: WorkerOutput) -> None:
    sys.stdout.write(output.model_dump_json() + '\n')
    sys.stdout.flush()


async def run(request: WorkerInput, config: AgentConfig) -> None:
    sandbox = DockerSandbox(request.attempt_id, image=config.sandbox_image, command_timeout=config.command_timeout)
    try:
        async with asyncio.timeout(config.investigation_timeout):
            await sandbox.start()
            async with connect_grafana(config) as grafana_tools:
                model = create_model(config)
                agent = InvestigationAgent(
                    model, grafana_tools, sandbox, emit, max_model_calls=config.max_model_calls,
                    secrets=(config.openrouter_api_key.get_secret_value(), config.grafana_access_token.get_secret_value(),
                             config.grafana_mcp_token.get_secret_value()),
                )
                await agent.run(request.trigger)
    finally:
        await sandbox.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format='%(levelname)s %(name)s: %(message)s')
    try:
        request = WorkerInput.model_validate_json(sys.stdin.readline())
        config = AgentConfig.from_environment()
        asyncio.run(run(request, config))
        return 0
    except Exception as error:
        # Provider/transport exceptions can contain credential-bearing request details.
        logger.error('Agent execution failed (%s).', type(error).__name__)
        return 1


if __name__ == '__main__':
    sys.exit(main())
