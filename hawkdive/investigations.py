"""Structured worker inputs and outputs, independent of an alert integration."""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('source', 'query', 'reasoning', 'source_url', 'summary', 'conclusion',
                     'integration', 'reference', check_fields=False)
    @classmethod
    def require_text(cls, value: str) -> str:
        # Runtime validation does not add provider-specific JSON Schema length keywords.
        if not value.strip():
            raise ValueError('Text must not be blank')
        return value


class Evidence(Contract):
    source: str
    query: str
    starts_at: AwareDatetime = Field(strict=False)
    ends_at: AwareDatetime = Field(strict=False)
    reasoning: str = Field(description='Concise explanation of the evidence and what it establishes.')
    source_url: str

    @model_validator(mode='after')
    def ordered_range(self) -> 'Evidence':
        if self.ends_at < self.starts_at:
            raise ValueError('Evidence end time precedes its start time')
        return self


class Observation(Contract):
    summary: str
    evidence_ids: list[UUID] = Field(default_factory=list)
    memory_references: list[str] = Field(default_factory=list)


class Finding(Contract):
    summary: str
    observation_ids: list[UUID]

    @field_validator('observation_ids')
    @classmethod
    def require_observations(cls, value: list[UUID]) -> list[UUID]:
        if not value:
            raise ValueError('A finding must reference at least one observation')
        return value


class Outcome(Contract):
    conclusion: str
    finding_ids: list[UUID]
    uncertainty: str = Field(default='', description='Evidence gaps and limits of the final interpretation.')
    next_steps: list[str] = Field(default_factory=list, description='Suggested follow-up checks or actions; not executed by the wrapper.')

    @field_validator('finding_ids')
    @classmethod
    def require_findings(cls, value: list[UUID]) -> list[UUID]:
        if not value:
            raise ValueError('An outcome must reference at least one finding')
        return value


class AlertTrigger(Contract):
    """Original occurrence reference and its unchanged source payload."""

    integration: str
    occurrence_id: int
    reference: str
    alert: dict[str, JsonValue]


class WorkerInput(Contract):
    investigation_id: UUID = Field(strict=False)
    attempt_id: UUID = Field(strict=False)
    trigger: AlertTrigger


class OutputKind(StrEnum):
    EVIDENCE = 'EVIDENCE'
    OBSERVATION = 'OBSERVATION'
    FINDING = 'FINDING'
    OUTCOME = 'OUTCOME'


class WorkerOutput(Contract):
    """Worker-authored record. The orchestrator supplies its execution ownership."""

    id: UUID = Field(strict=False)
    kind: OutputKind
    content: Evidence | Observation | Finding | Outcome

    @model_validator(mode='after')
    def matching_content(self) -> 'WorkerOutput':
        if not isinstance(self.content, OUTPUT_TYPES[self.kind]):
            raise ValueError('Output kind must match its content type')
        return self


OUTPUT_TYPES: dict[OutputKind, type[Evidence | Observation | Finding | Outcome]] = {
    OutputKind.EVIDENCE: Evidence, OutputKind.OBSERVATION: Observation,
    OutputKind.FINDING: Finding, OutputKind.OUTCOME: Outcome,
}


class AttemptRecord(Contract):
    model_config = ConfigDict(extra='forbid', strict=True, from_attributes=True)

    id: UUID = Field(strict=False)
    investigation_id: UUID = Field(strict=False)
    number: int
    status: str
    created_at: AwareDatetime = Field(strict=False)
    started_at: AwareDatetime | None = Field(strict=False)
    finished_at: AwareDatetime | None = Field(strict=False)
    execution_reference: str | None
    exit_code: int | None
    error: str | None


class OutputRecord(WorkerOutput):
    attempt_id: UUID = Field(strict=False)
    created_at: AwareDatetime = Field(strict=False)


class InvestigationRecord(Contract):
    id: UUID = Field(strict=False)
    signature: list[str]
    trigger: AlertTrigger
    status: str
    created_at: AwareDatetime = Field(strict=False)
    window_ends_at: AwareDatetime = Field(strict=False)
    occurrence_ids: list[int]
    attempts: list[AttemptRecord]
    outputs: list[OutputRecord]
