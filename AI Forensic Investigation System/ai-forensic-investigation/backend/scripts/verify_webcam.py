"""Laptop webcam device test - opens the REAL OpenCV capture device.

No simulation, no demo video, no synthetic frames. If the device cannot be
opened the script reports FAIL; it never claims a webcam works without actually
opening it and reading pixels from it.

Usage:
    python scripts/verify_webcam.py --device 0 --seconds 10
    python scripts/verify_webcam.py --probe          # probe indices 0..3
    python scripts/verify_webcam.py --device 2 --fps 15 --width 1280 --height 720

Exit code 0 = RESULT: PASS, 1 = RESULT: FAIL.
"""

from __future__ import annotations

import argparse
import sys
import time

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, bool(ok), detail))
    print(f"{name + ':':<22}{'PASS' if ok else 'FAIL'}" + (f" ({detail})" if detail else ""))
    return bool(ok)


def probe(max_index: int = 3) -> dict[int, dict]:
    """Open indices 0..max_index and report which really deliver frames."""
    import cv2

    found: dict[int, dict] = {}
    for index in range(max_index + 1):
        cap = cv2.VideoCapture(index)
        info: dict = {"opened": False, "frames": 0, "size": None, "fps": None}
        try:
            if cap is not None and cap.isOpened():
                info["opened"] = True
                ok, frame = cap.read()
                if ok and frame is not None:
                    info["frames"] = 1
                    info["size"] = (int(frame.shape[1]), int(frame.shape[0]))
                    info["fps"] = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        finally:
            if cap is not None:
                cap.release()
        if info["frames"]:
            found[index] = info
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Laptop webcam device verification")
    parser.add_argument("--device", type=int, default=None,
                        help="OpenCV capture device index (default: WEBCAM_DEVICE_INDEX or 0)")
    parser.add_argument("--seconds", type=float, default=10.0, help="capture duration")
    parser.add_argument("--fps", type=float, default=None, help="requested capture fps")
    parser.add_argument("--width", type=int, default=None, help="requested width")
    parser.add_argument("--height", type=int, default=None, help="requested height")
    parser.add_argument("--probe", action="store_true",
                        help="probe device indices 0..3 and exit")
    args = parser.parse_args()

    if args.probe:
        print("\nWEBCAM PROBE (indices 0..3)")
        print("=" * 40)
        try:
            import cv2
        except Exception as exc:  # noqa: BLE001
            print(f"OpenCV import: FAIL ({exc})")
            return 1
        found = probe(3)
        if found:
            for idx, info in found.items():
                print(f"  device {idx}: {info['size'][0]}x{info['size'][1]} @ {info['fps']} fps")
            print("RESULT: DEVICES FOUND")
            return 0
        print("  no capture device produced a frame on indices 0..3")
        print("RESULT: NO DEVICE")
        return 1

    try:
        from app.core.config import settings

        device = args.device if args.device is not None else int(settings.WEBCAM_DEVICE_INDEX)
        fps = args.fps if args.fps is not None else float(settings.WEBCAM_FPS)
        width = args.width if args.width is not None else int(settings.WEBCAM_WIDTH)
        height = args.height if args.height is not None else int(settings.WEBCAM_HEIGHT)
    except Exception:  # noqa: BLE001 - allow running outside the app package
        device = 0 if args.device is None else args.device
        fps = args.fps or 10.0
        width = args.width or 640
        height = args.height or 480

    print("\nWEBCAM TEST")
    print("============")
    print(f"Device: {device}")

    try:
        import cv2

        record("OpenCV", True, getattr(cv2, "__version__", "unknown"))
    except Exception as exc:  # noqa: BLE001
        record("OpenCV", False, str(exc))
        print("\nRESULT: FAIL")
        return 1

    cap = cv2.VideoCapture(device)
    opened = cap is not None and cap.isOpened()
    record("Camera opened", opened, f"index={device}")
    if not opened:
        if cap is not None:
            cap.release()
        print("  hint: run with --probe to list available capture devices")
        print("\nRESULT: FAIL")
        return 1

    if fps and fps > 0:
        cap.set(cv2.CAP_PROP_FPS, float(fps))
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))

    frames = 0
    dropped = 0
    first_size = None
    monotonic = True
    last_ts = 0.0
    gaps: list[float] = []
    expected_period = 1.0 / fps if fps and fps > 0 else 0.0
    started = time.time()
    deadline = started + args.seconds

    while time.time() < deadline:
        ok, frame = cap.read()
        now = time.time()
        if not ok or frame is None:
            dropped += 1
            continue
        if frames == 0:
            first_size = (int(frame.shape[1]), int(frame.shape[0]))
        if now < last_ts:
            monotonic = False
        if last_ts and expected_period:
            gap = now - last_ts
            # A gap far beyond 3 frame periods indicates a dropped capture.
            if gap > expected_period * 3:
                gaps.append(gap)
        last_ts = now
        frames += 1
        time.sleep(0.001)

    elapsed = time.time() - started
    measured_fps = frames / elapsed if elapsed > 0 else 0.0

    record("Frame capture", frames > 0, f"{frames} frames in {elapsed:.1f}s")
    record("Resolution", bool(first_size), f"{first_size[0]}x{first_size[1]}" if first_size else "no frame")
    record("FPS", measured_fps > 0, f"measured={measured_fps:.2f} target={fps}")
    record("Frame continuity", monotonic, f"{dropped} failed reads, {len(gaps)} long gaps")

    cap.release()
    cap = None
    try:
        import gc

        gc.collect()
    except Exception:  # noqa: BLE001
        pass
    # Re-open probe to prove the device was released cleanly.
    released_ok = True
    try:
        cap2 = cv2.VideoCapture(device)
        released_ok = cap2 is not None and cap2.isOpened()
        if cap2 is not None:
            cap2.release()
    except Exception:  # noqa: BLE001
        released_ok = False
    record("Camera release", released_ok, "device re-openable after release")

    failed = [name for name, ok, _ in CHECKS if not ok]
    print()
    if failed:
        print(f"RESULT: FAIL ({', '.join(failed)})")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
