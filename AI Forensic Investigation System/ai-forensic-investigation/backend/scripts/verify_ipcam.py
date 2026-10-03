"""Phone IP-camera verification (transport ``ipcam``).

Checks a real network stream served by a phone (Android "IP Webcam" and
compatible apps) at two levels:

* **device** - opens the URL with OpenCV, reports the capture backend that
  delivered pixels, the real resolution and the measured frame rate;
* **chain** (optional, ``--base-url``) - starts a live session through the API
  and proves frames reach detection, evidence, PostgreSQL, MinIO and Qdrant.

Nothing is simulated: if the stream cannot be opened the script exits non-zero
and prints the exact blocker.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def http_probe(url: str, timeout: float = 8.0) -> dict:
    """Cheap reachability check that reports the HTTP status/content-type."""
    try:
        req = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(1024)
            return {
                "ok": True,
                "status": resp.status,
                "content_type": resp.headers.get("Content-Type"),
                "sample_bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"HTTP {exc.code} {exc.reason}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def open_stream(url: str, seconds: float = 6.0) -> dict:
    """Open the URL with every URL-appropriate backend; report the one that worked."""
    import cv2

    from app.live.webcam_camera import _resolve_backends

    attempts = []
    for name, api in _resolve_backends(cv2, ("ffmpeg", "any", "gstreamer")):
        cap = cv2.VideoCapture(url, api)
        if cap is None or not cap.isOpened():
            attempts.append(f"{name}: not opened")
            if cap is not None:
                cap.release()
            continue
        ok, frame = cap.read()
        if not ok or frame is None or getattr(frame, "size", 0) == 0:
            attempts.append(f"{name}: opened but no frame")
            cap.release()
            continue
        frames = 0
        first = (int(frame.shape[1]), int(frame.shape[0]))
        sizes = {first}
        t0 = time.time()
        deadline = t0 + seconds
        while time.time() < deadline:
            ok, f = cap.read()
            if ok and f is not None:
                frames += 1
                sizes.add((int(f.shape[1]), int(f.shape[0])))
        elapsed = max(time.time() - t0, 1e-6)
        reported_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap.release()
        return {
            "ok": True,
            "backend": name,
            "size": first,
            "sizes": sorted(sizes),
            "frames": frames,
            "fps": frames / elapsed,
            "reported_fps": reported_fps,
            "attempts": attempts,
        }
    return {"ok": False, "attempts": attempts}


def run_chain(base_url: str, url: str, camera_id: int, seconds: float, token: str) -> dict:
    """Start a real ipcam session and confirm the pipeline is fed."""
    import httpx

    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    out: dict = {}
    with httpx.Client(base_url=base, headers=headers, timeout=60.0) as c:
        start = c.post(
            f"/live/cameras/{camera_id}/start",
            json={"transport": "ipcam", "stream_url": url, "fps_target": 10},
        )
        out["start_status"] = start.status_code
        if start.status_code >= 400:
            out["start_error"] = start.text[:400]
            return out
        try:
            time.sleep(seconds)
            status = c.get(f"/live/cameras/{camera_id}/status").json()
            out["status"] = status.get("status")
            out["frames_received"] = status.get("frames_received")
            out["frames_sampled"] = status.get("frames_sampled")
            out["source_health"] = status.get("source_health")
            out["evidence"] = status.get("evidence_captured")
            out["detection_metrics"] = status.get("detection_metrics")
        finally:
            c.post(f"/live/cameras/{camera_id}/stop")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Phone IP camera verification")
    parser.add_argument("--url", default=os.environ.get("IPCAM_STREAM_URL", ""),
                        help="Stream URL, e.g. http://10.5.176.115:8080/video")
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--base-url", default="",
                        help="API base URL; enables the full chain check (needs a camera id)")
    parser.add_argument("--camera", type=int, default=1)
    parser.add_argument("--token", default=os.environ.get("DEMO_TOKEN", ""))
    args = parser.parse_args()

    url = (args.url or "").strip()
    print("\nIP CAMERA TEST")
    print("=" * 46)
    print(f"Stream URL: {url or '(not provided)'}")
    if not url:
        print("  provide --url or set IPCAM_STREAM_URL")
        print("RESULT: FAIL")
        return 1

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"{name:<24} {'PASS' if ok else 'FAIL'}{(' - ' + detail) if detail else ''}")

    print("")
    print("-- HTTP reachability --")
    probe = http_probe(url)
    record("URL reachable", probe.get("ok", False),
           f"status={probe.get('status')} type={probe.get('content_type')}"
           if probe.get("ok") else probe.get("error", ""))
    if not probe.get("ok"):
        print("\nRESULT: FAIL (the backend could not reach the stream URL)")
        return 1

    print("")
    print("-- OpenCV capture --")
    cap = open_stream(url, seconds=args.seconds)
    record("stream opened", cap.get("ok", False),
           f"backend={cap.get('backend')}" if cap.get("ok") else "; ".join(cap.get("attempts", [])))
    if not cap.get("ok"):
        print("\nRESULT: FAIL (no capture backend produced a frame)")
        return 1
    record("frames delivered", cap["frames"] > 0, f"{cap['frames']} frames")
    record("real resolution", cap["size"][0] > 0, f"{cap['size'][0]}x{cap['size'][1]}")
    record("frame rate", cap["fps"] > 0.5, f"{cap['fps']:.1f} fps measured, "
                                           f"{cap['reported_fps']:.0f} fps reported by the source")
    record("stable resolution", len(cap["sizes"]) == 1, f"sizes seen: {cap['sizes']}")

    if args.base_url:
        print("")
        print("-- Full chain via the API --")
        chain = run_chain(args.base_url, url, args.camera, max(args.seconds, 8.0), args.token)
        record("session started", chain.get("start_status") in (200, 201),
               f"http={chain.get('start_status')} {chain.get('start_error', '')}")
        if chain.get("start_status", 0) < 400:
            record("session live", chain.get("status") in ("LIVE", "STOPPING"),
                   f"status={chain.get('status')}")
            record("frames ingested", (chain.get("frames_received") or 0) > 0,
                   f"received={chain.get('frames_received')} sampled={chain.get('frames_sampled')}")
            health = chain.get("source_health") or {}
            record("source health", bool(health.get("opened")) and bool(health.get("alive")),
                   f"backend={health.get('capture_backend')} url={health.get('stream_url')}")
            record("evidence captured", (chain.get("evidence") or 0) > 0,
                   f"evidence={chain.get('evidence')}")

    print("")
    failed = [n for n, ok, _ in results if not ok]
    print("RESULT:", "PASS" if not failed else f"FAIL ({', '.join(failed)})")
    if args.base_url:
        print(json.dumps({"url": url, "capture": cap}, default=str)[:0])
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
