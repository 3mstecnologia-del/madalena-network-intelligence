"""Register real devices as collector targets WITHOUT storing credentials.

Operator tool: creates/upserts Tenant, Site, Device and a
DeviceCredentialReference (secret_provider + secret_prefix) so the scheduler can
resolve device credentials at runtime from the configured secret provider.

Device specs come from a JSON file or per-field flags. This script stores only
non-secret labels and an external secret *reference* — never a host IP, username,
or password.

Example spec file (gitignored, outside the repo):
    [
      {
        "tenant": "uniplac", "site": "uniplac-main",
        "name": "OLT-G08-01", "device_type": "intelbras_g08",
        "vendor": "Intelbras", "model": "G08",
        "secret_prefix": "OLT_UNIPLAC",
        "collectors_enabled": ["ont_mac_table", "ont_brief"]
      }
    ]

Usage:
    python -m scripts.register_devices --spec /path/to/devices.json
    python -m scripts.register_devices --tenant uniplac --site uniplac-main \\
        --name OLT-G08-01 --type intelbras_g08 --prefix OLT_UNIPLAC

Secrets are resolved later by collectors via resolve_secrets(provider, prefix).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import (
    Device,
    DeviceCredentialReference,
    Site,
    Tenant,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("register_devices")

ALLOWED_TYPES = {"mikrotik", "intelbras_g08", "unifi_network", "switch"}


def _safe_str(value: Any, field: str) -> str:
    text = (str(value or "")).strip()
    if not text:
        raise SystemExit(f"missing required field: {field}")
    return text


def _ensure_tenant_site(db, tenant_slug: str, site_slug: str, site_name: Optional[str]):
    tenant = db.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        tenant = Tenant(slug=tenant_slug, name=tenant_slug)
        db.add(tenant)
        db.flush()
    site = db.scalar(
        select(Site).where(Site.tenant_id == tenant.id, Site.slug == site_slug)
    )
    if site is None:
        site = Site(tenant_id=tenant.id, slug=site_slug, name=site_name or site_slug)
        db.add(site)
        db.flush()
    return tenant, site


def register_device(
    *,
    tenant_slug: str,
    site_slug: str,
    name: str,
    device_type: str,
    prefix: str,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    site_name: Optional[str] = None,
    collectors_enabled: Optional[list[str]] = None,
    enabled: bool = True,
) -> dict[str, str]:
    db = SessionLocal()
    try:
        tenant, site = _ensure_tenant_site(db, tenant_slug, site_slug, site_name)
        device = db.scalar(
            select(Device).where(Device.site_id == site.id, Device.name == name)
        )
        created = device is None
        if device is None:
            device = Device(
                tenant_id=tenant.id,
                site_id=site.id,
                name=name,
                device_type=device_type,
                vendor=vendor,
                model=model,
                management_host_ref=f"secret://{prefix}_HOST",
                enabled=enabled,
                collectors_enabled=_json_list(collectors_enabled),
            )
            db.add(device)
            db.flush()
        else:
            device.device_type = device_type
            device.vendor = vendor or device.vendor
            device.model = model or device.model
            device.enabled = enabled
            if collectors_enabled is not None:
                device.collectors_enabled = _json_list(collectors_enabled)
            db.add(device)

        ref = db.scalar(
            select(DeviceCredentialReference).where(
                DeviceCredentialReference.device_id == device.id
            )
        )
        provider = os.getenv("SECRET_PROVIDER", "infisical").strip().lower() or "infisical"
        if ref is None:
            db.add(
                DeviceCredentialReference(
                    tenant_id=tenant.id,
                    device_id=device.id,
                    secret_provider=provider,
                    secret_prefix=prefix,
                    notes="External secret reference only; resolved at runtime",
                )
            )
        else:
            ref.secret_provider = provider
            ref.secret_prefix = prefix
            db.add(ref)
        db.commit()
        return {
            "tenant": tenant.slug,
            "site": site.slug,
            "name": device.name,
            "type": device.device_type,
            "prefix": prefix,
            "created": "yes" if created else "no",
        }
    finally:
        db.close()


def _json_list(value: Optional[list[str]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def _from_spec(spec: dict[str, Any]) -> None:
    name = _safe_str(spec.get("name"), "name")
    device_type = _safe_str(spec.get("device_type"), "device_type")
    if device_type not in ALLOWED_TYPES:
        raise SystemExit(f"unsupported device_type: {device_type}")
    tenant = _safe_str(spec.get("tenant"), "tenant")
    site = _safe_str(spec.get("site"), "site")
    prefix = _safe_str(spec.get("secret_prefix"), "secret_prefix")
    collectors = spec.get("collectors_enabled")
    if collectors is not None:
        collectors = [str(c).strip() for c in collectors if str(c).strip()]

    info = register_device(
        tenant_slug=tenant,
        site_slug=site,
        name=name,
        device_type=device_type,
        prefix=prefix,
        vendor=spec.get("vendor"),
        model=spec.get("model"),
        site_name=spec.get("site_name"),
        collectors_enabled=collectors,
        enabled=bool(spec.get("enabled", True)),
    )
    log.info(
        "[%s/%s] %s (%s) created=%s prefix=%s",
        info["tenant"],
        info["site"],
        info["name"],
        info["type"],
        info["created"],
        info["prefix"],
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, help="JSON file with a list of device specs")
    ap.add_argument("--tenant", help="tenant slug")
    ap.add_argument("--site", help="site slug")
    ap.add_argument("--name", help="device name")
    ap.add_argument("--type", dest="device_type", choices=sorted(ALLOWED_TYPES))
    ap.add_argument("--prefix", help="secret prefix (e.g. OLT_UNIPLAC)")
    ap.add_argument("--vendor", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument(
        "--collector",
        action="append",
        default=None,
        help="enabled collector key (repeatable)",
    )
    args = ap.parse_args()

    if args.spec:
        try:
            data = json.loads(args.spec.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"failed to read spec file: {exc}") from exc
        specs = data if isinstance(data, list) else [data]
        for spec in specs:
            _from_spec(spec)
        log.info("registered %d device(s)", len(specs))
        return

    required = [args.tenant, args.site, args.name, args.device_type, args.prefix]
    if any(v is None for v in required):
        raise SystemExit("--spec OR (--tenant --site --name --type --prefix) required")
    info = register_device(
        tenant_slug=args.tenant,
        site_slug=args.site,
        name=args.name,
        device_type=args.device_type,
        prefix=args.prefix,
        vendor=args.vendor,
        model=args.model,
        collectors_enabled=args.collector,
    )
    log.info(
        "[%s/%s] %s (%s) created=%s prefix=%s",
        info["tenant"],
        info["site"],
        info["name"],
        info["type"],
        info["created"],
        info["prefix"],
    )


if __name__ == "__main__":
    main()