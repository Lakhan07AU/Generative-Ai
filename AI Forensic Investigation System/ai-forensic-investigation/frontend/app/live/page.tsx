"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Camera as CameraIcon,
  Video,
  VideoOff,
  Radio,
  SwitchCamera,
  RefreshCw,
  Smartphone,
  Loader2,
  AlertTriangle,
  Eye,
  Sparkles,
  Search,
  Image as ImageIcon,
  Fingerprint,
} from "lucide-react";
import {
  api,
  getToken,
  wsUrl,
  API_URL,
  Camera,
  CameraSession,
  LiveStatus,
  LiveStatusEvent,
  LiveDetectionFrame,
  LiveDetectionMetrics,
  LiveDetectionStatusEvent,
  TrackUpdate,
  TrackingEvent,
  TrackingMetricsOut,
  TrackingStatusEvent,
  VlmObservation,
  VlmStatusMessage,
  VlmRequestMessage,
  VlmErrorMessage,
  VlmMetricsMessage,
  VlmKeepaliveMessage,
  LiveEvidence,
  LiveEvidenceDetail,
  EvidenceSearchHit,
  DemoVideoAsset,
  ApiError,
} from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";

const LIVE_ROLES_OK = ["ADMIN", "SECURITY_OFFICER", "INVESTIGATOR"];

function statusVariant(status: string): "success" | "warning" | "danger" | "muted" {
  const s = (status || "").toUpperCase();
  if (s === "LIVE") return "success";
  if (s === "ERROR") return "danger";
  if (s === "OFFLINE" || s === "COMPLETED" || s === "DISCONNECTED") return "muted";
  return "warning";
}

function evidenceTypeVariant(
  type: string
): "success" | "warning" | "danger" | "muted" {
  const t = (type || "").toUpperCase();
  if (t === "VLM_OBSERVATION") return "success";
  if (t === "TRACK_EVENT") return "warning";
  if (t === "FRAME") return "muted";
  return "warning";
}

function indexVariant(status: string): "success" | "warning" | "danger" | "muted" {
  const s = (status || "").toUpperCase();
  if (s === "INDEXED") return "success";
  if (s === "FAILED") return "danger";
  if (s === "INDEXING" || s === "PENDING") return "warning";
  return "muted";
}

type LiveTransport = "webrtc" | "webcam" | "droidcam_usb" | "ipcam" | "simulation" | "file";

/** Human-readable, unambiguous camera-source labels (never call simulation "real"). */
const SOURCE_LABEL: Record<string, string> = {
  webcam: "Laptop Webcam (real)",
  droidcam_usb: "USB / DroidCam (real)",
  ipcam: "Phone IP Camera (real network stream)",
  webrtc: "Phone WebRTC (real)",
  simulation: "Simulation (synthetic)",
  file: "Demo Video (not evidence)",
};

function LiveCounters({ status }: { status: LiveStatus | null }) {
  const health = (status?.source_health ?? null) as Record<string, unknown> | null;
  const startedAt = status?.started_at ? Date.parse(status.started_at) : NaN;
  const lastFrameAt = typeof health?.last_frame_at === "number" ? (health.last_frame_at as number) : NaN;
  const seconds =
    Number.isFinite(startedAt) && Number.isFinite(lastFrameAt) && lastFrameAt > startedAt / 1000
      ? Math.max(lastFrameAt - startedAt / 1000, 0.001)
      : 0;
  const fps = seconds > 0 ? (status?.frames_received ?? 0) / seconds : 0;
  const connected = Boolean(health?.opened) && Boolean(health?.alive);
  const metrics = (status?.detection_metrics ?? {}) as Record<string, unknown>;

  const cells: Array<[string, string, string?]> = [
    ["Connection", connected ? "CONNECTED" : health ? "DISCONNECTED" : "—", connected ? "text-emerald-700" : "text-amber-700"],
    ["Live", status?.active ? "LIVE" : status ? "STOPPED" : "—", status?.active ? "text-emerald-700" : "text-slate-500"],
    ["Frames", String(health?.frames_read ?? status?.frames_received ?? 0)],
    ["Dropped", String(health?.dropped_frames ?? 0)],
    ["Restarts", String(health?.restarts ?? 0)],
    ["FPS", fps > 0 ? fps.toFixed(1) : "—"],
    ["Detection count", String(status?.detection_recent_count ?? 0)],
    ["Track count", String(status?.active_tracks ?? 0)],
    ["Event count", String(status?.total_events ?? 0)],
    ["Evidence count", String(status?.evidence_captured ?? 0)],
    ["Evidence indexed", String(status?.evidence_indexed ?? 0)],
    ["VLM count", String(status?.vlm_observations ?? 0)],
  ];
  if (metrics.model || metrics.device) {
    cells.push([
      "YOLO",
      `${metrics.model ?? "—"} · ${metrics.device ?? "?"} · imgsz ${metrics.imgsz ?? "?"}`,
    ]);
  }
  if (typeof metrics.inference_latency_avg_ms === "number" && metrics.inference_latency_avg_ms > 0) {
    cells.push(["Inference latency", `${metrics.inference_latency_avg_ms.toFixed(0)} ms avg`]);
  }
  if (health?.error) cells.push(["Source error", String(health.error), "text-red-700"]);

  return (
    <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
      {cells.map(([label, value, tone]) => (
        <div key={label} className="rounded-md bg-slate-50 p-3">
          <p className="text-xs text-slate-500">{label}</p>
          <p className={`font-medium ${tone ?? "text-navy"}`}>{value}</p>
        </div>
      ))}
    </div>
  );
}

type OverlayFrame = {
  detections: LiveDetectionFrame["detections"];
  frameWidth: number | null;
  frameHeight: number | null;
};

