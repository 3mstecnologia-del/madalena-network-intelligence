"""Scheduler isolates device failures and honors enabled collectors."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import CollectionRun, DeviceCredentialReference, DhcpLease
from app.services.ingest import IngestService
from collectors.common.types import CollectorResult, NormalizedDhcpLease
from collectors.mikrotik.collector import MikroTikCollector
from scheduler.main import _collect_one, full_cron_times
from tests.conftest import seed_two_tenants

MAC = "AA:BB:CC:DD:EE:FF"


def test_full_cron_times_parses_only_valid_hhmm():
    assert full_cron_times("07:00,12:00,18:00,23:59") == [
        (7, 0),
        (12, 0),
        (18, 0),
        (23, 59),
    ]
    # Invalid/out-of-range tokens are skipped, never crash the scheduler.
    assert full_cron_times("25:00,abc,9:5,,07:60") == [(9, 5)]
    assert full_cron_times("") == []
    assert full_cron_times(None) == []


def test_scheduler_continues_after_one_device_fails(db: Session, monkeypatch):
    t1, _, d1, d1b, _, _ = seed_two_tenants(db)
    db.add(
        DeviceCredentialReference(
            tenant_id=t1.id, device_id=d1.id, secret_provider="env", secret_prefix="fail-prefix"
        )
    )
    db.add(
        DeviceCredentialReference(
            tenant_id=t1.id, device_id=d1b.id, secret_provider="env", secret_prefix="ok-prefix"
        )
    )
    db.commit()

    def fake_live(self, *, lightweight=True, dhcp_only=False, enabled_collectors=None):
        if self.secret_prefix == "fail-prefix":
            raise RuntimeError("password=super-secret host=192.0.2.8")
        return CollectorResult(
            dhcp=[NormalizedDhcpLease(mac=MAC, ip_address="10.30.1.50")],
            meta={"status": "ok", "completeness": "complete"},
        )

    monkeypatch.setattr(MikroTikCollector, "collect_live", fake_live)
    ingest = IngestService(db)
    _collect_one(db, ingest, d1, "mikrotik", True)
    _collect_one(db, ingest, d1b, "mikrotik", True)
    db.commit()
    failed = db.scalar(
        select(CollectionRun).where(CollectionRun.device_id == d1.id).order_by(CollectionRun.started_at.desc())
    )
    ok = db.scalar(
        select(CollectionRun).where(CollectionRun.device_id == d1b.id).order_by(CollectionRun.started_at.desc())
    )
    assert failed.status == "error"
    assert failed.error_summary is not None
    assert "super-secret" not in failed.error_summary
    assert ok.status in {"success", "ok", "partial"}
    assert db.scalar(select(DhcpLease).where(DhcpLease.tenant_id == t1.id, DhcpLease.mac == MAC)) is not None
