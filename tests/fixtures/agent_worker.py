"""Deterministic graph worker for an HTTP-to-process-to-storage integration test."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastmcp import FastMCP
from langchain.mcp import MCPAdapter
from test_agent_graph import ScratchShell, ScriptedModel

from hawkdive.agent.graph import InvestigationAgent
from hawkdive.investigations import WorkerInput


async def run():
    assert os.environ['OPENROUTER_API_KEY'] == 'model-secret'
    assert os.environ['HAWKDIVE_GRAFANA_ACCESS_TOKEN'] == 'mcp-secret'
    request = WorkerInput.model_validate_json(sys.stdin.readline())
    server = FastMCP('Test telemetry')

    @server.tool
    def query_prometheus(expression: str) -> str:
        return 'Memory reached 512 MiB'

    async with MCPAdapter(server) as adapter:
        agent = InvestigationAgent(
            ScriptedModel(), await adapter.list_tools(), ScratchShell(),
            lambda output: print(output.model_dump_json(), flush=True),
        )
        await agent.run(request.trigger)


asyncio.run(run())
