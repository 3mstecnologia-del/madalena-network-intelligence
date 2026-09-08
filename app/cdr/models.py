from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class CdrLeg:
    calldate: datetime
    linkedid: str
    uniqueid: str | None
    src: str | None
    dst: str | None
    dcontext: str | None
    channel: str | None
    dstchannel: str | None
    lastapp: str | None
    lastdata: str | None
    duration: int | None
    billsec: int | None
    disposition: str | None
    accountcode: str | None
    userfield: str | None
    peeraccount: str | None
    sequence: int | None


@dataclass(slots=True)
class CdrCanonicalCall:
    linkedid: str
    first_seen: datetime
    last_seen: datetime
    source: str | None
    destination: str | None
    direction: str
    status: str
    answered: bool
    legs: int
    billsec: int
    duration: int
    channel_count: int
    dcontexts: list[str] = field(default_factory=list)
    channel_labels: list[str] = field(default_factory=list)
    dispositions: list[str] = field(default_factory=list)
    ring_time: int = 0
    trunk: str | None = None
    trunk_channel: str | None = None
    extension: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CdrFilters:
    start: datetime
    end: datetime
    direction: str | None = None
    status: str | None = None
    extension: str | None = None
    source: str | None = None
    destination: str | None = None
    trunk: str | None = None
    search: str | None = None
    limit: int = 100
    offset: int = 0
    sort: str = "first_seen_desc"


@dataclass(slots=True)
class CdrDashboard:
    period_start: datetime
    period_end: datetime
    total_calls: int
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
    canonical_calls: list[CdrCanonicalCall]

