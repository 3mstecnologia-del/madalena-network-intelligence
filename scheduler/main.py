"""Containerized collector scheduler (APScheduler). No host cron.

One device failure never deletes prior observations. Partial collection is
recorded as completeness=partial. Errors are sanitized before persistence.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import CollectionRun, Device, DeviceCredentialReference
from app.services.ingest import IngestService
from collectors.common.transport import sanitize_error, sanitized_exception_message
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.mikrotik.collector import MikroTikCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _device_lock(device_id: str) -> threading.Lock:
    with _locks_guard:
        if device_id not in _locks:
            _locks[device_id] = threading.Lock()
        return _locks[device_id]


def _cred_prefix(db, device: Device) -> tuple[str, str]:
    ref = db.scalar(
        select(DeviceCredentialReference).where(DeviceCredentialReference.device_id == device.id)
    )
    settings = get_settings()
    if ref is None:
        return settings.secret_provider, ""
    return ref.secret_provider, ref.secret_prefix


def _finish_from_meta(ingest: IngestService, run, result, stats: Optional[dict]) -> None:
    meta = result.meta or {}
    status = str(meta.get("status") or "ok")
    completeness = str(meta.get("completeness") or "unknown")
    if status in {"ok", "success"} and completeness == "complete":
        persist_status = "success"
    elif status in {"skipped", "not_implemented"}:
        persist_status = status
        completeness = completeness if completeness != "unknown" else "none"
    elif completeness == "partial" or status == "partial":
        persist_status = "partial"
        completeness = "partial"
    elif status == "error" or completeness == "none":
        persist_status = "error"
    else:
        persist_status = status
    raw_err = meta.get("error_summary") or meta.get("reason") or meta.get("todo")
    ingest.finish_run(
        run,
        status=persist_status,
        seen=(stats or {}).get("seen", 0),
        created=(stats or {}).get("created", 0),
        updated=(stats or {}).get("updated", 0),
        error=sanitize_error(str(raw_err)) if raw_err else None,
        completeness=completeness,
        commands_ok=int(meta.get("commands_ok") or 0),
        commands_failed=int(meta.get("commands_failed") or 0),
        collector_version=meta.get("collector_version"),
    )


def run_mikrotik_lightweight() -> None:
    _run_by_type("mikrotik", lightweight=True)


def run_olt() -> None:
    _run_by_type("intelbras_g08", lightweight=True)


def run_full_inventory() -> None:
    _run_by_type("mikrotik", lightweight=False)
    _run_by_type("intelbras_g08", lightweight=False)


def _run_by_type(device_type: str, lightweight: bool) -> None:
    db = SessionLocal()
    try:
        devices = list(
            db.scalars(
                select(Device).where(Device.device_type == device_type, Device.enabled.is_(True))
            )
        )
        if not devices:
            log.info("no enabled devices for type=%s", device_type)
            return
        ingest = IngestService(db)
        for device in devices:
            lock = _device_lock(str(device.id))
            if not lock.acquire(blocking=False):
                log.warning("skip concurrent run device=%s", device.name)
                continue
            try:
                provider, prefix = _cred_prefix(db, device)
                collector_label = device_type + ("_light" if lightweight else "_full")
                version = None
                if device_type == "mikrotik":
                    version = MikroTikCollector.collector_version
                run = ingest.start_run(
                    tenant_id=device.tenant_id,
                    collector_type=collector_label,
                    device_id=device.id,
                    site_id=device.site_id,
                    collector_version=version,
                )
                db.commit()
                try:
                    if device_type == "mikrotik":
                        collector = MikroTikCollector(provider, prefix)
                        result = collector.collect_live(lightweight=lightweight)
                    else:
                        collector = IntelbrasG08Collector(provider, prefix)
                        result = collector.collect_live()
                    status = result.meta.get("status", "ok")
                    stats = None
                    if status not in {"skipped", "not_implemented", "error"} or (
                        result.dhcp or result.arp or result.fdb or result.interfaces or result.neighbors
                    ):
                        if status not in {"skipped", "not_implemented"}:
                            stats = ingest.ingest_result(
                                tenant_id=device.tenant_id,
                                device_id=device.id,
                                result=result,
                                run=run,
                            )
                    _finish_from_meta(ingest, run, result, stats)
                    db.commit()
                    log.info(
                        "collection device=%s type=%s status=%s completeness=%s",
                        device.name,
                        device_type,
                        run.status,
                        run.completeness,
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    run = db.get(CollectionRun, run.id)
                    if run is not None:
                        ingest.finish_run(
                            run,
                            status="error",
                            completeness="none",
                            error=sanitized_exception_message(exc),
                            collector_version=version,
                        )
                        db.commit()
                    log.error(
                        "collection failed device=%s err=%s — prior observations kept",
                        device.name,
                        sanitized_exception_message(exc),
                    )
            finally:
                lock.release()
    finally:
        db.close()


def main() -> None:
    settings = get_settings()
    if not settings.scheduler_enabled:
        log.info("SCHEDULER_ENABLED=false — idling")
        while True:
            time.sleep(3600)
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(
        run_mikrotik_lightweight,
        "interval",
        seconds=settings.scheduler_mikrotik_interval_sec,
        id="mikrotik_light",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        run_olt,
        "interval",
        seconds=settings.scheduler_olt_interval_sec,
        id="olt",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        run_full_inventory,
        "interval",
        seconds=settings.scheduler_full_inventory_interval_sec,
        id="full_inventory",
        max_instances=1,
        coalesce=True,
    )
    log.info(
        "scheduler started mikrotik=%ss olt=%ss full=%ss",
        settings.scheduler_mikrotik_interval_sec,
        settings.scheduler_olt_interval_sec,
        settings.scheduler_full_inventory_interval_sec,
    )
    run_mikrotik_lightweight()
    sched.start()


if __name__ == "__main__":
    main()