function DetectionOverlay({
  frame,
  enabled,
  error,
}: {
  frame: OverlayFrame | null;
  enabled: boolean;
  error?: string | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || !frame || !enabled) {
      if (canvas) {
        const ctx = canvas.getContext("2d");
        if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }
    const rect = wrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // The preview is rendered with object-contain, so a 4:3 camera inside a 16:9
    // box is pillarboxed. Scale the absolute-pixel boxes onto the *image* area,
    // otherwise they drift onto the black bars and look misaligned.
    const frameW = frame.frameWidth || 0;
    const frameH = frame.frameHeight || 0;
    let offX = 0;
    let offY = 0;
    let scaleX = 1;
    let scaleY = 1;
    if (frameW > 0 && frameH > 0) {
      const boxAspect = rect.width / rect.height;
      const imgAspect = frameW / frameH;
      let dispW: number;
      let dispH: number;
      if (imgAspect > boxAspect) {
        dispW = rect.width;
        dispH = rect.width / imgAspect;
      } else {
        dispH = rect.height;
        dispW = rect.height * imgAspect;
      }
      offX = (rect.width - dispW) / 2;
      offY = (rect.height - dispH) / 2;
      scaleX = dispW / frameW;
      scaleY = dispH / frameH;
    } else {
      // Dimensions unknown (should not happen - the engine always reports the
      // frame shape): draw the absolute-pixel boxes 1:1 as a last resort
      // instead of dropping them.
      scaleX = 1;
      scaleY = 1;
    }
    {
      const stroke = 2 * dpr;
      ctx.lineWidth = stroke;
      ctx.font = `${Math.max(11, Math.round(13 * dpr))}px system-ui, sans-serif`;

      for (const det of frame.detections) {
        const [x1, y1, x2, y2] = det.bbox;
        const px = (offX + x1 * scaleX) * dpr;
        const py = (offY + y1 * scaleY) * dpr;
        const pw = Math.max(0, (x2 - x1) * scaleX * dpr);
        const ph = Math.max(0, (y2 - y1) * scaleY * dpr);
        ctx.strokeStyle = "#22d3ee";
        ctx.strokeRect(px, py, pw, ph);
        const label = `${det.class_name} ${Math.round(det.confidence * 100)}%`;
        ctx.fillStyle = "rgba(8, 145, 178, 0.9)";
        const tw = ctx.measureText(label).width;
        const labelY = Math.max(0, py - 20 * dpr);
        ctx.fillRect(px, labelY, tw + 10 * dpr, 20 * dpr);
        ctx.fillStyle = "#ffffff";
        ctx.textBaseline = "middle";
        ctx.fillText(label, px + 5 * dpr, labelY + 10 * dpr);
      }
    }
  }, [frame, enabled]);

  if (!enabled) return null;

  return (
    <div ref={wrapRef} className="pointer-events-none absolute inset-0">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      {error ? (
        <p className="absolute left-2 top-2 rounded bg-amber-500/90 px-2 py-1 text-xs font-medium text-white">
          Detection unavailable: {error}
        </p>
      ) : null}
    </div>
  );
}

