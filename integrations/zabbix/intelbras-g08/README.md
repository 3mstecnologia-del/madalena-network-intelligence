# Zabbix template — Intelbras G08 (Madalena)

Reusable **Zabbix 7** SNMP template for monitoring **Intelbras OLT G08** in the Madalena/Hermes ecosystem.

## Purpose

Provide a production-oriented Zabbix template that:

- monitors OLT hardware (CPU, memory, chipset temperatures);
- discovers ONUs on GPON PON ports and tracks status / optics-related metrics via item prototypes;
- discovers network interfaces and tracks bandwidth / operational status;
- keeps ONU discovery **inside the OLT host** (item/trigger/graph prototypes; per-ONU host prototypes intentionally removed).

This is a **monitoring integration artifact**, not a collector of Madalena Network Intelligence. Collectors in this repository ingest inventory/correlation data; Zabbix remains the polling/alerting plane.

## Compatibility

| Item | Expectation |
|------|-------------|
| Zabbix | **7.0** export format (`zabbix_export.version: '7.0'`) |
| Device | Intelbras **G08** (enterprise OID under `1.3.6.1.4.1.13464…`) |
| Protocol | **SNMP agent** items (`type: SNMP_AGENT`) |

Validate against your firmware/SNMP agent revision in lab before production rollout.

## SNMP requirements

Defined by the template items themselves:

- Host in Zabbix must have a working **SNMP interface** (v2c or v3 as configured on the Zabbix host — **not** stored in this YAML).
- Community / USM credentials are configured on the **Zabbix host/macros**, never in this repository.
- Template macros included (thresholds only): `{$CPU_BUSY}`, `{$HIGH_TEMP}`, `{$OUT_MEMORY}`.

No SNMP community string, username, password, or management IP is present in the exported YAML.

## Import

1. Zabbix UI → **Data collection** → **Templates** → **Import**.
2. Select `Template_Madalena_Intelbras_G08_Zabbix_7.yaml`.
3. Review rules (create new / update existing) and import.
4. Link the template to the OLT host; configure SNMP interface + credentials on the host.
5. Wait for discovery rules (ONU / interfaces) and confirm items populate.

Template group in export: `Templates/Intelbras`.  
Template name: `Template Madalena Intelbras G08 SNMP`.

## Versioning

- File name includes `Zabbix_7` to signal export generation.
- Treat changes as SemVer-style documentation in git history:
  - **patch**: descriptions, docs, non-functional metadata;
  - **minor**: new items/triggers that remain backward compatible;
  - **major**: breaking OID/key renames or Zabbix major version bumps.
- Prefer exporting from a validated lab Zabbix and replacing this file intentionally — do not hand-edit OIDs without lab proof.

## Lab improvements

Improvements validated in laboratory (additional OIDs, tighter triggers, dashboards) may be published in future commits after:

1. lab validation;
2. secret scan;
3. maintainer review.

Do not commit customer-specific hosts, communities, or real running configs alongside this template.
