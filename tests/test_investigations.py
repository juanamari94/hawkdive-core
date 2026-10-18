import asyncio
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import BaseModel
from test_webhooks import AUTH, payload, read, send

from hawkdive.agent.config import AgentConfig
from hawkdive.app import create_app
from hawkdive.database import migration_config
from hawkdive.investigation_store import InvestigationConflict
from hawkdive.investigations import AlertTrigger, Finding, Outcome, WorkerInput
from hawkdive.store import Store

WORKER = Path(__file__).parent / 'fixtures' / 'worker.py'


@pytest.fixture
def setup(tmp_path, monkeypatch):
    path = tmp_path / 'alerts.sqlite3'
    monkeypatch.setenv('HAWKDIVE_DB_PATH', str(path))
    command.upgrade(migration_config(), 'head')
    now = [datetime(2026, 10, 14, 10, tzinfo=timezone.utc)]

    def make(mode='success', **kwargs):
        return TestClient(create_app(
            db_path=path, webhook_token='test-token', clock=lambda: now[0],
            worker_command=[sys.executable, str(WORKER), mode, str(tmp_path / 'release')], **kwargs,
        ))

    return make, now, tmp_path


def dispatch(client, identifier, action='dispatch'):
    return client.post(f'/investigations/{identifier}/{action}', headers=AUTH)


def finished(client, identifier):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = read(client, f'investigations/{identifier}')
        if record['status'] in ('COMPLETED', 'FAILED'):
            return record
        time.sleep(0.02)
    pytest.fail('Worker did not finish')


def test_successful_worker_preserves_the_evidence_chain(setup):
    make, _, _ = setup
    with make() as client:
        send(client, payload())
        investigation = read(client, 'investigations')[0]
        assert investigation['status'] == 'PENDING'
        assert investigation['signature'] == ['grafana', 'local', '1', 'sample-errors']
        assert dispatch(client, investigation['id']).status_code == 202
        result = finished(client, investigation['id'])
        assert result['status'] == 'COMPLETED'
        assert [entry['kind'] for entry in result['outputs']] == ['EVIDENCE', 'OBSERVATION', 'FINDING', 'OUTCOME']
        assert result['outputs'][-1]['content']['finding_ids'] == [result['outputs'][-2]['id']]
        assert result['attempts'][0]['exit_code'] == 0
        assert result['attempts'][0]['execution_reference']
        assert dispatch(client, investigation['id']).status_code == 409


@pytest.mark.parametrize('mode', ['failure', 'missing', 'invalid', 'foreign', 'failure_after_outcome'])
def test_failed_worker_retains_failure_and_allows_a_new_attempt(setup, mode):
    make, _, _ = setup
    with make(mode) as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        assert dispatch(client, identifier).status_code == 202
        result = finished(client, identifier)
        assert result['status'] == 'FAILED'
        assert result['attempts'][0]['error']
    with make() as client:
        assert dispatch(client, identifier, 'retry').status_code == 202
        result = finished(client, identifier)
        assert result['status'] == 'COMPLETED'
        assert [attempt['status'] for attempt in result['attempts']] == ['FAILED', 'COMPLETED']
        assert len({attempt['id'] for attempt in result['attempts']}) == 2


def test_window_links_occurrences_without_creating_extra_investigations(setup):
    make, now, _ = setup
    with make() as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        dispatch(client, identifier)
        finished(client, identifier)
        send(client, payload('resolved'))
        now[0] += timedelta(minutes=59)
        assert send(client, payload('recurring')).json()['queued'] == 0
        records = read(client, 'investigations')
        assert len(records) == 1
        assert len(records[0]['occurrence_ids']) == 2
        now[0] += timedelta(minutes=1)
        body = payload()
        body['alerts'][0]['startsAt'] = '2026-10-14T11:00:00Z'
        assert send(client, body).json()['queued'] == 1
        assert len(read(client, 'investigations')) == 2


def test_resolution_keeps_pending_investigation_eligible(setup):
    make, _, _ = setup
    with make() as client:
        send(client, payload())
        send(client, payload('resolved'))
        investigation = read(client, 'investigations')[0]
        assert investigation['status'] == 'PENDING'
        assert dispatch(client, investigation['id']).status_code == 202
        assert finished(client, investigation['id'])['status'] == 'COMPLETED'


