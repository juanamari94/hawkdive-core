import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event, select, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry
from pydantic import JsonValue

from hawkdive.database import database_url, migration_config
from hawkdive.investigation_store import InvestigationStore
from hawkdive.investigations import AlertTrigger
from hawkdive.tables import AlertOccurrence, Notification


class Store:
    def __init__(self, path: Path, *, window_seconds: int = 3600,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self.engine = create_async_engine(database_url(path), connect_args={'timeout': 10})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.investigations = InvestigationStore(self.sessions, window_seconds=window_seconds, clock=clock)

        @event.listens_for(self.engine.sync_engine, 'connect')
        def enable_foreign_keys(connection: DBAPIConnection, _: ConnectionPoolEntry) -> None:
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys = ON')
            cursor.close()

    async def initialize(self) -> None:
        message = 'Run uv run alembic upgrade head before starting Hawkdive'
        if not self.path.is_file():
            raise RuntimeError(message)
        async with self.engine.connect() as connection:
            current = await connection.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_heads()
            )
        expected = tuple(ScriptDirectory.from_config(migration_config()).get_heads())
        if set(current) != set(expected):
            raise RuntimeError(message)

    async def close(self) -> None:
        await self.engine.dispose()

    async def accept(self, source: str, payload: dict[str, Any]) -> dict[str, int | bool]:
        serialized = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        response = {
            'received': len(payload['alerts']), 'created': 0, 'queued': 0,
            'duplicate': False, 'truncated_alerts': payload.get('truncatedAlerts', 0),
        }
        async with self.sessions.begin() as session:
            # Acquire the writer lock before reading occurrence state.
            await session.execute(text('BEGIN IMMEDIATE'))
            existing_notification = await session.scalar(select(Notification.id).where(
                Notification.source == source, Notification.grafana_org_id == payload['orgId'],
                Notification.digest == digest,
            ))
            if existing_notification is not None:
                response['duplicate'] = True
                return response
            session.add(Notification(source=source, grafana_org_id=payload['orgId'],
                                     digest=digest, payload=serialized))
            for alert in payload['alerts']:
                started = datetime.fromisoformat(alert['startsAt']).astimezone(timezone.utc).isoformat()
                issue = await session.scalar(select(AlertOccurrence).where(
                    AlertOccurrence.source == source, AlertOccurrence.grafana_org_id == payload['orgId'],
                    AlertOccurrence.fingerprint == alert['fingerprint'], AlertOccurrence.starts_at == started,
                ))
                if issue is None:
                    issue = AlertOccurrence(source=source, grafana_org_id=payload['orgId'],
                                  fingerprint=alert['fingerprint'], starts_at=started,
                                  status=alert['status'], alert=json.dumps(alert))
                    session.add(issue)
                    await session.flush()
                    response['created'] += 1
                    if alert['status'] == 'firing':
                        created = await self.investigations.ensure(
                            session, issue.id, ['grafana', source, str(payload['orgId']), alert['fingerprint']],
                            AlertTrigger(integration='grafana', occurrence_id=issue.id,
                                         reference=f'/issues/{issue.id}', alert=alert),
                        )
                        response['queued'] += int(created)
                elif issue.status != 'resolved':
                    # Resolution remains terminal when firing arrives late.
                    issue.status = alert['status']
                    issue.alert = json.dumps(alert)
        return response

    async def issues(self) -> list[dict[str, JsonValue]]:
        async with self.sessions() as session:
            rows = await session.scalars(select(AlertOccurrence).order_by(AlertOccurrence.id))
            return [dict(id=row.id, source=row.source, grafana_org_id=row.grafana_org_id,
                         fingerprint=row.fingerprint, starts_at=row.starts_at,
                         status=row.status, alert=json.loads(row.alert)) for row in rows]

    async def jobs(self) -> list[dict[str, JsonValue]]:
        # Compatibility view. Investigations replace the old per-occurrence queue.
        return [dict(id=str(row.id), issue_id=row.trigger.occurrence_id, status=row.status.lower())
                for row in await self.investigations.records()]

    async def notifications(self) -> list[dict[str, JsonValue]]:
        async with self.sessions() as session:
            rows = await session.scalars(select(Notification).order_by(Notification.id))
            return [dict(id=row.id, source=row.source, grafana_org_id=row.grafana_org_id,
                         payload=json.loads(row.payload)) for row in rows]
