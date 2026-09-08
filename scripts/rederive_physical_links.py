"""Re-derive the consolidated physical-links read model from persisted evidence.

The `physical_links` table is the consolidated/read model for physical topology
discovery. Its `directly_observed`/`inferred`/`confidence` semantics changed:

- NEW rule (physical-topology-intelligence): a link is `directly_observed`
  ONLY when BOTH directions are observed (peer A observes B AND B observes A).
  A lone unilateral observation materializes as `inferred` (lower confidence).

Links materialized under the OLD rule carry a stale `directly_observed=True`
even when the reverse was never observed. This operator tool recomputes each
link's semantic flags from the persisted evidence (`topology_observations` for
direction, `link_evidence` for confidence/time range) so the consolidated model
matches the new rule.

It is IDEMPOTENT and NEVER deletes historical/raw evidence: it only updates the
consolidated `physical_links` flags. No secret or customer value lives in this
file; it reads current DB state at runtime.

Usage (Docker, write path is intentional):
    docker compose run --rm api python -m scripts.rederive_physical_links
    # or with a bind mount so the latest tree is used:
    docker compose run --rm -v "$PWD:/app" api python -m scripts.rederive_physical_links
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.entities import LinkEvidence, PhysicalLink, TopologyObservation

log = logging.getLogger("rederive_physical_links")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Same confidence cap the ingest path applies to unilateral links.
UNILATERAL_CONFIDENCE_CAP = 0.7


def _is_bilateral(db, tenant_id, a_id, b_id) -> bool:
    """True when persisted evidence shows BOTH directions for the (a,b) pair.

    Unlike the ingest-time helper (which can assume the forward observation
    exists because it is the row being materialized), re-derivation must verify
    the full pair from the evidence: peer A observing B AND peer B observing A.
    """
    fwd = db.scalar(
        select(TopologyObservation.id)
        .where(
            TopologyObservation.tenant_id == tenant_id,
            TopologyObservation.local_device_id == a_id,
            TopologyObservation.remote_device_id == b_id,
        )
        .limit(1)
    )
    rev = db.scalar(
        select(TopologyObservation.id)
        .where(
            TopologyObservation.tenant_id == tenant_id,
            TopologyObservation.local_device_id == b_id,
            TopologyObservation.remote_device_id == a_id,
        )
        .limit(1)
    )
    return fwd is not None and rev is not None


def rederive(db, *, dry_run: bool) -> int:
    links = list(db.scalars(select(PhysicalLink)))
    changed = 0
    for link in links:
        ev = db.scalars(
            select(LinkEvidence)
            .where(LinkEvidence.physical_link_id == link.id)
        ).all()
        max_conf = max((e.confidence or 1.0 for e in ev), default=1.0)
        observed_at = [e.observed_at for e in ev if e.observed_at]
        first_seen = min(observed_at) if observed_at else None
        last_seen = max(observed_at) if observed_at else None

        bilateral = _is_bilateral(db, link.tenant_id, link.device_a_id, link.device_b_id)
        directly_observed = bool(bilateral)
        inferred = not directly_observed
        confidence = max_conf if directly_observed else min(max_conf, UNILATERAL_CONFIDENCE_CAP)

        if (
            link.directly_observed != directly_observed
            or link.inferred != inferred
            or link.confidence != confidence
            or link.first_seen != first_seen
            or link.last_seen != last_seen
        ):
            changed += 1
            if not dry_run:
                link.directly_observed = directly_observed
                link.inferred = inferred
                link.confidence = confidence
                link.first_seen = first_seen
                link.last_seen = last_seen
    if not dry_run:
        db.commit()
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report how many links would change without writing.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        total, bilateral, unilateral = db.execute(
            select(
                func.count(PhysicalLink.id),
                func.count(PhysicalLink.id).filter(PhysicalLink.directly_observed),
                func.count(PhysicalLink.id).filter(PhysicalLink.inferred),
            )
        ).one()
        n_changed = rederive(db, dry_run=args.dry_run)
        total2, bilateral2, unilateral2 = db.execute(
            select(
                func.count(PhysicalLink.id),
                func.count(PhysicalLink.id).filter(PhysicalLink.directly_observed),
                func.count(PhysicalLink.id).filter(PhysicalLink.inferred),
            )
        ).one()
        verb = "would" if args.dry_run else "updated"
        log.info("before: total=%d bilateral=%d unilateral=%d", total, bilateral, unilateral)
        log.info("%s %d link(s)", "would update" if args.dry_run else "updated", n_changed)
        log.info("after:  total=%d bilateral=%d unilateral=%d", total2, bilateral2, unilateral2)
    finally:
        db.close()


if __name__ == "__main__":
    main()