def test_atomic_claim_prevents_overlapping_workers_and_saves_intermediate_output(setup):
    make, now, directory = setup
    with make('wait') as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: dispatch(client, identifier), range(2)))
        assert sorted(response.status_code for response in responses) == [202, 409]
        deadline = time.monotonic() + 10
        while not read(client, f'investigations/{identifier}')['outputs']:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        now[0] += timedelta(hours=2)
        send(client, payload('recurring'))
        assert len(read(client, 'investigations')) == 1
        result = read(client, f'investigations/{identifier}')
        assert result['status'] == 'RUNNING'
        assert len(result['attempts']) == 1
        assert result['outputs'][0]['kind'] == 'EVIDENCE'
        (directory / 'release').touch()
        assert finished(client, identifier)['status'] == 'COMPLETED'


def test_launch_failure_is_recorded_without_leaving_a_claim(setup):
    make, _, _ = setup
    with make() as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
    with TestClient(create_app(
        db_path=setup[2] / 'alerts.sqlite3', webhook_token='test-token',
        worker_command=[str(setup[2] / 'missing-worker')],
    )) as client:
        assert dispatch(client, identifier).status_code == 202
        assert finished(client, identifier)['status'] == 'FAILED'
    with make() as client:
        assert dispatch(client, identifier, 'retry').status_code == 202
        assert finished(client, identifier)['status'] == 'COMPLETED'


def test_dispatch_and_retry_require_authentication(setup):
    make, _, _ = setup
    with make() as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        for action in ('dispatch', 'retry'):
            assert client.post(f'/investigations/{identifier}/{action}').status_code == 401


def test_configurable_window_and_atomic_eligibility(setup):
    make, now, _ = setup
    with make(window_seconds=10) as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        dispatch(client, identifier)
        finished(client, identifier)
        now[0] += timedelta(seconds=10)

        def new_occurrence(number):
            body = payload()
            body['alerts'][0]['startsAt'] = f'2026-10-14T11:00:0{number}Z'
            return send(client, body).json()['queued']

        with ThreadPoolExecutor(max_workers=4) as pool:
            assert sum(pool.map(new_occurrence, range(4))) == 1
        assert len(read(client, 'issues')) == 5
        assert len(read(client, 'investigations')) == 2


def test_shutdown_stops_worker_before_permitting_a_retry(setup):
    make, _, _ = setup
    with make('wait') as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        dispatch(client, identifier)
        deadline = time.monotonic() + 10
        while not read(client, f'investigations/{identifier}')['outputs']:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert dispatch(client, identifier, 'retry').status_code == 409
    with make() as client:
        assert read(client, f'investigations/{identifier}')['status'] == 'FAILED'
        assert dispatch(client, identifier, 'retry').status_code == 202
        assert finished(client, identifier)['status'] == 'COMPLETED'


def test_older_active_attempt_blocks_creation_and_other_dispatch(setup):
    make, now, directory = setup
    with make('failure') as client:
        send(client, payload())
        first = read(client, 'investigations')[0]['id']
        dispatch(client, first)
        finished(client, first)
    now[0] += timedelta(hours=2)
    with make() as client:
        send(client, payload('recurring'))
        second = read(client, 'investigations')[1]['id']
        dispatch(client, second)
        finished(client, second)
    with make('wait') as client:
        assert dispatch(client, first, 'retry').status_code == 202
        now[0] += timedelta(hours=2)
        body = payload()
        body['alerts'][0]['startsAt'] = '2026-10-14T14:00:00Z'
        assert send(client, body).json()['queued'] == 0
        assert len(read(client, 'investigations')) == 2
        assert len(read(client, f'investigations/{first}')['occurrence_ids']) == 2
        (directory / 'release').touch()
        finished(client, first)


