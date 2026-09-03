"""One-shot lab collection through the official collector path.

Runtime secrets come from LAB_SECRETS_FILE (mounted, never copied into the image).
Prints counts only — never hosts, users, MACs, IPs, or command output.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import CollectionRun, Device, DeviceCredentialReference, Site, Tenant
from app.services.ingest import IngestService
from collectors.common.envfile import apply_mapped_env, read_env_file_keys
from collectors.common.transport import sanitize_error, sanitized_exception_message
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.mikrotik.collector import MikroTikCollector
from scheduler.main import _finish_from_meta

OLT_PREFIX = "DEVICE_LAB_OLT"
MK_PREFIX = "DEVICE_LAB_MK200"

_KEY_MAP = {
    "olt_ip": f"{OLT_PREFIX}_HOST",
    "olt_username": f"{OLT_PREFIX}_USERNAME",
    "olt_password": f"{OLT_PREFIX}_PASSWORD",
    "olt_port": f"{OLT_PREFIX}_PORT",
    "olt_protocol": f"{OLT_PREFIX}_PROTOCOL",
    "mk200_ip": f"{MK_PREFIX}_HOST",
    "mk200_username": f"{MK_PREFIX}_USERNAME",
    "mk200_password": f"{MK_PREFIX}_PASSWORD",
    "mk200_port": f"{MK_PREFIX}_PORT",
    "mk200_protocol": f"{MK_PREFIX}_PROTOCOL",
}


def _load_runtime_secrets() -> None:
    raw = os.environ.get("LAB_SECRETS_FILE")
    if not raw:
        raise SystemExit("LAB_SECRETS_FILE is required")
    path = Path(raw)
    if not path.is_file():
        raise SystemExit("LAB_SECRETS_FILE is not a file")
    values = read_env_file_keys(path)
    applied = apply_mapped_env(values, _KEY_MAP)
    print(f"runtime keys applied: {len(applied)}")


def _ensure_inventory(db):
    settings = get_settings()
    tenant = db.scalar(select(Tenant).where(Tenant.slug == settings.seed_tenant_slug))
    if tenant is None:
        tenant = Tenant(slug=settings.seed_tenant_slug, name="Example Tenant")
        db.add(tenant)
        db.flush()
    site = db.scalar(select(Site).where(Site.tenant_id == tenant.id, Site.slug == settings.seed_site_slug))
    if site is None:
        site = Site(tenant_id=tenant.id, slug=settings.seed_site_slug, name="Example Site")
        db.add(site)
        db.flush()

    def ensure(name: str, dtype: str, vendor: str, model: str, prefix: str) -> Device:
        device = db.scalar(select(Device).where(Device.site_id == site.id, Device.name == name))
        if device is None:
            device = Device(
                tenant_id=tenant.id,
                site_id=site.id,
                name=name,
                device_type=dtype,
                vendor=vendor,
                model=model,
                management_host_ref=f"secret://{prefix}_HOST",
                enabled=True,
            )
            db.add(device)
            db.flush()
        ref = db.scalar(
            select(DeviceCredentialReference).where(DeviceCredentialReference.device_id == device.id)
        )
        if ref is None:
            db.add(
                DeviceCredentialReference(
                    tenant_id=tenant.id,
                    device_id=device.id,
                    secret_provider="env",
                    secret_prefix=prefix,
                    notes="External secret reference only",
                )
            )
        else:
            ref.secret_provider = "env"
            ref.secret_prefix = prefix
            db.add(ref)
        return device

    olt = ensure("LAB-G08", "intelbras_g08", "Intelbras", "G08", OLT_PREFIX)
    mk = ensure("LAB-MK200", "mikrotik", "MikroTik", "RouterOS", MK_PREFIX)
    db.commit()
    return tenant, olt, mk


def _run_device(db, tenant, device, collect_fn, collector_type: str, version: str | None) -> dict:
    ingest = IngestService(db)
    run = ingest.start_run(
        tenant_id=tenant.id,
        collector_type=collector_type,
        device_id=device.id,
        site_id=device.site_id,
        collector_version=version,
    )
    db.commit()
    try:
        result = collect_fn()
        diag = (result.meta or {}).get("ssh_diag")
        if diag:
            print(
                f"{device.name} ssh tcp={diag.get('tcp')} banner={diag.get('banner')} "
                f"handshake={diag.get('handshake')} auth={diag.get('authentication')} "
                f"command={diag.get('command')} port={diag.get('port_configured')}"
            )
        stats = None
        status = (result.meta or {}).get("status", "ok")
        if status not in {"skipped", "not_implemented"}:
            stats = ingest.ingest_result(
                tenant_id=tenant.id,
                device_id=device.id,
                result=result,
                run=run,
            )
        _finish_from_meta(ingest, run, result, stats)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        run = db.get(type(run), run.id)
        if run is not None:
            ingest.finish_run(
                run,
                status="error",
                completeness="none",
                error=sanitized_exception_message(exc),
                collector_version=version,
            )
            db.commit()
        print(f"{device.name}: FAIL status=error err={sanitized_exception_message(exc)}")
        return {"status": "error", "seen": 0}
    print(
        f"{device.name}: status={run.status} completeness={run.completeness} "
        f"seen={run.records_seen} created={run.records_created} updated={run.records_updated} "
        f"commands_ok={run.commands_ok} commands_failed={run.commands_failed} "
        f"parse_failures={(result.meta or {}).get('parse_failures', 0)}"
    )
    return {
        "status": run.status,
        "completeness": run.completeness,
        "seen": run.records_seen,
        "created": run.records_created,
    }


def _resanitize_stored_errors(db) -> None:
    dirty = 0
    for run in db.scalars(select(CollectionRun).where(CollectionRun.error_summary.is_not(None))):
        cleaned = sanitize_error(run.error_summary)
        if cleaned != run.error_summary:
            run.error_summary = cleaned
            db.add(run)
            dirty += 1
    if dirty:
        db.commit()
        print(f"resanitized_error_summaries={dirty}")


def main() -> None:
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    _load_runtime_secrets()
    db = SessionLocal()
    try:
        _resanitize_stored_errors(db)
        tenant, olt, mk = _ensure_inventory(db)
        from collectors.common.secrets import resolve_secrets

        mk_secrets = resolve_secrets("env", MK_PREFIX)
        olt_secrets = resolve_secrets("env", OLT_PREFIX)
        if olt_secrets:
            print(f"olt configured_protocol={olt_secrets.protocol} configured_port={olt_secrets.port}")
        if mk_secrets:
            print(f"mk configured_protocol={mk_secrets.protocol} configured_port={mk_secrets.port}")
        print(f"tenant={tenant.slug}")
        _run_device(
            db,
            tenant,
            olt,
            lambda: IntelbrasG08Collector("env", OLT_PREFIX).collect_live(),
            "intelbras_g08",
            IntelbrasG08Collector.collector_version,
        )
        _run_device(
            db,
            tenant,
            mk,
            lambda: MikroTikCollector("env", MK_PREFIX).collect_live(dhcp_only=True),
            "mikrotik_dhcp",
            MikroTikCollector.collector_version,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
