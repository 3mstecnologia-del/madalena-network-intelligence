from __future__ import annotations

import json
import os

import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import Device, Tenant


def main() -> int:
    db = SessionLocal()
    try:
        rows = list(
            db.execute(
                select(Device, Tenant.slug)
                .join(Tenant, Tenant.id == Device.tenant_id)
                .where(Device.enabled.is_(True), Device.device_type.in_(("mikrotik", "unifi_network")))
                .order_by(Device.device_type, Device.created_at)
            )
        )
    finally:
        db.close()

    report = {"devices": []}
    ok = True
    with httpx.Client(timeout=30.0) as client:
        for device, tenant in rows:
            api = client.get(
                f"http://127.0.0.1:8000/devices/{device.id}/links",
                params={"tenant": tenant, "include_history": "false", "limit": 200},
            )
            mcp = client.post(
                "http://mcp:8081/tools/get_device_links",
                json={"tenant": tenant, "device_id": str(device.id), "include_history": False, "limit": 200},
            )
            api_json = api.json() if api.headers.get("content-type", "").startswith("application/json") else None
            mcp_json = mcp.json() if mcp.headers.get("content-type", "").startswith("application/json") else None
            mcp_data = (mcp_json or {}).get("data") if isinstance(mcp_json, dict) else None
            equal = api_json == mcp_data
            serialized = json.dumps({"api": api_json, "mcp": mcp_json}, sort_keys=True)
            secret_hits = []
            prefixes = []
            for key in os.environ:
                if key.endswith(("_PASSWORD", "_API_KEY", "_TOKEN", "_SECRET")):
                    prefixes.append(key)
                    value = os.environ.get(key) or ""
                    if len(value) >= 4 and value in serialized:
                        secret_hits.append(key)
            item_ok = (
                api.status_code == 200
                and mcp.status_code == 200
                and bool((mcp_json or {}).get("ok"))
                and equal
                and not secret_hits
            )
            ok = ok and item_ok
            report["devices"].append(
                {
                    "device_id": str(device.id),
                    "device_name": device.name,
                    "device_type": device.device_type,
                    "tenant": tenant,
                    "api_status": api.status_code,
                    "mcp_status": mcp.status_code,
                    "mcp_ok": bool((mcp_json or {}).get("ok")),
                    "api_mcp_equal": equal,
                    "secret_env_keys_checked": sorted(prefixes),
                    "secret_hits": secret_hits,
                    "api": api_json,
                    "mcp": mcp_json,
                }
            )
    report["ok"] = ok
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