def test_two_dispatchers_cannot_run_workers_for_the_same_signature(setup):
    make, now, directory = setup
    with make('failure') as client:
        send(client, payload())
        first = read(client, 'investigations')[0]['id']
        dispatch(client, first)
        finished(client, first)
        now[0] += timedelta(hours=2)
        send(client, payload('recurring'))
        second = read(client, 'investigations')[1]['id']
    with make('wait') as one, make('wait') as two:
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(dispatch, one, first, 'retry'), pool.submit(dispatch, two, second)]
            responses = [request.result() for request in requests]
        assert sorted(response.status_code for response in responses) == [202, 409]
        (directory / 'release').touch()
        for identifier, response in zip((first, second), responses):
            if response.status_code == 202:
                assert finished(one, identifier)['status'] == 'COMPLETED'


def test_finished_attempt_cannot_append_outputs_after_a_retry(setup):

    make, _, directory = setup
    with make('failure') as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        dispatch(client, identifier)
        old = finished(client, identifier)['attempts'][0]['id']
    with make() as client:
        dispatch(client, identifier, 'retry')
        result = finished(client, identifier)
    async def append_late():
        store = Store(directory / 'alerts.sqlite3')
        request = WorkerInput(investigation_id=identifier, attempt_id=old,
                              trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}))
        raw = json.dumps({
            'id': str(uuid4()),
            'kind': 'OBSERVATION', 'content': {'summary': 'Late output'},
        })
        try:
            with pytest.raises(InvestigationConflict, match='not active'):
                await store.investigations.append(request, raw)
        finally:
            await store.close()
    asyncio.run(append_late())
    with make() as client:
        assert read(client, f'investigations/{identifier}')['outputs'] == result['outputs']


def test_store_returns_validated_records_with_uuid_identity(setup):

    make, _, directory = setup
    with make() as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        dispatch(client, identifier)
        response = finished(client, identifier)

    async def inspect():
        store = Store(directory / 'alerts.sqlite3')
        try:
            record = await store.investigations.records(identifier)
            assert isinstance(record, BaseModel)
            assert record.id == UUID(identifier)
            assert record.trigger.occurrence_id == response['trigger']['occurrence_id']
            attempt = record.attempts[0]
            assert attempt.id == UUID(response['attempts'][0]['id'])
            assert attempt.investigation_id == record.id
            assert record.outputs[0].attempt_id == attempt.id
            assert isinstance(record.outputs[0].id, UUID)
            assert isinstance(record.outputs[-2].content, Finding)
            assert isinstance(record.outputs[-1].content, Outcome)
            assert record.model_dump(mode='json') == response
        finally:
            await store.close()

    asyncio.run(inspect())


def test_disabled_dispatch_keeps_intake_enabled_without_creating_an_attempt(setup, monkeypatch):
    monkeypatch.delenv('HAWKDIVE_WORKER_COMMAND', raising=False)
    with TestClient(create_app(db_path=setup[2] / 'alerts.sqlite3', webhook_token='test-token')) as client:
        assert send(client, payload()).status_code == 202
        record = read(client, 'investigations')[0]
        response = dispatch(client, record['id'])
        assert response.status_code == 409
        assert response.json()['detail'] == 'No worker command is configured'
        result = read(client, f"investigations/{record['id']}")
        assert result['status'] == 'PENDING'
        assert result['attempts'] == []
        assert result['outputs'] == []


def test_agent_graph_process_receives_configuration_and_persists_supported_results(setup):

    config = AgentConfig(openrouter_api_key='model-secret', grafana_access_token='mcp-secret', grafana_mcp_token='caller-secret',
                         grafana_url='https://example.grafana.net')
    with TestClient(create_app(
        db_path=setup[2] / 'alerts.sqlite3', webhook_token='test-token', agent_config=config,
        worker_command=[sys.executable, str(WORKER.with_name('agent_worker.py'))],
    )) as client:
        send(client, payload())
        identifier = read(client, 'investigations')[0]['id']
        assert dispatch(client, identifier).status_code == 202
        result = finished(client, identifier)
        assert result['status'] == 'COMPLETED'
        assert [entry['kind'] for entry in result['outputs']] == ['EVIDENCE', 'OBSERVATION', 'FINDING', 'OUTCOME']
        assert result['outputs'][-1]['content']['finding_ids'] == [result['outputs'][-2]['id']]
        saved = json.dumps(result)
        assert 'model-secret' not in saved
        assert 'mcp-secret' not in saved
