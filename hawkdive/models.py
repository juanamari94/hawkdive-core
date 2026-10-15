from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GrafanaAlert(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    fingerprint: str = Field(min_length=1)
    startsAt: str

    @field_validator("startsAt")
    @classmethod
    def require_timestamp_with_timezone(cls, value: str) -> str:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError("startsAt must include a timezone")
        return value


class GrafanaNotification(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    receiver: str = Field(min_length=1)
    status: Literal["firing", "resolved"]
    orgId: int = Field(ge=1)
    alerts: list[GrafanaAlert] = Field(min_length=1)
    truncatedAlerts: int = Field(default=0, ge=0)
