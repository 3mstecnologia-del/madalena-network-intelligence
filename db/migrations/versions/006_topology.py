"""topology observations, inventory nodes, neighbor protocol fields

Revision ID: 006
Revises: 005
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("chassis_mac", sa.String(17)))
    op.add_column("devices", sa.Column("source_ref", sa.String(64)))
    op.create_index("ix_devices_tenant_chassis_mac", "devices", ["tenant_id", "chassis_mac"])
    op.create_index("ix_devices_tenant_source_ref", "devices", ["tenant_id", "source_ref"])

    op.add_column("neighbor_observations", sa.Column("remote_interface", sa.String(128)))
    op.add_column("neighbor_observations", sa.Column("protocol", sa.String(32)))
    op.add_column("neighbor_observations", sa.Column("version", sa.String(128)))

    op.create_table(
        "inventory_node_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "controller_device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("devices.id"),
            nullable=False,
        ),
        sa.Column("observed_device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id")),
        sa.Column("source_id", sa.String(64)),
        sa.Column("name", sa.String(255)),
        sa.Column("mac", sa.String(17)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("category", sa.String(64)),
        sa.Column("state", sa.String(64)),
        sa.Column("firmware", sa.String(128)),
        sa.Column("uplink_source_id", sa.String(64)),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="unifi_inventory"),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_inv_node_tenant_id", "inventory_node_observations", ["tenant_id"])
    op.create_index("ix_inv_node_tenant_mac", "inventory_node_observations", ["tenant_id", "mac"])
    op.create_index(
        "ix_inv_node_tenant_source", "inventory_node_observations", ["tenant_id", "source_id"]
    )

    op.create_table(
        "topology_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
        sa.Column(
            "local_device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False
        ),
        sa.Column("local_interface", sa.String(128)),
        sa.Column("remote_device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id")),
        sa.Column("remote_interface", sa.String(128)),
        sa.Column("remote_identity", sa.String(255)),
        sa.Column("remote_mac", sa.String(17)),
        sa.Column("remote_ip", sa.String(64)),
        sa.Column("remote_source_id", sa.String(64)),
        sa.Column("protocol", sa.String(32)),
        sa.Column("source", sa.String(64), nullable=False, server_default="mikrotik_neighbor"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
    )
    op.create_index("ix_topo_tenant_id", "topology_observations", ["tenant_id"])
    op.create_index("ix_topo_tenant_local", "topology_observations", ["tenant_id", "local_device_id"])
    op.create_index("ix_topo_tenant_remote_mac", "topology_observations", ["tenant_id", "remote_mac"])


def downgrade() -> None:
    op.drop_index("ix_topo_tenant_remote_mac", table_name="topology_observations")
    op.drop_index("ix_topo_tenant_local", table_name="topology_observations")
    op.drop_index("ix_topo_tenant_id", table_name="topology_observations")
    op.drop_table("topology_observations")
    op.drop_index("ix_inv_node_tenant_source", table_name="inventory_node_observations")
    op.drop_index("ix_inv_node_tenant_mac", table_name="inventory_node_observations")
    op.drop_index("ix_inv_node_tenant_id", table_name="inventory_node_observations")
    op.drop_table("inventory_node_observations")
    op.drop_column("neighbor_observations", "version")
    op.drop_column("neighbor_observations", "protocol")
    op.drop_column("neighbor_observations", "remote_interface")
    op.drop_index("ix_devices_tenant_source_ref", table_name="devices")
    op.drop_index("ix_devices_tenant_chassis_mac", table_name="devices")
    op.drop_column("devices", "source_ref")
    op.drop_column("devices", "chassis_mac")
