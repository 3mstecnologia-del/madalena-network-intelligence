"""dhcp lease kind / client-id / reported last-seen

Revision ID: 004
Revises: 003
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dhcp_leases", sa.Column("lease_kind", sa.String(32)))
    op.add_column("dhcp_leases", sa.Column("client_id", sa.String(128)))
    op.add_column("dhcp_leases", sa.Column("reported_last_seen", sa.String(64)))


def downgrade() -> None:
    op.drop_column("dhcp_leases", "reported_last_seen")
    op.drop_column("dhcp_leases", "client_id")
    op.drop_column("dhcp_leases", "lease_kind")
