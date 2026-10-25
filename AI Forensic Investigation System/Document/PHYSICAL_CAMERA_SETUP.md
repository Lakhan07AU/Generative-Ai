# Physical Camera Setup Guide

Test the AI Forensic Investigation System with a real phone camera over a real
WebRTC connection (Phase 1 transport), against the FAST backend pipeline: real
frame ingestion -> YOLO -> tracking -> event detection -> optional VLM ->
evidence capture / RAG / investigation, all driven from the Live Camera page.

> **Status:** backend + WebRTC signaling verified by
> `backend/scripts/verify_physical_camera.py` (READINESS: PASS, SIGNALING: PASS).
> The actual phone-to-PC end-to-end test below is a **MANUAL** step and must be
> executed on a physical phone before the final `PHYSICAL CAMERA READY` verdict
> can be claimed.

---

## 1. Why this page / this transport

- The Live Camera page (`frontend/app/live/page.tsx`, route `/live`) is the
  phone-facing camera page. It reuses the Phase 1 WebRTC implementation
  (`backend/app/live/webrtc.py` + the `/live/cameras/{camera_id}/ws/signaling`
  WebSocket). No new transport was built.
- The phone's browser is the WebRTC **sender** (offers + sends media via
  `getUserMedia` + `RTCPeerConnection.addTrack`); the backend is the
  **receive-only** peer (`LiveWebRTCConnection`) that decodes frames as BGR and
  feeds the same live pipeline used by simulation tests.
- Real decoded frames are pushed to the ingestion pipeline exactly like file /
  simulation sources; nothing is mocked for the physical-device demo.

## 2. Network layout

```
Phone (browser)                PC / backend host
----------------             ----------------------
/  live  (HTTPS:3000)   <--  next dev TLS server     (frontend)
getUserMedia + RTCPeer     ws/wss signaling 8000      (backend)
```

- The phone must reach the **PC over your LAN** (same Wi-Fi). It can never use
  `127.0.0.1` / `localhost` (those point at the phone itself).
- WebRTC media (RTP/RTCP/UDP) flows peer-to-peer between browser and backend.
  Host candidates are exchanged over the signaling WebSocket; for the same-LAN
  demo no STUN/TURN is required (default `WEBRTC_ICE_SERVERS=[]`).
- `getUserMedia` requires a **secure context**: the phone must open the *frontend*
  over **HTTPS** (or `localhost`, which does not apply here).

## 3. Preflight checklist (PC)

| Check | Command / value |
| --- | --- |
| Backend running on all interfaces | `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| PC LAN IPv4 | `ipconfig` -> e.g. `10.121.240.164` (Wi-Fi adapter) |
| Frontend over HTTPS on LAN | `npm run dev:https` (see below), served on `0.0.0.0:3000` |
| Verify script green | `python scripts/verify_physical_camera.py --base-url http://127.0.0.1:8000` |
| Camera exists | `/live` camera selector lists e.g. `Smoke Mobile Cam` (MOBILE, id=1) |
| Login works from phone | demo `demo.investigation@forensics-demo.com` / `demo-investigation-2026` |

### 3.1 HTTPS for the phone (required)

`getUserMedia` requires a **secure context**. When the phone opens the page via a
LAN IP (not `localhost`), both the frontend **and** the backend must be served
over TLS — an HTTPS page blocks plain `ws://` mixed content.

1. Generate a cert for the PC's LAN IP (no openssl needed, uses `cryptography`):
   ```bash
   # from frontend/
   python scripts/make_dev_cert.py --ip 10.121.240.164
   # writes frontend/scripts/cert.pem + key.pem
   ```
2. Frontend over HTTPS (custom-server wrapper, verified):
   ```bash
   # from frontend/
   npm run build
   HTTPS_CERT_FILE=scripts/cert.pem HTTPS_KEY_FILE=scripts/key.pem npm run dev:https
   # -> https://0.0.0.0:3000 (phone: https://10.121.240.164:3000/live)
   ```
