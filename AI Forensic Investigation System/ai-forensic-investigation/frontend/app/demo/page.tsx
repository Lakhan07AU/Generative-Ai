"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Play, AlertTriangle, Film, FolderOpen, Image as ImageIcon, Activity, CheckCircle2, XCircle, Clock } from "lucide-react";
import { api, ApiError, DemoCase, DemoManifest, DemoScenario } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

function statusBadge(status?: string | null) {
  if (!status) return <Badge variant="muted">not uploaded</Badge>;
  const s = String(status).toUpperCase();
  if (s === "READY" || s === "COMPLETED" || s === "PROCESSED") {
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> {status}
      </Badge>
    );
  }
  if (s === "PROCESSING" || s === "PENDING" || s === "UPLOADED") {
    return (
      <Badge variant="warning" className="gap-1">
        <Clock className="h-3 w-3" /> {status}
      </Badge>
    );
  }
  return (
    <Badge variant="danger" className="gap-1">
      <XCircle className="h-3 w-3" /> {status}
    </Badge>
  );
}

export default function DemoPage() {
  const [manifest, setManifest] = useState<DemoManifest | null>(null);
  const [cases, setCases] = useState<DemoCase[]>([]);
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [expandedScenario, setExpandedScenario] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.demoDataset().catch(() => null),
      api.demoCases().catch(() => [] as DemoCase[]),
      api.demoScenarios().catch(() => [] as DemoScenario[]),
    ])
      .then(([m, c, s]) => {
        setManifest(m);
        setCases(c);
        setScenarios(s);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load demo dataset"));
  }, []);

  const videoByDemoId = new Map((manifest?.videos || []).map((v) => [v.demo_id, v]));

  return (
    <ProtectedShell>
      <div className="space-y-6">
        <div className="rounded-md border-2 border-amber-400 bg-amber-50 px-4 py-3">
          <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <AlertTriangle className="h-4 w-4" />
            DEMO DATA — NOT REAL FORENSIC EVIDENCE
          </p>
          <p className="mt-1 text-sm text-amber-800">
            This dataset and its {manifest?.videos.length || 0} demo videos and{" "}
            {cases.length} cases are demonstrations built from publicly licensed
            sample media. Nothing here is real investigative evidence and must not
            be treated as such.
          </p>
        </div>

        <div>
          <h1 className="text-2xl font-semibold text-navy">Demo Investigation Dataset</h1>
          <p className="text-sm text-slate-500">
            Real video files (CV2 → detection → tracking → VLM → evidence → RAG → agent) with honest,
            measured results. Pick a video and run it through the live pipeline.
          </p>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {manifest && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Film className="h-5 w-5 text-accent" /> Source Videos
                <span className="ml-auto text-sm font-normal text-slate-400">
                  {manifest.videos.length} files
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {manifest.videos.map((v) => (
                  <div key={v.demo_id} className="flex flex-col overflow-hidden rounded-lg border border-slate-200">
                    <div className="relative aspect-video w-full overflow-hidden bg-slate-900">
                      {v.demo_id ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={api.demoThumbnailUrl(v.demo_id)}
                          alt={v.filename}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-slate-500">
                          <ImageIcon className="h-8 w-8" />
                        </div>
                      )}
                      <div className="absolute left-1.5 top-1.5">
                        <span className="rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-white">
                          {v.demo_id}
                        </span>
                      </div>
                      <div className="absolute bottom-1.5 right-1.5 flex items-center gap-1">
                        {statusBadge(v.status)}
                      </div>
                    </div>
                    <div className="flex flex-1 flex-col p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-slate-800">{v.filename}</span>
                        <Badge>{v.scene_archetype || "video"}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-slate-500">
                        {v.width && v.height ? `${v.width}×${v.height} · ` : ""}
                        {v.duration ? `${v.duration.toFixed(1)}s` : ""}
                        {v.fps ? ` · ${v.fps} fps` : ""}
                      </p>
                      {v.stable_name && (
                        <p className="mt-1 font-mono text-[11px] text-slate-400">→ {v.stable_name}</p>
                      )}
                      {v.scenario_keys && v.scenario_keys.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {v.scenario_keys.map((k) => (
                            <span
                              key={k}
                              className="rounded bg-cyan-50 px-1.5 py-0.5 text-[10px] font-medium text-cyan-700"
                            >
                              {k}
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="mt-2 line-clamp-2 text-xs text-slate-500">{v.description}</p>
                      <p className="mt-2 text-[11px] text-slate-400">{v.license}</p>
                      <Link
                        href={`/live?demo=${encodeURIComponent(v.filename)}`}
                        className="mt-3 inline-flex h-8 w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-xs font-medium transition-colors hover:bg-slate-50"
                      >
                        <Play className="h-4 w-4" /> Run in Live
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {scenarios.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-accent" /> Scenarios (12)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 md:grid-cols-2">
                {scenarios.map((s) => (
                  <div key={s.scenario_id} className="rounded-lg border border-slate-200 p-3">
                    <button
                      className="flex w-full items-start justify-between gap-2 text-left"
                      onClick={() => setExpandedScenario(expandedScenario === s.scenario_id ? null : s.scenario_id)}
                    >
                      <div>
                        <p className="font-mono text-xs font-semibold text-navy">{s.scenario_id}</p>
                        <p className="mt-0.5 text-sm font-medium text-slate-800">{s.title}</p>
                      </div>
                      <span className="shrink-0 text-xs text-slate-400">
                        {expandedScenario === s.scenario_id ? "▾" : "▸"}
                      </span>
                    </button>
                    <p className="mt-1 text-xs text-slate-500">{s.purpose}</p>
                    <p className="mt-1 font-mono text-[11px] text-slate-400">{s.stable_name}</p>
                    {expandedScenario === s.scenario_id && (
                      <div className="mt-2 space-y-1 border-t border-slate-100 pt-2 text-xs">
                        <p className="text-slate-600">
                          <span className="font-medium">Event expectation:</span> {s.event_expectation}
                        </p>
                        {s.videos && s.videos.length > 0 && (
                          <p className="text-slate-500">
                            <span className="font-medium">Backing videos:</span>{" "}
                            {s.videos.map((v) => v.demo_id).join(", ")}
                          </p>
                        )}
                        {s.observed_questions && s.observed_questions.length > 0 && (
                          <div className="space-y-0.5 text-slate-600">
                            <p className="font-medium text-emerald-700">OBSERVED-style questions</p>
                            {s.observed_questions.map((q) => (
                              <p key={q}>• {q}</p>
                            ))}
                          </div>
                        )}
                        {s.unknown_questions && s.unknown_questions.length > 0 && (
                          <div className="space-y-0.5 text-slate-600">
                            <p className="font-medium text-slate-500">UNKNOWN (must abstain)</p>
                            {s.unknown_questions.map((q) => (
                              <p key={q}>• {q}</p>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-accent" /> Demo Cases
            </CardTitle>
          </CardHeader>
          <CardContent>
            {cases.length === 0 ? (
              <p className="text-sm text-slate-500">No demo cases loaded.</p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {cases.map((c) => {
                  const src = videoByDemoId.get(String(c.video_demo_id || ""));
                  return (
                    <div key={c.case_id} className="rounded-lg border border-slate-200 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs font-semibold text-navy">{c.case_id}</p>
                        {c.priority === "high" && <Badge variant="warning">high priority</Badge>}
                      </div>
                      <p className="mt-1 text-sm font-medium text-slate-800">{c.title}</p>
                      <p className="mt-1 text-sm text-slate-600">{c.description}</p>
                      <p className="mt-2 text-xs text-slate-500">
                        Source: {c.video_file}
                        {src?.status ? ` · status: ${src.status}` : ""}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">Query: {c.query}</p>
                      <Link
                        href={`/live?demo=${encodeURIComponent(c.video_file)}`}
                        className="mt-3 inline-flex h-8 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-xs font-medium transition-colors hover:bg-slate-50"
                      >
                        <Play className="h-4 w-4" /> Run case in Live
                      </Link>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </ProtectedShell>
  );
}