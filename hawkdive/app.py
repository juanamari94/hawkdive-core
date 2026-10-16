import json
import os
import secrets
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError

from hawkdive.agent.config import AgentConfig
from hawkdive.agent.shell import DockerSandbox
from hawkdive.dispatcher import Dispatcher
from hawkdive.execution import ExecutionDisabled, NullBackend, ProcessBackend
from hawkdive.investigation_store import InvestigationConflict
from hawkdive.investigations import InvestigationRecord, WorkerInput
from hawkdive.models import GrafanaNotification
from hawkdive.store import Store


def create_app(*, db_path: str | Path | None = None, webhook_token: str | None = None,
               window_seconds: int | None = None, clock: Callable[[], datetime] | None = None,
               worker_command: list[str] | None = None, agent_config: AgentConfig | None = None) -> FastAPI:
    window_seconds = window_seconds if window_seconds is not None else int(os.getenv('HAWKDIVE_INVESTIGATION_WINDOW_SECONDS', '3600'))
    store = Store(Path(db_path or os.getenv("HAWKDIVE_DB_PATH", "hawkdive.sqlite3")),
                  window_seconds=window_seconds, clock=clock)
    if worker_command is None and os.getenv('HAWKDIVE_WORKER_COMMAND'):
        worker_command = json.loads(os.environ['HAWKDIVE_WORKER_COMMAND'])
    if agent_config is None and os.getenv('HAWKDIVE_AGENT_ENABLED', '').lower() == 'true':
        agent_config = AgentConfig.from_environment()
    agent_worker = agent_config is not None and worker_command is None
    if agent_config is not None and worker_command is None:
        worker_command = [sys.executable, '-m', 'hawkdive.agent']
    environment = agent_config.worker_environment() if agent_config else None

    async def cleanup_sandbox(request: WorkerInput) -> None:
        assert agent_config is not None
        sandbox = DockerSandbox(request.attempt_id, image=agent_config.sandbox_image)
        await sandbox.remove()

    dispatcher = Dispatcher(store.investigations,
                            ProcessBackend(worker_command, environment=environment,
                                           cleanup=cleanup_sandbox if agent_worker else None)
                            if worker_command else NullBackend())
    token = webhook_token if webhook_token is not None else os.getenv(
        "HAWKDIVE_WEBHOOK_TOKEN", "local-dev-token"
    )
    if not token:
        raise ValueError("The webhook token must not be empty")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await store.initialize()
            yield
        finally:
            await dispatcher.close()
            await store.close()

    async def authorize(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}".encode()
        if not secrets.compare_digest((authorization or "").encode(), expected):
            raise HTTPException(
                status_code=401, detail="Invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    app = FastAPI(title="Hawkdive Core", lifespan=lifespan, dependencies=[Depends(authorize)])

    @app.post("/webhooks/grafana/{source}", status_code=202)
    async def receive(source: str, notification: GrafanaNotification) -> dict[str, int | bool]:
        try:
            return await store.accept(source, notification.model_dump(exclude_unset=True))
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="Alert storage unavailable") from error

    @app.get("/issues")
    async def issues() -> list[dict[str, JsonValue]]:
        return await store.issues()

    @app.get('/issues/{identifier}')
    async def issue(identifier: int) -> dict[str, JsonValue]:
        rows = await store.issues()
        for row in rows:
            if row['id'] == identifier:
                return row
        raise HTTPException(status_code=404, detail='Occurrence not found')

    @app.get('/investigations')
    async def investigations() -> list[InvestigationRecord]:
        return await store.investigations.records()

    @app.get('/investigations/{identifier}')
    async def investigation(identifier: str) -> InvestigationRecord:
        try:
            return await store.investigations.records(identifier)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    async def dispatch_investigation(identifier: str, retry: bool = False) -> dict[str, str | UUID]:
        try:
            return await dispatcher.dispatch(identifier, retry=retry)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (InvestigationConflict, ExecutionDisabled) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail='Investigation storage unavailable') from error

    @app.post('/investigations/{identifier}/dispatch', status_code=202)
    async def dispatch(identifier: str) -> dict[str, str | UUID]:
        return await dispatch_investigation(identifier)

    @app.post('/investigations/{identifier}/retry', status_code=202)
    async def retry(identifier: str) -> dict[str, str | UUID]:
        return await dispatch_investigation(identifier, retry=True)

    @app.get("/jobs")
    async def jobs() -> list[dict[str, JsonValue]]:
        return await store.jobs()

    @app.get("/notifications")
    async def notifications() -> list[dict[str, JsonValue]]:
        return await store.notifications()

    return app


app = create_app()
