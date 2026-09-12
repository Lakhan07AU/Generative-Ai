"""Demo Investigation Dataset seeder (canonical, manifest-driven).

Idempotently populates the AI Forensic Investigation System with DEMO-only
resources: a dedicated demo admin, DEMO cameras, ALL demo videos from the
dataset manifest (uploaded + processed through the REAL offline pipeline),
enrichment (optional) and CASE-DEMO investigations for every case in
cases.json. Every created resource is clearly labeled

    DEMO DATA - NOT REAL FORENSIC EVIDENCE

This is the canonical superset seeder for the demo dataset. All demo cameras
use the ``DEMO-`` prefix, all cases use ``CASE-DEMO-`` and all uploads reuse
the ``demo_video_*`` filenames from the manifest.

Run from the backend directory with the API up:

    python scripts/seed_demo_videos.py [--base-url http://127.0.0.1:8000]
    python scripts/seed_demo_videos.py --upload-only        # do not process
    python scripts/seed_demo_videos.py --only new           # only upload/process new videos
    python scripts/seed_demo_videos.py --no-investigations # skip cases

Requires the demo dataset to exist (scripts/download_demo_investigation_data.py
and scripts/gen_demo_scenarios.py first).
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
MANIFEST_PATH = os.path.join(ROOT, "metadata", "manifest.json")
CASES_PATH = os.path.join(ROOT, "cases.json")

DEMO_EMAIL = "demo.investigation@forensics-demo.com"
DEMO_PASSWORD = "demo-investigation-2026"
DEMO_NAME = "Demo Investigation Data"
DISCLAIMER = "DEMO DATA - NOT REAL FORENSIC EVIDENCE"

# case_id -> demo CCTV camera mapping
CAMERAS = {
    "CASE-DEMO-001": ("DEMO-Parking-Entry", "Parking area (demo)"),
    "CASE-DEMO-002": ("DEMO-Street-Intersection", "Street intersection (demo)"),
    "CASE-DEMO-003": ("DEMO-Retail-Aisle", "Retail store aisle (demo)"),
    "CASE-DEMO-004": ("DEMO-Public-Plaza", "Public plaza (demo)"),
    "CASE-DEMO-005": ("DEMO-Archive-Classroom", "Archive classroom (demo)"),
    "CASE-DEMO-006": ("DEMO-Corridor-OneByOne", "Corridor entry (demo)"),
    "CASE-DEMO-007": ("DEMO-Worker-Zone", "Industrial worker zone (demo)"),
    "CASE-DEMO-008": ("DEMO-Corridor-Movement", "Corridor movement (demo)"),
    "CASE-DEMO-009": ("DEMO-Corridor-Pause", "Corridor walking-pause (demo)"),
    "CASE-DEMO-010": ("DEMO-Cartoon-Robustness", "Cartoon non-permission awareness (demo)"),
}

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


def _ensure_cameras(client_fn, token, case_ids) -> dict[str, int]:
    cameras = {}
    status, existing = client_fn("GET", "/cameras", token)
    by_name = {c["camera_name"]: c["id"] for c in existing} if status == 200 else {}
    for case_id in case_ids:
        name, location = CAMERAS.get(case_id, (f"DEMO-{case_id}", "Demo"))
        if name in by_name:
            cameras[case_id] = by_name[name]
            continue
        status, cam = client_fn("POST", "/cameras", token, body={
            "camera_name": name,
            "location": location,
            "camera_type": "CCTV",
            "stream_source": f"demo://{case_id}/file",
            "description": DISCLAIMER,
        })
        if status == 201:
            cameras[case_id] = cam["id"]
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


def _wait_ready(client_fn, token, video_id: int, timeout: int) -> dict:
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


def _process(client_fn, token, video_id: int, timeout: int) -> dict:
    _request("POST", f"/videos/{video_id}/process", token)
    return _wait_ready(client_fn, token, video_id, timeout)


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="Seed demo investigation dataset (canonical)")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--upload-only", action="store_true", help="upload videos but do not process")
    parser.add_argument("--no-investigations", action="store_true", help="skip CASE-DEMO creation")
    parser.add_argument("--no-enrich", action="store_true", help="skip enrichment of the primary video")
    parser.add_argument("--per-video-timeout", type=int, default=900, help="seconds to wait per video")
    parser.add_argument("--only", choices=["new", "all"], default="all",
                        help="'new' only processes videos not already READY; 'all' (default) re-checks every video")
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")

    if not os.path.isdir(VIDEOS_DIR):
        print(f"demo dataset videos not found under {VIDEOS_DIR}")
        print("run: python scripts/download_demo_investigation_data.py first")
        sys.exit(1)
    if not os.path.isfile(CASES_PATH):
        print(f"cases.json not found ({CASES_PATH}); run scripts/gen_demo_scenarios.py")
        sys.exit(1)

    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    cases = json.load(open(CASES_PATH, encoding="utf-8"))
    # case -> video file (from cases.json)
    case_videos = {c["case_id"]: c["video_file"] for c in cases if c.get("video_file")}
    case_meta = {c["case_id"]: c for c in cases}
    all_case_ids = list(case_videos.keys())

    summary = {
        "disclaimer": DISCLAIMER,
        "cameras": {}, "videos": {}, "jobs": {}, "cases": {},
        "manifest_videos": len(manifest.get("videos", [])),
        "cases_total": len(cases),
    }

    user_id, token = _ensure_user(_request)
    print(f"demo seeder user id={user_id}")
    cameras = _ensure_cameras(_request, token, all_case_ids)
    summary["cameras"] = cameras

    existing = _existing_videos(_request, token)

    for case_id in all_case_ids:
        video = case_videos[case_id]
        path = os.path.join(VIDEOS_DIR, video)
        if not os.path.isfile(path):
            print(f"  skipping {video}: file missing")
            continue
        camera_id = cameras.get(case_id)
        meta = case_meta.get(case_id, {})

        if video in existing:
            video_id = existing[video]
            print(f"  {video} already uploaded (id={video_id})")
        else:
            status, data = _multipart(_request, token, camera_id, path, video,
                                      f"{DISCLAIMER}. {meta.get('description', case_id)}")
            if status != 201:
                print(f"  upload {video} failed: {status} {data}")
                continue
            video_id = data["video_id"]
            existing[video] = video_id
            print(f"  uploaded {video} -> video_id={video_id}")

        summary["videos"][case_id] = video_id
        summary["videos"][f"{case_id}__file"] = video

        if not args.upload_only:
            job = _wait_ready(_request, token, video_id, args.per_video_timeout)
            if job.get("status") == "READY":
                if args.only == "new":
                    print(f"  {video} already READY (id={video_id}); skipping re-process")
                    summary["jobs"].setdefault(case_id, {"id": job.get("id"), "status": "READY", "skipped": True})
                    continue
            else:
                job = _process(_request, token, video_id, args.per_video_timeout)
            summary["jobs"][case_id] = {"id": job.get("id"), "status": job.get("status"), "error": job.get("error")}
            print(f"  {video} job status={job.get('status')} progress={job.get('progress')}")

    if not args.no_investigations:
        status, invs = _request("GET", "/investigations", token)
        existing_titles = {i.get("title"): i for i in invs} if status == 200 else {}
        for case_id in all_case_ids:
            meta = case_meta.get(case_id, {})
            title = meta.get("title", case_id)
            if title in existing_titles:
                print(f"  investigation {case_id} exists (id={existing_titles[title]['id']})")
                summary["cases"][case_id] = existing_titles[title]["id"]
                continue
            video_id = summary["videos"].get(case_id)
            status, inv = _request("POST", "/investigations", token, body={
                "title": title,
                "description": f"{DISCLAIMER}. {meta.get('description', case_id)}",
                "query": meta.get("query", ""),
                "video_id": video_id,
            })
            if status == 201:
                summary["cases"][case_id] = inv["id"]
                print(f"  created investigation {case_id} (id={inv['id']})")
            else:
                print(f"  investigation {case_id} failed: {status} {inv}")

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