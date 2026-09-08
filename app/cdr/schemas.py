from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CdrAuthOut(BaseModel):
    authenticated: bool
    username: str
    service: str = "cdr-lesante-portal"

    model_config = {"from_attributes": True}


class CdrFiltersOut(BaseModel):
    start: datetime
    end: datetime
    direction: str | None = None

    model_config = {"from_attributes": True}
    status: str | None = None
    extension: str | None = None
    source: str | None = None
    destination: str | None = None
    trunk: str | None = None
    search: str | None = None
    limit: int
    offset: int
    sort: str


class CdrCanonicalCallOut(BaseModel):
    linkedid: str
    first_seen: datetime
    last_seen: datetime

    model_config = {"from_attributes": True}
    source: str | None = None
    destination: str | None = None
    direction: str
    status: str
    answered: bool
    legs: int
    billsec: int
    duration: int
    channel_count: int
    dcontexts: list[str] = Field(default_factory=list)
    channel_labels: list[str] = Field(default_factory=list)
    dispositions: list[str] = Field(default_factory=list)
    ring_time: int = 0
    trunk: str | None = None
    trunk_channel: str | None = None
    extension: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CdrDashboardOut(BaseModel):
    period_start: datetime
    period_end: datetime
    total_calls: int

    model_config = {"from_attributes": True}
    inbound_calls: int
    outbound_calls: int
    answered_calls: int
    missed_calls: int
    answer_rate: float
    total_duration: int
    total_billsec: int
    total_legs: int
    extensions: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    destinations: list[dict[str, Any]]
    hourly_distribution: list[dict[str, Any]]
    canonical_calls: list[CdrCanonicalCallOut]


class CdrReportOut(BaseModel):
    title: str
    generated_at: datetime
    period_start: datetime

    model_config = {"from_attributes": True}
    period_end: datetime
    summary_html: str
    html: str
    dashboard: CdrDashboardOut
