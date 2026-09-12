"""Demo Investigation Dataset seeder.

Idempotently populates the AI Forensic Investigation System with DEMO-only
resources: a dedicated demo admin, DEMO cameras, the demo videos (uploaded +
processed through the REAL offline pipeline), enrichment (optional) and
CASE-DEMO investigations. Every created resource is clearly labeled

    DEMO DATA - NOT REAL FORENSIC EVIDENCE

To keep demo data clearly separated from real data, all cameras and cases use
the ``DEMO-``/``CASE-DEMO-`` prefix and all uploads reuse the ``demo_video_*``
filenames from the demo dataset.

Run from the backend directory with the API up:

    python scripts/seed_demo_investigation.py [--base-url http://127.0.0.1:8000]
    python scripts/seed_demo_investigation.py --upload-only        # do not process
    python scripts/seed_demo_investigation.py --no-investigations # skip cases

Requires the demo dataset to exist (run scripts/download_demo_investigation_data.py first).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://127.0.0.1:8000"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(BACKEND_DIR, "data", "demo_investigation")
VIDEOS_DIR = os.path.join(ROOT, "videos")

DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"
DEMO_NAME = "Demo Investigation Data"
DISCLAIMER = "DEMO DATA - NOT REAL FORENSIC EVIDENCE"

# case_id -> camera name/location + expected video file
CASES = [
    {
        "case_id": "CASE-DEMO-001",
        "title": "Parking Area Vehicle Activity",
        "query": "Are there vehicles present in the parking area footage?",
        "camera_name": "DEMO-Parking-Entry",
        "camera_location": "Parking area (demo)",
        "video": "demo_video_01_parking_cars.mp4",
        "description": "Parking area vehicle activity demo case.",
    },
    {
        "case_id": "CASE-DEMO-002",
        "title": "Street Intersection Persons and Cyclists",
        "query": "What persons, cyclists and vehicles are visible at this intersection?",
        "camera_name": "DEMO-Street-Intersection",
        "camera_location": "Street intersection (demo)",
        "video": "demo_video_02_street_persons_bikes.mp4",
        "description": "Street intersection demo case (primary E2E).",
    },
    {
        "case_id": "CASE-DEMO-003",
        "title": "Retail Store Aisle Crowd Check",
        "query": "Are there shoppers present in the retail aisle?",
        "camera_name": "DEMO-Retail-Aisle",
        "camera_location": "Retail store aisle (demo)",
        "video": "demo_video_03_retail_store_aisle.mp4",
        "description": "Retail store aisle crowd check demo case.",
    },
    {
        "case_id": "CASE-DEMO-004",
        "title": "Public Area People Detection",
        "query": "How many persons are present in the public area?",
        "camera_name": "DEMO-Public-Plaza",
        "camera_location": "Public plaza (demo)",
        "video": "demo_video_04_public_people.mp4",
        "description": "Public area people detection demo case.",
    },
    {
        "case_id": "CASE-DEMO-005",
        "title": "Archive Classroom Review",
        "query": "Are there people seated in the classroom footage?",
        "camera_name": "DEMO-Archive-Classroom",
        "camera_location": "Archive classroom (demo)",
        "video": "demo_video_05_archive_classroom.mp4",
        "description": "Archive classroom review demo case.",
    },
]

SUMMARY_PATH = os.path.join(ROOT, "results", "seed_summary.json")


# --------------------------------------------------------------------- http


def _request(method: str, path: str, token: str | None = None, body=None, form: bytes | None = None, content_type=None, timeout: int = 60):
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        data = form
        if content_type:
            headers["Content-Type"] = content_type
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))["detail"]
        except Exception:
            detail = str(exc)
        return exc.code, {"detail": detail}


def _ensure_user(client_fn) -> tuple[str, str]:
    """Register (or use) the demo seeder admin. Returns (user_id, token)."""
    status, data = client_fn("POST", "/auth/register", body={
        "email": DEMO_EMAIL, "name": DEMO_NAME, "password": DEMO_PASSWORD, "role": "ADMIN",
    })
    if status not in (201, 409):
        print(f"  register failed: {status} {data}")
        sys.exit(1)
    status, data = client_fn("POST", "/auth/login", body={
        "email": DEMO_EMAIL, "password": DEMO_PASSWORD,
    })
    if status != 200:
        print(f"  login failed: {status} {data}")
        sys.exit(1)
    return str(data["user"]["id"]), data["access_token"]


def _ensure_cameras(client_fn, token) -> dict[str, int]:
    cameras = {}
    status, existing = client_fn("GET", "/cameras", token)
    by_name = {c["camera_name"]: c["id"] for c in existing} if status == 200 else {}
    for case in CASES:
        name = case["camera_name"]
        if name in by_name:
            cameras[case["case_id"]] = by_name[name]
            continue
        status, cam = client_fn("POST", "/cameras", token, body={
            "camera_name": name,
            "location": case["camera_location"],
            "camera_type": "CCTV",
            "stream_source": f"demo://{case['case_id']}/file",
            "description": DISCLAIMER,
        })
        if status == 201:
            cameras[case["case_id"]] = cam["id"]
            print(f"  created camera {name} (id={cam['id']})")
        else:
            print(f"  camera {name}: {status} {cam}")
    return cameras


def _multipart(client_fn, token, camera_id: int, path: str, filename: str, description: str, timeout: int = 120):
    boundary = "----forensicsDemoSeed"
    with open(path, "rb") as fh:
        content = fh.read()

    def field(name, value):
        return (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )

    def file_field(name, fname):
        return (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
            f"filename=\"{fname}\"\r\nContent-Type: video/mp4\r\n\r\n".encode("utf-8")
        )

    parts = [
        field("camera_id", str(camera_id)),
        field("description", description),
        file_field("file", filename),
        content,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ]
    status, data = client_fn("POST", "/videos/upload", token, form=b"".join(parts),
                             content_type=f"multipart/form-data; boundary={boundary}", timeout=timeout)
    return status, data


def _existing_videos(client_fn, token) -> dict[str, int]:
    status, videos = client_fn("GET", "/videos", token)
    out = {}
    if status == 200:
        for v in videos:
            out[v.get("filename")] = v.get("id")
    return out


def _wait_ready(client_fn, token, video_id: int, timeout: int, job_id_prefix: str = "") -> dict:
    """Poll /videos/{id}/status until READY or FAILED. Returns final job."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        status, job = client_fn("GET", f"/videos/{video_id}/status", token)
        if status == 200:
            last = job
            if job.get("status") in ("READY", "FAILED"):
                return job
        time.sleep(3)
    return last


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="Seed demo investigation data")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--upload-only", action="store_true", help="upload videos but do not process")
    parser.add_argument("--no-investigations", action="store_true", help="skip CASE-DEMO creation")
    parser.add_argument("--no-enrich", action="store_true", help="skip enrichment of the primary video")
    parser.add_argument("--per-video-timeout", type=int, default=600, help="seconds to wait per video")
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")

    if not os.path.isdir(VIDEOS_DIR):
        print(f"demo dataset videos not found under {VIDEOS_DIR}")
        print("run: python scripts/download_demo_investigation_data.py first")
        sys.exit(1)

    summary = {"disclaimer": DISCLAIMER, "cameras": {}, "videos": {}, "jobs": {}, "cases": {}}

    user_id, token = _ensure_user(_request)
    print(f"demo seeder user id={user_id}")
    cameras = _ensure_cameras(_request, token)
    summary["cameras"] = cameras

    existing = _existing_videos(_request, token)

    for case in CASES:
        video = case["video"]
        path = os.path.join(VIDEOS_DIR, video)
        if not os.path.isfile(path):
            print(f"  skipping {video}: file missing")
            continue
        camera_id = cameras.get(case["case_id"])
        if (video in existing):
            video_id = existing[video]
            print(f"  {video} already uploaded (id={video_id})")
        else:
            status, data = _multipart(_request, token, camera_id, path, video,
                                      f"{DISCLAIMER}. {case['description']}")
            if status != 201:
                print(f"  upload {video} failed: {status} {data}")
                continue
            video_id = data["video_id"]
            existing[video] = video_id
            print(f"  uploaded {video} -> video_id={video_id}")

        summary["videos"][case["case_id"]] = video_id

        if not args.upload_only:
            if video_id in summary["jobs"]:
                continue
            job = _wait_ready(_request, token, video_id, args.per_video_timeout)
            if job.get("status") != "READY":
                # (re)queue processing if not yet processed
                _request("POST", f"/videos/{video_id}/process", token)
                job = _wait_ready(_request, token, video_id, args.per_video_timeout)
            summary["jobs"][case["case_id"]] = {"id": job.get("id"), "status": job.get("status"), "error": job.get("error")}
            print(f"  {video} job status={job.get('status')} progress={job.get('progress')}")

    if not args.no_investigations:
        status, invs = _request("GET", "/investigations", token)
        existing_titles = {i.get("title"): i for i in invs} if status == 200 else {}
        for case in CASES:
            if case["title"] in existing_titles:
                print(f"  investigation {case['case_id']} exists (id={existing_titles[case['title']]['id']})")
                summary["cases"][case["case_id"]] = existing_titles[case["title"]]["id"]
                continue
            video_id = summary["videos"].get(case["case_id"])
            status, inv = _request("POST", "/investigations", token, body={
                "title": case["title"],
                "description": f"{DISCLAIMER}. {case['description']}",
                "query": case["query"],
                "video_id": video_id,
            })
            if status == 201:
                summary["cases"][case["case_id"]] = inv["id"]
                print(f"  created investigation {case['case_id']} (id={inv['id']})")
            else:
                print(f"  investigation {case['case_id']} failed: {status} {inv}")

    if not args.upload_only and not args.no_enrich:
        primary_id = summary["videos"].get("CASE-DEMO-002")
        if primary_id:
            status, _ = _request("POST", f"/videos/{primary_id}/enrich", token)
            print(f"  enrichment for video {primary_id}: status={status} (async)")

    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nsummary written to {SUMMARY_PATH}")
    print("demo seeding complete - dashboard should list DEMO cameras/videos and CASE-DEMO cases")


if __name__ == "__main__":
    main()