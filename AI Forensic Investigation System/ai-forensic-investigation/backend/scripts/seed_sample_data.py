"""Phase 2 sample-data seeder.

Downloads publicly available sample videos (Google GTV bucket - freely
distributed short clips) with the Python standard library ONLY, registers sample
cameras + videos through the real API so the dashboard shows genuine content.

Run (backend must be up, default http://localhost:8000):

    python scripts/seed_sample_data.py [--base-url http://localhost:8000]

Adding ``--process`` triggers processing of uploaded videos (ffmpeg + retrieval)
so the dashboard gains a fully COMPLETED video with detections; leave it off for
a quick content-only seed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

BASE_URL_DEFAULT = "http://localhost:8000"
DOWNLOAD_DIR = os.environ.get(
    "SAMPLE_VIDEO_DIR", os.path.join(tempfile.gettempdir(), "forensics_sample_videos")
)

# Verified public sample videos (small, freely redistributable - Sintel &
# Big Buck Bunny trailers and a generic CC test clip).
VIDEOS = [
    ("sintel_trailer.mp4", "https://media.w3.org/2010/05/sintel/trailer.mp4",
     "Sintel open-movie trailer (sample clip)", "CCTV_Lobby"),
    ("bigbuckbunny_trailer.mp4", "https://media.w3.org/2010/05/bunny/trailer.mp4",
     "Big Buck Bunny open-movie trailer (sample clip)", "CCTV_Plaza"),
    ("bbb_360_10s_1mb.mp4", "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
     "Big Buck Bunny 10s test clip (sample clip)", "CCTV_Retail_Floor"),
    ("sample_640x360.mp4", "https://filesamples.com/samples/video/mp4/sample_640x360.mp4",
     "Generic 640x360 sample clip", "CCTV_Parking"),
]

CAMERAS = [
    ("CCTV_Retail_Floor", "Retail floor - camera 01", "CCTV"),
    ("CCTV_Parking", "Outdoor parking - camera 02", "CCTV"),
    ("CCTV_Plaza", "Public plaza - camera 03", "CCTV"),
    ("CCTV_Street_Corridor", "Street corridor - camera 04", "OTHER"),
    ("CCTV_Lobby", "Building lobby - camera 05", "OTHER"),
]


# --------------------------------------------------------------------- http


def _request(method: str, path: str, token: str | None = None, body=None, form: bytes | None = None, content_type=None):
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))["detail"]
        except Exception:
            detail = str(exc)
        return exc.code, {"detail": detail}


def _download(url: str, dest: str) -> None:
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return
    print(f"  downloading {url} -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Forensic-Investigation-Sample-Seeder/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


# ------------------------------------------------------------------- main


def _ensure_user(client_fn) -> tuple[str, str]:
    """Register (or login) the sample seeder admin. Returns (user_id, token)."""
    status, data = client_fn("POST", "/auth/register", body={
        "email": "sample.data@forensics-demo.com", "name": "Sample Data", "password": "sample12345", "role": "ADMIN",
    })
    if status not in (201, 409):
        print(f"  register failed: {status} {data}")
        sys.exit(1)
    status, data = client_fn("POST", "/auth/login", body={
        "email": "sample.data@forensics-demo.com", "password": "sample12345",
    })
    if status != 200:
        print(f"  login failed: {status} {data}")
        sys.exit(1)
    token = data["access_token"]
    return str(data["user"]["id"]), token


def _ensure_cameras(client_fn, token) -> dict[str, int]:
    cameras = {}
    status, existing = client_fn("GET", "/cameras", token)
    if status == 200:
        by_name = {c["camera_name"]: c["id"] for c in existing}
    else:
        by_name = {}
    for name, location, ctype in CAMERAS:
        if name in by_name:
            cameras[name] = by_name[name]
            continue
        status, cam = client_fn("POST", "/cameras", token, body={
            "camera_name": name, "location": location, "camera_type": ctype,
            "stream_source": f"file-sample-{name.lower()}",
        })
        if status == 201:
            cameras[name] = cam["id"]
            print(f"  created camera {name} (id={cam['id']})")
        else:
            cameras[name] = by_name.get(name)
            print(f"  camera {name}: {status} {cam}")
    return cameras


def _upload_video(client_fn, token, camera_id: int, path: str, filename: str, description: str) -> None:
    boundary = "----forensicsSeed"
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
    form = b"".join(parts)
    status, data = client_fn("POST", "/videos/upload", token, form=form,
                             content_type=f"multipart/form-data; boundary={boundary}")
    if status == 201:
        print(f"  uploaded {filename} -> video_id={data.get('video_id')}")
    else:
        print(f"  upload {filename} failed: {status} {data}")


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="Seed sample cameras + videos")
    parser.add_argument("--base-url", default=BASE_URL_DEFAULT)
    parser.add_argument("--process", action="store_true", help="also trigger processing")
    parser.add_argument("--skip-download", action="store_true", help="use already downloaded videos")
    args = parser.parse_args()
    BASE = args.base_url.rstrip("/")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    user_id, token = _ensure_user(_request)
    print(f"seeder user id={user_id}")
    cameras = _ensure_cameras(_request, token)

    touch = []
    for filename, url, description, camera in VIDEOS:
        dest = os.path.join(DOWNLOAD_DIR, filename)
        if not args.skip_download:
            try:
                _download(url, dest)
            except (urllib.error.URLError, OSError) as exc:
                print(f"  download {filename} failed: {exc}")
                continue
        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            print(f"  skipping {filename} (missing/empty)")
            continue
        camera_id = cameras.get(camera)
        _upload_video(_request, token, camera_id, dest, filename, description)
        touch.append(dest)

    if args.process:
        import time

        time.sleep(1)  # give the upload handler a beat
        status, videos = _request("GET", "/videos", token)
        if status == 200:
            for vid in videos:
                if isinstance(vid, dict) and vid.get("id"):
                    print(f"  processing video {vid['id']}...")
                    _request("POST", f"/videos/{vid['id']}/process", token)
        print("processing queued - check /videos for COMPLETED progress")

    print(f"\nsample videos in {DOWNLOAD_DIR}")
    print("dashboard should now list sample cameras + uploaded videos")


if __name__ == "__main__":
    main()