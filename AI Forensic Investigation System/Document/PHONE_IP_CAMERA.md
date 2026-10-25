# Phone IP Camera (transport `ipcam`)

Use a phone as a live forensic camera source. The phone serves a video stream
over the local network; the backend pulls those frames and feeds them into
**exactly the same** pipeline used by the laptop webcam and USB/DroidCam:

```
phone (IP-camera app) --HTTP/RTSP--> LocalOpenCVCameraSource --OpenCV--> ingest
   -> sampling -> rolling buffer -> YOLO -> tracking -> events
   -> ForensicEvidence -> PostgreSQL + MinIO (sha256) -> Qdrant -> VLM
```

`ipcam` is a thin subclass of the existing capture class
(`backend/app/live/webcam_camera.py`). There is no second detection, tracking,
evidence or audit path: only the capture target differs (a URL instead of a
device index), which is why behaviour, provenance and evidence semantics are
identical to `webcam`.

---

## 1. On the phone

Any IP-camera app works. With Android **"IP Webcam"** (the verified setup):

1. Install and open the app; the screen shows an address like
   `http://192.168.1.42:8080/`.
2. **Keep the app in the foreground.** When the app is backgrounded or the
   screen sleeps it stops its HTTP server and the port stops accepting
   connections (symptom: `ConnectionRefusedError` while ping still answers).
3. Start the server if the app asks you to.

The phone and the backend must be on the same network, and the host firewall
must allow inbound connections on the chosen port.

---

## 2. Endpoints

| What | URL | Notes |
|---|---|---|
| Web UI (not a stream) | `http://<phone-ip>:8080/` | Status page, battery, etc. |
| **MJPEG stream (use this)** | `http://<phone-ip>:8080/video` | Verified: 1920x1080 @ ~30 fps |
| Still image | `http://<phone-ip>:8080/photo.jpg` | Single JPEG snapshot |
| H.264 | `http://<phone-ip>:8080/h264` | Usually needs a player, not OpenCV |
| RTSP (some apps) | `rtsp://<phone-ip>:554/...` | Also supported |

Open `http://<phone-ip>:8080/video` in a browser: if a live picture appears,
the stream is serving. `/video` is the endpoint to give the backend.

---

## 3. Configuration

Defaults live in `.env` (copy from `.env.example`):

```dotenv
IPCAM_STREAM_URL=http://10.5.176.115:8080/video
IPCAM_FPS=10.0            # analysis rate fed to YOLO
IPCAM_WIDTH=1280
IPCAM_HEIGHT=720
IPCAM_STALE_SECONDS=5.0
IPCAM_MAX_RESTARTS=3
IPCAM_CAPTURE_BACKENDS=   # empty = ffmpeg,any,gstreamer
```

`IPCAM_STREAM_URL` is only a default: a URL passed per session (or typed in
the UI) overrides it. If neither is set, the start request fails with
`IP camera unavailable: ipcam transport requires a stream URL` — it never
silently falls back to a local device.

If a URL embeds credentials (`http://user:pass@phone:8080/video`), any
password is replaced with `***` in health output, logs and error messages.

---

## 4. Using the UI

1. Create/select a camera, open **Live**.
2. Source: **Phone IP camera (real network stream)**.
3. Stream URL: `http://10.5.176.115:8080/video` (pre-filled from
   `IPCAM_STREAM_URL`).
4. Set FPS (10 is a good analysis rate) and press Start.

The browser preview is served by the backend at
`/live/cameras/{camera_id}/stream.mjpg`, so the picture you see is the exact
stream being analysed — the browser does not open the phone a second time.

If the phone cannot be reached, the start request returns **HTTP 503** with the
underlying reason. No synthetic frames are ever substituted.

---

## 5. Verification

Device-level check (no backend needed, proves the stream is real):

```bash
cd backend
python scripts/verify_ipcam.py --url http://10.5.176.115:8080/video --seconds 6
```

It reports URL reachability, which capture backend delivered pixels, the real
resolution, the measured frame rate and whether the resolution stayed stable.

Full forensic chain (YOLO, tracking, events, evidence, MinIO, Qdrant):

```bash
python scripts/verify_live_webcam.py --base-url http://127.0.0.1:8000 \
    --stream-url http://10.5.176.115:8080/video --seconds 60
```

Exit code `0` = `RESULT: PASS`. VLM stays `NOT TESTED` unless a provider is
configured; that alone does not change the capture result.

---

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionRefusedError`, ping works | App server stopped | Reopen the app, keep it foregrounded, disable screen sleep |
| `403 Forbidden` in browser | App password set | Use the credentials in the URL, or remove the app password |
| `not opened` / no frame | Wrong endpoint | Use `/video` (MJPEG) or an RTSP URL, not `/` |
| Intermittent `restarts` | Wi-Fi loss / phone sleep | Keep the app open; improve signal; raise `IPCAM_MAX_RESTARTS` |
| `cannot open stream URL` from the container only | Firewall blocks Docker/VM traffic | Allow the port for the host and the Docker network |
| Address changed | DHCP lease | Read the current address from the app |

---

## 7. Guarantees

* A frame is read during `connect()`; a source that cannot deliver pixels is
  rejected, so "live" always means real frames.
* Backend order for URLs is `ffmpeg, any, gstreamer` — DirectShow/MSMF are
  meaningless for network streams. Override with `IPCAM_CAPTURE_BACKENDS`.
* Capture is a daemon thread; a dead stream is retried a bounded number of
  times and then ends the session cleanly (never an infinite reconnect loop).
* Evidence provenance is identical to `webcam`: sha256, storage path, frame
  sequence, timestamps, event and track IDs.
