"""Phase 9 - Evidence integrity verifier.

Reconciles the forensic evidence ledger (``forensic_evidence``) against the
storage layer and the vector index, then reports orphaned references inside the
Phase 8 analysis artifacts.

Per ``ForensicEvidence`` row it checks:

  * storage object exists at ``storage_path`` (when set);
  * bytes integrity: SHA-256 of the stored object equals the recorded ``sha256``
    (large objects > 8 MB are skipped to stay fast - reported, not failed);
  * vector index: ``INDEXED`` rows have a live Qdrant point; rows in any other
    state are counted with their device.

Orphaned references checked:

  * ``ForensicTimelineEvent.evidence_ids`` -> missing ``ForensicEvidence``
  * Forensic analysis/finding JSON ``evidence_id``/``public_id`` refs -> missing
  * ``ClaimEvidence.clip_id`` -> missing ``Clip``

Run from ``backend/``::

    python scripts/verify_evidence_integrity.py
    python scripts/verify_evidence_integrity.py --resubmit-failed

Exit codes: 0 = clean, 1 = discrepancies found, 2 = fatal error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

MAX_VERIFY_BYTES = 8 * 1024 * 1024
_JSON_FIELDS = (
    "timeline",
    "findings",
    "correlations",
    "contradictions",
    "relationships",
    "multi_camera",
    "gaps",
)


class _Status:
    CLEAN = "CLEAN"
    DESC = {
        "checks": 0,
        "storage_missing": 0,
        "structure": [],
        "hash_mismatch": 0,
        "hash_skipped": 0,
        "index_close": {},
        "index_corrupt": 0,
        "orphans": [],
    }


def _loads(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else ([parsed] if parsed else [])


def _check_storage(db, rows, flags: dict) -> list:
    from app.storage.service import storage

    flags.setdefault("checks", 0)
    problems = []
    skipped = 0
    mismatched = []
    present = 0
    for row in rows:
        flags["checks"] += 1
        if not row.storage_path:
            continue
        try:
            ok = storage.exists(row.storage_path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{row.public_id}: storage.exists failed ({exc})")
            continue
        if not ok:
            problems.append(f"{row.public_id}: object missing at {row.storage_path}")
            continue
        present += 1
        if not row.sha256:
            continue
        if (row.size_bytes or 0) > MAX_VERIFY_BYTES:
            skipped += 1
            continue
        try:
            data = storage.get_bytes(row.storage_path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{row.public_id}: unreadable object ({exc})")
            continue
        actual = hashlib.sha256(data).hexdigest()
        if actual != row.sha256:
            mismatched.append(f"{row.public_id}: sha256 mismatch (recorded {row.sha256[:12]}…, actual {actual[:12]}…)")
    return problems, present, skipped, mismatched


def _check_index(db, rows, real_qdrant: bool) -> dict:
    from app.ai.qdrant_service import qdrant
    from app.core.config import settings

    counts = {}
    corrupt = []
    for row in rows:
        st = row.index_status or "PENDING"
        counts[st] = counts.get(st, 0) + 1
        if st == "INDEXED":
            if not qdrant.point_exists(settings.QDRANT_COLLECTION_EVIDENCE, row.public_id):
                corrupt.append(f"{row.public_id}: marked INDEXED but no Qdrant point")
    return counts, corrupt


def _check_orphans(db) -> list:
    from app.database.models import ClaimEvidence, Clip, ForensicEvidence, ForensicTimelineEvent

    orphans = []
    existing = {r[0] for r in db.query(ForensicEvidence.public_id).all() if r[0]}

    rows = db.query(ForensicTimelineEvent).all()
    for t in rows:
        for eid in _loads(t.evidence_ids):
            if eid and eid not in existing:
                orphans.append(
                    f"timeline event {t.timeline_event_id}: evidence {eid!r} does not exist"
                )

    from app.database.models import ForensicAnalysis

    analyses = db.query(ForensicAnalysis).all()
    for a in analyses:
        payloads = [_loads(getattr(a, field)) for field in _JSON_FIELDS]
        local_claims = set()
        for payload in payloads:
            for item in payload:
                if isinstance(item, dict):
                    for key in ("evidence_id", "public_id", "evidence"):
                        val = item.get(key)
                        if isinstance(val, str) and val.startswith("EVD-"):
                            local_claims.add(val)
                        elif isinstance(val, list):
                            for v in val:
                                if isinstance(v, str) and v.startswith("EVD-"):
                                    local_claims.add(v)
                elif isinstance(item, str) and item.startswith("EVD-"):
                    local_claims.add(item)
        for eid in sorted(local_claims - existing):
            orphans.append(f"analysis #{a.id}: {eid!r} does not exist")

    clip_ids = {c[0] for c in db.query(Clip.id).all()}
    link_rows = db.query(ClaimEvidence).filter(ClaimEvidence.clip_id.isnot(None)).all()
    for link in link_rows:
        if link.clip_id not in clip_ids:
            orphans.append(f"claim evidence link {link.id}: clip {link.clip_id} does not exist")
    return orphans


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify forensic evidence integrity")
    parser.add_argument("--resubmit-failed", action="store_true",
                        help="re-enqueue PENDING/FAILED evidence rows for indexing")
    parser.add_argument("--limit", type=int, default=0, help="cap rows checked (debug)")
    args = parser.parse_args()

    from app.database.models import ForensicEvidence
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        q = db.query(ForensicEvidence)
        if args.limit:
            q = q.limit(args.limit)
        rows = q.all()

        from app.ai.qdrant_service import qdrant

        vector_backend = qdrant.backend_name()

        storage_problems, present, skipped, hash_mismatch = _check_storage(db, rows, {})
        counts, index_corrupt = _check_index(db, rows, vector_backend == "qdrant")
        orphans = _check_orphans(db)

        if args.resubmit_failed:
            from app.evidence.indexer import evidence_indexer

            queued = 0
            for row in rows:
                if row.index_status in ("PENDING", "FAILED"):
                    if evidence_indexer.submit(row.id, row.public_id):
                        queued += 1
            print(f"[integrity] resubmitted {queued} PENDING/FAILED rows to the indexer")

        print("=" * 72)
        print("EVIDENCE INTEGRITY REPORT")
        print("=" * 72)
        print(f"evidence rows        : {len(rows)}")
        print(f"vector backend       : {vector_backend}")
        print(f"storage objects ok   : {present}")
        print(f"hash verified (skip) : {skipped} (> {MAX_VERIFY_BYTES // (1024 * 1024)} MB skipped)")
        problems = list(storage_problems) + list(hash_mismatch) + list(index_corrupt)
        print(f"index state          : {counts or {'none': len(rows)}}")
        print(f"problems             : {len(problems) + len(orphans)}")
        for label, items in (
            ("storage / structure", storage_problems),
            ("hash mismatch", hash_mismatch),
            ("index corrupt", index_corrupt),
            ("orphaned refs", orphans),
        ):
            for it in items:
                print(f"  [{label}] {it}")

        if not problems and not orphans:
            print("\nRESULT: CLEAN")
            return
        print("\nRESULT: DISCREPANCIES FOUND")
        raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()