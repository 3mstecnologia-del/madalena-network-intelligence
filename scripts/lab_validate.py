"""Validate lab collection via API + MCP. Prints placeholder MAC_TEST_n only."""

from __future__ import annotations

import os
import sys

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models.entities import CollectionRun, Device, DhcpLease, OltMacObservation


def _tenant() -> str:
    return get_settings().seed_tenant_slug


def _anonymize(macs: list[str]) -> dict[str, str]:
    return {mac: f"MAC_TEST_{i}" for i, mac in enumerate(macs, start=1)}


def main() -> int:
    api = os.environ.get("API_BASE_URL", "http://api:8000").rstrip("/")
    mcp = os.environ.get("MCP_BASE_URL", "http://mcp:8081").rstrip("/")
    tenant = _tenant()
    db = SessionLocal()
    try:
        olt_macs = list(
            db.scalars(
                select(OltMacObservation.mac)
                .join(Device, Device.id == OltMacObservation.device_id)
                .where(Device.name == "LAB-G08")
                .distinct()
            )
        )
        dhcp_macs = list(
            db.scalars(
                select(DhcpLease.mac)
                .join(Device, Device.id == DhcpLease.device_id)
                .where(Device.name == "LAB-MK200")
                .distinct()
            )
        )
        overlap = sorted(set(olt_macs) & set(dhcp_macs))
        sample_pool = overlap or sorted(set(olt_macs) or set(dhcp_macs))
        aliases = _anonymize(sample_pool[:5])
        print(f"olt_macs={len(set(olt_macs))} dhcp_macs={len(set(dhcp_macs))} overlap={len(overlap)}")
        if overlap:
            print("cross_source=YES")
        else:
            print("cross_source=NO_CORRELATED_SAMPLE")
        names = ("LAB-G08", "LAB-MK200")
        tenant_ids = select(Device.tenant_id).where(Device.name.in_(names))
        runs = list(
            db.scalars(
                select(CollectionRun)
                .where(CollectionRun.tenant_id.in_(tenant_ids))
                .order_by(CollectionRun.started_at.desc())
            )
        )
        for run in runs[:8]:
            print(
                f"run collector={run.collector_type} status={run.status} "
                f"completeness={run.completeness} seen={run.records_seen}"
            )
    finally:
        db.close()

    if not aliases:
        print("API: SKIP no samples")
        print("MCP: SKIP no samples")
        return 0

    ok = True
    with httpx.Client(timeout=15.0) as client:
        first_mac, first_alias = next(iter(aliases.items()))
        api_mac = client.get(f"{api}/macs/{first_mac}", params={"tenant": tenant})
        api_hist = client.get(f"{api}/macs/{first_mac}/history", params={"tenant": tenant})
        print(f"API find {first_alias}: {api_mac.status_code}")
        print(f"API history {first_alias}: {api_hist.status_code}")
        if api_mac.status_code != 200 or api_hist.status_code != 200:
            ok = False
        if api_mac.status_code == 200:
            body = api_mac.json()
            olt = body.get("olt_macs") or []
            pon = (body.get("access_path") or {}).get("pon") or (olt[0].get("pon") if olt else None)
            print(
                f"SAMPLE {first_alias}: found=yes "
                f"ip={bool(body.get('current_ips'))} "
                f"onu={bool(olt)} "
                f"pon={bool(pon)} "
                f"sources={body.get('sources')} "
                f"conflicts={len(body.get('conflicts') or [])} "
                f"first_seen={bool(body.get('first_seen'))} "
                f"last_seen={bool(body.get('last_seen'))}"
            )
        if api_hist.status_code == 200:
            hist = api_hist.json()
            print(f"SAMPLE {first_alias} timeline_events={len(hist.get('timeline') or [])}")

        mcp_find = client.post(f"{mcp}/tools/find_mac", json={"tenant": tenant, "mac": first_mac})
        mcp_hist = client.post(f"{mcp}/tools/get_mac_history", json={"tenant": tenant, "mac": first_mac})
        mcp_stat = client.post(f"{mcp}/tools/get_collection_status", json={"tenant": tenant, "limit": 10})
        mcp_ok = mcp_find.json().get("ok") if mcp_find.status_code == 200 else False
        print(f"MCP find_mac {first_alias}: {mcp_find.status_code} ok={mcp_ok}")
        print(f"MCP get_mac_history {first_alias}: {mcp_hist.status_code}")
        print(f"MCP get_collection_status: {mcp_stat.status_code}")
        if mcp_find.status_code != 200 or mcp_hist.status_code != 200 or mcp_stat.status_code != 200:
            ok = False
        if mcp_find.status_code == 200 and api_mac.status_code == 200:
            data = mcp_find.json().get("data") or {}
            print(
                f"MCP SAMPLE {first_alias}: "
                f"dhcp={bool(data.get('dhcp'))} olt={bool(data.get('olt_macs'))} "
                f"provenance={data.get('sources')}"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
