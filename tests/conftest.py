"""Shared in-memory SQLite session and synthetic two-tenant lab."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models import entities  # noqa: F401
from app.models.entities import Device, Site, Tenant

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def seed_two_tenants(db: Session):
    t1 = Tenant(id=uuid.uuid4(), slug="example-tenant", name="Example")
    t2 = Tenant(id=uuid.uuid4(), slug="other-tenant", name="Other")
    db.add_all([t1, t2])
    s1 = Site(id=uuid.uuid4(), tenant_id=t1.id, slug="site-a", name="Site A")
    s2 = Site(id=uuid.uuid4(), tenant_id=t2.id, slug="site-b", name="Site B")
    db.add_all([s1, s2])
    d1 = Device(
        id=uuid.uuid4(),
        tenant_id=t1.id,
        site_id=s1.id,
        name="LAB-MK",
        device_type="mikrotik",
        vendor="MikroTik",
    )
    d1b = Device(
        id=uuid.uuid4(),
        tenant_id=t1.id,
        site_id=s1.id,
        name="LAB-MK-EDGE",
        device_type="mikrotik",
        vendor="MikroTik",
    )
    d1o = Device(
        id=uuid.uuid4(),
        tenant_id=t1.id,
        site_id=s1.id,
        name="LAB-G08",
        device_type="intelbras_g08",
        vendor="Intelbras",
    )
    d2 = Device(
        id=uuid.uuid4(),
        tenant_id=t2.id,
        site_id=s2.id,
        name="OTHER-MK",
        device_type="mikrotik",
    )
    db.add_all([d1, d1b, d1o, d2])
    db.commit()
    return t1, t2, d1, d1b, d1o, d2
