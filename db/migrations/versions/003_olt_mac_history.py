"""olt mac command + history indexes

Revision ID: 003
Revises: 002
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("olt_mac_observations", sa.Column("command", sa.String(128)))
    op.create_index("ix_olt_mac_tenant_mac", "olt_mac_observations", ["tenant_id", "mac"])
    op.create_index("ix_olt_mac_tenant_ont", "olt_mac_observations", ["tenant_id", "ont_id"])


def downgrade() -> None:
    op.drop_index("ix_olt_mac_tenant_ont", table_name="olt_mac_observations")
    op.drop_index("ix_olt_mac_tenant_mac", table_name="olt_mac_observations")
    op.drop_column("olt_mac_observations", "command")
