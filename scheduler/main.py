"""Containerized collector scheduler (APScheduler). No host cron."""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import Device, DeviceCredentialReference
from app.services.ingest import IngestService
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


def run_mikrotik_lightweight() -> None:
    """Phase 1: record skipped/not_implemented runs — no live equipment."""
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
                run = ingest.start_run(
                    tenant_id=device.tenant_id,
                    collector_type=device_type + ("_light" if lightweight else "_full"),
                    device_id=device.id,
                )
                try:
                    if device_type == "mikrotik":
                        collector = MikroTikCollector(provider, prefix)
                        result = collector.collect_live()
                    else:
                        collector = IntelbrasG08Collector(provider, prefix)
                        result = collector.collect_live()
                    status = result.meta.get("status", "ok")
                    if status in {"skipped", "not_implemented"}:
                        ingest.finish_run(
                            run,
                            status=status,
                            error=str(result.meta.get("reason") or result.meta.get("todo")),
                        )
                    else:
                        stats = ingest.ingest_result(
                            tenant_id=device.tenant_id,
                            device_id=device.id,
                            result=result,
                            run=run,
                        )
                        ingest.finish_run(
                            run,
                            status="success",
                            seen=stats["seen"],
                            created=stats["created"],
                            updated=stats["updated"],
                        )
                    db.commit()
                    log.info(
                        "collection device=%s type=%s status=%s",
                        device.name,
                        device_type,
                        run.status,
                    )
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    # Re-open a short error run record after rollback
                    err_run = ingest.start_run(
                        tenant_id=device.tenant_id,
                        collector_type=device_type,
                        device_id=device.id,
                    )
                    ingest.finish_run(err_run, status="error", error=str(exc)[:1000])
                    db.commit()
                    log.exception("collection failed device=%s", device.name)
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
    # Initial tick (safe — live collectors skip without secrets)
    run_mikrotik_lightweight()
    sched.start()


if __name__ == "__main__":
    main()
