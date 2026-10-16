import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from hawkdive.execution import ExecutionDisabled, NullBackend, ProcessBackend
from hawkdive.investigations import AlertTrigger, WorkerInput


def test_null_backend_reports_disabled_execution():
    request = WorkerInput(
        investigation_id=uuid4(), attempt_id=uuid4(),
        trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}),
    )
    with pytest.raises(ExecutionDisabled, match='No worker command is configured'):
        asyncio.run(NullBackend().start(request))


def test_worker_receives_explicit_execution_environment():
    async def run():
        backend = ProcessBackend(
            [sys.executable, '-c', 'import os,sys; data=sys.stdin.read(); print(os.environ["TEST_EXECUTION_TOKEN"]); print("TEST_EXECUTION_TOKEN" in data)'],
            environment={'TEST_EXECUTION_TOKEN': 'private-value'},
        )
        request = WorkerInput(
            investigation_id=uuid4(), attempt_id=uuid4(),
            trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}),
        )
        execution = await backend.start(request)
        lines = [line.strip() async for line in execution.updates()]
        assert await execution.wait() == 0
        assert lines == ['private-value', 'False']

    asyncio.run(run())


def test_execution_waits_for_owned_resource_cleanup_before_completion():
    async def run():
        cleaned = []

        async def cleanup(request):
            cleaned.append(request.attempt_id)

        backend = ProcessBackend([sys.executable, '-c', 'import sys; sys.stdin.read()'], cleanup=cleanup)
        request = WorkerInput(
            investigation_id=uuid4(), attempt_id=uuid4(),
            trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}),
        )
        execution = await backend.start(request)
        assert await execution.wait() == 0
        assert cleaned == [request.attempt_id]
        await execution.wait()
        assert cleaned == [request.attempt_id]

    asyncio.run(run())


def test_stopping_a_worker_does_not_wait_for_unread_output():
    async def run():
        backend = ProcessBackend([sys.executable, str(Path(__file__).parent / 'fixtures' / 'worker.py'), 'bad_stream'])
        execution = await backend.start(WorkerInput(
            investigation_id=uuid4(), attempt_id=uuid4(),
            trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}),
        ))
        assert (await anext(execution.updates())).strip() == 'invalid-json'
        # Let the worker fill the output pipe before requesting termination.
        await asyncio.sleep(0.1)
        try:
            await asyncio.wait_for(execution.stop(), timeout=2)
            assert execution.process.returncode is not None
        finally:
            await execution.process.stdout.read()
            await execution.wait()

    asyncio.run(run())