3. Backend over TLS too (uvicorn's built-in SSL flags, verified):
   ```bash
   # from backend/; 8443 picked to keep 8000 free for http verification runs
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8443 \
     --ssl-keyfile "..\frontend\scripts\key.pem" --ssl-certfile "..\frontend\scripts\cert.pem"
   # -> wss://... signaling; REST at https://10.121.240.164:8443
   ```
4. Point the frontend at the TLS backend (importantly `NEXT_PUBLIC_API_BASE_URL`
   drives the `wss://` signaling origin too):
   ```bash
   # frontend/.env
   NEXT_PUBLIC_API_BASE_URL=https://10.121.240.164:8443
   ```
5. Trusting the cert: on the PC (so desktop browsers stop warning) or phone
   (one-time, or accept the "not private" warning and proceed).

> Note: the self-signed cert is a dev-only artifact. In a real deployment use a
> proper CA / Let's Encrypt; this file is only for the LAN demo.

### 3.2 Backend env needed for the LAN

```bash
# backend/.env (or environment):
BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://10.121.240.164:3000
WEBRTC_ICE_SERVERS=[]          # default; omit for same-LAN
```

- Restart uvicorn after changing these (`BACKEND_CORS_ORIGINS` and
  `WEBRTC_ICE_SERVERS` are read at startup).
- Never use `BACKEND_CORS_ORIGINS=*`.

### 3.3 Windows Firewall (allow only what is required)

Do **not** disable the firewall. Add narrow inbound rules:

```powershell
New-NetFirewallRule -DisplayName "Forensics Backend TCP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
New-NetFirewallRule -DisplayName "Forensics WebRTC UDP" -Direction Inbound -Protocol UDP -LocalPort 49152-65535 -Action Allow
```

(Only needed if the phone cannot reach the backend — UDP rule covers WebRTC
media ports. Tighten to the PC's LAN subnet if you can.)

## 4. Phone setup

1. Same Wi-Fi as the PC.
2. Open the **HTTPS frontend URL** on the phone:
   `https://10.121.240.164:3000/live`.
3. Accept the self-signed certificate warning (created by `mkcert -install` on
   the PC only if the CA is also trusted on the phone; otherwise tap
   "Advanced -> proceed").
4. Log in with `demo.investigation@forensics-demo.com` /
   `demo-investigation-2026`.
5. Live Camera page -> select `Smoke Mobile Cam` -> camera permissions prompt ->
   **Allow**. Rear camera is the default; use the flip control for front.
6. Press **Start**. The status should progress: `connecting` -> `connected`
   (WebRTC ICE) -> frames flowing -> detections/tracking appearing in real time.

## 5. Desktop verification steps (on the PC)

Run `backend/scripts/verify_physical_camera.py` first; it must show
`WebRTC signaling : PASS`. Then with the phone streaming:

- Live session list / API: `GET /live/cameras/{camera_id}/session` ;
  `GET /detections/live/{session_id}`.
- Evidence capture: run the Live Evidence capture flow from the Live page
  button; confirm a clip/frame is stored in MinIO and indexed (search in
  `/search`).
- Optional VLM: with `LLM_PROVIDER` set to a vision-capable provider, request an
  observation; confirm keyframes are described.
- Create an investigation from the live events and confirm the generated report
  includes the real event facts (not simulation).

## 6. Demo scenario script

1. Phone logs in and starts the camera (3-5 s to `connected`; frames at ~30 fps
   ingest, sampling ~5 fps into the buffer).
2. Walk in front of the rear camera, hold still ~2-3 s at various spots; verify
   YOLO boxes overlay on the Live page and tracking IDs appear.
3. Trigger events (cross line, linger, enter/exit) and confirm events land on the
   event feed with real timestamps.
4. Capture 1-2 evidence clips; confirm thumbnail + frames appear in the UI, and
   the investigation timeline shows the captured evidence.
5. Switch front/rear camera mid-stream; confirm the stream does not drop.
6. Turn the phone off Wi-Fi or tap **Stop**; confirm the backend marks the
   session disconnected and cleanup runs, and the status bar reflects it.

## 7. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `getUserMedia` fails / "Camera access requires a secure context" | Phone URL must be **HTTPS** (or localhost). See 3.1. |
| Phone can't open the page | Different network / firewall / HTTPS cert. Use the PC LAN IP, allow TCP 3000 + 8000 inbound, verify cert. |
| Status stuck on `connecting` | ICE could not complete. Verify signaling WS uses `wss://` (HTTPS frontend), `WEBRTC_ICE_SERVERS` matches your network, UDP rule present; check PC firewall. |
| Detections empty | Confirm the ingestion pipeline is on (backend logs; `Live Status` shows frame count increasing). |
| Backend CORS error in phone console | `BACKEND_CORS_ORIGINS` missing the phone's origin (`https://10.121.240.164:3000`). |
| Backend not reachable on 0.0.0.0 | Run uvicorn with `--host 0.0.0.0`; `netstat -ano | findstr :8000` while phone connects. |

## 8. Auto-verification summary (last run at time of writing)

```
Backend readiness : PASS   (/health, login, 19 cameras reachable)
WebRTC signaling  : PASS   (offer/answer + ICE loopback reached 'connected')
Physical camera   : MANUAL TEST REQUIRED
```

Run `python scripts/verify_physical_camera.py --base-url http://127.0.0.1:8000`
from `backend/` to reproduce.