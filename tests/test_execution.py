import asyncio
import pytest
import sys
from pathlib import Path
from uuid import uuid4

from hawkdive.execution import ExecutionDisabled, NullBackend, ProcessBackend
from hawkdive.investigations import AlertTrigger, WorkerInput


def test_null_backend_reports_disabled_execution():
    request = WorkerInput(
        investigation_id=uuid4(), attempt_id=uuid4(),
        trigger=AlertTrigger(integration='test', occurrence_id=1, reference='/issues/1', alert={}),
    )
    with pytest.raises(ExecutionDisabled, match='No worker command is configured'):
        asyncio.run(NullBackend().start(request))


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
