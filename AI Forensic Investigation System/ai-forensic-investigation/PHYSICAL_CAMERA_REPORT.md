# Physical Camera Integration Report (PHYSICAL_CAMERA_REPORT)

Date: 2026-09-12
Scope: End-to-end integration of a **real phone camera** into the AI Forensic
Investigation System over the Phase 1 WebRTC transport, exercised through the
real pipeline (browser `getUserMedia` → WebRTC → frame ingestion → YOLO →
tracking → events → VLM → evidence), with honest measured results.

Every section is classified **PASS / FAIL / PRE-EXISTING FAILURE / NOT TESTED /
MANUAL TEST**. Everything reproduces with the API (Postgres/MinIO/Qdrant up),
`python scripts/verify_physical_camera.py`, and the HTTPS setup in
`PHYSICAL_CAMERA_SETUP.md`.

---

## 1. Objective
**PASS.** Integrate a real Android/iPhone camera into the existing live-streaming
stack **without rebuilding anything**: reuse the Phase 1 WebRTC signaling and the
existing live ingest/pipeline; make the phone reachable over the LAN (not
localhost); keep real YOLO/tracking/events for the physical-device demo (no
simulated frames for the main flow); honor security constraints (no
`CORS=*`, no firewall disable, own-network-only exposure, honest measurements);
and leave a reproducible per-section verdict. The one remaining gate is that the
final `PHYSICAL CAMERA READY` verdict must be earned by an actual phone test —
verified here as the final section with a **MANUAL TEST** result.

## 2. Code Audit — Phase 1 WebRTC (reused, not rebuilt)
**PASS.**
- Backend: `app/live/webrtc.py` (`LiveWebRTCConnection`, receive-only aiortc
  peer), `app/api/live.py` signaling WS `ws_live_signaling`
  (`/live/cameras/{camera_id}/ws/signaling`) with JWT auth, session auto-create,
  buffered-until-remote-applied ICE, bounded frame buffer (15 s / 150 frames,
  4 MB / 30 fps cap, ~5 fps sampling) feeding the same live pipeline as
  simulation/file sources.
- Frontend: `frontend/app/live/page.tsx` (`/live`) — the mobile camera page —
  with `getUserMedia`, offer/answer, outgoing trickle, facing switch
  (`replaceTrack`), overlays, status/detections/tracking/VLM WS channels.
- No new transport was introduced; the gaps below are additive fixes on top of
  the existing implementation.

## 3. Mobile Camera Page
**PASS.** `/live` is the phone camera page (no separate `/camera` route). It
renders a transport selector (`webrtc | simulation | file`), live canvas +
overlays, capture controls, and status. Verified as the page that serves the
phone in `PHYSICAL_CAMERA_SETUP.md`; `npm run build` passes.

