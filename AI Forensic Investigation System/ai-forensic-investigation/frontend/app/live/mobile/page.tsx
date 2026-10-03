"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Video, VideoOff, Loader2, Smartphone, ShieldCheck } from "lucide-react";

import { wsUrl } from "@/lib/api";

/**
 * QR-paired mobile camera page.
 *
 * The desktop console generates a single-use pairing (POST /live/cameras/{id}/pair)
 * and renders it as a QR code. Scanning it opens this page with
 * `?pair=<pairing_id>`; the phone presents the code over the signaling WebSocket
 * (no JWT is needed) and streams its camera over WebRTC into the investigation
 * pipeline for THAT camera only. The code cannot be reused after the first
 * connection and expires after a few minutes server-side.
 */
export default function LiveMobilePage() {
  const [pair, setPair] = useState<string | null>(null);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [state, setState] = useState<"idle" | "connecting" | "streaming" | "stopped">("idle");
  const [error, setError] = useState<string | null>(null);
  const [pcState, setPcState] = useState("");

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const sigWsRef = useRef<WebSocket | null>(null);
  const sigOpenRef = useRef(false);
  const [facing, setFacing] = useState<"environment" | "user">("environment");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = q.get("pair");
    setPair(p);
    const c = q.get("camera_id");
    setCameraId(c ? Number(c) : null);
  }, []);

  const stop = useCallback(() => {
    const ws = sigWsRef.current;
    sigWsRef.current = null;
    if (ws) {
      try {
        if (sigOpenRef.current) ws.send(JSON.stringify({ type: "bye" }));
      } catch {
        /* ignore */
      }
      try {
        ws.close();
      } catch {
        /* ignore */
      }
    }
    sigOpenRef.current = false;
    const pc = pcRef.current;
    pcRef.current = null;
    if (pc) {
      try {
        pc.close();
      } catch {
        /* ignore */
      }
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setPcState("");
  }, []);

  const start = useCallback(async () => {
    if (!pair || !cameraId) {
      setError("Missing pairing code or camera id. Re-scan the QR code shown on the camera console.");
      return;
    }
    setError(null);
    setState("connecting");

    let stream: MediaStream;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError("Camera access requires a secure context (HTTPS or localhost). Open this page over HTTPS.");
      setState("idle");
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 1280 } },
        audio: false,
      });
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError") setError("Camera permission denied. Allow camera access and retry.");
      else if (name === "NotFoundError") setError("No camera device found on this device.");
      else if (name === "NotReadableError") setError("Camera is in use by another application.");
      else setError(`Could not access camera: ${e instanceof Error ? e.message : String(e)}`);
      setState("idle");
      return;
    }
    streamRef.current = stream;
    if (videoRef.current) videoRef.current.srcObject = stream;

    const pc = new RTCPeerConnection();
    pcRef.current = pc;
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    pc.onicecandidate = (e) => {
      if (!e.candidate || !sigOpenRef.current || !sigWsRef.current) return;
      sigWsRef.current.send(
        JSON.stringify({
          type: "trickle",
          candidate: {
            candidate: e.candidate.candidate,
            sdpMid: e.candidate.sdpMid,
            sdpMLineIndex: e.candidate.sdpMLineIndex,
          },
        }),
      );
    };
    pc.onconnectionstatechange = () => {
      setPcState(pc.connectionState);
      if (pc.connectionState === "failed") {
        setError("WebRTC connection failed. Try again or generate a new QR code.");
        setState("stopped");
      }
    };

    const ws = new WebSocket(wsUrl(`/live/cameras/${cameraId}/ws/signaling`));
    sigWsRef.current = ws;
    ws.onopen = () => {
      sigOpenRef.current = true;
      ws.send(JSON.stringify({ type: "auth", pair }));
    };
    ws.onclose = () => {
      sigOpenRef.current = false;
      if (sigWsRef.current === ws) sigWsRef.current = null;
    };
    ws.onmessage = async (ev) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      if (msg.type === "auth_ok") {
        setState("streaming");
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
        const candidate = msg.candidate as {
          candidate?: string;
          sdpMid?: string | null;
          sdpMLineIndex?: number | null;
        } | null;
        const pcNow = pcRef.current;
        if (pcNow && candidate?.candidate) {
          try {
            await pcNow.addIceCandidate({
              candidate: candidate.candidate,
              sdpMid: candidate.sdpMid ?? null,
              sdpMLineIndex: candidate.sdpMLineIndex ?? null,
            });
          } catch {
            /* late/duplicate candidates are normal */
          }
        }
      } else if (msg.type === "error") {
        setError(String(msg.detail ?? "Signaling error"));
        setState("stopped");
      }
    };
  }, [facing, pair, cameraId]);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return (
    <main className="flex min-h-screen flex-col bg-slate-950 text-white">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <Smartphone className="h-5 w-5 text-cyan-400" />
          <h1 className="text-sm font-semibold tracking-wide">Paired Camera Stream</h1>
        </div>
        {pair ? (
          <span className="flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-1 text-xs text-emerald-300">
            <ShieldCheck className="h-3.5 w-3.5" /> QR paired
          </span>
        ) : (
          <span className="rounded-full bg-amber-500/10 px-2 py-1 text-xs text-amber-300">No pairing code</span>
        )}
      </header>

      <section className="flex flex-1 flex-col items-center justify-center gap-4 p-4">
        <div className="relative aspect-video w-full max-w-3xl overflow-hidden rounded-xl bg-black">
          <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-contain" />
          {state !== "streaming" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-500">
              <Video className="h-10 w-10" />
              <p className="text-sm">
                {state === "connecting" ? "Connecting to the investigation pipeline…" : "Ready"}
              </p>
            </div>
          )}
        </div>

        {error && (
          <p className="max-w-2xl rounded-md bg-red-500/10 p-3 text-center text-sm text-red-300">{error}</p>
        )}

        <div className="flex items-center gap-3">
          {state === "streaming" ? (
            <button
              onClick={() => {
                stop();
                setState("stopped");
              }}
              className="inline-flex items-center gap-2 rounded-lg bg-red-500 px-4 py-2 text-sm font-medium hover:bg-red-600"
            >
              <VideoOff className="h-4 w-4" /> Stop
            </button>
          ) : (
            <button
              onClick={() => void start()}
              disabled={state === "connecting" || !pair}
              className="inline-flex items-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {state === "connecting" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Video className="h-4 w-4" />
              )}
              {state === "connecting" ? "Connecting…" : "Start streaming"}
            </button>
          )}
          <button
            onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
            disabled={state === "connecting"}
            className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-50"
          >
            Switch camera
          </button>
        </div>

        {pcState && (
          <p className="text-xs text-slate-500">
            Peer state: <span className="font-mono">{pcState}</span>
          </p>
        )}
      </section>
    </main>
  );
}