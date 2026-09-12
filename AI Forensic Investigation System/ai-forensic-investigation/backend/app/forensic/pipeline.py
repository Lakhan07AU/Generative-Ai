"""Phase 8 forensic pipeline orchestrator.

Runs the deterministic forensic stages over a completed Phase 7 run's evidence
and persists a ForensicAnalysis. Inputs are the evidence rows the run actually
used (via ``result.evidence_used``): never fabricated, never extrapolated.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import models
from app.forensic import correlation, gaps as gap_module, multicamera, sequencing, store, timeline as timeline_module, verification
from app.forensic.timestamps import iso_utc
from app.investigator.store import loads_json


def _evidence_ids_of(run: models.InvestigationRun) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    result = loads_json(run.result, {})
    evidence_used = result.get("evidence_used") or []
    if not isinstance(evidence_used, list):
        evidence_used = []
    conflicts = result.get("conflicts") or []
    return evidence_used, conflicts


def _conflicting_id_set(conflicts: List[Dict[str, Any]]) -> set:
    ids: set = set()
    for pair in conflicts or []:
        a = pair.get("evidence_a")
        b = pair.get("evidence_b")
        if a:
            ids.add(str(a))
        if b:
            ids.add(str(b))
    return ids


def _evidence_id_of(item: Dict[str, Any]) -> Optional[str]:
    value = item.get("evidence_id") or item.get("public_id")
    return str(value) if value else None


def _rows_for_run(db: Session, run: models.InvestigationRun, evidence_used: List[Dict[str, Any]], camera_ids: List[int]) -> tuple[List[Any], Dict[str, int]]:
    public_ids = [_evidence_id_of(item) for item in evidence_used]
    public_ids = [pid for pid in public_ids if pid]
    if not public_ids:
        return [], {}
    rows = (
        db.query(models.ForensicEvidence)
        .filter(models.ForensicEvidence.public_id.in_(public_ids))
        .all()
    )
    scoped: List[Any] = []
    skipped: Dict[str, int] = {}
    for row in rows:
        if camera_ids and row.camera_id is not None and row.camera_id not in camera_ids:
            skipped[row.public_id] = row.camera_id
            continue
        scoped.append(row)
    return scoped, skipped


def _camera_names(db: Session, camera_ids: List[int]) -> Dict[int, str]:
    names: Dict[int, str] = {}
    if not camera_ids:
        return names
    cameras = db.query(models.Camera).filter(models.Camera.id.in_(camera_ids)).all()
    for cam in cameras:
        names[cam.id] = cam.camera_name
    return names


def _contradiction_detail(conflicts: List[Dict[str, Any]], entries) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    entry_by_evidence: Dict[str, List[str]] = {}
    for entry in entries:
        for eid in entry.get("evidence_ids") or []:
            entry_by_evidence.setdefault(eid, []).append(entry.get("timeline_event_id"))
    for pair in conflicts or []:
        a = pair.get("evidence_a")
        b = pair.get("evidence_b")
        entry_ids = set(entry_by_evidence.get(a, [])) | set(entry_by_evidence.get(b, []))
        out.append(
            {
                "evidence_a": a,
                "evidence_b": b,
                "type": pair.get("type") or pair.get("kind"),
                "reason": pair.get("reason"),
                "timeline_entries": sorted(entry_ids),
            }
        )
    return out


def analyze_run(
    db: Session,
    run: models.InvestigationRun,
    investigation: models.Investigation,
    user_id: Optional[int],
    camera_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    if run.result is None:
        raise ValueError("Run has no result to analyze")

    evidence_used, conflicts = _evidence_ids_of(run)
    camera_ids = list(camera_ids or [])
    camera_names = _camera_names(db, camera_ids)

    metrics: Dict[str, float] = {}

    t0 = time.perf_counter()
    rows, skipped = _rows_for_run(db, run, evidence_used, camera_ids)
    rows_by_public = {getattr(r, "public_id", None): r for r in rows}
    conflicting_set = _conflicting_id_set(conflicts)
    metrics["load_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    correlations = correlation.correlate_evidence(rows, camera_names)
    sources = correlation.source_authorities(rows, camera_names)
    metrics["correlation_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    analytics_time = datetime.utcnow()
    entries = timeline_module.build_forensic_timeline(
        rows,
        camera_names,
        conflicting_ids=conflicting_set,
        max_entries=int(settings.FORENSIC_MAX_TIMELINE_ENTRIES),
        epsilon=float(settings.FORENSIC_OVERLAP_EPSILON_SECONDS),
        analytics_time=analytics_time,
    )
    metrics["timeline_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    findings = verification.verify_findings(entries, rows_by_public)
    metrics["verification_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    contradictions = _contradiction_detail(conflicts, entries)
    metrics["contradiction_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    covered_names = [camera_names.get(cid) or f"camera {cid}" for cid in camera_ids]
    covered_names = [c for c in covered_names if c]
    gaps_result = gap_module.detect_evidence_gaps(
        rows,
        query=run.query,
        covered_camera_names=covered_names or ["(unknown)"],
        gap_threshold_seconds=float(settings.FORENSIC_GAP_THRESHOLD_SECONDS),
        low_resolution_px=int(settings.FORENSIC_LOW_RESOLUTION_PX),
    )
    metrics["gaps_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    relationships = sequencing.sequence_entries(
        entries,
        epsilon=float(settings.FORENSIC_OVERLAP_EPSILON_SECONDS),
        near_seconds=float(settings.FORENSIC_NEAR_SECONDS),
    )
    metrics["sequencing_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    multi_camera = multicamera.correlate_across_cameras(entries)
    metrics["multicamera_seconds"] = round(time.perf_counter() - t0, 4)

    observed = [f for f in findings if f.get("classification") == "OBSERVED"]
    verified = [f for f in findings if f.get("verification_status") in ("VERIFIED", "PARTIALLY_VERIFIED")]
    summary = (
        f"Forensic analysis of run {run.id} for investigation '{investigation.title}'. "
        f"Reconstructed {len(entries)} timeline events from {len(rows)} supporting evidence records "
        f"({len(verified)} sufficiently supported findings, {len(observed)} directly observed, "
        f"{len(conflicting_set)} conflicting evidence records, {len(gaps_result.get('gaps', []))} evidence gaps detected)."
    )
    if not rows:
        summary += " No evidence was used by this run; the available evidence is insufficient to determine what occurred."

    metrics["total_seconds"] = round(sum(metrics.values()), 4)

    analysis: Dict[str, Any] = {
        "run_id": run.id,
        "investigation_id": investigation.id,
        "investigation_title": investigation.title,
        "status": "PENDING_REVIEW",
        "generated_at": iso_utc(analytics_time),
        "summary": summary,
        "timeline": entries,
        "findings": findings,
        "correlations": correlations,
        "contradictions": contradictions,
        "gaps": gaps_result,
        "relationships": relationships,
        "multi_camera": multi_camera,
        "sources": sources,
        "metrics": metrics,
        "evidence_counts": {"used": len(rows), "scoped_out": list(skipped.keys())},
    }

    store.persist_analysis(db, run, analysis, user_id)
    store.persist_timeline_rows(db, run.id, investigation.id, entries, analytics_time)
    return analysis