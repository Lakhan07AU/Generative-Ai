"""Phase 6 demo end-to-end verifier: grounded search over DEMO-PHASE6 evidence.

In-process FastAPI test client against the real PostgreSQL + Qdrant stack (no
mocks): seeds the demo evidence, logs in as the demo admin, and runs the five
reconstructed demo queries plus three negative UNKNOWN checks, an isolation
check (a case whose camera has no evidence must answer UNKNOWN) and an RBAC
check (REVIEWER must be denied). Prints PASS/FAIL per step and exits non-zero on
any failure.

Run from ``backend/``::

    python -m scripts.seed_demo_evidence
    python -m scripts.verify_video_rag_demo
"""

from __future__ import annotations

import time
from typing import Dict, List

from fastapi.testclient import TestClient

from app.auth.security import hash_password
from app.database.models import Camera, Investigation, User, Video
from app.database.session import SessionLocal
from app.main import app
from scripts.seed_demo_evidence import (
    DEMO_CAMERA,
    DEMO_EMAIL,
    DEMO_INVESTIGATION_TITLE,
    DEMO_PASSWORD,
    seed_demo_evidence,
)

_CHECKS: List[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    _CHECKS.append(name)
    print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        raise AssertionError(f"check failed: {name}: {detail}")


def _run(
    client: TestClient,
    token: str,
    query: str,
    case_id: int,
    top_k: int = 8,
) -> Dict:
    started = time.perf_counter()
    res = client.post(
        "/investigation/search",
        json={"query": query, "case_id": case_id, "top_k": top_k},
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


def _ensure_no_evidence_case(db) -> int:
    cam = db.query(Camera).filter(Camera.camera_name == "DEMO-Phase6-Lobby-NoEvidence").first()
    if cam is None:
        cam = Camera(
            camera_name="DEMO-Phase6-Lobby-NoEvidence",
            location="Lobby - no demo evidence",
            description="Used for the demo isolation check",
            camera_type="CCTV",
            is_live=False,
            stream_status="OFFLINE",
        )
        db.add(cam)
        db.flush()
    video = db.query(Video).filter(Video.filename == "phase6_demo_lobby_no_evidence.mp4").first()
    if video is None:
        video = Video(
            filename="phase6_demo_lobby_no_evidence.mp4",
            storage_path="demo/phase6_demo_lobby_no_evidence.mp4",
            camera_id=cam.id,
            status="READY",
        )
        db.add(video)
        db.flush()
    inv = (
        db.query(Investigation)
        .filter(Investigation.title == "CASE-DEMO-P6-ISOLATION Lobby (no evidence)")
        .first()
    )
    if inv is None:
        inv = Investigation(
            title="CASE-DEMO-P6-ISOLATION Lobby (no evidence)",
            query="Isolation negative control case.",
            video_id=video.id,
            status="OPEN",
        )
        db.add(inv)
        db.flush()
    inv_id = int(inv.id)
    db.commit()
    return inv_id


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
        no_evidence_case = _ensure_no_evidence_case(db)
    finally:
        db.close()

    client = TestClient(app)
    token = _login(client, DEMO_EMAIL, DEMO_PASSWORD)
    case_id = int(demo["case_id"])
    cam_id = int(demo["camera_id"])
    cam_name = demo["camera_name"]

    t0, t1 = 36000.0, 36950.0

    # ---------------- five demo queries ----------------
    q1 = "Was there a person present in the parking area between 10:00 and 10:15?"
    r1 = _run(client, token, q1, case_id)
    _check("Q1 person presence, window answered", r1["status"] == "ANSWERED", r1["status"])
    _check("Q1 answer asserts presence", "YES -" in r1["answer"], r1["answer"][:80])
    _check(
        "Q1 results bounded to window + camera",
        bool(r1["results"])
        and all(t0 <= float(r["timestamp"] or -1) <= t1 for r in r1["results"])
        and all(r["camera_id"] == cam_id for r in r1["results"]),
        f"camera={cam_id}",
    )

    q2 = "What happened to the vehicles in the parking lot after 10:05?"
    r2 = _run(client, token, q2, case_id)
    _check("Q2 what-happened after time answered", r2["status"] == "ANSWERED", r2["status"])
    _check(
        "Q2 results are after 10:05",
        bool(r2["results"]) and all(float(r["timestamp"] or -1) >= 36300 for r in r2["results"]),
        f"n={len(r2['results'])}",
    )

    q3 = "Show all events where a person entered the parking area."
    r3 = _run(client, token, q3, case_id)
    _check("Q3 person-entered answered", r3["status"] == "ANSWERED", r3["status"])
    _check(
        "Q3 results are person entered events",
        bool(r3["results"])
        and all(r["event_type"] == "object_entered" for r in r3["results"])
        and all((r["object_class"] or "").lower() == "person" for r in r3["results"]),
        str([(r["event_type"], r["object_class"]) for r in r3["results"]]),
    )

    q4 = "Find all evidence for track T-P6-CAR-2."
    r4 = _run(client, token, q4, case_id)
    _check("Q4 track-dedicated answered", r4["status"] == "ANSWERED", r4["status"])
    _check(
        "Q4 all results belong to T-P6-CAR-2",
        bool(r4["results"]) and all(r["tracking_id"] == "T-P6-CAR-2" for r in r4["results"]),
        f"tracks={ {r['tracking_id'] for r in r4['results']} }",
    )
    _check("Q4 answer names the track", "T-P6-CAR-2" in r4["answer"], r4["answer"][:80])

    q5 = "How many vehicles entered the parking lot between 10:00 and 10:15?"
    r5 = _run(client, token, q5, case_id)
    _check("Q5 vehicle count answered", r5["status"] == "ANSWERED", r5["status"])
    _check(
        "Q5 count reflects both entered cars",
        "OBSERVED" in r5["answer"] and "2" in r5["answer"],
        r5["answer"][:100],
    )
    _check(
        "Q5 results are entered car events in window",
        bool(r5["results"])
        and all(r["event_type"] == "object_entered" for r in r5["results"])
        and all((r["object_class"] or "").lower() == "car" for r in r5["results"]),
        str([(r["event_type"], r["timestamp"]) for r in r5["results"]]),
    )

    # ---------------- negative UNKNOWN checks ----------------
    n1 = "Who is the person seen entering the parking area at 10:01?"
    rn1 = _run(client, token, n1, case_id)
    _check("N1 identity question UNKNOWN", rn1["status"] == "UNKNOWN", rn1["status"])
    _check("N1 no fabricated identity", "UNKNOWN" in rn1["answer"] and not rn1["results"], rn1["answer"][:80])

    n2 = "Why did the person enter the parking area?"
    rn2 = _run(client, token, n2, case_id)
    _check("N2 intent question UNKNOWN", rn2["status"] == "UNKNOWN", rn2["status"])
    _check("N2 intent not inferred", "UNKNOWN" in rn2["answer"] and not rn2["results"], rn2["answer"][:80])

    n3 = "Did anything happen outside the camera view during the incident?"
    rn3 = _run(client, token, n3, case_id)
    _check("N3 outside-view question UNKNOWN", rn3["status"] == "UNKNOWN", rn3["status"])
    _check("N3 nothing invented", "UNKNOWN" in rn3["answer"] and not rn3["results"], rn3["answer"][:80])

    # ---------------- isolation (case camera has no evidence) ----------------
    iso = _run(client, token, "Was there a person present between 10:00 and 10:15?", no_evidence_case)
    _check("Isolation: no-evidence case answers UNKNOWN", iso["status"] == "UNKNOWN", iso["status"])

    # ---------------- RBAC: REVIEWER denied ----------------
    reviewer_token = _login(client, "reviewer.demo@forensics-demo.com", "ReviewerDemo123!")
    res = client.post(
        "/investigation/search",
        json={"query": "any person?", "case_id": case_id},
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    _check("RBAC: REVIEWER is denied (403)", res.status_code == 403, f"status={res.status_code}")

    # ---------------- latency summary ----------------
    print("\n  latencies (ms):")
    for label, r in (("Q1", r1), ("Q2", r2), ("Q3", r3), ("Q4", r4), ("Q5", r5),
                     ("N1", rn1), ("N2", rn2), ("N3", rn3)):
        print(f"    {label}: {r['_elapsed_ms']}")
    print(f"\n   camera scope used: {cam_name} (id {cam_id})")

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
