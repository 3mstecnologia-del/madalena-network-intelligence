"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_site_tenant_slug"),
    )
    op.create_index("ix_sites_tenant_id", "sites", ["tenant_id"])
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("device_type", sa.String(64), nullable=False),
        sa.Column("vendor", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("management_host_ref", sa.String(255)),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "name", name="uq_device_site_name"),
    )
    op.create_index("ix_devices_tenant_id", "devices", ["tenant_id"])
    op.create_index("ix_devices_site_id", "devices", ["site_id"])
    op.create_table(
        "device_credentials_reference",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, unique=True),
        sa.Column("secret_provider", sa.String(64), nullable=False),
        sa.Column("secret_prefix", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text()),
    )
    op.create_index("ix_cred_ref_tenant_id", "device_credentials_reference", ["tenant_id"])
    op.create_table(
        "interfaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("if_type", sa.String(64)),
        sa.Column("admin_status", sa.String(32)),
        sa.Column("oper_status", sa.String(32)),
        sa.UniqueConstraint("device_id", "name", name="uq_iface_device_name"),
    )
    op.create_table(
        "vlans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128)),
        sa.UniqueConstraint("tenant_id", "vlan_id", "site_id", name="uq_vlan_site"),
    )
    op.create_table(
        "mac_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "mac", name="uq_mac_tenant"),
    )
    op.create_index("ix_mac_addresses_mac", "mac_addresses", ["mac"])
    op.create_table(
        "ip_addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("address", sa.String(64), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "address", name="uq_ip_tenant"),
    )
    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("collector_type", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_datasource_tenant_code"),
    )
    op.create_table(
        "collection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id")),
        sa.Column("data_source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("data_sources.id")),
        sa.Column("collector_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("records_seen", sa.Integer(), server_default="0"),
        sa.Column("records_created", sa.Integer(), server_default="0"),
        sa.Column("records_updated", sa.Integer(), server_default="0"),
        sa.Column("error_summary", sa.Text()),
    )
    for table in ("dhcp_leases", "arp_observations", "mac_observations", "olt_mac_observations"):
        pass
    op.create_table(
        "dhcp_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=False),
        sa.Column("hostname", sa.String(255)),
        sa.Column("server", sa.String(128)),
        sa.Column("status", sa.String(64)),
        sa.Column("comment", sa.Text()),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(64)),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_dhcp_leases_mac", "dhcp_leases", ["mac"])
    op.create_table(
        "arp_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=False),
        sa.Column("interface", sa.String(128)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(64)),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_arp_mac", "arp_observations", ["mac"])
    op.create_table(
        "mac_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("interface", sa.String(128)),
        sa.Column("vlan_id", sa.Integer()),
        sa.Column("bridge", sa.String(128)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(64)),
        sa.Column("confidence", sa.Float()),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_mac_obs_mac", "mac_observations", ["mac"])
    op.create_table(
        "olt_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("profile_type", sa.String(64)),
        sa.UniqueConstraint("device_id", "name", name="uq_olt_profile_device"),
    )
    op.create_table(
        "olt_onus",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("ont_id", sa.String(32), nullable=False),
        sa.Column("pon", sa.String(32)),
        sa.Column("serial", sa.String(64)),
        sa.Column("status", sa.String(32)),
        sa.Column("profile_name", sa.String(128)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("device_id", "ont_id", name="uq_onu_device_ont"),
    )
    op.create_table(
        "olt_mac_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("mac", sa.String(17), nullable=False),
        sa.Column("ont_id", sa.String(32)),
        sa.Column("pon", sa.String(32)),
        sa.Column("vlan_id", sa.Integer()),
        sa.Column("gem", sa.String(32)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(64)),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_olt_mac_mac", "olt_mac_observations", ["mac"])


def downgrade() -> None:
    for t in [
        "olt_mac_observations",
        "olt_onus",
        "olt_profiles",
        "mac_observations",
        "arp_observations",
        "dhcp_leases",
        "collection_runs",
        "data_sources",
        "ip_addresses",
        "mac_addresses",
        "vlans",
        "interfaces",
        "device_credentials_reference",
        "devices",
        "sites",
        "tenants",
    ]:
        op.drop_table(t)
