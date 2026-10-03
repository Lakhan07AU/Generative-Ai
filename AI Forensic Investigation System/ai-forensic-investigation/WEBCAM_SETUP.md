# Laptop Webcam Setup (`webcam` transport)

The `webcam` transport opens a **real local capture device** with
`cv2.VideoCapture(device_index)` and pushes frames into the existing live ingest
pipeline. It is the same implementation used by `droidcam_usb` - there is no
second capture path in the codebase:

```text
webcam            droidcam_usb
   \               /
    LocalOpenCVCameraSource        backend/app/live/webcam_camera.py
                |
                v
      runtime.ingest_frame(frame, timestamp)
                |
  FrameIngestion -> FrameSampler -> RollingFrameBuffer -> YOLO -> tracking
      -> events -> ForensicEvidence -> PostgreSQL + MinIO -> Qdrant -> VLM
```

`UsbCameraSource` (`app/live/usb_camera.py`) is a thin subclass that only changes
the transport name and reads `DROIDCAM_*` defaults, so existing API clients and
tests keep working unchanged.

---

## 1. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `WEBCAM_DEVICE_INDEX` | `0` | OpenCV capture index (0 is the usual integrated webcam, **not guaranteed**) |
| `WEBCAM_FPS` | `10` | Requested capture rate (frames/sec) |
| `WEBCAM_WIDTH` | `640` | Requested capture width |
| `WEBCAM_HEIGHT` | `480` | Requested capture height |
| `WEBCAM_STALE_SECONDS` | `5.0` | Seconds without a frame before the source reports `alive=false` |
| `WEBCAM_MAX_RESTARTS` | `3` | **Bounded** reconnect attempts (0 = none). Never an infinite loop |
| `WEBCAM_MAX_CONSECUTIVE_FAILURES` | `10` | Failed reads before a reconnect is attempted |

DroidCam keeps its own `DROIDCAM_*` equivalents.

---

## 2. Probing: device 0 is not assumed to exist

`cv2.VideoCapture(0)` frequently returns an object that reports `isOpened() == True`
for a device that does not exist, and only fails on the first `read()`. The source
therefore **reads one real frame inside `connect()`** before declaring the device
open, so a missing camera produces `HTTP 503` instead of a silent zero-frame session.

Probe the host first:

```bash
cd backend
python scripts/verify_webcam.py --probe          # lists indices 0..3 that deliver a frame
python scripts/verify_webcam.py --device 0 --seconds 10
```

Expected output:

```text
WEBCAM TEST
============

Device: 0
OpenCV: PASS
Camera opened: PASS
Frame capture: PASS
Resolution: PASS
FPS: PASS
Frame continuity: PASS
Camera release: PASS

RESULT: PASS
```

---

## 3. Docker cannot see your laptop camera

Docker Desktop's Linux VM does **not** pass `/dev/video*` (or a Windows capture
device) into containers. Inside a container:

```bash
docker exec forensic-backend python scripts/verify_webcam.py --probe
# RESULT: NO DEVICE
```

For a physically verified webcam run, start the backend **natively on the host**:

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
# point .env at host-reachable services, then:
alembic upgrade head
uvicorn app.main:app --reload
python scripts/verify_webcam.py --probe
python scripts/verify_live_webcam.py --device 0 --seconds 45
```

The full-pipeline script requires an authenticated demo user and creates its own
camera, so nothing has to be pre-created by hand.

---

## 4. Using it from the UI

`/live` → **Camera source** → *Laptop Webcam (real local camera)*, then set
**Camera device** (device index) and **FPS**, then *Start* / *Stop*.

The source list is explicit about what is real:

| Source | Label in UI | Real frames? |
|---|---|---|
| Phone over WebRTC | Phone WebRTC (real) | yes, from the phone |
| Laptop camera | Laptop Webcam (real) | yes, from the physical device |
| DroidCam / USB capture | USB / DroidCam (real) | yes, from the physical device |
| Synthetic feeder | Simulation (synthetic) | **no** - never evidence |
| Licensed demo clip | Demo Video (not evidence) | real video, **not** forensic evidence |

While a session runs the console shows `CONNECTED` / `DISCONNECTED`, frames read,
dropped frames, restarts, measured FPS, detection count, active tracks, event
count, evidence captured/indexed, VLM observation count and the real YOLO model +
device reported by the backend.

---

## 5. Health payload

```json
{
  "source": "webcam",
  "device_index": 0,
  "opened": true,
  "alive": true,
  "running": true,
  "frames_read": 100,
  "dropped_frames": 0,
  "restarts": 0,
  "last_frame_at": 1234567890,
  "error": null
}
```

On disconnect: `alive` goes `false` once no frame arrives for
`WEBCAM_STALE_SECONDS`, the capture thread attempts **at most**
`WEBCAM_MAX_RESTARTS` reconnects, then ends the session with a health `error` and
an audit entry. There is no infinite reconnect loop.

---

## 6. Verifying the whole chain

```bash
# device only
python scripts/verify_webcam.py --device 0 --seconds 10

# device -> ingest -> YOLO -> tracking -> events -> evidence -> PG -> MinIO -> Qdrant -> VLM
python scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 --device 0 --seconds 45

# everything, including the phase checks
python scripts/verify_final_system.py --base-url http://127.0.0.1:8000
```

`verify_live_webcam.py` never fabricates success: when the backend cannot open a
device it exits with `RESULT: FAIL` and prints the exact blocker.

---

## 7. Browser preview (why the screen used to stay black)

webrtc is the only transport with a native video track in the browser. For
webcam, droidcam_usb, ile and simulation the **backend** owns the
capture, so the console has no `MediaStream` to attach to a `<video>` element
and the surface renders black while detection keeps working.

The console therefore subscribes to:

``
GET /live/cameras/{camera_id}/stream.mjpg?token=<access_token>
Content-Type: multipart/x-mixed-replace; boundary=frame...
``

* Publishes the **exact frames pushed into detection**, so the picture and the
  bounding boxes can never disagree.
* JPEG encoding only runs while a browser is watching
  (`WEBCAM_PREVIEW_JPEG_QUALITY`, default 70), so a WebRTC session pays nothing.
* A slow client drops the oldest queued frame (queue cap 64) instead of
  back-pressuring the capture thread; the stream ends when the session stops.
* `409` for WebRTC (already has a video track) and for a stopped session;
  `401`/`403` use the same auth + role check as the other live endpoints. The
  token is a query parameter because an `<img>` cannot send an `Authorization`
  header.
* Regression tests: `tests/test_live_preview_stream.py` (11 tests) cover the
  encode-only-when-watched rule, the multipart framing, JPEG decode, queue
  bounding, session-end behaviour and the auth/role/conflict matrix.
