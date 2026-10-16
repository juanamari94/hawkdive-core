import asyncio
import json
from uuid import uuid4

import pytest
from fastmcp import FastMCP
from langchain.mcp import MCPAdapter
from langchain_core.messages import AIMessage, ToolMessage

from hawkdive.agent.graph import InvestigationAgent
from hawkdive.investigations import AlertTrigger, OutputKind


class ScratchShell:
    def __init__(self):
        self.commands = []

    async def execute(self, command):
        self.commands.append(command)
        return {'stdout': '2', 'stderr': '', 'exit_code': 0}


class ScriptedModel:
    def __init__(self):
        self.step = 0
        self.record_ids = {}

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages):
        replies = [message for message in messages if isinstance(message, ToolMessage)]
        for reply in replies:
            if reply.name and reply.name.startswith('record_'):
                self.record_ids[reply.name] = json.loads(reply.content)['id']
        if self.step == 0:
            calls = [
                {'id': 'query', 'name': 'query_prometheus', 'args': {'expression': 'memory_usage'}},
                {'id': 'shell', 'name': 'run_shell', 'args': {'command': 'python -c "print(1 + 1)"'}},
            ]
        elif self.step == 1:
            assert {reply.tool_call_id for reply in replies} == {'query', 'shell'}
            calls = [{'id': 'evidence', 'name': 'record_evidence', 'args': {
                'source': 'Grafana MCP', 'query': 'memory_usage',
                'starts_at': '2026-10-14T10:00:00Z', 'ends_at': '2026-10-14T10:05:00Z',
                'reasoning': 'Memory reached 512 MiB.', 'source_url': 'https://example.grafana.net/explore',
            }}]
        elif self.step == 2:
            calls = [{'id': 'observation', 'name': 'record_observation', 'args': {
                'summary': 'Memory reached its limit.', 'evidence_ids': [self.record_ids['record_evidence']],
            }}]
        elif self.step == 3:
            calls = [{'id': 'finding', 'name': 'record_finding', 'args': {
                'summary': 'The service exhausted its memory limit.',
                'observation_ids': [self.record_ids['record_observation']],
            }}]
        else:
            calls = [{'id': 'outcome', 'name': 'finalize', 'args': {
                'conclusion': 'Memory exhaustion caused the restart.',
                'finding_ids': [self.record_ids['record_finding']],
            }}]
        self.step += 1
        return AIMessage(content='', tool_calls=calls)


def test_agent_routes_mcp_and_shell_then_emits_supported_output():
    async def run():
        server = FastMCP('Test telemetry')
        calls = []

        @server.tool
        def query_prometheus(expression: str) -> str:
            calls.append(expression)
            return 'Memory reached 512 MiB'

        shell, outputs = ScratchShell(), []
        async with MCPAdapter(server) as adapter:
            agent = InvestigationAgent(
                ScriptedModel(), await adapter.list_tools(), shell, outputs.append, max_model_calls=8,
            )
            await agent.run(AlertTrigger(integration='grafana', occurrence_id=1, reference='/issues/1', alert={}))
        assert calls == ['memory_usage']
        assert len(shell.commands) == 1
        assert [output.kind for output in outputs] == list(OutputKind)
        assert outputs[-1].content.finding_ids == [outputs[-2].id]
        assert outputs[-2].content.observation_ids == [outputs[-3].id]
        assert outputs[-3].content.evidence_ids == [outputs[-4].id]

    asyncio.run(run())


def test_agent_stops_when_model_call_budget_is_exhausted():
    async def run():
        agent = InvestigationAgent(ScriptedModel(), [], ScratchShell(), lambda output: None, max_model_calls=1)
        with pytest.raises(RuntimeError, match='model call limit'):
            await agent.run(AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}))

    asyncio.run(run())


def test_agent_rejects_a_finding_without_a_saved_observation():
    class UnsupportedModel:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return AIMessage(content='', tool_calls=[{
                'id': str(uuid4()), 'name': 'record_finding',
                'args': {'summary': 'Unsupported cause', 'observation_ids': [str(uuid4())]},
            }])

    async def run():
        outputs = []
        agent = InvestigationAgent(UnsupportedModel(), [], ScratchShell(), outputs.append, max_model_calls=2)
        with pytest.raises(RuntimeError, match='model call limit'):
            await agent.run(AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}))
        assert outputs == []

    asyncio.run(run())


def test_mcp_credentials_are_redacted_before_results_reach_the_model():
    class InspectingModel(ScriptedModel):
        async def ainvoke(self, messages):
            assert 'mcp-secret' not in json.dumps([message.model_dump(mode='json') for message in messages])
            return await super().ainvoke(messages)

    async def run():
        server = FastMCP('Test telemetry')

        @server.tool
        def query_prometheus(expression: str) -> str:
            return 'Telemetry response containing mcp-secret'

        outputs = []
        async with MCPAdapter(server) as adapter:
            agent = InvestigationAgent(
                InspectingModel(), await adapter.list_tools(), ScratchShell(), outputs.append,
                secrets=('mcp-secret',),
            )
            await agent.run(AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}))
        assert len(outputs) == 4
        assert 'mcp-secret' not in ''.join(output.model_dump_json() for output in outputs)

    asyncio.run(run())
