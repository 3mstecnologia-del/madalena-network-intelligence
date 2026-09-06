"""physical topology: interface observations, device identifiers, links, evidence

Introduces persisted first-class entities for the physical discovery pipeline:

- interface_observations : temporal evidence per interface (name/desc/status/mac,
  source_identifiers and raw evidence preserved; a new row on each change).
- device_identifiers     : trustworthy identity tokens (MAC, chassis-id, serial,
  source_id, mgmt IP) used for correlating links across collectors.
- physical_links         : one consolidated, tenant-scoped link between two
  devices (optionally anchored to local/remote interfaces), never duplicated.
- link_evidence          : each contributing observation/source for a link with
  directly_observed/inferred/confidence and provenance.

Revision ID: 007
Revises: 006
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Interface model gained alert/observability columns in this migration;
    # the (pre-existing) interfaces table must get them too, or persistence
    # fails with UndefinedColumn once the model writes description/source.
    op.add_column("interfaces", sa.Column("description", sa.Text()))
    op.add_column("interfaces", sa.Column("source", sa.String(64), server_default="unknown"))
    op.add_column(
        "interfaces",
        sa.Column("source_identifiers", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "interfaces", sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id"))
    )

    op.create_table(
        "interface_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("interface_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interfaces.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("if_type", sa.String(64)),
        sa.Column("admin_status", sa.String(32)),
        sa.Column("oper_status", sa.String(32)),
        sa.Column("mac", sa.String(17)),
        sa.Column("source_identifiers", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_interface_obs_tenant_id", "interface_observations", ["tenant_id"])
    op.create_index("ix_interface_obs_interface_id", "interface_observations", ["interface_id"])
    op.create_index("ix_interface_obs_device_id", "interface_observations", ["device_id"])

    op.create_table(
        "device_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_device_identifier_lookup", "device_identifiers", ["tenant_id", "kind", "value"])
    op.create_index("ix_dev_id_tenant_id", "device_identifiers", ["tenant_id"])
    op.create_index("ix_dev_id_device_id", "device_identifiers", ["device_id"])

    op.create_table(
        "physical_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("device_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("device_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("interface_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interfaces.id")),
        sa.Column("interface_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interfaces.id")),
        sa.Column("directly_observed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("inferred", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(64)),
        sa.Column("protocol", sa.String(32)),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.UniqueConstraint("tenant_id", "device_a_id", "device_b_id", name="uq_physical_link_pair"),
    )
    op.create_index("ix_phys_link_tenant_id", "physical_links", ["tenant_id"])
    op.create_index("ix_phys_link_device_a", "physical_links", ["device_a_id"])
    op.create_index("ix_phys_link_device_b", "physical_links", ["device_b_id"])

    op.create_table(
        "link_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "physical_link_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("physical_links.id"), nullable=False
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("protocol", sa.String(32)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collection_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("collection_runs.id")),
        sa.Column("directly_observed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("inferred", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_link_evidence_tenant_id", "link_evidence", ["tenant_id"])
    op.create_index("ix_link_evidence_link_id", "link_evidence", ["physical_link_id"])


def downgrade() -> None:
    op.drop_column("interfaces", "collection_run_id")
    op.drop_column("interfaces", "source_identifiers")
    op.drop_column("interfaces", "source")
    op.drop_column("interfaces", "description")
    op.drop_index("ix_link_evidence_link_id", table_name="link_evidence")
    op.drop_index("ix_link_evidence_tenant_id", table_name="link_evidence")
    op.drop_table("link_evidence")
    op.drop_index("ix_phys_link_device_b", table_name="physical_links")
    op.drop_index("ix_phys_link_device_a", table_name="physical_links")
    op.drop_index("ix_phys_link_tenant_id", table_name="physical_links")
    op.drop_table("physical_links")
    op.drop_index("ix_dev_id_device_id", table_name="device_identifiers")
    op.drop_index("ix_dev_id_tenant_id", table_name="device_identifiers")
    op.drop_index("ix_device_identifier_lookup", table_name="device_identifiers")
    op.drop_table("device_identifiers")
    op.drop_index("ix_interface_obs_device_id", table_name="interface_observations")
    op.drop_index("ix_interface_obs_interface_id", table_name="interface_observations")
    op.drop_index("ix_interface_obs_tenant_id", table_name="interface_observations")
    op.drop_table("interface_observations")