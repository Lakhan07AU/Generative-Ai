"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Film, Box, ListOrdered, Activity, ExternalLink } from "lucide-react";
import { api, Video, Clip, Detection, Event, ProcessingJob } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { statusBadge } from "@/components/ui/badge";

export default function VideoDetailPage({
  params,
  searchParams,
}: {
  params: { id: string };
  searchParams: { t?: string };
}) {
  const videoId = Number(params.id);
  const seekParam = searchParams?.t ? Number(searchParams.t) : null;
  const [video, setVideo] = useState<Video | null>(null);
  const [status, setStatus] = useState<ProcessingJob | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [originalUrl, setOriginalUrl] = useState("");
  const [thumbUrls, setThumbUrls] = useState<Record<number, string>>({});
  const [clipUrls, setClipUrls] = useState<Record<number, string>>({});
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);

  async function loadDetail() {
    const [v, st, cl, de, ev] = await Promise.all([
      api.video(videoId),
      api.videoStatus(videoId).catch(() => null),
      api.clips(videoId).catch(() => []),
      api.detections(videoId).catch(() => []),
      api.events(videoId).catch(() => []),
    ]);
    setVideo(v);
    setStatus(st);
    setClips(cl);
    setDetections(de);
    setEvents(ev);
    if (v.status === "READY") {
      const orig = await api.originalMedia(videoId).catch(() => null);
      if (orig) setOriginalUrl(orig.url);
    }
  }

  useEffect(() => {
    loadDetail().catch((e) => setError(e.message));
    const interval = setInterval(async () => {
      try {
        const v = await api.video(videoId);
        setVideo(v);
        const st = await api.videoStatus(videoId).catch(() => null);
        setStatus(st);
        if (v.status === "READY") {
          loadDetail().catch(() => {});
        }
      } catch {
        /* ignore */
      }
    }, 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  useEffect(() => {
    if (clips.length === 0) return;
    let active = true;
    Promise.all(
      clips.map(async (c) => {
        if (c.thumbnail_path) {
          try {
            const m = await api.thumbnailMedia(c.id);
            return { id: c.id, type: "thumb" as const, url: m.url };
          } catch {
            return null;
          }
        }
        return null;
      })
    ).then((results) => {
      if (!active) return;
      const map: Record<number, string> = {};
      results.forEach((r) => {
        if (r) map[r.id] = r.url;
      });
      setThumbUrls(map);
    });
    return () => {
      active = false;
    };
  }, [clips]);

  const seekTo = useCallback((t?: number | null) => {
    if (t == null) return;
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = t;
    v.play().catch(() => {});
  }, []);

  useEffect(() => {
    if (seekParam == null) return;
    const v = videoRef.current;
    if (v && v.readyState >= 1) {
      seekTo(seekParam);
    } else {
      const t = setTimeout(() => seekTo(seekParam), 500);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekParam, originalUrl]);

  function loadClip(url: string, clipId: number) {
    if (!videoRef.current) return;
    videoRef.current.src = url;
    videoRef.current.play().catch(() => {});
    setClipUrls((prev) => ({ ...prev, [clipId]: url }));
  }

  function formatTime(sec?: number | null) {
    if (sec == null) return "—";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s
      .toString()
      .padStart(2, "0")}`;
  }

  function formatDuration(sec?: number | null) {
    return formatTime(sec);
  }

  const isProcessing =
    video &&
    (video.status === "PROCESSING" ||
      video.status === "QUEUED" ||
      video.status === "UPLOADED");

  return (
    <ProtectedShell>
      <Link
        href="/videos"
        className="mb-4 inline-flex items-center gap-1 text-sm text-accent hover:underline"
      >
        <ArrowLeft className="h-4 w-4" /> Back to videos
      </Link>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      {!video && !error && <p className="text-slate-500">Loading...</p>}

      {video && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-navy">{video.filename}</h1>
              <p className="text-sm text-slate-500">
                {video.camera_name || "No camera"} · {formatDuration(video.duration_seconds)} ·{" "}
                {video.uploaded_at ? new Date(video.uploaded_at).toLocaleString() : ""}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-500">Status:</span>
              {statusBadge(video.status)}
            </div>
          </div>

          {isProcessing && (
            <Card>
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-600">
                    Processing: stage <strong>{status?.stage || "..."}</strong>
                  </span>
                  <span className="font-medium text-navy">
                    {Math.round(status?.progress ?? 0)}%
                  </span>
                </div>
                <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-200">
                  <div
                    className="h-full rounded-full bg-accent transition-all"
                    style={{ width: `${Math.round(status?.progress ?? 0)}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  Scene detection, clip extraction, object detection and tracking run in the
                  background.
                </p>
              </CardContent>
            </Card>
          )}

          {video.status === "FAILED" && (
            <Card className="border-red-200 bg-red-50">
              <CardContent className="p-5 text-sm text-red-700">
                Processing failed: {status?.error || "Unknown error"}. You can retry from the
                videos page.
              </CardContent>
            </Card>
          )}
          {video.status === "FAILED" && (
            <Button
              onClick={async () => {
                await api.processVideo(videoId);
                loadDetail();
              }}
            >
              Retry Processing
            </Button>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Meta + player */}
            <Card>
              <CardHeader>
                <CardTitle>Video & Metadata</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <video
                  ref={videoRef}
                  controls
                  className="aspect-video w-full rounded-md border border-slate-200 bg-black"
                  src={originalUrl || undefined}
                />
                {video.status === "READY" && !originalUrl && (
                  <p className="text-sm text-slate-500">Loading video stream...</p>
                )}
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <MetaItem label="Resolution" value={`${video.width || "—"} × ${video.height || "—"}`} />
                  <MetaItem label="FPS" value={video.fps?.toFixed(1) ?? "—"} />
                  <MetaItem label="Duration" value={formatDuration(video.duration_seconds)} />
                  <MetaItem label="Codec" value={video.codec || "—"} />
                  <MetaItem label="Recording date" value={video.recording_date ? new Date(video.recording_date).toLocaleDateString() : "—"} />
                  <MetaItem label="Start time" value={video.start_time ? new Date(video.start_time).toLocaleString() : "—"} />
                </div>
                {video.description && (
                  <div>
                    <p className="mb-1 text-sm font-medium">Description</p>
                    <p className="text-sm text-slate-600">{video.description}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Clips */}
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Film className="h-5 w-5 text-accent" /> Extracted Clips
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {clips.length === 0 && (
                  <p className="py-6 text-center text-sm text-slate-500">
                    {video.status === "READY"
                      ? "No clips extracted."
                      : "Will appear after processing."}
                  </p>
                )}
                {clips.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center gap-3 rounded-md border border-slate-200 p-2"
                  >
                    {thumbUrls[c.id] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={thumbUrls[c.id]}
                        alt={c.public_id}
                        className="h-16 w-24 rounded object-cover"
                      />
                    ) : (
                      <div className="flex h-16 w-24 items-center justify-center rounded bg-slate-100 text-xs text-slate-400">
                        {c.public_id}
                      </div>
                    )}
                    <div className="flex-1">
                      <p className="text-sm font-medium text-navy">{c.public_id}</p>
                      <p className="text-xs text-slate-500">
                        {formatTime(c.start_time)} → {formatTime(c.end_time)}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        if (!clipUrls[c.id]) {
                          try {
                            const m = await api.clipMedia(c.id);
                            loadClip(m.url, c.id);
                          } catch {
                            /* ignore */
                          }
                        } else {
                          loadClip(clipUrls[c.id], c.id);
                        }
                      }}
                    >
                      <ExternalLink className="h-3 w-3" /> Play
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Detections */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Box className="h-5 w-5 text-accent" /> Detections
                <span className="text-sm font-normal text-slate-500">
                  (click a detection to jump to its timestamp)
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {detections.length === 0 && (
                <p className="py-6 text-center text-sm text-slate-500">
                  {video.status === "READY"
                    ? "No objects detected."
                    : "Detections will appear after processing."}
                </p>
              )}
              {detections.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-slate-500">
                        <th className="py-2 pr-4">Timestamp</th>
                        <th className="py-2 pr-4">Label</th>
                        <th className="py-2 pr-4">Tracking ID</th>
                        <th className="py-2 pr-4">Confidence</th>
                        <th className="py-2">Frame</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detections.map((d) => (
                        <tr
                          key={d.id}
                          onClick={() => seekTo(d.timestamp)}
                          className="cursor-pointer border-b last:border-0 hover:bg-accent/5"
                        >
                          <td className="py-2 pr-4 font-mono text-accent">
                            {formatTime(d.timestamp)}
                          </td>
                          <td className="py-2 pr-4 capitalize">{d.label}</td>
                          <td className="py-2 pr-4 font-mono text-slate-600">
                            {d.tracking_id || "—"}
                          </td>
                          <td className="py-2 pr-4">
                            {d.detection_confidence != null
                              ? `${(d.detection_confidence * 100).toFixed(0)}%`
                              : "—"}
                          </td>
                          <td className="py-2 text-slate-500">{d.frame_number ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Events */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-accent" /> Events
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {events.length === 0 && (
                <p className="py-6 text-center text-sm text-slate-500">
                  {video.status === "READY"
                    ? "No events detected."
                    : "Events will appear after processing."}
                </p>
              )}
              <div className="space-y-2">
                {events.map((ev) => (
                  <div
                    key={ev.id}
                    onClick={() => seekTo(ev.start_time)}
                    className="flex cursor-pointer items-center gap-3 rounded-md border border-slate-200 p-3 hover:bg-accent/5"
                  >
                    <ListOrdered className="h-4 w-4 text-accent" />
                    <div className="flex-1">
                      <p className="text-sm font-medium text-navy">{ev.event_type}</p>
                      <p className="text-xs text-slate-500">{ev.description}</p>
                    </div>
                    <span className="font-mono text-sm text-accent">
                      {formatTime(ev.start_time)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </ProtectedShell>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="font-medium text-navy">{value}</p>
    </div>
  );
}
