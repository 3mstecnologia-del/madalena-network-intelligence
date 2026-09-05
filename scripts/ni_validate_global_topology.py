from __future__ import annotations

import json
import os
import httpx
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.entities import Tenant


def main() -> int:
    db = SessionLocal()
    try:
        tenants = list(db.scalars(select(Tenant.slug).order_by(Tenant.slug)))
    finally:
        db.close()
    if len(tenants) != 1:
        print(json.dumps({"ok": False, "reason": "expected exactly one tenant", "tenant_count": len(tenants)}))
        return 1
    tenant = tenants[0]
    with httpx.Client(timeout=30.0) as client:
        api = client.get(
            "http://127.0.0.1:8000/topology",
            params={"tenant": tenant, "include_history": "false", "limit": 200},
        )
        mcp = client.post(
            "http://mcp:8081/tools/get_topology",
            json={"tenant": tenant, "include_history": False, "limit": 200},
        )
    api_json = api.json()
    mcp_json = mcp.json()
    mcp_data = mcp_json.get("data") if isinstance(mcp_json, dict) else None
    serialized = json.dumps({"api": api_json, "mcp": mcp_json}, sort_keys=True)
    checked = []
    hits = []
    for key, value in os.environ.items():
        if key.endswith(("_PASSWORD", "_API_KEY", "_TOKEN", "_SECRET")):
            checked.append(key)
            if len(value) >= 4 and value in serialized:
                hits.append(key)
    ok = api.status_code == 200 and mcp.status_code == 200 and mcp_json.get("ok") is True and api_json == mcp_data and not hits
    print(
        json.dumps(
            {
                "ok": ok,
                "api_status": api.status_code,
                "mcp_status": mcp.status_code,
                "api_mcp_equal": api_json == mcp_data,
                "secret_env_keys_checked": sorted(checked),
                "secret_hits": hits,
                "api": api_json,
                "mcp": mcp_json,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
