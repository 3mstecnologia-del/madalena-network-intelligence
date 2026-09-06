"""Restart/reopen must preserve observation history (portable SQLite analog of PG volume)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import entities  # noqa: F401
from app.models.entities import DhcpLease, Tenant, TopologyObservation
from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease, NormalizedTopologyLink
from tests.conftest import seed_two_tenants


def test_reopen_preserves_postgres_like_history(tmp_path: Path):
    db_path = tmp_path / "ni.sqlite"
    url = f"sqlite+pysqlite:///{db_path}"

    engine = create_engine(url)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    t1, _, d1, _, _, _ = seed_two_tenants(session)
    IngestService(session).ingest_result(
        tenant_id=t1.id,
        device_id=d1.id,
        result=CollectorResult(
            dhcp=[
                NormalizedDhcpLease(
                    mac="AA:BB:CC:DD:EE:FF",
                    ip_address="10.30.1.50",
                    hostname="notebook-exemplo",
                )
            ],
            topology_links=[
                NormalizedTopologyLink(
                    local_interface="sfp1",
                    remote_mac="AA:BB:CC:10:00:02",
                    protocol="lldp",
                )
            ],
        ),
    )
    session.commit()
    tenant_id = t1.id
    session.close()
    engine.dispose()

    engine2 = create_engine(url)
    Session2 = sessionmaker(bind=engine2)
    session2 = Session2()
    tenant = session2.scalar(select(Tenant).where(Tenant.slug == "example-tenant"))
    assert tenant is not None
    assert tenant.id == tenant_id
    leases = list(session2.scalars(select(DhcpLease).where(DhcpLease.tenant_id == tenant.id)))
    assert len(leases) == 1
    assert leases[0].mac == "AA:BB:CC:DD:EE:FF"
    assert leases[0].ip_address == "10.30.1.50"
    links = list(
        session2.scalars(
            select(TopologyObservation).where(TopologyObservation.tenant_id == tenant.id)
        )
    )
    assert len(links) == 1
    assert links[0].remote_mac == "AA:BB:CC:10:00:02"
    session2.close()
    engine2.dispose()
