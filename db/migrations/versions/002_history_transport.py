"""collection-run completeness, neighbors, history indexes

Revision ID: 002
Revises: 001
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("last_identity", sa.String(255)))
    op.add_column("devices", sa.Column("last_version", sa.String(128)))
    op.add_column("devices", sa.Column("last_observed_at", sa.DateTime(timezone=True)))

    op.add_column("interfaces", sa.Column("mac", sa.String(17)))
    op.add_column(
        "interfaces",
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "interfaces",
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "interfaces",
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column("collection_runs", sa.Column("collector_version", sa.String(32)))
    op.add_column(
        "collection_runs",
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
    )
    op.add_column(
        "collection_runs",
        sa.Column("completeness", sa.String(16), server_default="unknown"),
    )
    op.add_column(
        "collection_runs",
        sa.Column("commands_ok", sa.Integer(), server_default="0"),
    )
    op.add_column(
        "collection_runs",
        sa.Column("commands_failed", sa.Integer(), server_default="0"),
    )
    op.create_index("ix_collection_runs_site_id", "collection_runs", ["site_id"])
    op.create_index(
        "ix_collection_runs_tenant_started",
        "collection_runs",
        ["tenant_id", "started_at"],
    )

    op.create_index("ix_dhcp_tenant_mac", "dhcp_leases", ["tenant_id", "mac"])
    op.create_index("ix_dhcp_tenant_ip", "dhcp_leases", ["tenant_id", "ip_address"])
    op.create_index("ix_arp_tenant_mac", "arp_observations", ["tenant_id", "mac"])
    op.create_index("ix_arp_tenant_ip", "arp_observations", ["tenant_id", "ip_address"])
    op.create_index("ix_mac_obs_tenant_mac", "mac_observations", ["tenant_id", "mac"])
    op.create_index("ix_ip_addresses_address", "ip_addresses", ["address"])
    op.create_index("ix_ip_addresses_tenant_id", "ip_addresses", ["tenant_id"])
    op.create_index("ix_mac_addresses_tenant_id", "mac_addresses", ["tenant_id"])

    op.create_table(
        "neighbor_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("mac", sa.String(17)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("interface", sa.String(128)),
        sa.Column("identity", sa.String(255)),
        sa.Column("platform", sa.String(128)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(64)),
        sa.Column(
            "collection_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collection_runs.id"),
        ),
    )
    op.create_index("ix_neighbor_observations_tenant_id", "neighbor_observations", ["tenant_id"])
    op.create_index("ix_neighbor_observations_device_id", "neighbor_observations", ["device_id"])
    op.create_index("ix_neighbor_observations_mac", "neighbor_observations", ["mac"])
    op.create_index("ix_neighbor_tenant_mac", "neighbor_observations", ["tenant_id", "mac"])
    op.create_index("ix_neighbor_tenant_ip", "neighbor_observations", ["tenant_id", "ip_address"])


def downgrade() -> None:
    op.drop_table("neighbor_observations")
    op.drop_index("ix_mac_addresses_tenant_id", table_name="mac_addresses")
    op.drop_index("ix_ip_addresses_tenant_id", table_name="ip_addresses")
    op.drop_index("ix_ip_addresses_address", table_name="ip_addresses")
    op.drop_index("ix_mac_obs_tenant_mac", table_name="mac_observations")
    op.drop_index("ix_arp_tenant_ip", table_name="arp_observations")
    op.drop_index("ix_arp_tenant_mac", table_name="arp_observations")
    op.drop_index("ix_dhcp_tenant_ip", table_name="dhcp_leases")
    op.drop_index("ix_dhcp_tenant_mac", table_name="dhcp_leases")
    op.drop_index("ix_collection_runs_tenant_started", table_name="collection_runs")
    op.drop_index("ix_collection_runs_site_id", table_name="collection_runs")
    op.drop_column("collection_runs", "commands_failed")
    op.drop_column("collection_runs", "commands_ok")
    op.drop_column("collection_runs", "completeness")
    op.drop_column("collection_runs", "site_id")
    op.drop_column("collection_runs", "collector_version")
    op.drop_column("interfaces", "observed_at")
    op.drop_column("interfaces", "last_seen")
    op.drop_column("interfaces", "first_seen")
    op.drop_column("interfaces", "mac")
    op.drop_column("devices", "last_observed_at")
    op.drop_column("devices", "last_version")
    op.drop_column("devices", "last_identity")
