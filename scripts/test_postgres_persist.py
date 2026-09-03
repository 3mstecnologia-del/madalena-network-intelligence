"""Write/read a synthetic tenant to verify PostgreSQL volume survival.

Used by `make test-persist` around `docker compose restart db`.
Never called against production. Fixtures are synthetic.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import Device, DhcpLease, Site, Tenant
from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease

SLUG = "persist-lab"
MAC = "AA:BB:CC:DD:EE:01"
IP = "10.30.9.9"


def write() -> int:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == SLUG))
        if tenant is None:
            tenant = Tenant(slug=SLUG, name="Persist Lab")
            db.add(tenant)
            db.flush()
        site = db.scalar(select(Site).where(Site.tenant_id == tenant.id, Site.slug == "lab"))
        if site is None:
            site = Site(tenant_id=tenant.id, slug="lab", name="Lab")
            db.add(site)
            db.flush()
        device = db.scalar(select(Device).where(Device.site_id == site.id, Device.name == "LAB-PERSIST"))
        if device is None:
            device = Device(
                tenant_id=tenant.id,
                site_id=site.id,
                name="LAB-PERSIST",
                device_type="mikrotik",
            )
            db.add(device)
            db.flush()
        IngestService(db).ingest_result(
            tenant_id=tenant.id,
            device_id=device.id,
            result=CollectorResult(dhcp=[NormalizedDhcpLease(mac=MAC, ip_address=IP)]),
        )
        db.commit()
        print(f"wrote tenant={SLUG} mac={MAC} ip={IP}")
        return 0
    finally:
        db.close()


def read() -> int:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == SLUG))
        if tenant is None:
            print("FAIL: tenant missing after restart")
            return 1
        lease = db.scalar(
            select(DhcpLease).where(DhcpLease.tenant_id == tenant.id, DhcpLease.mac == MAC)
        )
        if lease is None or lease.ip_address != IP:
            print("FAIL: observation missing after restart")
            return 1
        print("PASS: postgresql volume preserved synthetic observation")
        return 0
    finally:
        db.close()


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {"write", "read"}:
        print("usage: python -m scripts.test_postgres_persist write|read")
        return 2
    return write() if sys.argv[1] == "write" else read()


if __name__ == "__main__":
    sys.exit(main())
