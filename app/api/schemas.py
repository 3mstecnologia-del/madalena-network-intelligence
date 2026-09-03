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

    model_config = {"from_attributes": True}


class MacListItem(BaseModel):
    mac: str
    first_seen: datetime
    last_seen: datetime


class CollectionRunOut(BaseModel):
    id: UUID
    tenant_id: UUID
    device_id: Optional[UUID] = None
    collector_type: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    records_seen: int
    records_created: int
    records_updated: int
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
    dhcp: list[dict[str, Any]] = Field(default_factory=list)
    arp: list[dict[str, Any]] = Field(default_factory=list)
    fdb: list[dict[str, Any]] = Field(default_factory=list)
    access_path: Optional[dict[str, Any]] = None
    olt_macs: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
