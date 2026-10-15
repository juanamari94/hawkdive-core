import asyncio
from uuid import UUID

from hawkdive.execution import ExecutionBackend
from hawkdive.investigation_store import InvestigationStore
from hawkdive.investigations import WorkerInput


class Dispatcher:
    def __init__(self, store: InvestigationStore, backend: ExecutionBackend) -> None:
        self.store = store
        self.backend = backend
        self.tasks: set[asyncio.Task[None]] = set()

    async def dispatch(self, identifier: str | UUID, *, retry: bool = False) -> dict[str, str | UUID]:
        self.backend.check_available()
        request = await self.store.claim(identifier, retry=retry)
        # The task owns launch through completion, even if the HTTP caller disconnects.
        task = asyncio.create_task(self._run(request))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {'investigation_id': identifier, 'attempt_id': request.attempt_id, 'status': 'PENDING'}

    async def _run(self, request: WorkerInput) -> None:
        execution = None
        launch = asyncio.create_task(self.backend.start(request))
        try:
            execution = await asyncio.shield(launch)
            await self.store.started(request, execution.reference)
            async for update in execution.updates():
                await self.store.append(request, update)
            exit_code = await execution.wait()
            await self.store.finish(request, exit_code)
        except asyncio.CancelledError:
            if execution is None:
                try:
                    execution = await launch
                except Exception as error:
                    await self.store.finish(request, None, f'Worker launch failed: {error}')
                    return
            if execution is not None:
                code = await execution.stop()
            else:
                code = None
            await self.store.finish(request, code, 'Dispatcher stopped before execution completed')
        except Exception as error:
            # Keep the claim until termination is confirmed, including invalid output.
            code = await execution.stop() if execution is not None else None
            await self.store.finish(request, code, f'{type(error).__name__}: {error}')

    async def close(self) -> None:
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks)