export default function LivePage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [transport, setTransport] = useState<LiveTransport>("webrtc");
  const [deviceIndex, setDeviceIndex] = useState(0);
  const [streamUrl, setStreamUrl] = useState("");
  const [fpsTarget, setFpsTarget] = useState(10);
  const [demoVideos, setDemoVideos] = useState<DemoVideoAsset[]>([]);
  const [selectedDemoPath, setSelectedDemoPath] = useState("");
  const [session, setSession] = useState<CameraSession | null>(null);
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [liveList, setLiveList] = useState<LiveStatus[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [starting, setStarting] = useState(false);
  const [facing, setFacing] = useState<"user" | "environment">("environment");
  const [error, setError] = useState("");
  const [pcState, setPcState] = useState("");
  const [detectionFrame, setDetectionFrame] = useState<OverlayFrame | null>(null);
  const [detectionEnabled, setDetectionEnabled] = useState(false);
  const [detectionError, setDetectionError] = useState<string | null>(null);
  const [detectionMetrics, setDetectionMetrics] = useState<LiveDetectionMetrics | null>(null);
  const [trackingEnabled, setTrackingEnabled] = useState(false);
  const [trackingMetrics, setTrackingMetrics] = useState<TrackingMetricsOut | null>(null);
  const [trackingEvents, setTrackingEvents] = useState<TrackingEvent[]>([]);
  const [vlmEnabled, setVlmEnabled] = useState(false);
  const [vlmError, setVlmError] = useState<string | null>(null);
  const [vlmRequests, setVlmRequests] = useState(0);
  const [vlmObservations, setVlmObservations] = useState(0);
  const [vlmRecent, setVlmRecent] = useState<VlmObservation[]>([]);
  const [vlmAnalyzing, setVlmAnalyzing] = useState(false);

  // forensic evidence (Phase 5)
  const [evidence, setEvidence] = useState<LiveEvidence[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceSearchText, setEvidenceSearchText] = useState("");
  const [evidenceSearchHits, setEvidenceSearchHits] = useState<EvidenceSearchHit[]>([]);
  const [evidencePreview, setEvidencePreview] = useState<string | null>(null);
  const [evidencePreviewMeta, setEvidencePreviewMeta] = useState<LiveEvidence | null>(null);
  const [evidenceDetail, setEvidenceDetail] = useState<LiveEvidenceDetail | null>(null);

  // camera registration form
  const [newName, setNewName] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [newType, setNewType] = useState("MOBILE");

  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const signalingWsRef = useRef<WebSocket | null>(null);
  const statusWsRef = useRef<WebSocket | null>(null);
  const detectionWsRef = useRef<WebSocket | null>(null);
  const trackingWsRef = useRef<WebSocket | null>(null);
  const vlmWsRef = useRef<WebSocket | null>(null);
  const sigOpenRef = useRef(false);
  const closingRef = useRef(false);

  // ------------------------------------------------------------ data loading

  const loadCameras = useCallback(async () => {
    try {
      const cs = await api.cameras();
      setCameras(cs);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load cameras");
    }
  }, []);

  const loadLiveList = useCallback(async () => {
    try {
      setLiveList(await api.liveSessions().catch(() => []));
    } catch {
      /* ignore */
    }
  }, []);

  const loadEvidence = useCallback(async () => {
    if (!session?.id) {
      setEvidence([]);
      return;
    }
    setEvidenceLoading(true);
    try {
      const rows = await api.liveEvidenceList({ session_id: session.id, limit: 50 });
      setEvidence(rows);
      setEvidenceError(null);
    } catch (e) {
      setEvidenceError(e instanceof ApiError ? e.message : "Failed to load evidence");
    } finally {
      setEvidenceLoading(false);
    }
  }, [session?.id]);

  useEffect(() => {
    loadEvidence();
  }, [loadEvidence]);

  const openEvidencePreview = async (row: LiveEvidence) => {
    try {
      if (evidencePreview) URL.revokeObjectURL(evidencePreview);
      const blob = await api.liveEvidenceContent(row.public_id);
      const url = URL.createObjectURL(blob);
      setEvidencePreviewMeta(row);
      setEvidencePreview(url);
      const detail = await api.liveEvidenceDetail(row.public_id).catch(() => null);
      setEvidenceDetail(detail);
    } catch {
      setEvidenceError("Could not load evidence content");
    }
  };

  const closeEvidencePreview = () => {
    if (evidencePreview) URL.revokeObjectURL(evidencePreview);
    setEvidencePreview(null);
    setEvidencePreviewMeta(null);
    setEvidenceDetail(null);
  };

  const reindexEvidence = async (row: LiveEvidence) => {
    await api.liveEvidenceReindex(row.public_id).catch(() => {});
    loadEvidence();
  };

  const runEvidenceSearch = async () => {
    const q = evidenceSearchText.trim();
    if (!q) {
      setEvidenceSearchHits([]);
      return;
    }
    try {
      const res = await api.liveEvidenceSearch(q, undefined, 20);
      setEvidenceSearchHits(res.results);
    } catch (e) {
      setEvidenceError(e instanceof ApiError ? e.message : "Evidence search failed");
    }
  };

  useEffect(() => {
    loadCameras();
    loadLiveList();
    const demo = new URLSearchParams(window.location.search).get("demo");
    api
      .demoDataset()
      .then((m) => {
        setDemoVideos(m.videos);
        if (demo) {
          setTransport("file");
          const match = m.videos.find((v) => v.filename === demo || v.demo_id === demo);
          if (match) setSelectedDemoPath(match.abs_path);
        }
      })
      .catch(() => {});
    const interval = setInterval(() => {
      loadLiveList();
      if (selectedCameraId) {
        api.liveStatus(Number(selectedCameraId)).then(setStatus).catch(() => {});
      }
    }, 4000);
    return () => {
      clearInterval(interval);
      closeConnections();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCameraId]);

  // ------------------------------------------------------------- connections

  const closeStatusWs = useCallback(() => {
    const ws = statusWsRef.current;
    statusWsRef.current = null;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const openStatusWs = useCallback((cameraId: number) => {
    closeStatusWs();
    const token = getToken();
    if (!token) return;
    const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/status`));
    statusWsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as LiveStatusEvent & Record<string, unknown>;
        if (msg.type === "status") {
          setStatus(msg as unknown as LiveStatus);
          loadLiveList();
        }
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      if (statusWsRef.current === ws) statusWsRef.current = null;
    };
  }, [closeStatusWs, loadLiveList]);

  const closeDetectionWs = useCallback(() => {
    const ws = detectionWsRef.current;
    detectionWsRef.current = null;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const closeTrackingWs = useCallback(() => {
    const ws = trackingWsRef.current;
    trackingWsRef.current = null;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const openTrackingWs = useCallback((cameraId: number) => {
    closeTrackingWs();
    const token = getToken();
    if (!token) return;
    setTrackingMetrics(null);
    setTrackingEvents([]);
    setTrackingEnabled(false);
    const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/tracking`));
    trackingWsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as TrackingStatusEvent | TrackUpdate | TrackingEvent | TrackingMetricsOut;
        if (msg.type === "tracking_status" || msg.type === "tracking_keepalive") {
          setTrackingEnabled(Boolean((msg as TrackingStatusEvent).tracking_enabled));
        } else if (msg.type === "track_update") {
          setTrackingEnabled(true);
        } else if (msg.type === "track_event" || msg.type === "tracking_event") {
          setTrackingEnabled(true);
          setTrackingEvents((prev) => [...prev.slice(-19), msg as TrackingEvent]);
        } else if (msg.type === "tracking_metrics") {
          setTrackingEnabled(true);
          setTrackingMetrics(msg as TrackingMetricsOut);
        }
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      if (trackingWsRef.current === ws) trackingWsRef.current = null;
    };
  }, [closeTrackingWs]);

  const closeVlmWs = useCallback(() => {
    const ws = vlmWsRef.current;
    vlmWsRef.current = null;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const openVlmWs = useCallback((cameraId: number) => {
    closeVlmWs();
    const token = getToken();
    if (!token) return;
    setVlmError(null);
    setVlmRecent([]);
    setVlmEnabled(false);
    const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/vlm`));
    vlmWsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as VlmStatusMessage | VlmObservation | VlmRequestMessage | VlmErrorMessage | VlmMetricsMessage | VlmKeepaliveMessage;
        if (msg.type === "vlm_status") {
          setVlmEnabled(Boolean(msg.vlm_enabled));
          setVlmError(msg.vlm_last_error ?? null);
          setVlmRequests(msg.vlm_requests ?? 0);
          setVlmObservations(msg.vlm_observations ?? 0);
          if (msg.recent?.length) setVlmRecent(msg.recent);
        } else if (msg.type === "vlm_keepalive") {
          setVlmEnabled(Boolean((msg as VlmKeepaliveMessage).vlm_enabled));
        } else if (msg.type === "vlm_request") {
          setVlmEnabled(true);
          setVlmRequests((n) => n + 1);
        } else if (msg.type === "vlm_observation") {
          setVlmEnabled(true);
          setVlmError(null);
          setVlmObservations((n) => n + 1);
          setVlmRecent((prev) => [...prev, msg as VlmObservation].slice(-20));
        } else if (msg.type === "vlm_error") {
          setVlmEnabled(true);
          setVlmError((msg as VlmErrorMessage).detail);
        } else if (msg.type === "vlm_metrics") {
          setVlmEnabled(true);
          const m = msg as VlmMetricsMessage;
          setVlmRequests(m.total_requests);
          setVlmObservations(m.total_observations);
          setVlmError(m.last_error ?? null);
        }
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      if (vlmWsRef.current === ws) vlmWsRef.current = null;
    };
  }, [closeVlmWs]);

  const openDetectionWs = useCallback((cameraId: number) => {
    closeDetectionWs();
    const token = getToken();
    if (!token) return;
    setDetectionFrame(null);
    setDetectionMetrics(null);
    const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/detections`));
    detectionWsRef.current = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as LiveDetectionStatusEvent | LiveDetectionFrame;
        if (msg.type === "detection_status") {
          setDetectionEnabled(Boolean(msg.detection_enabled));
          setDetectionError(msg.detection_error ?? null);
          setDetectionMetrics(msg.detection_metrics ?? null);
        } else if (msg.type === "detection_keepalive") {
          setDetectionEnabled(Boolean(msg.detection_enabled));
        } else if (msg.type === "detection") {
          setDetectionEnabled(true);
          setDetectionFrame({
            detections: msg.detections,
            frameWidth: msg.frame_width,
            frameHeight: msg.frame_height,
          });
        }
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      if (detectionWsRef.current === ws) detectionWsRef.current = null;
    };
  }, [closeDetectionWs]);

  const closeSignalingWs = useCallback(() => {
    const ws = signalingWsRef.current;
    signalingWsRef.current = null;
    sigOpenRef.current = false;
    if (ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const stopTracks = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  const closeConnections = useCallback(() => {
    closingRef.current = true;
    closeSignalingWs();
    closeStatusWs();
    closeDetectionWs();
    closeTrackingWs();
    closeVlmWs();
    setDetectionFrame(null);
    setDetectionMetrics(null);
    setTrackingEnabled(false);
    setTrackingMetrics(null);
    setTrackingEvents([]);
    setVlmEnabled(false);
    setVlmError(null);
    setVlmRecent([]);
    const pc = pcRef.current;
    pcRef.current = null;
    if (pc) {
      try {
        pc.close();
      } catch {
        /* ignore */
      }
    }
    stopTracks();
    setStreaming(false);
    setPcState("");
  }, [closeSignalingWs, closeStatusWs, closeDetectionWs, closeTrackingWs, closeVlmWs, stopTracks]);

  // -------------------------------------------------------------- webrtc flow

  const startWebRtc = useCallback(
    async (cameraId: number) => {
      const token = getToken();
      if (!token) {
        setError("Not logged in. Please sign in again.");
        return;
      }
      let stream: MediaStream;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setError(
          "Camera access requires a secure context (HTTPS or localhost). Open this page over HTTPS on your phone and retry."
        );
        setStarting(false);
        await stopSessionApi(cameraId);
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: facing } },
          audio: false,
        });
      } catch (e) {
        const name = e instanceof DOMException ? e.name : "";
        if (name === "NotAllowedError") {
          setError("Camera permission denied. Allow camera access and retry.");
        } else if (name === "NotFoundError") {
          setError("No camera device found on this device.");
        } else if (name === "NotReadableError") {
          setError("Camera is in use by another application.");
        } else {
          setError(`Could not access camera: ${e instanceof Error ? e.message : String(e)}`);
        }
        setStarting(false);
        await stopSessionApi(cameraId);
        return;
      }
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;

      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
      pc.onicecandidate = (e) => {
        if (!e.candidate || !sigOpenRef.current || !signalingWsRef.current) return;
        signalingWsRef.current.send(
          JSON.stringify({
            type: "trickle",
            candidate: {
              candidate: e.candidate.candidate,
              sdpMid: e.candidate.sdpMid,
              sdpMLineIndex: e.candidate.sdpMLineIndex,
            },
          })
        );
      };
      pc.onconnectionstatechange = () => {
        setPcState(pc.connectionState);
        if (pc.connectionState === "failed") {
          setError("WebRTC connection failed. Try again.");
        }
      };

      const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/signaling`));
      signalingWsRef.current = ws;
      ws.onopen = () => {
        sigOpenRef.current = true;
        ws.send(JSON.stringify({ type: "auth", token }));
      };
      ws.onmessage = async (ev) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(ev.data as string);
        } catch {
          return;
        }
        if (msg.type === "auth_ok") {
          setStreaming(true);
          setError("");
          try {
            const offer = await pc.createOffer();
            await pc.setLocalDescription(offer);
            ws.send(JSON.stringify({ type: "offer", sdp: offer.sdp }));
          } catch (err) {
            setError(`Could not create WebRTC offer: ${err instanceof Error ? err.message : String(err)}`);
          }
        } else if (msg.type === "answer") {
          if (pcRef.current && typeof msg.sdp === "string") {
            await pc.setRemoteDescription({ type: "answer", sdp: msg.sdp });
          }
        } else if (msg.type === "trickle") {
          // The backend relays its own ICE candidates here; feed them into the
          // peer connection so connectivity checks can complete.
          const candidate = msg.candidate as {
            candidate?: string;
            sdpMid?: string | null;
            sdpMLineIndex?: number | null;
          } | null;
          const pcNow = pcRef.current;
          if (pcNow && candidate && candidate.candidate) {
            try {
              await pcNow.addIceCandidate({
                candidate: candidate.candidate,
                sdpMid: candidate.sdpMid ?? null,
                sdpMLineIndex: candidate.sdpMLineIndex ?? null,
              });
            } catch (err) {
              // Late/duplicate candidates are normal; keep the session alive.
            }
          }
        } else if (msg.type === "error") {
          setError(String(msg.detail || "Signaling error"));
          closeConnections();
          stopSessionApi(cameraId);
        }
      };
      ws.onerror = () => setError("Signaling connection error");
      ws.onclose = () => {
        sigOpenRef.current = false;
        if (signalingWsRef.current === ws) signalingWsRef.current = null;
      };
    },
    [facing, closeConnections]
  );

  // ------------------------------------------------------------------ actions

  async function stopSessionApi(cameraId: number) {
    await api.liveStop(cameraId).catch(() => {});
    setSession(null);
    setStatus((prev) => (prev ? { ...prev, active: false, status: "OFFLINE" } : prev));
  }

  async function onRegisterCamera(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const cam = await api.createCamera({
        camera_name: newName,
        location: newLocation || undefined,
        camera_type: newType,
        stream_source: "mobile-" + newName.toLowerCase().replace(/[^a-z0-9-]/g, "-"),
      });
      setCameras((prev) => [...prev, cam]);
      setSelectedCameraId(String(cam.id));
      setNewName("");
      setNewLocation("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to register camera");
    }
  }

  async function onStart() {
    setError("");
    const cameraId = Number(selectedCameraId);
    if (!cameraId) {
      setError("Select a camera first");
      return;
    }
    if (transport === "file" && !selectedDemoPath) {
      setError("Select a demo video file for file transport");
      return;
    }
    setStarting(true);
    try {
      const ses = await api.liveStart(cameraId, {
        transport,
        video_path: transport === "file" ? selectedDemoPath || undefined : undefined,
        device_index:
          transport === "webcam" || transport === "droidcam_usb"
            ? Number(deviceIndex) || 0
            : undefined,
        stream_url: transport === "ipcam" ? streamUrl.trim() || undefined : undefined,
        fps_target:
          transport === "webcam" || transport === "droidcam_usb" || transport === "ipcam"
            ? fpsTarget
            : 5,
        buffer_window_seconds: 15,
        buffer_max_frames: 150,
      });
      setSession(ses);
      openStatusWs(cameraId);
      openDetectionWs(cameraId);
      openTrackingWs(cameraId);
      openVlmWs(cameraId);
      if (transport === "webrtc") {
        await startWebRtc(cameraId);
      } else {
        setStreaming(true);
        await loadLiveList();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start live session");
    } finally {
      setStarting(false);
    }
  }

  async function onStop() {
    const cameraId = Number(selectedCameraId);
    closeConnections();
    if (cameraId) await stopSessionApi(cameraId);
  }

  async function onSwitchCamera() {
    const next = facing === "environment" ? "user" : "environment";
    setFacing(next);
    const pc = pcRef.current;
    if (!pc || !next) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: next } },
        audio: false,
      });
      const newTrack = stream.getVideoTracks()[0];
      const sender = pc.getSenders().find((s) => s.track?.kind === "video");
      if (sender && newTrack) {
        await sender.replaceTrack(newTrack);
      }
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setError("");
    } catch (e) {
      setError(`Failed to switch camera: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  const selectedCamera = cameras.find((c) => c.id === Number(selectedCameraId));
  const liveNow = liveList.find((s) => s.camera_id === Number(selectedCameraId));

  // Backend-owned captures (webcam / droidcam_usb / file / simulation) have no
  // MediaStream in the browser, so the console subscribes to the MJPEG preview
  // of the very frames that are being analysed. WebRTC keeps the native <video>.
  const previewUrl =
    streaming && transport !== "webrtc" && selectedCameraId
      ? `${API_URL}/live/cameras/${selectedCameraId}/stream.mjpg?token=${encodeURIComponent(
          getToken() ?? "",
        )}`
      : null;

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">Live Cameras</h1>
        <p className="text-sm text-slate-500">
          Stream a mobile camera in real time over WebRTC into the investigation pipeline.
        </p>
      </div>

      {error && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-red-50 p-3 text-sm text-red-700">
          <AlertTriangle className="h-4 w-4" /> {error}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Controls */}
        <div className="space-y-6 lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Smartphone className="h-5 w-5 text-accent" /> Mobile Camera
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <label className="text-sm font-medium">Camera</label>
                <Select value={selectedCameraId} onChange={(e) => setSelectedCameraId(e.target.value)}>
                  <option value="">— select camera —</option>
                  {cameras.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.camera_name} {c.camera_type ? `(${c.camera_type})` : ""}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-sm font-medium">Camera source</label>
                <Select
                  value={transport}
                  onChange={(e) => setTransport(e.target.value as LiveTransport)}
                >
                  <option value="webrtc">Phone WebRTC (real camera over network)</option>
                  <option value="webcam">Laptop Webcam (real local camera)</option>
                  <option value="droidcam_usb">USB / DroidCam camera (real local camera)</option>
                  <option value="ipcam">Phone IP camera (real network stream)</option>
                  <option value="simulation">Simulation (synthetic frames — NOT evidence)</option>
                  <option value="file">Demo Video (licensed clip — NOT evidence)</option>
                </Select>
                <p className="text-xs text-slate-500">
                  <strong>Phone WebRTC</strong> streams the phone camera via SDP signaling.{" "}
                  <strong>Laptop Webcam</strong> and <strong>USB / DroidCam</strong> open a real local
                  capture device over OpenCV (device 0 by default — it must exist; probe with{" "}
                  <code>python backend/scripts/verify_webcam.py --probe</code>).{" "}
                  <strong>Simulation</strong> feeds synthetic frames and <strong>Demo Video</strong>{" "}
                  replays a licensed clip — neither is real forensic evidence; both run the real
                  CV2 → detection → tracking → VLM → evidence pipeline.
                </p>
              </div>

              {transport === "file" && (
                <div className="space-y-1 rounded-md border border-amber-200 bg-amber-50 p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold text-amber-900">
                    <AlertTriangle className="h-4 w-4" /> DEMO DATA — NOT REAL FORENSIC EVIDENCE
                  </p>
                  <label className="text-sm font-medium">Demo video file</label>
                  <Select value={selectedDemoPath} onChange={(e) => setSelectedDemoPath(e.target.value)}>
                    <option value="">— select demo video —</option>
                    {demoVideos.map((v) => (
                      <option key={v.demo_id} value={v.abs_path}>
                        {v.demo_id} · {v.filename}
                      </option>
                    ))}
                  </Select>
                  <p className="text-xs text-slate-500">
                    The selected clip is replayed as a camera feed on the backend. Make sure the camera below is an
                    offline/CCTV demo camera.
                  </p>
                </div>
              )}

              {transport === "ipcam" && (
                <div className="space-y-3 rounded-md border border-emerald-200 bg-emerald-50 p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold text-emerald-900">
                    <Video className="h-4 w-4" /> PHONE IP CAMERA - the backend pulls a real network stream from a
                    phone. An unreachable stream fails the start request (HTTP 503); it never fakes frames.
                  </p>
                  <div className="space-y-1">
                    <label className="text-sm font-medium">Stream URL</label>
                    <Input
                      value={streamUrl}
                      onChange={(e) => setStreamUrl(e.target.value)}
                      placeholder="http://10.5.176.115:8080/video"
                    />
                    <p className="text-xs text-slate-500">
                      Android &quot;IP Webcam&quot;: <code>http://&lt;phone-ip&gt;:8080/video</code> (MJPEG) or{" "}
                      <code>http://&lt;phone-ip&gt;:8080/h264</code>; RTSP also works, e.g.{" "}
                      <code>rtsp://&lt;phone-ip&gt;:554/...</code>. The backend must be able to reach that
                      address. Verify with <code>verify_ipcam.py</code>.
                    </p>
                  </div>
                  <div className="space-y-1">
                    <label className="text-sm font-medium">FPS</label>
                    <Input
                      type="number"
                      min={1}
                      max={30}
                      value={fpsTarget}
                      onChange={(e) => setFpsTarget(Number(e.target.value) || 5)}
                    />
                    <p className="text-xs text-slate-500">
                      Analysis rate fed to YOLO. The phone may send more; frames are sampled down.
                    </p>
                  </div>
                </div>
              )}

              {(transport === "droidcam_usb" || transport === "webcam") && (
                <div className="space-y-3 rounded-md border border-emerald-200 bg-emerald-50 p-3">
                  <p className="flex items-center gap-2 text-xs font-semibold text-emerald-900">
                    <Video className="h-4 w-4" /> REAL LOCAL CAMERA — the backend opens a physical capture
                    device. A missing device fails the start request (HTTP 503); it never fakes frames.
                  </p>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-sm font-medium">Camera device</label>
                      <Input
                        type="number"
                        min={0}
                        step={1}
                        value={deviceIndex}
                        onChange={(e) => setDeviceIndex(Number(e.target.value) || 0)}
                      />
                      <p className="text-xs text-slate-500">
                        OpenCV capture index (integrated webcam is usually 0). Probe with{" "}
                        <code>verify_webcam.py --probe</code> if the start fails.
                      </p>
                    </div>
                    <div className="space-y-1">
                      <label className="text-sm font-medium">FPS</label>
                      <Input
                        type="number"
                        min={1}
                        max={30}
                        step={1}
                        value={fpsTarget}
                        onChange={(e) => setFpsTarget(Number(e.target.value) || 10)}
                      />
                      <p className="text-xs text-slate-500">
                        Requested capture rate (frames/sec). Lower values reduce CPU load.
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <div className="flex gap-2">
                <Button onClick={onStart} disabled={!selectedCameraId || starting || streaming} className="flex-1">
                  {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                  {streaming ? "Streaming…" : "Start"}
                </Button>
                <Button variant="destructive" onClick={onStop} disabled={!streaming && !session}>
                  <VideoOff className="h-4 w-4" /> Stop
                </Button>
              </div>
              {streaming && (
                <Button variant="outline" className="w-full" onClick={onSwitchCamera}>
                  <SwitchCamera className="h-4 w-4" />
                  {facing === "environment" ? "Front camera (selfie)" : "Rear camera"}
                </Button>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CameraIcon className="h-5 w-5 text-accent" /> Register Mobile Camera
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={onRegisterCamera} className="space-y-3">
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Camera name, e.g. Investigating Officer 01"
                  required
                />
                <Input value={newLocation} onChange={(e) => setNewLocation(e.target.value)} placeholder="Location / scene" />
                <Select value={newType} onChange={(e) => setNewType(e.target.value)}>
                  <option value="MOBILE">MOBILE</option>
                  <option value="CCTV">CCTV</option>
                  <option value="OTHER">OTHER</option>
                </Select>
                <Button type="submit" className="w-full" disabled={!newName.trim()}>
                  Register camera
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>

        {/* Preview + live status */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <Radio className="h-5 w-5 text-accent" /> Live Session
              </CardTitle>
              {status && (
                <Badge variant={statusVariant(status.status)}>{status.status}</Badge>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="relative aspect-video w-full overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
                {streaming ? (
                  <>
                    {transport === "webrtc" ? (
                      <video
                        ref={videoRef}
                        autoPlay
                        playsInline
                        muted
                        className="h-full w-full object-contain"
                      />
                    ) : (
                      /* The backend owns the camera for webcam / droidcam_usb /
                         file / simulation, so the browser has no MediaStream.
                         Stream the exact frames that YOLO analysed, otherwise
                         the surface stays black. */
                      previewUrl ? (
                        <img
                          key={previewUrl}
                          src={previewUrl}
                          alt="Live camera preview"
                          className="h-full w-full object-contain"
                        />
                      ) : (
                        <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-400">
                          <CameraIcon className="h-10 w-10" />
                          <p className="text-sm">Waiting for the first analysed frame…</p>
                        </div>
                      )
                    )}
                  </>
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-2 text-slate-500">
                    <CameraIcon className="h-10 w-10" />
                    <p className="text-sm">No live feed — start a session to begin</p>
                  </div>
                )}
                <DetectionOverlay frame={detectionFrame} enabled={detectionEnabled} error={detectionError} />
              </div>

              {detectionEnabled && (
                <div className="flex items-center gap-2 rounded-md bg-cyan-50 p-2 text-xs text-cyan-800">
                  <Eye className="h-4 w-4" />
                  <span className="font-medium">YOLO detection active</span>
                  {detectionMetrics ? (
                    <span className="ml-auto">
                      {detectionMetrics.total_detections} detections · {detectionMetrics.detection_fps} det/s ·{" "}
                      {detectionMetrics.processed_fps} proc/s · avg {detectionMetrics.inference_latency_avg_ms} ms · drops{" "}
                      {detectionMetrics.total_dropped}
                    </span>
                  ) : (
                    <span className="ml-auto">waiting for detection stream…</span>
                  )}
                </div>
              )}

              {vlmEnabled && (
                <div className="flex items-center gap-2 rounded-md bg-violet-50 p-2 text-xs text-violet-800">
                  <Sparkles className="h-4 w-4" />
                  <span className="font-medium">VLM observation active</span>
                  {vlmError ? (
                    <span className="ml-auto truncate text-amber-700">last error: {vlmError}</span>
                  ) : (
                    <span className="ml-auto">
                      {vlmObservations} observations · {vlmRequests} requests
                    </span>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    className="ml-2 h-6 text-xs"
                    disabled={vlmAnalyzing}
                    onClick={async () => {
                      if (!selectedCameraId) return;
                      setVlmAnalyzing(true);
                      try {
                        await api.liveVlmAnalyze(Number(selectedCameraId));
                      } catch (e) {
                        setVlmError(e instanceof ApiError ? e.message : "Analyze request failed");
                      } finally {
                        setVlmAnalyzing(false);
                      }
                    }}
                  >
                    {vlmAnalyzing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Sparkles className="mr-1 h-3 w-3" />}
                    Analyze Now
                  </Button>
                </div>
              )}

              {trackingEnabled && (
                <div className="flex items-center gap-2 rounded-md bg-emerald-50 p-2 text-xs text-emerald-800">
                  <span className="font-medium">Tracking active</span>
                  {trackingMetrics ? (
                    <span className="ml-auto">
                      {trackingMetrics.active_tracks} active tracks · {trackingMetrics.total_events} events · {trackingMetrics.total_updates} updates
                    </span>
                  ) : (
                    <span className="ml-auto">waiting for tracking stream…</span>
                  )}
                </div>
              )}

              {liveNow && !status?.active && (
                <div className="flex items-center justify-between rounded-md bg-amber-50 p-3 text-sm">
                  <span className="text-amber-800">
                    Active session detected: {liveNow.status} on {liveNow.camera_name || `camera ${liveNow.camera_id}`}
                  </span>
                  <Button size="sm" variant="outline" onClick={() => setSelectedCameraId(String(liveNow.camera_id))}>
                    Focus
                  </Button>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Camera source</p>
                  <p className="font-medium text-navy">{SOURCE_LABEL[status?.transport ?? ""] ?? status?.transport ?? "—"}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Frames received</p>
                  <p className="font-medium text-navy">{status?.frames_received ?? 0}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Frames sampled</p>
                  <p className="font-medium text-navy">{status?.frames_sampled ?? 0}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Buffered</p>
                  <p className="font-medium text-navy">{status?.frames_buffered ?? 0}</p>
                </div>
              </div>

              <LiveCounters status={status} />

              <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">FPS target</p>
                  <p className="font-medium text-navy">{status?.fps_target ?? "—"}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Buffer window</p>
                  <p className="font-medium text-navy">
                    {status?.window_seconds ? `${status.window_seconds}s` : "—"}
                  </p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">WebRTC state</p>
                  <p className="font-medium text-navy">{pcState || "—"}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Detections</p>
                  <p className="font-medium text-navy">
                    {detectionMetrics?.total_detections ?? (status?.detection_recent_count ?? "—")}
                  </p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Active tracks</p>
                  <p className="font-medium text-navy">{trackingMetrics?.active_tracks ?? status?.active_tracks ?? "—"}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Tracking events</p>
                  <p className="font-medium text-navy">{trackingMetrics?.total_events ?? status?.total_events ?? "—"}</p>
                </div>
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="text-xs text-slate-500">Session ID</p>
                  <p className="font-medium text-navy">{status?.session_id ?? session?.id ?? "—"}</p>
                </div>
              </div>

              {trackingEvents.length > 0 && (
                <div className="rounded-md bg-slate-50 p-3">
                  <p className="mb-1 text-xs font-medium text-slate-600">Recent tracking events</p>
                  <div className="max-h-40 space-y-1 overflow-y-auto">
                    {trackingEvents.map((ev, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="font-medium text-navy">{ev.event_type}: {ev.tracking_id}</span>
                        <span className="text-slate-500">
                          {ev.description || ev.metadata ? JSON.stringify(ev.description ?? ev.metadata) : `frame ${ev.frame_index}`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {vlmRecent.length > 0 && (
                <div className="rounded-md bg-violet-50 p-3">
                  <p className="mb-1 text-xs font-medium text-slate-600">Recent VLM observations</p>
                  <div className="max-h-56 space-y-2 overflow-y-auto">
                    {vlmRecent.map((obs) => (
                      <div key={obs.observation_id} className="rounded border border-violet-200 bg-white p-2 text-xs">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-navy">
                            {obs.trigger}{obs.trigger_detail ? ` · ${obs.trigger_detail}` : ""}
                          </span>
                          <span className="text-slate-500">{obs.provider_mode}</span>
                        </div>
                        <p className="mt-1 text-navy leading-relaxed">{obs.summary}</p>
                        {obs.items.length > 0 && (
                          <div className="mt-1.5 space-y-1">
                            {obs.items.map((it) => (
                              <div key={it.item_id} className="flex items-start gap-2">
                                <span className={`mt-px inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold leading-none ${
                                  it.classification === "OBSERVED"
                                    ? "bg-green-100 text-green-800"
                                    : it.classification === "INFERRED"
                                    ? "bg-amber-100 text-amber-800"
                                    : "bg-slate-100 text-slate-600"
                                }`}>
                                  {it.classification}
                                </span>
                                <span className="text-navy">{it.statement}</span>
                                <span className="ml-auto shrink-0 text-slate-400">
                                  {Math.round(it.confidence * 100)}%
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                        {obs.source_frames.length > 0 && (
                          <p className="mt-1 text-slate-500">
                            {obs.source_frames.length} source frame{obs.source_frames.length !== 1 ? "s" : ""}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {status?.error && (
                <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{status.error}</p>
              )}
            </CardContent>
          </Card>

          {session && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <Fingerprint className="h-4 w-4" /> Forensic Evidence
                </CardTitle>
                <Button variant="ghost" size="sm" onClick={loadEvidence} disabled={evidenceLoading}>
                  <RefreshCw className="h-4 w-4" /> Refresh
                </Button>
              </CardHeader>
              <CardContent className="space-y-3 pt-0">
                {evidenceError && (
                  <p className="rounded-md bg-red-50 p-2 text-xs text-red-700">{evidenceError}</p>
                )}
                <div className="flex gap-2">
                  <Input
                    value={evidenceSearchText}
                    onChange={(e) => setEvidenceSearchText(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && runEvidenceSearch()}
                    placeholder="Search captured evidence…"
                  />
                  <Button size="sm" onClick={runEvidenceSearch}>
                    <Search className="h-4 w-4" />
                  </Button>
                </div>
                {evidenceSearchHits.length > 0 && (
                  <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-2">
                    <p className="mb-1 flex items-center justify-between text-xs font-medium text-blue-800">
                      <span>Semantic search results</span>
                      <button
                        className="text-blue-500"
                        onClick={() => setEvidenceSearchHits([])}
                      >
                        clear
                      </button>
                    </p>
                    <div className="space-y-1">
                      {evidenceSearchHits.slice(0, 5).map((h) => (
                        <div key={h.evidence_id || h.score} className="flex items-center gap-2 text-xs">
                          <Badge variant={statusVariant(h.evidence_type || "")}>
                            {h.evidence_type}
                          </Badge>
                          <span className="truncate text-slate-700">{h.source_text || h.evidence_id}</span>
                          <span className="ml-auto shrink-0 text-slate-400">{h.score.toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {evidencePreviewMeta && evidencePreview && (
                  <div className="rounded-lg border border-slate-200 p-2">
                    <div className="mb-1 flex items-center justify-between">
                      <p className="flex items-center gap-1 text-xs font-medium text-navy">
                        <ImageIcon className="h-3 w-3" /> {evidencePreviewMeta.public_id}
                      </p>
                      <button
                        className="text-xs text-slate-400 hover:text-slate-600"
                        onClick={closeEvidencePreview}
                      >
                        close
                      </button>
                    </div>
                    <img
                      src={evidencePreview}
                      alt={evidencePreviewMeta.public_id}
                      className="max-h-48 w-full rounded bg-slate-900 object-contain"
                    />
                    <p className="mt-1 truncate text-[10px] text-slate-500">
                      sha256 {evidencePreviewMeta.sha256} · {evidencePreviewMeta.width}x{evidencePreviewMeta.height}
                      {" · "}frame {evidencePreviewMeta.frame_sequence}
                    </p>
                    {evidenceDetail?.provenance && (
                      <p className="mt-1 truncate text-[10px] text-slate-400">
                        {evidenceDetail.provenance.source || evidenceDetail.provenance.generated_by || "server-generated"}
                        {evidenceDetail.provenance.event_type
                          ? ` · ${evidenceDetail.provenance.event_type}`
                          : ""}
                        {evidenceDetail.provenance.tracking_id
                          ? ` · track ${evidenceDetail.provenance.tracking_id}`
                          : ""}
                      </p>
                    )}
                  </div>
                )}
                {evidenceLoading && (
                  <div className="flex items-center gap-2 py-2 text-xs text-slate-400">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading evidence…
                  </div>
                )}
                {!evidenceLoading && evidence.length === 0 && (
                  <p className="py-6 text-center text-xs text-slate-500">
                    No evidence captured in this session yet.
                  </p>
                )}
                <div className="space-y-2">
                  {evidence.map((row) => (
                    <div
                      key={row.id}
                      className="rounded-lg border border-slate-200 p-2 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <Badge variant={evidenceTypeVariant(row.evidence_type)}>
                          {row.evidence_type}
                        </Badge>
                        <span className="truncate font-medium text-navy">{row.public_id}</span>
                        <Badge variant={indexVariant(row.index_status)}>{row.index_status}</Badge>
                      </div>
                      <p className="mt-1 truncate text-slate-500">
                        {row.captured_at
                          ? new Date(row.captured_at).toLocaleString()
                          : "no timestamp"}
                        {" · "}frame {row.frame_sequence ?? "—"}
                        {row.event_type ? ` · ${row.event_type}` : ""}
                        {row.vlm_observation_id ? ` · obs ${row.vlm_observation_id}` : ""}
                      </p>
                      <div className="mt-1.5 flex items-center justify-between gap-2">
                        <span className="truncate text-slate-400">
                          {row.content_text?.slice(0, 90) || "—"}
                        </span>
                        <span className="flex shrink-0 gap-1">
                          {row.storage_path && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 px-2 text-[10px]"
                              onClick={() => openEvidencePreview(row)}
                            >
                              <Eye className="h-3 w-3" /> view
                            </Button>
                          )}
                          {row.index_status === "FAILED" && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-6 px-2 text-[10px]"
                              onClick={() => reindexEvidence(row)}
                            >
                              <RefreshCw className="h-3 w-3" /> reindex
                            </Button>
                          )}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Active Live Sessions</CardTitle>
              <Button variant="ghost" size="sm" onClick={loadLiveList}>
                <RefreshCw className="h-4 w-4" /> Refresh
              </Button>
            </CardHeader>
            <CardContent className="pt-0">
              {liveList.length === 0 && (
                <p className="py-8 text-center text-sm text-slate-500">
                  No active live sessions right now.
                </p>
              )}
              <div className="space-y-2">
                {liveList.map((s) => (
                  <div
                    key={s.camera_id}
                    className="flex items-center justify-between rounded-lg border border-slate-200 p-3 text-sm"
                  >
                    <div>
                      <p className="font-medium text-navy">{s.camera_name || `Camera ${s.camera_id}`}</p>
                      <p className="text-xs text-slate-500">
                        {s.frames_received} received · {s.frames_buffered} buffered · {s.transport}
                      </p>
                    </div>
                    <Badge variant={statusVariant(s.status)}>{s.status}</Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </ProtectedShell>
  );
}
