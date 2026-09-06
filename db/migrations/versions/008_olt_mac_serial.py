"""olt mac observations: persist ONU serial on each MAC/VLAN/ONT row

The Intelbras G08 collector already parses the ONU serial (SN) from the
`show ont mac-address-table interface gpon ...` output. This migration adds the
`serial` column to the pre-existing `olt_mac_observations` table (the ORM gained
the field, and create_all would diverge from the migration chain), so a learned
MAC row carries MAC + VLAN + ONT-ID + PON + serial + OLT + collection run.
That lets correlation map a UniFi AP / switch MAC observed behind an ONU to the
specific ONU/PON/OLT (location/path evidence, not a direct physical link).

Revision ID: 008
Revises: 007
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("olt_mac_observations", sa.Column("serial", sa.String(64)))
    op.create_index(
        "ix_olt_mac_serial",
        "olt_mac_observations",
        ["serial"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_olt_mac_serial", table_name="olt_mac_observations")
    op.drop_column("olt_mac_observations", "serial")