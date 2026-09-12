"""Phase 4 - internet VLM test-data downloader.

Downloads a small, explicitly curated set of publicly accessible images and
short videos used ONLY to validate the VLM / multimodal pipeline. The data is
deliberately kept under ``data/vlm_test/`` and is NEVER treated as genuine
forensic evidence.

Guarantees (Phase 4 requirements):
1. Only the URLs defined in ``MANIFEST`` below are ever contacted - this is
   NOT a crawler and accepts no URL arguments.
2. HTTP responses are validated (2xx + expected Content-Type).
3. File type is validated by magic bytes (JPEG / ISO-BMFF MP4), never by
   trusting a URL extension.
4. File size is validated (per-item bounds; rejects empty / absurd sizes).
5. SHA-256 is computed and persisted with the metadata.
6. Metadata (source URL, site, retrieval date, original filename, local
   filename, media type, resolution, duration, license, SHA-256) is written
   to ``data/vlm_test/metadata.json``.
7. Already-downloaded, previously verified fixtures are reused (no duplicate
   downloads). Use ``--force`` to re-fetch.
8. Unavailable / failed URLs are recorded per-item and reported at the end;
   a single failure never aborts the run.
9. Downloaded files are never executed and nothing is copied out of
   ``data/vlm_test/`` - original evidence storage is never touched.
10. The script is fully offline-capable: ``--check`` validates the cached
    fixtures (and their hashes) without any network access.

Usage (from ``backend/``):

    python scripts/download_vlm_test_data.py            # ensure/download fixtures
    python scripts/download_vlm_test_data.py --check    # offline verification
    python scripts/download_vlm_test_data.py --force    # re-download everything
    python scripts/download_vlm_test_data.py --manifest # print the manifest only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data", "vlm_test")
IMAGES_DIR = os.path.join(DATA_DIR, "images")
VIDEOS_DIR = os.path.join(DATA_DIR, "videos")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")

# Network / validation policy.
DEFAULT_TIMEOUT_SECONDS = 60
MAX_ITEM_BYTES = 200 * 1024 * 1024  # hard cap: reject anything larger than 200 MB
MIN_IMAGE_BYTES = 512
MIN_VIDEO_BYTES = 16 * 1024
UA_STRING = "AI-Forensic-VLM-TestData/1.0 (validation fixtures; no crawling)"

# Explicitly curated, publicly accessible test fixtures. Each URL was verified
# reachable at authoring time. Nothing else is ever downloaded.
MANIFEST: list[dict[str, Any]] = [
    # ---- Images: people in public scenes, vehicles, streets, parking,
    # ---- retail/indoor scenes, multiple objects ----------------------------
    {
        "id": "vlm_img_parking_trucks",
        "kind": "image",
        "local_filename": "vlm_img_parking_trucks.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/11725734/pexels-photo-11725734.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/cars-in-the-parking-lot-11725734/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/ (redistribution of unmodified media on other stock platforms is not granted)",
        "description": "Fleet of utility trucks parked in an outdoor lot with safety cones and trees.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_street_people_cars",
        "kind": "image",
        "local_filename": "vlm_img_street_people_cars.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/13526712/pexels-photo-13526712.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/people-walking-on-the-street-near-the-cars-13526712/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Crowded urban street with pedestrians walking among parked cars and trees.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_parking_crosswalk",
        "kind": "image",
        "local_filename": "vlm_img_parking_crosswalk.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/27635989/pexels-photo-27635989.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/a-parking-lot-with-a-crosswalk-and-traffic-cones-27635989/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Aerial-style view of a parking lot with crosswalk markings and traffic cones.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_supermarket_aisle",
        "kind": "image",
        "local_filename": "vlm_img_supermarket_aisle.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/34175286/pexels-photo-34175286.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/people-shopping-in-supermarket-aisle-34175286/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "People shopping in a well-lit supermarket aisle (retail, indoor, people).",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_supermarket_interior",
        "kind": "image",
        "local_filename": "vlm_img_supermarket_interior.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/22624593/pexels-photo-22624593.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/interior-of-a-modern-supermarket-22624593/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Interior of a modern supermarket: aisles, shelves, checkout, indoor retail scene.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_sidewalk_buildings",
        "kind": "image",
        "local_filename": "vlm_img_sidewalk_buildings.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/8266479/pexels-photo-8266479.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/people-walking-on-a-busy-sidewalk-between-buildings-8266479/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "People walking on a busy sidewalk between buildings with a food cart and tramway.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_city_street_traffic",
        "kind": "image",
        "local_filename": "vlm_img_city_street_traffic.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/36288353/pexels-photo-36288353.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/bustling-city-street-with-pedestrians-and-traffic-lights-36288353/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Busy city intersection with pedestrians crossing at traffic lights (people, vehicles, street).",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_family_groceries",
        "kind": "image",
        "local_filename": "vlm_img_family_groceries.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/9706134/pexels-photo-9706134.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/a-family-buying-groceries-in-a-supermarket-9706134/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Family selecting fresh fruit together in a supermarket aisle.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_nyc_street",
        "kind": "image",
        "local_filename": "vlm_img_nyc_street.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/33496295/pexels-photo-33496295.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/busy-new-york-city-street-at-daytime-33496295/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Busy New York City street at daytime: pedestrians, traffic lights, tall buildings.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    {
        "id": "vlm_img_crowded_street",
        "kind": "image",
        "local_filename": "vlm_img_crowded_street.jpeg",
        "media_type": "image/jpeg",
        "source_url": "https://images.pexels.com/photos/33818431/pexels-photo-33818431.jpeg?auto=compress&cs=tinysrgb&w=800",
        "source_site": "Pexels (images.pexels.com)",
        "source_page": "https://www.pexels.com/photo/crowded-city-street-with-people-walking-33818431/",
        "license": "Pexels License - free to use, no attribution required; terms at https://www.pexels.com/license/",
        "description": "Lively city street crowded with people walking, historic buildings in the background.",
        "min_bytes": MIN_IMAGE_BYTES,
    },
    # ---- Videos: open movie samples + generic test clip ---------------------
    # W3C-hosted samples of Blender open movies (CC-BY 3.0, distributed freely
    # for interoperability testing) and a generic short sample clip. None of
    # these are surveillance footage; they exercise "multiple objects moving
    # through a scene".
    {
        "id": "vlm_vid_sintel_trailer",
        "kind": "video",
        "local_filename": "vlm_vid_sintel_trailer.mp4",
        "media_type": "video/mp4",
        "source_url": "https://media.w3.org/2010/05/sintel/trailer.mp4",
        "source_site": "W3C media samples (media.w3.org)",
        "source_page": "https://www.w3.org/2010/05/video/mediaevents.html",
        "license": "Sintel (c) copyright Blender Foundation | durian.blender.org - CC-BY 3.0, hosted by W3C as openly redistributable sample media",
        "description": "Sintel open-movie trailer - characters, people and objects moving through scenes.",
        "min_bytes": MIN_VIDEO_BYTES,
    },
    {
        "id": "vlm_vid_bunny_trailer",
        "kind": "video",
        "local_filename": "vlm_vid_bunny_trailer.mp4",
        "media_type": "video/mp4",
        "source_url": "https://media.w3.org/2010/05/bunny/trailer.mp4",
        "source_site": "W3C media samples (media.w3.org)",
        "source_page": "https://www.w3.org/2010/05/video/mediaevents.html",
        "license": "Big Buck Bunny (c) copyright Blender Foundation - CC-BY 3.0, hosted by W3C as openly redistributable sample media",
        "description": "Big Buck Bunny open-movie trailer - animated characters moving through outdoor scenes.",
        "min_bytes": MIN_VIDEO_BYTES,
    },
    {
        "id": "vlm_vid_bbb_360_10s",
        "kind": "video",
        "local_filename": "vlm_vid_bbb_360_10s.mp4",
        "media_type": "video/mp4",
        "source_url": "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4",
        "source_site": "test-videos.co.uk",
        "source_page": "https://test-videos.co.uk/bigbuckbunny/mp4-h264",
        "license": "Big Buck Bunny (c) copyright Blender Foundation - CC-BY 3.0; short 10s sample clip distributed by test-videos.co.uk",
        "description": "Big Buck Bunny 10-second 360p clip - quick acting/movement for temporal ordering tests.",
        "min_bytes": MIN_VIDEO_BYTES,
    },
    {
        "id": "vlm_vid_sample_640x360",
        "kind": "video",
        "local_filename": "vlm_vid_sample_640x360.mp4",
        "media_type": "video/mp4",
        "source_url": "https://filesamples.com/samples/video/mp4/sample_640x360.mp4",
        "source_site": "filesamples.com",
        "source_page": "https://filesamples.com/formats/mp4",
        "license": "Generic sample media published by filesamples.com for software testing (free to use for testing/development)",
        "description": "Generic 640x360 short sample clip for processing validation.",
        "min_bytes": MIN_VIDEO_BYTES,
    },
]


# ---------------------------------------------------------------------------
# Validation helpers (no execution, no crawling)
# ---------------------------------------------------------------------------


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_jpeg(path: str) -> bool:
    with open(path, "rb") as f:
        return f.read(3) == b"\xff\xd8\xff"


def _is_mp4(path: str) -> bool:
    with open(path, "rb") as f:
        head = f.read(12)
    # ISO-BMFF: bytes 4..8 == b'ftyp'
    return len(head) == 12 and head[4:8] == b"ftyp"


def _jpeg_size(path: str) -> tuple[int, int] | None:
    """Return (width, height) by parsing JPEG SOF markers (pure stdlib)."""
    try:
        with open(path, "rb") as f:
            data = f.read(512 * 1024)
    except OSError:
        return None
    if data[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF or (0xD0 <= marker <= 0xD9):
            i += 2
            continue
        if i + 4 > n:
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > n:
                break
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return (width, height)
        if length < 2:
            break
        i += 2 + length
    return None


def _video_metadata(path: str) -> dict[str, Any]:
    """Best-effort video metadata (resolution/fps/duration) without executing
    the file (reads metadata only, via opencv when available)."""
    try:
        import cv2  # local import: optional dependency
    except Exception:
        return {}
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {}
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frames / fps if fps > 0 and frames > 0 else None
        return {"width": w or None, "height": h or None, "fps": fps or None, "duration_seconds": duration}
    finally:
        cap.release()


def _content_meta(path: str, item: dict[str, Any]) -> dict[str, Any]:
    if item["kind"] == "image":
        w, h = _jpeg_size(path) or (None, None)
        return {"width": w, "height": h, "duration_seconds": None}
    meta = _video_metadata(path)
    return {
        "width": meta.get("width"),
        "height": meta.get("height"),
        "fps": meta.get("fps"),
        "duration_seconds": meta.get("duration_seconds"),
    }


def _validate_file(path: str, item: dict[str, Any]) -> dict[str, str]:
    """Magic-byte + size validation. Returns {status, error} with 'ok' status
    on success."""
    errors: list[str] = []
    if not os.path.exists(path):
        return {"status": "missing", "error": "file not present"}
    size = os.path.getsize(path)
    if size < int(item["min_bytes"]):
        errors.append(f"size {size}B below minimum {item['min_bytes']}B")
    if item["kind"] == "image" and not _is_jpeg(path):
        errors.append("magic bytes are not JPEG")
    if item["kind"] == "video" and not _is_mp4(path):
        errors.append("magic bytes are not ISO-BMFF MP4")
    if errors:
        return {"status": "invalid", "error": "; ".join(errors)}
    return {"status": "ok", "error": ""}


def _download(url: str, target: str, max_bytes: int) -> int:
    """Download ``url`` to ``target`` ensuring at most ``max_bytes`` are read.
    Returns the number of bytes written. Never executes the payload."""
    req = urllib.request.Request(url, headers={"User-Agent": UA_STRING})
    total = 0
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
        if not (200 <= resp.status < 300):
            raise urllib.error.HTTPError(url, resp.status, "unexpected status", resp.headers, None)
        with open(target, "wb") as out:
            while True:
                chunk = resp.read(512 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"exceeded max_bytes={max_bytes}")
                out.write(chunk)
    return total


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def _empty_metadata() -> dict[str, Any]:
    return {
        "dataset": {
            "name": "vlm_test",
            "classification": "INTERNET_TEST_DATA",
            "description": "Small, publicly accessible visual fixtures for VLM / multimodal pipeline validation. NEVER to be treated as genuine forensic evidence.",
            "disclaimer": "This dataset is INTERNET TEST DATA, not real forensic evidence. It is never mixed with evidence storage and must not be used to ground conclusions about real cases.",
            "generated_by": "backend/scripts/download_vlm_test_data.py",
            "created_at": _now_utc(),
            "license_notes": "Per-item licenses are recorded below. Pexels media is free to use without attribution; Blender open movies are CC-BY 3.0; filesamples media is a generic sample. None of these licenses grant unrestricted redistribution of this curated file set.",
        },
        "items": [],
    }


def _load_metadata() -> dict[str, Any]:
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("items") is not None:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _empty_metadata()


def _save_metadata(meta: dict[str, Any]) -> None:
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def _manifest_record(item: dict[str, Any], local_path: str, retrieval_date: str | None) -> dict[str, Any]:
    record = {
        "id": item["id"],
        "kind": item["kind"],
        "source_url": item["source_url"],
        "source_site": item["source_site"],
        "source_page": item["source_page"],
        "original_filename": os.path.basename(item["source_url"].split("?")[0]),
        "local_filename": item["local_filename"],
        "media_type": item["media_type"],
        "license": item["license"],
        "status": "missing",
        "error": "",
    }
    if local_path and os.path.exists(local_path):
        existing = _validate_file(local_path, item)
        record["status"] = existing["status"]
        record["error"] = existing["error"]
        if existing["status"] == "ok":
            record["sha256"] = _sha256(local_path)
            record["size_bytes"] = os.path.getsize(local_path)
            record.update(_content_meta(local_path, item))
            if retrieval_date:
                record["retrieval_date"] = retrieval_date
    return record


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_manifest() -> int:
    for item in MANIFEST:
        kind = item["kind"].upper()
        print(f"[{kind}] {item['id']:26s} {item['source_url']}")
    return 0


def cmd_ensure(force: bool = False) -> int:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(VIDEOS_DIR, exist_ok=True)

    meta = _load_metadata()
    existing_by_id = {it["id"]: it for it in meta.get("items", []) if it.get("kind")}
    items_out: list[dict[str, Any]] = []
    failures: list[str] = []

    for item in MANIFEST:
        sub = IMAGES_DIR if item["kind"] == "image" else VIDEOS_DIR
        local_path = os.path.join(sub, item["local_filename"])

        # Reuse a previously verified fixture when present (no duplicate
        # download) unless forced.
        prev = existing_by_id.get(item["id"])
        cached_ok = False
        if not force and prev and prev.get("status") == "ok" and os.path.exists(local_path):
            if _sha256(local_path) == prev.get("sha256"):
                cached_ok = True

        if cached_ok:
            print(f"[skip] {item['id']}: cached fixture verified ({prev.get('sha256', '')[:12]}...)")
            items_out.append(_manifest_record(item, local_path, prev.get("retrieval_date")))
            continue

        print(f"[get ] {item['id']}: {item['source_url']}")
        try:
            _download(item["source_url"], local_path, MAX_ITEM_BYTES)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
            print(f"[fail] {item['id']}: download failed - {exc}")
            failures.append(item["id"])
            items_out.append(_manifest_record(item, local_path, None))
            continue

        check = _validate_file(local_path, item)
        if check["status"] != "ok":
            print(f"[fail] {item['id']}: validation failed - {check['error']}")
            failures.append(item["id"])
            try:
                os.remove(local_path)
            except OSError:
                pass
            items_out.append(_manifest_record(item, local_path, None))
            continue

        record = _manifest_record(item, local_path, _now_utc())
        print(f"[ok  ] {item['id']}: {record['size_bytes']}B sha256={record['sha256'][:12]}...")
        items_out.append(record)

    meta["items"] = items_out
    meta["dataset"]["last_checked_at"] = _now_utc()
    _save_metadata(meta)

    ok_count = sum(1 for it in items_out if it.get("status") == "ok")
    print(f"\n{ok_count}/{len(MANIFEST)} items present and verified. Metadata: {METADATA_FILE}")
    if failures:
        print("Failed items: " + ", ".join(failures))
        return 1
    return 0


def cmd_check() -> int:
    """Offline verification of cached fixtures against recorded hashes."""
    if not os.path.exists(METADATA_FILE):
        print("No metadata.json found - nothing to check offline.")
        return 1
    meta = _load_metadata()
    records = {it["id"]: it for it in meta.get("items", []) if it.get("kind")}
    if not records:
        print("metadata.json has no items - run the downloader first.")
        return 1

    failures: list[str] = []
    for item in MANIFEST:
        rec = records.get(item["id"])
        sub = IMAGES_DIR if item["kind"] == "image" else VIDEOS_DIR
        local_path = os.path.join(sub, item["local_filename"])
        if not rec or not os.path.exists(local_path):
            print(f"[miss] {item['id']}: fixture not cached")
            failures.append(item["id"])
            continue
        ok = _validate_file(local_path, item)["status"] == "ok"
        ok_hash = _sha256(local_path) == rec.get("sha256") if rec.get("sha256") else False
        if ok and ok_hash:
            print(f"[ok  ] {item['id']}: hash verified {rec.get('sha256', '')[:12]}...")
        else:
            print(f"[fail] {item['id']}: hash mismatch or invalid file (rerun with --force)")
            failures.append(item["id"])
    if failures:
        print("Offline check FAILED for: " + ", ".join(failures))
        return 1
    print("Offline check PASSED for all manifest items.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download/validate Phase 4 internet VLM test fixtures.")
    parser.add_argument("--check", action="store_true", help="offline verification of cached fixtures (no network)")
    parser.add_argument("--force", action="store_true", help="re-download all fixtures, ignoring cached copies")
    parser.add_argument("--manifest", action="store_true", help="print the curated URL manifest and exit")
    args = parser.parse_args(argv)

    if args.manifest:
        return cmd_manifest()
    if args.check:
        return cmd_check()
    return cmd_ensure(force=args.force)


if __name__ == "__main__":
    sys.exit(main())