"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Upload, RefreshCw, ArrowRight, Video as VideoIcon } from "lucide-react";
import { api, Camera, Video, ApiError } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { statusBadge } from "@/components/ui/badge";

export default function VideosPage() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  // upload form state
  const [file, setFile] = useState<File | null>(null);
  const [cameraId, setCameraId] = useState("");
  const [cameraName, setCameraName] = useState("");
  const [location, setLocation] = useState("");
  const [recordingDate, setRecordingDate] = useState("");
  const [startTime, setStartTime] = useState("");
  const [description, setDescription] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      const [vs, cs] = await Promise.all([api.videos(), api.cameras().catch(() => [])]);
      setVideos(vs);
      setCameras(cs);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load videos");
    }
  }

  useEffect(() => {
    load();
    const interval = setInterval(() => {
      // Poll for processing videos
      setVideos((prev) => {
        if (prev.some((v) => v.status === "PROCESSING" || v.status === "QUEUED" || v.status === "UPLOADED")) {
          return prev; // trigger reload below
        }
        return prev;
      });
      api
        .videos()
        .then(setVideos)
        .catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  async function onUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Please select a video file");
      return;
    }
    setError("");
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      if (cameraId) form.append("camera_id", cameraId);
      if (cameraName) form.append("camera_name", cameraName);
      if (location) form.append("location", location);
      if (recordingDate) form.append("recording_date", new Date(recordingDate).toISOString());
      if (startTime) form.append("start_time", new Date(startTime).toISOString());
      if (description) form.append("description", description);
      await api.uploadVideo(form);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setFile(null);
      setCameraId("");
      setCameraName("");
      setLocation("");
      setDescription("");
      setRecordingDate("");
      setStartTime("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function formatDuration(sec?: number | null) {
    if (!sec) return "—";
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s
      .toString()
      .padStart(2, "0")}`;
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">Videos</h1>
        <p className="text-sm text-slate-500">
          Upload CCTV footage and track processing status.
        </p>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Upload form */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5 text-accent" /> Upload CCTV Video
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={onUpload} className="space-y-3">
              <div className="space-y-1">
                <label className="text-sm font-medium">Video file (mp4, mov, mkv, avi)</label>
                <Input
                  ref={fileInputRef}
                  type="file"
                  accept=".mp4,.mov,.mkv,.avi"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  required
                />
                {file && (
                  <p className="text-xs text-slate-500">
                    {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
                  </p>
                )}
              </div>

              {cameras.length > 0 && (
                <div className="space-y-1">
                  <label className="text-sm font-medium">Existing camera</label>
                  <Select value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
                    <option value="">— select camera —</option>
                    {cameras.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.camera_name} {c.location ? `(${c.location})` : ""}
                      </option>
                    ))}
                  </Select>
                </div>
              )}

              <div className="space-y-1">
                <label className="text-sm font-medium">Camera name (or create new)</label>
                <Input
                  value={cameraName}
                  onChange={(e) => setCameraName(e.target.value)}
                  placeholder="CAM-03"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Location</label>
                <Input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="Main entrance"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-sm font-medium">Recording date</label>
                  <Input
                    type="date"
                    value={recordingDate}
                    onChange={(e) => setRecordingDate(e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm font-medium">Start time</label>
                  <Input
                    type="datetime-local"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Description</label>
                <textarea
                  className="flex min-h-[70px] w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Incident context, notes..."
                />
              </div>

              <Button type="submit" className="w-full" disabled={uploading}>
                {uploading ? "Uploading..." : "Upload Video"}
              </Button>
              <p className="text-xs text-slate-400">
                Original footage is stored immutably. Processing runs in the background.
              </p>
            </form>
          </CardContent>
        </Card>

        {/* Video list */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Uploaded Videos</CardTitle>
            <Button variant="ghost" size="sm" onClick={load}>
              <RefreshCw className="h-4 w-4" /> Refresh
            </Button>
          </CardHeader>
          <CardContent className="pt-0">
            {videos.length === 0 && (
              <p className="py-10 text-center text-sm text-slate-500">
                No videos uploaded yet. Upload your first CCTV video.
              </p>
            )}
            <div className="space-y-3">
              {videos.map((v) => (
                <div
                  key={v.id}
                  className="flex items-center justify-between rounded-lg border border-slate-200 p-4"
                >
                  <div className="flex items-center gap-3">
                    <div className="rounded-md bg-navy/10 p-2 text-navy">
                      <VideoIcon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium text-navy">{v.filename}</p>
                      <p className="text-xs text-slate-500">
                        {v.camera_name || "No camera"} · {formatDuration(v.duration_seconds)}{" "}
                        · {v.uploaded_at ? new Date(v.uploaded_at).toLocaleString() : ""}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {statusBadge(v.status)}
                    <Link
                      href={`/videos/${v.id}`}
                      className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
                    >
                      Details <ArrowRight className="h-4 w-4" />
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </ProtectedShell>
  );
}