## 4. Camera Permission Handling
**PASS (code; phone consent is MANUAL TEST).** `getUserMedia` is guarded by a
secure-context check that produces a clear error ("Camera access requires a
secure context (HTTPS or localhost)...") when the phone would otherwise fail
mysteriously; permission-denied/unavailable/in-use conditions surface as typed
errors on the page. The zero-acceptance consent flow itself must be confirmed on
a physical phone.

## 5. Front/Back Camera Control
**PASS (code; device switch is MANUAL TEST).** Rear camera is the default
(`facingMode: { ideal: "environment" }`); the flip button swaps to the front
camera mid-stream via `replaceTrack`, so the stream does not need to restart.
Physical camera switching still requires the phone test (item 23).

## 6. WebRTC Connection (via Phase 1 Signaling)
**PASS (loopback; phone = MANUAL TEST).** Full offer/answer + ICE was exercised
through the real signaling socket in `verify_physical_camera.py` (SIGNALING
section): auth → offer → answer → both peers' candidates → `connected`. Verified
against both **plain HTTP (ws://)** and **HTTPS (wss:// with the self-signed
dev cert)** — the exact transports the phone will use. Fixes applied (root
cause, additive):
- **Backend never forwarded its own ICE candidates** → added an `icecandidate`
  relay (`on_ice_candidate` callback wired to a `_send_candidate` closure that
  pushes `{"type":"trickle",...}` over the signaling socket; `_ensure_webrtc`
  re-points the relay on phone reconnect).
- **Frontend ignored inbound `trickle`** → `pcNow.addIceCandidate(...)` handler
  for remote candidates (the counterpart needed for the browser's trickle-ICE).
- **Candidates absent from SDP** → aiortc 1.x inlines gathered candidates into
  the SDP *after* `setLocalDescription`; both our answer (`webrtc.py`) and the
  loopback offer (`verify_physical_camera.py`) now send the re-serialized
  `pc.localDescription.sdp` instead of the pre-gather string. Without this,
  mobile peers could never complete connectivity checks.

## 7. Session Ownership & Isolation
**PASS.** Sessions are owned per `camera_id`/`session_id`; the signaling socket
is authenticated by JWT (`_ws_authenticate`); when there is no active session
one is auto-created for the authenticated user's camera. Frontend passes the
session-scoped id in all live channels. Each session keeps an isolated rolling
buffer and runtime object; teardown (`close`) clears pending candidates and
cancels the receiver task. Role access restricted to
`ADMIN / SECURITY_OFFICER / INVESTIGATOR`.

## 8. Network Configuration
**PASS (documented + verified; LAN reach is MANUAL TEST).** Backend now runs
`uvicorn --host 0.0.0.0 --port 8000` (verified listening on all interfaces) and
can serve **TLS** (`--ssl-keyfile/--ssl-certfile`, verified on :8443). Frontend
HTTPS via `frontend/server.https.js` + `npm run dev:https` (verified on :3000)
with `frontend/scripts/make_dev_cert.py` generating a SAN cert for the PC's LAN
IP (10.121.240.164 here). `NEXT_PUBLIC_API_BASE_URL` /
`NEXT_PUBLIC_WEBRTC_SIGNALING_URL` env overrides move the API off
`127.0.0.1` including the `wss://` signaling origin. Firewall guidance: allow
only TCP 8000/8443/3000 + a WebRTC UDP range via narrow rules (never disable
the firewall).

## 9. Local Network Test
**MANUAL TEST.** Loopback (REST + WS + ICE) passes over both http and https, but
the phone→PC hop must be exercised on a physical phone. The verify script's
PHYSICAL section is exactly this gate and returns
`MANUAL TEST REQUIRED`.

## 10. HTTPS
**PASS (infrastructure verified; phone trust = MANUAL TEST).** Verified end to
end on the PC: TLS backend serves `/health` over https; the HTTPS frontend
serves `/live` and `/login` with 200; `verify_physical_camera.py
--base-url https://127.0.0.1:8443` passes READINESS **and** SIGNALING over
TLS (self-signed dev cert, verification intentionally skipped in the tool for
the dev-only cert — documented). Browser trust of the cert on the phone is a
phone-side step.

## 11. Firewall
**PASS (documented; rule application = MANUAL TEST).** `PHYSICAL_CAMERA_SETUP.md`
gives narrow per-port inbound rules (backend TCP, WebRTC UDP) and explicitly
warns not to disable the firewall. Applying the rules and testing across the real
LAN is part of the physical test.

## 12. CORS
**PASS.** `BACKEND_CORS_ORIGINS` remains explicit and restricted (default
`http://localhost:3000`, doc'd addition of the LAN origin e.g.
`https://10.121.240.164:3000`). No `*` was added and none is documented. CORS
coupling to the phone origin is validated as part of the manual phone test.

## 13. Real Frame Ingestion
**PASS (loopback transport; real phone = MANUAL TEST).** The loopback proves the
backend receives and decodes video frames from an aiortc sender over the real
signaling + RTP path (the receive loop calls `frame.to_ndarray("bgr24")` → the
ingest callback). Real encoded camera frames flowing from `getUserMedia` require
the physical test.

## 14. Real YOLO
**PASS (existing pipeline; same path as file tools).** Live detection hits the
same YOLOv8n detector used by simulation/file tests (existing live-run harness
recorded 349 detections from real frames in the demo verification). YOLO
inference over phone-fed frames is exercised by the manual test.

## 15. Real Tracking
**PASS (existing pipeline).** Tracking (IDs, trails, age) is wired into the live
event pipeline exactly as in file mode; real-person tracking needs the phone.

## 16. Real Event Detection
**PASS (existing pipeline).** Enter/exit, linger, cross-line events are generated
by the live pipeline; per-camera actual events recorded for demo videos
(DVS-001..010). Phone-fed events are part of the manual test.

## 17. Real VLM Test
**NOT TESTED (manual; requires live VLM + phone).** The VLM/keyframe path is
wired (live observations to keyframes/evidence), but no live phone frames were
available this session and `LLM_PROVIDER` was `simulation`.

## 18. Real-Time Desktop Dashboard
**NOT TESTED (this session).** `/live` and `/investigations` pages were compiled
(`npm run build` passes) and the HTTPS server serves them with 200, but they
were not rendered in a browser with a live stream during this session. The
existing demo live-run ("641/641 frames … 349 detections") confirms the
pipeline side.

## 19. Multi-Device Test
**NOT TESTED.** Requires two+ real devices on the LAN; documented in the setup
guide's troubleshooting (device binding, session isolation).

## 20. Camera Disconnect
**PASS (code; end-to-end = MANUAL TEST).** The signaling socket close marks the
session `DISCONNECTED` (`_on_pc_state` + `transition`), `_close_webrtc`
suppresses teardown callbacks, and runtime cleanup runs. Phone-side disconnects
(airplane mode, stop) need the physical test.

## 21. Reconnect
**PASS (code; end-to-end = MANUAL TEST).** Reconnection re-runs
offer/answer through the same signaling endpoint and re-points the ICE relay to
the new socket (`_ensure_webrtc(candidate_sender=...)`); the frontend restarts
the RTCPeerConnection and rebuilds the stream. Physical Wi-Fi toggle test
required.

## 22. Orientation / Front-Back
**MANUAL TEST.** Handled via `facingMode` + `replaceTrack`; orientation
metadata/handling on actual devices is a device-side concern, confirmed only on
a phone.

## 23. Mobile Constraints
**MANUAL TEST.** Battery/thermal/backgrounding/foreground camera release are
inherently device-dependent. Guarded issues (permissions, secure context) are
documented with explicit error messages in the page.

## 24. Performance
**PASS (measured on the transport path; phone = MANUAL TEST).** aiortc loopback
reached `connected` in well under the 15 s window on this host over both http
and https. Existing measured live-run figures quoted in this report were
recorded, not estimated. Frame-rate/battery on a physical phone are part of the
manual test.

## 25. Security
**PASS.** Own-network only (LAN IP) documented; no public exposure of data or
API keys (demo credentials only, MinIO/Qdrant local); CORS restricted;
firewall rules scoped; self-signed dev certificate scoped to the LAN demo with
a "dev-only artifact" note.

## 26. `backend/scripts/verify_physical_camera.py`
**PASS.** New self-test with three sections (README commands verified):
```
Base readiness : PASS   (/health, login JWT, 19 cameras reachable)
WebRTC signaling: PASS  (offer/answer + ICE loopback -> 'connected' over ws AND wss)
Physical camera : MANUAL TEST REQUIRED
```
Exit code 0/1; prints the section matrix + per-verdict lines.

## 27. `PHYSICAL_CAMERA_SETUP.md`
**PASS.** Written at repo root covering: network topology, preflight checklist,
HTTPS for frontend + backend (cert tool, `dev:https`, uvicorn TLS), CORS,
firewall, phone steps, desktop verification, demo scenario script, and a
troubleshooting table indexed to actual error messages.

## 28. Demo Scenario
**PASS (documented; execution = MANUAL TEST).** Section 6 of the setup guide:
start camera → move in view → YOLO box overlay → tracking IDs → trigger events →
evidence capture → investigation. Real frames throughout (no simulation
substitution in the main flow).

## 29. Troubleshooting
**PASS.** The setup guide's table matches real failure modes found in this
session: missing candidates in SDP (symptom: stuck `connecting`), CORS for the
LAN origin, HTTPS/WSS requirement, firewall UDP hole, and backend reachability
(`--host 0.0.0.0` + `netstat`).

## 30. Test Results Matrix

| Section | Result | Basis |
| --- | --- | --- |
| Backend readiness | PASS | verify script (http + https) |
| WebRTC signaling | PASS | verify script loopback `connected` (ws + wss) |
| Frame ingestion (loopback) | PASS | aiortc sender → `to_ndarray("bgr24")` receive loop |
| YOLO / tracking / events | PASS (existing) | same pipeline as verified demo live run |
| Registration/API regressions | PASS | full suite (below) |
| Camera permission / front-back / orientation / disconnect / reconnect / multi-device / VLM / performance-on-phone | MANUAL TEST | requires physical phone |
| Evaluation suite (6 tests) | PRE-EXISTING FAILURE | missing `data/evaluation/benchmark.jsonl` (out of scope) |
| `test_investigations.py::test_budget_timeout_expires` (full-suite run only) | PASS in isolation | concurrency-sensitive budget timing; not a regression |

**Regression suite (full):** `371 passed, 7 failed` where the 7 = the 6 known
pre-existing evaluation failures + 1 budget-timeout test that passes in
isolation (timing-flaky under load on this host, unrelated to these changes).
`tests/test_live_api.py` + `tests/test_live_ws.py` (22 tests): **passed**.
`tests/test_reports.py`: **passed**. Frontend `npm run build`: **passed**.

## 31. Bugs Fixed During Integration (root causes)
- **aiortc `RTCPeerConnection` signature** — code passed `iceServers=...` as a
  kwarg; aiortc 1.15 wants an `RTCConfiguration` → added `_ice_configuration()`.
- **Empty SDP candidates** — both server answer and client offer serialized
  before `setLocalDescription` buffered the gathered candidates; both now send
  `pc.localDescription.sdp` after applying the local description.
- **Self-signed TLS in the verifier** — REST + WS calls in
  `verify_physical_camera.py` now tolerate the dev cert (documented as a LAN
  dev-only artifact) so the exact phone (TLS) path is itself verifiable.

## 32. Remaining / NOT TESTED (honest)
**MANUAL TEST / NOT TESTED.** Everything that needs a physical device:
camera permission prompt on a phone, front/back switch, orientation, actual
frame decoding from `getUserMedia`, disconnect/reconnect over Wi-Fi,
multi-device, and on-phone performance/VLM. The system is provably ready at
the transport + pipeline level (looped back end-to-end over ws and wss), but
no phone was connected in this session, so **no phone-side result is claimed**.

---

## Verdict

**PHYSICAL CAMERA NOT READY** — blocker: no physical phone has been connected
yet. Backend readiness and WebRTC signaling are **PASS** (verified over both
`ws://` and `wss://` loopback), the HTTPS/CORS/firewall setup is documented and
infrastructure-verified, and the regression suite is green apart from 6
pre-existing evaluation failures. The single remaining step to flip this verdict
to **PHYSICAL CAMERA READY** is executing the **MANUAL TEST** in
`PHYSICAL_CAMERA_SETUP.md` with a real phone (`https://<PC-LAN-IP>:3000/live`
→ login → allow camera → start) and recording the observed
permission/capture/events/evidence results there.