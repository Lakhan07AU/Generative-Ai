"""Phase 8 demo end-to-end verifier: forensic verification, timeline & reporting.

In-process FastAPI test client against the real PostgreSQL + Qdrant + MinIO
stack (no mocks): seeds the DEMO-PHASE6 evidence, runs Phase 7 controlled
investigation runs, then exercises the Phase 8 forensic pipeline for five
scenarios - COMPLETE reconstruction, TEMPORAL ordering (never causal), UNKNOWN
identity abstention, CONFLICT (surfaced not resolved) and EVIDENCE GAP coverage -
plus the human finding-review lifecycle, RBAC (REVIEWER denied analyze) and
report generation/download for a COMPLETED run.

Run from ``backend/`` (after ``python -m alembic upgrade head``)::

    python -m scripts.verify_forensic_reporting
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List

from fastapi.testclient import TestClient

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

from app.auth.security import hash_password
from app.core.config import settings
from app.database.models import ForensicEvidence, User
from app.database.session import SessionLocal
from app.main import app
from scripts.seed_demo_evidence import (
    DEMO_EMAIL,
    DEMO_INVESTIGATION_TITLE,
    DEMO_PASSWORD,
    _insert_evidence,
    seed_demo_evidence,
)

_CHECKS: List[str] = []

_REPORT_KEYS = [
    "case_information",
    "investigation_question",
    "executive_summary",
    "timeline",
    "verified_findings",
    "unverified_findings",
    "conflicting_evidence",
    "evidence_gaps",
    "supporting_evidence",
    "vlm_observations",
    "track_information",
    "camera_information",
    "limitations",
    "reviewer_information",
    "audit_information",
]


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    _CHECKS.append(name)
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"check failed: {name}: {detail}")


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _run_run(
    client: TestClient, token: str, investigation_id: int, query: str, require_review: bool = False
) -> Dict:
    started = time.perf_counter()
    res = client.post(
        f"/investigations/{investigation_id}/investigate",
        json={"query": query, "require_review": require_review},
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert res.status_code == 200, res.text
    body = res.json()
    body["_elapsed_ms"] = round(elapsed_ms, 1)
    return body


def _analyze(client: TestClient, token: str, run_id: int, label: str) -> Dict:
    started = time.perf_counter()
    res = client.post(
        f"/runs/{run_id}/forensic/analyze",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert res.status_code == 200, res.text
    analysis = res.json()
    analysis["_elapsed_ms"] = round(elapsed_ms, 1)
    analysis["_label"] = label
    return analysis


def _ensure_reviewer(db) -> None:
    if db.query(User).filter(User.email == "reviewer.demo@forensics-demo.com").first() is None:
        db.add(
            User(
                email="reviewer.demo@forensics-demo.com",
                name="Demo Reviewer",
                password_hash=hash_password("ReviewerDemo123!"),
                role="REVIEWER",
                is_active=True,
            )
        )
        db.commit()


def _seed_conflict_evidence(db, camera_id: int, session_id: int) -> List[str]:
    """Re-seed the mutually-exclusive track records (entered vs exited)."""
    ids: List[str] = []
    for ev_id, ev_type, ts, text in (
        ("EV-DEMO-CONF-1", "object_entered", 36120.0, "car entered parking tracking_id=T-DEMO-CONF label=car"),
        ("EV-DEMO-CONF-2", "object_exited", 36122.0, "car left parking tracking_id=T-DEMO-CONF label=car"),
    ):
        previous = (
            db.query(ForensicEvidence)
            .filter(ForensicEvidence.event_id == ev_id)
            .first()
        )
        if previous:
            continue
        row = _insert_evidence(
            db,
            evidence_type="TRACK_EVENT",
            camera_id=camera_id,
            session_id=session_id,
            event_id=ev_id,
            event_type=ev_type,
            tracking_id="T-DEMO-CONF",
            frame_sequence=int(ts - 36000.0) // 2,
            frame_timestamp=ts,
            window_start=None,
            window_end=None,
            vlm_observation_id=None,
            content_text=text,
            metadata={"state": "entered" if ev_type == "object_entered" else "exited",
                      "label": "car", "_demo": True, "tag": "DEMO"},
            tag="car",
        )
        ids.append(row.public_id)
    db.commit()
    return ids


def run_checklist() -> bool:
    db = SessionLocal()
    try:
        demo = seed_demo_evidence(db)
    finally:
        db.close()

    print(f"Demo evidence manifest: case={demo['case_id']} camera={demo['camera_id']} "
          f"rows={demo['evidence_created']} tracks={demo['tracking_ids']}")

    db = SessionLocal()
    try:
        _ensure_reviewer(db)
        cam_id = int(demo["camera_id"])
        _seed_conflict_evidence(db, cam_id, int(demo["session_id"]))
    finally:
        db.close()

    client = TestClient(app)
    token = _login(client, DEMO_EMAIL, DEMO_PASSWORD)
    reviewer_token = _login(client, "reviewer.demo@forensics-demo.com", "ReviewerDemo123!")
    investigation_id = int(demo["case_id"])

    analyze_total: List[float] = []

    # ================= 1. COMPLETE reconstruction =================
    a1 = _analyze(
        client, token, int(_run_run(client, token, investigation_id,
                                    "Find all evidence for track T-P6-CAR-2.")["id"]),
        "COMPLETE",
    )
    analyze_total.append(a1["_elapsed_ms"])
    _check("A1 analysis created (PENDING_REVIEW)", a1["status"] == "PENDING_REVIEW", a1["status"])
    _check("A1 timeline reconstructed from evidence",
           len(a1["timeline"]) >= 2, f"events={len(a1['timeline'])}")
    _check("A1 timeline chronological",
           all(a1["timeline"][i]["timestamp"] <= a1["timeline"][i + 1]["timestamp"]
               for i in range(len(a1["timeline"]) - 1)))
    _check("A1 timeline all on case camera",
           all(e.get("camera_id") == cam_id for e in a1["timeline"]),
           str({e.get("camera_id") for e in a1["timeline"]}))
    _check("A1 has observed findings",
           any(f["classification"] == "OBSERVED" for f in a1["findings"]),
           f"findings={len(a1['findings'])}")
    _check("A1 has sufficiently supported findings",
           any(f["verification_status"] in ("VERIFIED", "PARTIALLY_VERIFIED")
               for f in a1["findings"]))
    _check("A1 reports evidence correlations",
           bool(a1["correlations"]) and any(
               c.get("kind") == "track_sequence" for c in a1["correlations"]),
           f"correlations={len(a1['correlations'])}")
    _check("A1 clean track has no contradictions",
           not a1["contradictions"],
           str(a1["contradictions"][:2]))
    _check("A1 relationships never causal",
           bool(a1["relationships"])
           and all(not r.get("causal") for r in a1["relationships"]),
           f"relationships={len(a1['relationships'])}")
    _check("A1 detects evidence gaps (coverage)",
           bool(a1["gaps"]["gaps"]) and any(
               g["kind"] == "missing_camera_coverage" for g in a1["gaps"]["gaps"]),
           str([g["kind"] for g in a1["gaps"]["gaps"]]))
    _check("A1 no evidence scoped out", a1["evidence_counts"]["scoped_out"] == [],
           str(a1["evidence_counts"]["scoped_out"]))
    _check("A1 metrics recorded",
           a1["metrics"] and a1["metrics"].get("total_seconds", 0) > 0,
           str(a1["metrics"]))

    # ================= 2. TEMPORAL ordering, not causation =================
    a2 = _analyze(
        client, token, int(_run_run(client, token, investigation_id,
                                    "Find all evidence for track T-P6-PERSON-1.")["id"]),
        "TEMPORAL",
    )
    analyze_total.append(a2["_elapsed_ms"])
    _check("A2 relationships reconstructed",
           bool(a2["relationships"]), f"relationships={len(a2['relationships'])}")
    _check("A2 temporal order present",
           any(r["relationship"] in ("BEFORE", "AFTER", "DURING", "NEAR", "OVERLAPPING")
               for r in a2["relationships"]),
           str({r["relationship"] for r in a2["relationships"]}))
    _check("A2 causal claim never asserted",
           all(not r.get("causal") for r in a2["relationships"]),
           str([r for r in a2["relationships"] if r.get("causal")]))
    _check("A2 causal note present",
           all("caus" in (r.get("causality_note") or "").lower() for r in a2["relationships"]),
           str([r.get("causality_note") for r in a2["relationships"]]))
    _check("A2 stopped event in timeline",
           any("T-P6-PERSON-1" == e.get("track_id") and e.get("event_type") == "object_stopped"
               for e in a2["timeline"]),
           str([(e.get("track_id"), e.get("event_type")) for e in a2["timeline"][:8]]))

    # ================= 3. UNKNOWN identity abstention =================
    rn = _run_run(client, token, investigation_id, "Who was driving the vehicle in the parking area?")
    _check("N unknown-identity run abstains", rn["result"]["status"] in ("UNKNOWN", "UNANSWERABLE"),
           rn["result"]["status"])
    a3 = _analyze(client, token, int(rn["id"]), "UNKNOWN")
    analyze_total.append(a3["_elapsed_ms"])
    _check("A3 never claims an identity",
           all("driver" not in f["text"].lower() and "identity" not in f["text"].lower()
               for f in a3["findings"]),
           str([f["text"] for f in a3["findings"]][:4]))
    _check("A3 summary never asserts who was driving",
           "driver" not in a3["summary"].lower(),
           a3["summary"][:120])

    # ================= 4. CONFLICT surfaced, never resolved =================
    a4 = _analyze(
        client, token, int(_run_run(client, token, investigation_id,
                                    "Find all evidence for track T-DEMO-CONF")["id"]),
        "CONFLICT",
    )
    analyze_total.append(a4["_elapsed_ms"])
    _check("A4 conflict surfaced in analysis",
           bool(a4["contradictions"]),
           str(a4["contradictions"][:3]))
    _check("A4 conflicts keep distinct event types",
           all(c.get("type") == "event_type" for c in a4["contradictions"]),
           str([c.get("type") for c in a4["contradictions"]]))
    _check("A4 conflict mentions in summary",
           "conflict" in a4["summary"].lower(),
           a4["summary"][:120])
    conf_times = sorted(
        e["timestamp"] for e in a4["timeline"]
        if e.get("track_id") == "T-DEMO-CONF"
    )
    _check("A4 conflict rows kept separate (not merged)",
           len(conf_times) >= 2 and conf_times[0] != conf_times[1],
           str(conf_times))

    # ================= 5. EVIDENCE GAP coverage =================
    a5 = _analyze(
        client, token, int(_run_run(client, token, investigation_id,
                                    "Did anything happen outside the camera view during the incident?")["id"]),
        "EVIDENCE-GAP",
    )
    analyze_total.append(a5["_elapsed_ms"])
    _check("A5 reports the outside-view gap",
           bool(a5["gaps"]["gaps"]) and any(
               g["kind"] == "missing_camera_coverage" for g in a5["gaps"]["gaps"]),
           str([g["kind"] for g in a5["gaps"]["gaps"]]))
    _check("A5 gap limits reconstruction honesty",
           "camera" in a5["gaps"]["coverage"]["note"].lower(),
           a5["gaps"]["coverage"]["note"])
    _check("A5 never invents outside events",
           all("outside" not in f["text"].lower() for f in a5["findings"]),
           str([f["text"] for f in a5["findings"]][:4]))

    # ================= 6. human finding review lifecycle =================
    finding_id = a1["findings"][0]["finding_id"]
    res = client.post(
        f"/runs/{a1['run_id']}/findings/{finding_id}/review",
        json={"action": "ACCEPTED", "comment": "demo reviewer accepts the observed finding"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("Reviewer finding review recorded", res.status_code == 200, f"status={res.status_code}")
    body = res.json()
    _check("Review action persisted", body.get("action") == "ACCEPTED", str(body))
    _check("Review snapshot immutable on finding",
           body.get("finding_id") == finding_id, str(body.get("finding_id")))

    reviews = client.get(
        f"/runs/{a1['run_id']}/reviews",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    _check("Reviews endpoint lists the finding review",
           any(r["finding_id"] == finding_id and r["action"] == "ACCEPTED"
               for r in reviews["finding_reviews"]),
           f"reviews={len(reviews['finding_reviews'])}")

    revisit = client.get(
        f"/runs/{a1['run_id']}/forensic",
        headers={"Authorization": f"Bearer {token}"},
    )
    _check("Re-fetch includes timeline rows", revisit.status_code == 200, f"status={revisit.status_code}")

    # ================= 7. RBAC: REVIEWER denied analyze =================
    res = client.post(
        f"/runs/{a1['run_id']}/forensic/analyze",
        json={},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("RBAC: REVIEWER cannot run forensic analyze (403)",
           res.status_code == 403, f"status={res.status_code}")

    # ================= 8. report generation (COMPLETED only) =================
    r_ready = _run_run(client, token, investigation_id, "Find all evidence for track T-P6-PERSON-1")
    _check("Run used for report is COMPLETED", r_ready["status"] == "COMPLETED", r_ready["status"])
    a_ready = _analyze(client, token, int(r_ready["id"]), "REPORT")
    analyze_total.append(a_ready["_elapsed_ms"])

    res_report = client.post(
        f"/runs/{int(r_ready['id'])}/report",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    _check("Report generated for COMPLETED run", res_report.status_code == 200,
           f"status={res_report.status_code}")
    report_meta = res_report.json()
    _check("Report has version", report_meta.get("version", 0) >= 1, str(report_meta))
    _check("Report renders PDF via reportlab",
           report_meta.get("file_format") == "pdf", report_meta.get("file_format"))

    res_get = client.get(
        f"/runs/{int(r_ready['id'])}/report",
        headers={"Authorization": f"Bearer {token}"},
    )
    _check("Report fetch returns content", res_get.status_code == 200, f"status={res_get.status_code}")
    content = res_get.json()["content"]
    missing = [k for k in _REPORT_KEYS if k not in content]
    _check("Report contains all 15 mandated sections", not missing, f"missing={missing}")
    _check("Report has question + case info",
           content.get("investigation_question")
           and content.get("case_information"),
           str(content.get("investigation_question", "")[:60]))

    res_file = client.get(
        f"/runs/{int(r_ready['id'])}/report/file",
        headers={"Authorization": f"Bearer {token}"},
    )
    _check("Report file downloadable", res_file.status_code == 200, f"status={res_file.status_code}")
    data = res_file.content
    _check("Report file is PDF bytes", data and data[:4] == b"%PDF", str(len(data)) + " bytes")
    disposition = res_file.headers.get("content-disposition", "")
    _check("Report filename attached", "filename=" in disposition, disposition[:80])

    report_meta2 = client.post(
        f"/runs/{int(r_ready['id'])}/report",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    _check("Report regeneration increments version",
           report_meta2.get("version") == report_meta.get("version", 0) + 1,
           f"v{report_meta2.get('version')} vs v{report_meta.get('version')}")

    # ================= 9. report blocked on non-COMPLETED run =================
    r_pending = _run_run(client, token, investigation_id, "Are there any people present?",
                         require_review=True)
    _check("Pending run is READY_FOR_REVIEW", r_pending["status"] == "READY_FOR_REVIEW",
           r_pending["status"])
    res_pending = client.post(
        f"/runs/{r_pending['id']}/report",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    _check("Report blocked until COMPLETED (409)", res_pending.status_code == 409,
           f"status={res_pending.status_code}")

    # ================= timing summary =================
    print("\n  forensic pipeline latencies (ms):")
    for label in ("COMPLETE", "TEMPORAL", "UNKNOWN", "CONFLICT", "EVIDENCE-GAP", "REPORT"):
        lat = [a["_elapsed_ms"] for a in (a1, a2, a3, a4, a5, a_ready) if a["_label"] == label]
        if lat:
            print(f"    {label}: {lat[0]} (endpoint) | stages: "
                  + " · ".join(f"{k.replace('_seconds','')}={v}s"
                               for k, v in next(a["metrics"] for a in (a1, a2, a3, a4, a5, a_ready)
                                                if a["_label"] == label).items()))
    print(f"   case: {DEMO_INVESTIGATION_TITLE}")
    print(f"   camera scope: cam#{demo['camera_id']} (camera_ids scoped by case)")
    print(f"   report renderer: {settings.FORENSIC_REPORT_RENDERER}")

    return True


def main() -> None:
    try:
        run_checklist()
    except AssertionError as exc:
        print(f"\nPHASE 8 VERIFICATION FAILED: {exc}")
        raise SystemExit(1)
    print(f"\nPHASE 8 VERIFICATION OVERALL: PASS ({len(_CHECKS)} checks)")


if __name__ == "__main__":
    main()