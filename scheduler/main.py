"""Containerized collector scheduler (APScheduler). No host cron.

One device failure never stops the fleet and never deletes prior observations.
Partial collection is recorded as completeness=partial. Errors are sanitized.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.collectors_config import enabled_collectors
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import CollectionRun, Device, DeviceCredentialReference
from app.services.ingest import IngestService
from collectors.common.transport import sanitize_error, sanitized_exception_message
from collectors.intelbras_g08.collector import IntelbrasG08Collector
from collectors.mikrotik.collector import MikroTikCollector
from collectors.unifi.collector import UnifiNetworkCollector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scheduler")

HEARTBEAT_PATH = Path("/tmp/ni-scheduler-heartbeat")
HEARTBEAT_MAX_AGE_SEC = 120
BEAT_INTERVAL_SEC = 30

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_scheduler: Optional[BlockingScheduler] = None


def write_heartbeat() -> None:
    HEARTBEAT_PATH.write_text(str(time.time()), encoding="utf-8")


def _heartbeat_loop() -> None:
    while True:
        write_heartbeat()
        time.sleep(BEAT_INTERVAL_SEC)


def _start_heartbeat_thread() -> threading.Thread:
    """Keep the healthcheck meaningful between collection ticks.

    A <120s-stale heartbeat must reflect a live scheduler process, not whether a
    collection happened to run recently (ticks are every 900-21600s). Returns the
    daemon thread so the caller holds a reference.
    """
    thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    thread.start()
    return thread


def heartbeat_fresh(max_age_sec: int = HEARTBEAT_MAX_AGE_SEC) -> bool:
    try:
        age = time.time() - float(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return age <= max_age_sec


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


def _too_soon(db, device: Device) -> bool:
    interval = device.collection_interval_sec
    if not interval or interval <= 0:
        return False
    last = db.scalar(
        select(CollectionRun.finished_at)
        .where(CollectionRun.device_id == device.id, CollectionRun.finished_at.is_not(None))
        .order_by(CollectionRun.finished_at.desc())
        .limit(1)
    )
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last < timedelta(seconds=interval)


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
        excluded=(stats or {}).get("excluded", 0) or int(meta.get("records_excluded") or 0),
        parse_failures=int(meta.get("parse_failures") or 0),
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


def run_unifi() -> None:
    _run_by_type("unifi_network", lightweight=False)


def run_full_inventory() -> None:
    _run_by_type("mikrotik", lightweight=False)
    _run_by_type("intelbras_g08", lightweight=False)
    _run_by_type("unifi_network", lightweight=False)


def _run_by_type(device_type: str, lightweight: bool) -> None:
    write_heartbeat()
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
                _collect_one(db, ingest, device, device_type, lightweight)
            finally:
                lock.release()
    finally:
        db.close()
        write_heartbeat()


def _collect_one(db, ingest: IngestService, device: Device, device_type: str, lightweight: bool) -> None:
    if _too_soon(db, device):
        log.info("skip interval device=%s", device.name)
        return
    collectors = enabled_collectors(device)
    provider, prefix = _cred_prefix(db, device)
    collector_label = device_type + ("_light" if lightweight else "_full")
    version = None
    if device_type == "mikrotik":
        version = MikroTikCollector.collector_version
    elif device_type == "unifi_network":
        version = UnifiNetworkCollector.collector_version
    run = ingest.start_run(
        tenant_id=device.tenant_id,
        collector_type=collector_label,
        device_id=device.id,
        site_id=device.site_id,
        collector_version=version,
    )
    db.commit()
    try:
        if not collectors:
            from collectors.common.types import CollectorResult

            result = CollectorResult(
                meta={
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "no_enabled_collectors",
                }
            )
            _finish_from_meta(ingest, run, result, None)
            db.commit()
            return
        if device_type == "mikrotik":
            collector = MikroTikCollector(provider, prefix)
            result = collector.collect_live(lightweight=lightweight, enabled_collectors=collectors)
        elif device_type == "intelbras_g08":
            collector = IntelbrasG08Collector(provider, prefix)
            result = collector.collect_live(enabled_collectors=collectors)
        elif device_type == "unifi_network":
            collector = UnifiNetworkCollector(provider, prefix)
            result = collector.collect_live(enabled_collectors=collectors)
        else:
            from collectors.common.types import CollectorResult

            result = CollectorResult(
                meta={
                    "status": "skipped",
                    "completeness": "none",
                    "reason": "unknown_device_type",
                    "collector_version": version,
                }
            )
            _finish_from_meta(ingest, run, result, None)
            db.commit()
            return
        status = result.meta.get("status", "ok")
        stats = None
        has_rows = (
            result.dhcp
            or result.arp
            or result.fdb
            or result.interfaces
            or result.neighbors
            or result.topology_links
            or result.inventory_nodes
        )
        if status not in {"skipped", "not_implemented", "error"} or has_rows:
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


def full_cron_times(cron_spec: Optional[str]) -> list[tuple[int, int]]:
    """Parse a 'HH:MM,HH:MM,...' spec into sorted (hour, minute) pairs.

    Invalid tokens are skipped (a malformed schedule entry must never crash the
    scheduler, and a missing entry degrades to fewer FULL runs rather than a
    blocked process). Returns the requested times in input order.
    """
    out: list[tuple[int, int]] = []
    for token in (cron_spec or "").split(","):
        token = token.strip()
        if not token:
            continue
        hour_raw, _, minute_raw = token.partition(":")
        try:
            hour = int(hour_raw)
            minute = int(minute_raw or "0")
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append((hour, minute))
    return out


def _shutdown(signum, _frame) -> None:
    log.info("scheduler stopping signal=%s", signum)
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)


def main() -> None:
    global _scheduler
    write_heartbeat()
    settings = get_settings()
    once = "--once" in sys.argv
    if not settings.scheduler_enabled and not once:
        log.info("SCHEDULER_ENABLED=false — idling")
        _start_heartbeat_thread()
        while True:
            write_heartbeat()
            time.sleep(30)
    if once:
        # Manual run: everything, full. No automatic light runs exist anymore.
        run_full_inventory()
        return
    _start_heartbeat_thread()
    _scheduler = BlockingScheduler(timezone=settings.scheduler_timezone)
    times = full_cron_times(settings.scheduler_full_cron)
    if not times:
        log.error("SCHEDULER_FULL_CRON empty/invalid=%r — no automatic runs", settings.scheduler_full_cron)
        # Idle-but-alive: keep the heartbeat/healthcheck meaningful and safe.
        while True:
            write_heartbeat()
            time.sleep(30)
    for idx, (hour, minute) in enumerate(times):
        _scheduler.add_job(
            run_full_inventory,
            CronTrigger(hour=hour, minute=minute, timezone=settings.scheduler_timezone),
            id=f"full_run_{idx:02d}_{hour:02d}{minute:02d}",
            max_instances=1,
            coalesce=True,
        )
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    log.info(
        "scheduler started colletion cron=%s tz=%s full_runs=%d",
        settings.scheduler_full_cron,
        settings.scheduler_timezone,
        len(times),
    )
    _scheduler.start()


if __name__ == "__main__":
    main()
