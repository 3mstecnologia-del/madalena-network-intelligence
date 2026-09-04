from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    service: str = "madalena-network-intelligence"


class TenantOut(BaseModel):
    id: UUID
    slug: str
    name: str

    model_config = {"from_attributes": True}


class DeviceOut(BaseModel):
    id: UUID
    tenant_id: UUID
    site_id: UUID
    name: str
    device_type: str
    vendor: Optional[str] = None
    model: Optional[str] = None
    enabled: bool
    collectors_enabled: Optional[str] = None
    collection_interval_sec: Optional[int] = None
    last_identity: Optional[str] = None
    last_version: Optional[str] = None
    last_observed_at: Optional[datetime] = None
    chassis_mac: Optional[str] = None
    source_ref: Optional[str] = None

    model_config = {"from_attributes": True}


class MacListItem(BaseModel):
    mac: str
    first_seen: datetime
    last_seen: datetime


class CollectionRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    device_id: Optional[UUID] = None
    site_id: Optional[UUID] = None
    collector_type: str
    collector_version: Optional[str] = None
    status: str
    completeness: str = "unknown"
    started_at: datetime
    finished_at: Optional[datetime] = None
    records_seen: int
    records_created: int
    records_updated: int
    records_excluded: int = 0
    parse_failures: int = 0
    commands_ok: int = 0
    commands_failed: int = 0
    error_summary: Optional[str] = None

    model_config = {"from_attributes": True}


class MacDetailOut(BaseModel):
    mac: str
    tenant: str
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    hostname: Optional[str] = None
    current_ips: list[dict[str, Any]] = Field(default_factory=list)
    historical_ips: list[dict[str, Any]] = Field(default_factory=list)
    current_locations: list[dict[str, Any]] = Field(default_factory=list)
    historical_locations: list[dict[str, Any]] = Field(default_factory=list)
    dhcp: list[dict[str, Any]] = Field(default_factory=list)
    arp: list[dict[str, Any]] = Field(default_factory=list)
    fdb: list[dict[str, Any]] = Field(default_factory=list)
    neighbors: list[dict[str, Any]] = Field(default_factory=list)
    access_path: Optional[dict[str, Any]] = None
    olt_macs: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
