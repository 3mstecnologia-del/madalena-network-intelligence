from __future__ import annotations

import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.correlation.topology import TopologyCorrelator
from app.models.entities import Device, InventoryNodeObservation, Tenant, TopologyObservation


def main() -> int:
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant))
        if tenant is None:
            print(json.dumps({"ok": False, "reason": "tenant missing"}))
            return 1
        topology = TopologyCorrelator(db).topology(tenant.slug, include_history=False, limit=200)
        candidates = [
            link
            for link in topology["links"]
            if link["source"] == "unifi_uplink"
            and link["local_device_id"] != link["remote_device_id"]
            and link["status"] == "unilateral"
        ]
        selected = []
        used_remote = set()
        for link in candidates:
            if link["remote_device_id"] in used_remote:
                continue
            local = db.get(Device, link["local_device_id"])
            remote = db.get(Device, link["remote_device_id"])
            if local is None or remote is None or not local.source_ref or not remote.source_ref:
                continue
            raw = db.scalar(
                select(InventoryNodeObservation)
                .where(
                    InventoryNodeObservation.tenant_id == tenant.id,
                    InventoryNodeObservation.source_id == local.source_ref,
                    InventoryNodeObservation.uplink_source_id == remote.source_ref,
                )
                .order_by(InventoryNodeObservation.last_seen.desc())
                .limit(1)
            )
            reverse = db.scalar(
                select(TopologyObservation.id)
                .where(
                    TopologyObservation.tenant_id == tenant.id,
                    TopologyObservation.local_device_id == remote.id,
                    TopologyObservation.remote_device_id == local.id,
                )
                .limit(1)
            )
            selected.append(
                {
                    "local_device_id": str(local.id),
                    "local_device": local.name,
                    "local_source_ref": local.source_ref,
                    "remote_device_id": str(remote.id),
                    "remote_device": remote.name,
                    "remote_source_ref": remote.source_ref,
                    "status": link["status"],
                    "source": link["source"],
                    "evidence": link["evidence"],
                    "first_seen": link["first_seen"],
                    "last_seen": link["last_seen"],
                    "raw_inventory_uplink_match": raw is not None,
                    "raw_inventory_last_seen": raw.last_seen.isoformat() if raw is not None else None,
                    "reverse_observation_present": reverse is not None,
                }
            )
            used_remote.add(link["remote_device_id"])
            if len(selected) == 3:
                break
        ok = len(selected) == 3 and all(
            row["status"] == "unilateral"
            and row["raw_inventory_uplink_match"]
            and not row["reverse_observation_present"]
            for row in selected
        )
        print(json.dumps({"ok": ok, "links": selected}, indent=2, sort_keys=True))
        return 0 if ok else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
