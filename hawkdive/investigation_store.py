import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import overload
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hawkdive.investigations import (
    AlertTrigger,
    AttemptRecord,
    InvestigationRecord,
    OutputKind,
    OutputRecord,
    WorkerInput,
    WorkerOutput,
)
from hawkdive.tables import (
    Attempt,
    Investigation,
    InvestigationOccurrence,
    InvestigationOutput,
)


class InvestigationConflict(ValueError):
    pass


class InvestigationStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, window_seconds: int = 3600,
                 clock: Callable[[], datetime] | None = None) -> None:
        if window_seconds <= 0:
            raise ValueError('Investigation window must be positive')
        self.sessions = sessions
        self.window = timedelta(seconds=window_seconds)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def ensure(self, session: AsyncSession, occurrence_id: int, signature: list[str],
                     trigger: AlertTrigger) -> bool:
        """Called within the intake writer transaction; creation and linking are atomic."""
        now = self.clock()
        # Match alert identity across occurrences, not the digest of a whole notification.
        stored_signature = json.dumps(signature)
        existing = await session.scalar(select(Investigation).where(
            Investigation.signature == stored_signature, Investigation.status.in_(('PENDING', 'RUNNING')),
        ).order_by(Investigation.created_at.desc()).limit(1))
        if existing is None:
            existing = await session.scalar(select(Investigation).where(
                Investigation.signature == stored_signature,
            ).order_by(Investigation.created_at.desc(), Investigation.id.desc()).limit(1))
        should_create = existing is None or (
            existing.status in ('FAILED', 'COMPLETED') and
            datetime.fromisoformat(existing.window_ends_at) <= now
        )
        if should_create:
            existing = Investigation(
                id=str(uuid4()), signature=stored_signature, trigger=trigger.model_dump_json(), status='PENDING',
                created_at=now.isoformat(), window_ends_at=(now + self.window).isoformat(),
            )
            session.add(existing)
            await session.flush()
        session.add(InvestigationOccurrence(issue_id=occurrence_id, investigation_id=existing.id))
        return should_create

    @overload
    async def records(self, identifier: None = None) -> list[InvestigationRecord]: ...

    @overload
    async def records(self, identifier: str | UUID) -> InvestigationRecord: ...

    async def records(self, identifier: str | UUID | None = None) -> list[InvestigationRecord] | InvestigationRecord:
        async with self.sessions() as session:
            query = select(Investigation).order_by(Investigation.created_at, Investigation.id)
            if identifier is not None:
                query = query.where(Investigation.id == str(identifier))
            rows = await session.scalars(query)
            results: list[InvestigationRecord] = []
            for row in rows:
                links = await session.scalars(select(InvestigationOccurrence.issue_id).where(
                    InvestigationOccurrence.investigation_id == row.id,
                ).order_by(InvestigationOccurrence.issue_id))
                attempts = list(await session.scalars(select(Attempt).where(
                    Attempt.investigation_id == row.id,
                ).order_by(Attempt.number)))
                outputs = list(await session.scalars(select(InvestigationOutput).join(Attempt).where(
                    Attempt.investigation_id == row.id,
                ).order_by(Attempt.number, InvestigationOutput.sequence)))
                results.append(InvestigationRecord(
                    id=row.id, signature=json.loads(row.signature), trigger=AlertTrigger.model_validate_json(row.trigger),
                    status=row.status, created_at=row.created_at, window_ends_at=row.window_ends_at,
                    occurrence_ids=list(links),
                    attempts=[AttemptRecord.model_validate(attempt) for attempt in attempts],
                    outputs=[OutputRecord.model_validate_json(json.dumps(dict(
                                  id=output.id, attempt_id=output.attempt_id, kind=output.kind,
                                  content=json.loads(output.content), created_at=output.created_at)))
                             for output in outputs],
                ))
            if identifier is not None:
                if not results:
                    raise LookupError('Investigation not found')
                return results[0]
            return results

    async def claim(self, identifier: str | UUID, *, retry: bool = False) -> WorkerInput:
        identifier = str(identifier)
        async with self.sessions.begin() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            investigation = await session.get(Investigation, identifier)
            if investigation is None:
                raise LookupError('Investigation not found')
            expected = 'FAILED' if retry else 'PENDING'
            if investigation.status != expected:
                raise InvestigationConflict(f'Investigation must be {expected}')
            active = await session.scalar(select(Attempt.id).where(
                Attempt.active_signature == investigation.signature,
            ))
            if active:
                raise InvestigationConflict('An attempt for this alert signature is already active')
            number = await session.scalar(select(func.count()).select_from(Attempt).where(
                Attempt.investigation_id == identifier,
            ))
            if not retry and number:
                raise InvestigationConflict('Use retry to create another attempt')
            attempt = Attempt(
                id=str(uuid4()), investigation_id=identifier, active_signature=investigation.signature,
                number=number + 1, status='PENDING', created_at=self.clock().isoformat(),
            )
            session.add(attempt)
            investigation.status = 'PENDING'
            return WorkerInput(investigation_id=identifier, attempt_id=attempt.id,
                               trigger=AlertTrigger.model_validate_json(investigation.trigger))

    async def started(self, request: WorkerInput, execution_reference: str) -> None:
        async with self.sessions.begin() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            attempt = await session.get(Attempt, str(request.attempt_id))
            if attempt is None or attempt.status != 'PENDING' or attempt.investigation_id != str(request.investigation_id):
                raise InvestigationConflict('Attempt is not pending for this investigation')
            attempt.status = 'RUNNING'
            attempt.started_at = self.clock().isoformat()
            attempt.execution_reference = execution_reference
            investigation = await session.get(Investigation, str(request.investigation_id))
            investigation.status = 'RUNNING'

    async def append(self, request: WorkerInput, raw: str) -> None:
        output = WorkerOutput.model_validate_json(raw)
        content = output.content
        async with self.sessions.begin() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            # Ownership comes from the dispatcher's execution context, never from model output.
            attempt = await session.get(Attempt, str(request.attempt_id))
            if (attempt is None or attempt.status != 'RUNNING' or attempt.active_signature is None
                    or attempt.investigation_id != str(request.investigation_id)):
                raise InvestigationConflict('Attempt is not active')
            if await session.get(InvestigationOutput, (attempt.id, str(output.id))):
                raise ValueError('Output ID is already used in this attempt')
            references = {OutputKind.OBSERVATION: ('evidence_ids', OutputKind.EVIDENCE),
                          OutputKind.FINDING: ('observation_ids', OutputKind.OBSERVATION),
                          OutputKind.OUTCOME: ('finding_ids', OutputKind.FINDING)}
            if output.kind in references:
                field, expected = references[output.kind]
                for identifier in getattr(content, field):
                    referenced = await session.get(InvestigationOutput, (attempt.id, str(identifier)))
                    if referenced is None or referenced.kind != expected:
                        raise ValueError(f'{field} must reference saved {expected} records from this attempt')
            if output.kind == OutputKind.OUTCOME and await session.scalar(select(InvestigationOutput.id).where(
                InvestigationOutput.attempt_id == attempt.id, InvestigationOutput.kind == OutputKind.OUTCOME,
            )):
                raise ValueError('An attempt can have only one outcome')
            sequence = await session.scalar(select(func.count()).select_from(InvestigationOutput).where(
                InvestigationOutput.attempt_id == attempt.id,
            ))
            session.add(InvestigationOutput(
                attempt_id=attempt.id, id=str(output.id), kind=output.kind.value,
                content=content.model_dump_json(), created_at=self.clock().isoformat(), sequence=sequence,
            ))

    async def finish(self, request: WorkerInput, exit_code: int | None, error: str | None = None) -> None:
        async with self.sessions.begin() as session:
            await session.execute(text('BEGIN IMMEDIATE'))
            attempt = await session.get(Attempt, str(request.attempt_id))
            if (attempt is None or attempt.status not in ('PENDING', 'RUNNING')
                    or attempt.investigation_id != str(request.investigation_id)):
                raise InvestigationConflict('Attempt is already finished')
            outcome = await session.scalar(select(InvestigationOutput.id).where(
                InvestigationOutput.attempt_id == attempt.id, InvestigationOutput.kind == 'OUTCOME',
            ))
            if not error and (exit_code != 0 or not outcome):
                error = f'Worker exited with code {exit_code}' if exit_code != 0 else 'Worker exited without a valid outcome'
            attempt.status = 'FAILED' if error else 'COMPLETED'
            attempt.exit_code = exit_code
            attempt.error = error
            attempt.finished_at = self.clock().isoformat()
            attempt.active_signature = None
            investigation = await session.get(Investigation, str(request.investigation_id))
            investigation.status = attempt.status
