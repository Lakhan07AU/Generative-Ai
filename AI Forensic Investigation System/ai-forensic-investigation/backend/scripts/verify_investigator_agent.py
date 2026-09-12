"""Phase 7 demo end-to-end verifier: controlled investigation runs.

In-process FastAPI test client against the real PostgreSQL + Qdrant + MinIO
stack (no mocks): seeds the DEMO-PHASE6 evidence, logs in as the demo admin and
exercises the Phase 7 bounded investigator API - track / event / temporal runs,
UNKNOWN abstention (identity, intent, outside-view), hard budget bounds, camera
isolation, conflict reporting, RBAC (REVIEWER denied) and the human-review
lifecycle (READY_FOR_REVIEW -> APPROVE -> COMPLETED).

Run from ``backend/`` (after ``python -m alembic upgrade head``)::

    python -m scripts.seed_demo_evidence
    python -m scripts.verify_investigator_agent
"""

from __future__ import annotations

import time
from typing import Dict, List

from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.core.config import settings
from app.database.models import Camera, Investigation, User, Video
from app.database.session import SessionLocal
from app.main import app
from scripts.seed_demo_evidence import (
    DEMO_CAMERA,
    DEMO_EMAIL,
    DEMO_INVESTIGATION_TITLE,
    DEMO_PASSWORD,
    _insert_evidence,
    seed_demo_evidence,
)

_CHECKS: List[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    _CHECKS.append(name)
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"check failed: {name}: {detail}")


