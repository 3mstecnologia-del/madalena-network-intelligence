"""policy exclusions, per-device collectors, collection-run counters

Revision ID: 005
Revises: 004
Create Date: 2026-09-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("collectors_enabled", sa.Text()))
    op.add_column("devices", sa.Column("collection_interval_sec", sa.Integer()))
    op.add_column(
        "collection_runs",
        sa.Column("records_excluded", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "collection_runs",
        sa.Column("parse_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "exclusion_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id")),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id")),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("rule_value", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_exclusion_policies_tenant_id", "exclusion_policies", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_exclusion_policies_tenant_id", table_name="exclusion_policies")
    op.drop_table("exclusion_policies")
    op.drop_column("collection_runs", "parse_failures")
    op.drop_column("collection_runs", "records_excluded")
    op.drop_column("devices", "collection_interval_sec")
    op.drop_column("devices", "collectors_enabled")
