from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sites: Mapped[list[Site]] = relationship(back_populates="tenant")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_site_tenant_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="sites")
    devices: Mapped[list[Device]] = relationship(back_populates="site")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_device_site_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False)  # mikrotik | intelbras_g08 | switch
    vendor: Mapped[Optional[str]] = mapped_column(String(64))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    management_host_ref: Mapped[Optional[str]] = mapped_column(String(255))  # placeholder ref, not a secret
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    collectors_enabled: Mapped[Optional[str]] = mapped_column(Text)
    collection_interval_sec: Mapped[Optional[int]] = mapped_column(Integer)
    last_identity: Mapped[Optional[str]] = mapped_column(String(255))
    last_version: Mapped[Optional[str]] = mapped_column(String(128))
    last_observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="devices")
    interfaces: Mapped[list[Interface]] = relationship(back_populates="device")
    credential_ref: Mapped[Optional[DeviceCredentialReference]] = relationship(
        back_populates="device", uselist=False
    )


class DeviceCredentialReference(Base):
    """Logical pointer to an external secret. NEVER stores passwords/tokens."""

    __tablename__ = "device_credentials_reference"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id"), nullable=False, unique=True
    )
    secret_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="infisical")
    secret_prefix: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    device: Mapped[Device] = relationship(back_populates="credential_ref")


class Interface(Base):
    __tablename__ = "interfaces"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_iface_device_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    if_type: Mapped[Optional[str]] = mapped_column(String(64))
    admin_status: Mapped[Optional[str]] = mapped_column(String(32))
    oper_status: Mapped[Optional[str]] = mapped_column(String(32))
    mac: Mapped[Optional[str]] = mapped_column(String(17))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="interfaces")


class Vlan(Base):
    __tablename__ = "vlans"
    __table_args__ = (UniqueConstraint("tenant_id", "vlan_id", "site_id", name="uq_vlan_site"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sites.id"))
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(128))


class MacAddress(Base):
    __tablename__ = "mac_addresses"
    __table_args__ = (UniqueConstraint("tenant_id", "mac", name="uq_mac_tenant"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(17), nullable=False, index=True)  # AA:BB:CC:DD:EE:FF
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IpAddress(Base):
    __tablename__ = "ip_addresses"
    __table_args__ = (UniqueConstraint("tenant_id", "address", name="uq_ip_tenant"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSource(Base):
    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_datasource_tenant_code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    collector_type: Mapped[str] = mapped_column(String(64), nullable=False)


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("devices.id"), index=True)
    data_source_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("data_sources.id"))
    collector_type: Mapped[str] = mapped_column(String(64), nullable=False)
    collector_version: Mapped[Optional[str]] = mapped_column(String(32))
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sites.id"), index=True)
    completeness: Mapped[str] = mapped_column(String(16), default="unknown")
    commands_ok: Mapped[int] = mapped_column(Integer, default=0)
    commands_failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_excluded: Mapped[int] = mapped_column(Integer, default=0)
    parse_failures: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text)


class ExclusionPolicy(Base):
    """Runtime exclusion: drop matching observations before persist. No customer values in Git."""

    __tablename__ = "exclusion_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    site_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sites.id"))
    device_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("devices.id"))
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_value: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DhcpLease(Base):
    __tablename__ = "dhcp_leases"
    __table_args__ = (
        Index("ix_dhcp_tenant_mac", "tenant_id", "mac"),
        Index("ix_dhcp_tenant_ip", "tenant_id", "ip_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(17), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(255))
    server: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[Optional[str]] = mapped_column(String(64))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    lease_kind: Mapped[Optional[str]] = mapped_column(String(32))
    client_id: Mapped[Optional[str]] = mapped_column(String(128))
    reported_last_seen: Mapped[Optional[str]] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(64), default="mikrotik_dhcp")
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("collection_runs.id"))


class ArpObservation(Base):
    __tablename__ = "arp_observations"
    __table_args__ = (
        Index("ix_arp_tenant_mac", "tenant_id", "mac"),
        Index("ix_arp_tenant_ip", "tenant_id", "ip_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(17), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    interface: Mapped[Optional[str]] = mapped_column(String(128))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(64), default="mikrotik_arp")
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("collection_runs.id"))


class MacObservation(Base):
    """FDB / bridge host / switch MAC table observations."""

    __tablename__ = "mac_observations"
    __table_args__ = (Index("ix_mac_obs_tenant_mac", "tenant_id", "mac"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(17), nullable=False, index=True)
    interface: Mapped[Optional[str]] = mapped_column(String(128))
    vlan_id: Mapped[Optional[int]] = mapped_column(Integer)
    bridge: Mapped[Optional[str]] = mapped_column(String(128))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(64), default="bridge_fdb")
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("collection_runs.id"))


class OltProfile(Base):
    __tablename__ = "olt_profiles"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_olt_profile_device"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_type: Mapped[Optional[str]] = mapped_column(String(64))  # line | vlan | dba | rule


class OltOnu(Base):
    __tablename__ = "olt_onus"
    __table_args__ = (UniqueConstraint("device_id", "ont_id", name="uq_onu_device_ont"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    ont_id: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. 0/1/14
    pon: Mapped[Optional[str]] = mapped_column(String(32))
    serial: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    status: Mapped[Optional[str]] = mapped_column(String(32))
    profile_name: Mapped[Optional[str]] = mapped_column(String(128))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OltMacObservation(Base):
    __tablename__ = "olt_mac_observations"
    __table_args__ = (
        Index("ix_olt_mac_tenant_mac", "tenant_id", "mac"),
        Index("ix_olt_mac_tenant_ont", "tenant_id", "ont_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    mac: Mapped[str] = mapped_column(String(17), nullable=False, index=True)
    ont_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    pon: Mapped[Optional[str]] = mapped_column(String(32))
    vlan_id: Mapped[Optional[int]] = mapped_column(Integer)
    gem: Mapped[Optional[str]] = mapped_column(String(32))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(64), default="olt")
    command: Mapped[Optional[str]] = mapped_column(String(128))
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("collection_runs.id"))


class NeighborObservation(Base):
    """LLDP/CDP-style neighbor rows. Absence in a later run does not delete history."""

    __tablename__ = "neighbor_observations"
    __table_args__ = (
        Index("ix_neighbor_tenant_mac", "tenant_id", "mac"),
        Index("ix_neighbor_tenant_ip", "tenant_id", "ip_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    mac: Mapped[Optional[str]] = mapped_column(String(17), index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    interface: Mapped[Optional[str]] = mapped_column(String(128))
    identity: Mapped[Optional[str]] = mapped_column(String(255))
    platform: Mapped[Optional[str]] = mapped_column(String(128))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(64), default="mikrotik_neighbor")
    collection_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("collection_runs.id"))