def _run_run(
    client: TestClient,
    token: str,
    investigation_id: int,
    query: str,
    require_review: bool = False,
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


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


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


def _ensure_isolation_case(db) -> int:
    cam = db.query(Camera).filter(Camera.camera_name == "DEMO-Phase7-NoEvidence").first()
    if cam is None:
        cam = Camera(
            camera_name="DEMO-Phase7-NoEvidence",
            location="Lobby - no demo evidence",
            description="Phase 7 isolation control case",
            camera_type="CCTV",
            is_live=False,
            stream_status="OFFLINE",
        )
        db.add(cam)
        db.flush()
    video = db.query(Video).filter(Video.filename == "phase7_demo_lobby_no_evidence.mp4").first()
    if video is None:
        video = Video(
            filename="phase7_demo_lobby_no_evidence.mp4",
            storage_path="demo/phase7_demo_lobby_no_evidence.mp4",
            camera_id=cam.id,
            status="READY",
        )
        db.add(video)
        db.flush()
    inv = (
        db.query(Investigation)
        .filter(Investigation.title == "CASE-DEMO-P7-ISOLATION Lobby (no evidence)")
        .first()
    )
    if inv is None:
        inv = Investigation(
            title="CASE-DEMO-P7-ISOLATION Lobby (no evidence)",
            query="Isolation negative control case.",
            video_id=video.id,
            status="OPEN",
        )
        db.add(inv)
        db.flush()
    inv_id = int(inv.id)
    db.commit()
    return inv_id


def _seed_conflict_evidence(db, camera_id: int, session_id: int) -> None:
    """Seed two mutually-exclusive records for the same track (entered vs exited)."""
    _insert_evidence(
        db,
        evidence_type="TRACK_EVENT",
        camera_id=camera_id,
        session_id=session_id,
        event_id="EV-DEMO-CONF-1",
        event_type="object_entered",
        tracking_id="T-DEMO-CONF",
        frame_sequence=120,
        frame_timestamp=36120.0,
        window_start=None,
        window_end=None,
        vlm_observation_id=None,
        content_text="car entered parking tracking_id=T-DEMO-CONF label=car",
        metadata={"state": "entered", "label": "car", "_demo": True, "tag": "DEMO"},
        tag="car",
    )
    _insert_evidence(
        db,
        evidence_type="TRACK_EVENT",
        camera_id=camera_id,
        session_id=session_id,
        event_id="EV-DEMO-CONF-2",
        event_type="object_exited",
        tracking_id="T-DEMO-CONF",
        frame_sequence=121,
        frame_timestamp=36122.0,
        window_start=None,
        window_end=None,
        vlm_observation_id=None,
        content_text="car left parking tracking_id=T-DEMO-CONF label=car",
        metadata={"state": "exited", "label": "car", "_demo": True, "tag": "DEMO"},
        tag="car",
    )
    db.commit()


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
        isolation_case = _ensure_isolation_case(db)
        cam_id = int(demo["camera_id"])
        cam_name = demo["camera_name"]
        _seed_conflict_evidence(db, cam_id, int(demo["session_id"]))
    finally:
        db.close()

    client = TestClient(app)
    token = _login(client, DEMO_EMAIL, DEMO_PASSWORD)
    investigation_id = int(demo["case_id"])

    # ---------------- 1. track-dedicated run ----------------
    q1 = "Find all evidence for track T-P6-CAR-2."
    r1 = _run_run(client, token, investigation_id, q1)
    _check("Q1 run COMPLETED", r1["status"] == "COMPLETED", r1.get("error") or r1["status"])
    _check("Q1 classification is TRACK", r1["classification"]["category"] == "TRACK",
           r1["classification"]["category_reason"])
    _check("Q1 answered from verified evidence", r1["result"]["status"] == "ANSWERED",
           r1["result"]["status"])
    _check(
        "Q1 evidence all from case camera",
        bool(r1["result"]["evidence_used"])
        and all(e.get("camera_id") == cam_id for e in r1["result"]["evidence_used"]),
        f"cam={ {e.get('camera_id') for e in r1['result']['evidence_used']} }",
    )
    _check(
        "Q1 evidence all belong to T-P6-CAR-2",
        all(e.get("tracking_id") == "T-P6-CAR-2" for e in r1["result"]["evidence_used"]),
        str({e.get("tracking_id") for e in r1["result"]["evidence_used"]}),
    )
    _check("Q1 workspace claims persisted",
           bool(r1["claims"]) and any(
               c.get("verification", {}).get("result") == "VERIFIED" for c in r1["claims"]),
           f"claims={len(r1['claims'])} statuses="
           f"{[c.get('verification', {}).get('result') for c in r1['claims']]}")

    # ---------------- 2. event + temporal run ----------------
    q2 = "Show all events where a person entered the parking area between 10:00 and 10:15."
    r2 = _run_run(client, token, investigation_id, q2)
    _check("Q2 run COMPLETED", r2["status"] == "COMPLETED", r2.get("error") or r2["status"])
    _check("Q2 answered", r2["result"]["status"] == "ANSWERED", r2["result"]["status"])
    _check(
        "Q2 has person-entered evidence in window",
        bool(r2["result"]["evidence_used"])
        and any(
            (e.get("object_class") or "").lower() == "person"
            and e.get("event_type") == "object_entered"
            and float(e.get("timestamp") or -1) >= 36000.0
            for e in r2["result"]["evidence_used"]
        ),
        str([(e.get("object_class"), e.get("event_type"), e.get("timestamp"))
             for e in r2["result"]["evidence_used"]][:4]),
    )

    # ---------------- 3. counting run ----------------
    q3 = "How many vehicles entered the parking lot between 10:00 and 10:15?"
    r3 = _run_run(client, token, investigation_id, q3)
    _check("Q3 run COMPLETED", r3["status"] == "COMPLETED", r3.get("error") or r3["status"])
    _check("Q3 answered", r3["result"]["status"] == "ANSWERED", r3["result"]["status"])
    _check(
        "Q3 summary grounded in observed evidence",
        "OBSERVED" in r3["result"]["summary"],
        r3["result"]["summary"][:100],
    )
    _check(
        "Q3 shows entered-car events",
        bool(r3["result"]["evidence_used"])
        and any(
            (e.get("object_class") or "").lower() == "car"
            and e.get("event_type") == "object_entered"
            for e in r3["result"]["evidence_used"]
        ),
        str([(e.get("object_class"), e.get("event_type")) for e in r3["result"]["evidence_used"]][:4]),
    )

    # ---------------- 4. hard budget bounds ----------------
    for label, run in (("Q1", r1), ("Q2", r2), ("Q3", r3)):
        _check(
            f"{label} within step bound",
            int(run["metrics"]["steps_used"]) <= int(settings.AGENT_MAX_RUN_STEPS),
            f"steps={run['metrics']['steps_used']}",
        )
        _check(
            f"{label} within tool-call bound",
            int(run["metrics"]["tool_calls"]) <= int(settings.AGENT_MAX_RUN_TOOL_CALLS),
            f"calls={run['metrics']['tool_calls']}",
        )
        _check(
            f"{label} evidence retrieved bounded",
            int(run["metrics"]["evidence_used"]) <= int(settings.AGENT_MAX_RUN_EVIDENCE),
            f"evidence={run['metrics']['evidence_used']}",
        )

    # ---------------- 5. negative abstention checks ----------------
    n1 = "Who is the person seen entering the parking area at 10:01?"
    rn1 = _run_run(client, token, investigation_id, n1)
    _check("N1 identity question UNKNOWN", rn1["result"]["status"] == "UNKNOWN",
           rn1["result"]["status"])
    _check("N1 no fabricated identity", "UNKNOWN" in rn1["result"]["summary"],
           rn1["result"]["summary"][:80])

    n2 = "Why did the person enter the parking area?"
    rn2 = _run_run(client, token, investigation_id, n2)
    _check("N2 intent question classified UNANSWERABLE",
           rn2["classification"]["category"] == "UNANSWERABLE",
           rn2["classification"]["category_reason"])
    _check("N2 intent not inferred", rn2["result"]["status"] == "UNKNOWN",
           rn2["result"]["status"])

    n3 = "Did anything happen outside the camera view during the incident?"
    rn3 = _run_run(client, token, investigation_id, n3)
    _check("N3 outside-view question UNKNOWN", rn3["result"]["status"] == "UNKNOWN",
           rn3["result"]["status"])

    # ---------------- 6. isolation (case camera has no evidence) ----------------
    iso = _run_run(client, token, isolation_case, "Was there a person present between 10:00 and 10:15?")
    _check("Isolation: no-evidence case answers UNKNOWN", iso["result"]["status"] == "UNKNOWN",
           iso["result"]["status"])
    _check("Isolation: run still completes", iso["status"] == "COMPLETED", iso["status"])

    # ---------------- 7. conflict evidence reported, never resolved ----------------
    rc = _run_run(client, token, investigation_id, "Find all evidence for track T-DEMO-CONF")
    _check("Conflict run COMPLETED", rc["status"] == "COMPLETED", rc.get("error") or rc["status"])
    _check(
        "Conflict surfaced (not resolved)",
        bool(rc["result"]["conflicts"])
        and any(c["kind"] == "event_type" for c in rc["result"]["conflicts"]),
        str(rc["result"]["conflicts"]),
    )
    _check(
        "Conflict run still synthesizes findings",
        bool(rc["result"]["findings"]),
        f"findings={len(rc['result']['findings'])}",
    )

    # ---------------- 8. RBAC: REVIEWER denied as operator ----------------
    reviewer_token = _login(client, "reviewer.demo@forensics-demo.com", "ReviewerDemo123!")
    res = client.post(
        f"/investigations/{investigation_id}/investigate",
        json={"query": "any person?", "require_review": True},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("RBAC: REVIEWER cannot start a run (403)", res.status_code == 403,
           f"status={res.status_code}")

    # ---------------- 9. human-review lifecycle ----------------
    rh = _run_run(client, token, investigation_id, q1, require_review=True)
    _check("Review run paused for human review", rh["status"] == "READY_FOR_REVIEW", rh["status"])
    _check("Review run marked reviewable", rh["metrics"]["require_review"] is True,
           str(rh["metrics"]["require_review"]))

    res_ok = client.post(
        f"/runs/{rh['id']}/review",
        json={"decision": "APPROVE", "note": "demo reviewer approves"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("Reviewer APPROVE -> COMPLETED", res_ok.status_code == 200
           and res_ok.json()["status"] == "COMPLETED", f"status={res_ok.status_code}")

    res_done = client.post(
        f"/runs/{rh['id']}/review",
        json={"decision": "REJECT"},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("Re-review of completed run is rejected (409)", res_done.status_code == 409,
           f"status={res_done.status_code}")

    # ---------------- 10. run listing ----------------
    listed = client.get(
        f"/investigations/{investigation_id}/runs",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    _check("Run history lists the runs",
           any(r["id"] == rh["id"] for r in listed["runs"]),
           f"runs={len(listed['runs'])}")

    # ---------------- latency summary ----------------
    print("\n  latencies (ms):")
    for label, r in (("Q1", r1), ("Q2", r2), ("Q3", r3), ("N1", rn1), ("N2", rn2),
                     ("N3", rn3), ("CONF", rc), ("REVIEW", rh)):
        print(f"    {label}: {r['_elapsed_ms']}")
    print(f"\n   camera scope used: {cam_name} (id {cam_id})")
    print(f"   max steps allowed: {settings.AGENT_MAX_RUN_STEPS}, "
          f"max tool calls: {settings.AGENT_MAX_RUN_TOOL_CALLS}")

    return True


def main() -> None:
    try:
        run_checklist()
    except AssertionError as exc:
        print(f"\nDEMO VERIFICATION FAILED: {exc}")
        raise SystemExit(1)
    print(f"\nDEMO VERIFICATION PASSED ({len(_CHECKS)} checks)")


if __name__ == "__main__":
    main()