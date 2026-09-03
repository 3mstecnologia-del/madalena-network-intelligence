"""Seed non-secret lab labels for local development. No real IPs/credentials."""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import DataSource, Device, DeviceCredentialReference, Site, Tenant


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == settings.seed_tenant_slug))
        if tenant is None:
            tenant = Tenant(slug=settings.seed_tenant_slug, name="Example Tenant")
            db.add(tenant)
            db.flush()
        site = db.scalar(
            select(Site).where(Site.tenant_id == tenant.id, Site.slug == settings.seed_site_slug)
        )
        if site is None:
            site = Site(tenant_id=tenant.id, slug=settings.seed_site_slug, name="Example Site")
            db.add(site)
            db.flush()

        def ensure_device(name: str, dtype: str, vendor: str, model: str, prefix: str) -> Device:
            d = db.scalar(
                select(Device).where(Device.site_id == site.id, Device.name == name)
            )
            if d is None:
                d = Device(
                    tenant_id=tenant.id,
                    site_id=site.id,
                    name=name,
                    device_type=dtype,
                    vendor=vendor,
                    model=model,
                    management_host_ref=f"secret://{prefix}_HOST",
                    enabled=True,
                )
                db.add(d)
                db.flush()
                db.add(
                    DeviceCredentialReference(
                        tenant_id=tenant.id,
                        device_id=d.id,
                        secret_provider=settings.secret_provider,
                        secret_prefix=prefix,
                        notes="External secret reference only — never store passwords here",
                    )
                )
            return d

        ensure_device("LAB-MK", "mikrotik", "MikroTik", "RouterOS7", "DEVICE_EXAMPLE_MIKROTIK")
        ensure_device("LAB-MK200", "mikrotik", "MikroTik", "RouterOS", "DEVICE_LAB_MK200")
        ensure_device("LAB-G08", "intelbras_g08", "Intelbras", "G08", "DEVICE_LAB_OLT")

        for code, name, ctype in [
            ("mikrotik_dhcp", "MikroTik DHCP", "mikrotik"),
            ("intelbras_g08_mac", "Intelbras G08 MAC", "intelbras_g08"),
        ]:
            ds = db.scalar(
                select(DataSource).where(DataSource.tenant_id == tenant.id, DataSource.code == code)
            )
            if ds is None:
                db.add(
                    DataSource(
                        tenant_id=tenant.id, code=code, name=name, collector_type=ctype
                    )
                )
        db.commit()
        print(f"seeded tenant={tenant.slug} site={site.slug}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
