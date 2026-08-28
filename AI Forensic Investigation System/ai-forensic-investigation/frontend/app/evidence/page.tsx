"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Loader2,
  FileSearch,
  RefreshCw,
  ShieldCheck,
  Timer,
  ExternalLink,
  Film,
} from "lucide-react";
import { api, EvidenceClaimRow, Video } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function EvidencePage() {
  const [claims, setClaims] = useState<EvidenceClaimRow[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setBusy(true);
    setError("");
    try {
      const [cs, vs] = await Promise.all([
        api.evidenceClaims(),
        api.videos().catch(() => [] as Video[]),
      ]);
      setClaims(cs);
      setVideos(vs);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function statusTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "VERIFIED") return <Badge variant="success">VERIFIED</Badge>;
    if (s === "PARTIALLY_VERIFIED") return <Badge variant="warning">PARTIALLY_VERIFIED</Badge>;
    if (s === "INSUFFICIENT_EVIDENCE") return <Badge variant="danger">INSUFFICIENT_EVIDENCE</Badge>;
    if (s === "OBSERVATION") return <Badge variant="default">OBSERVATION</Badge>;
    if (s === "INFERENCE") return <Badge>INFERENCE</Badge>;
    if (s === "REJECTED") return <Badge variant="danger">REJECTED</Badge>;
    if (s === "OPEN") return <Badge variant="warning">OPEN</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  function clipLink(clipId?: number | null, videoId?: number | null, timestamp?: number | null) {
    if (clipId == null && videoId == null) return "#";
    if (videoId != null) return `/videos/${videoId}?t=${Math.floor(timestamp || 0)}`;
    return "#";
  }

  return (
    <ProtectedShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-navy">Evidence Workspace</h1>
          <p className="text-sm text-slate-500">
            Unified view of every claim, its supporting evidence, and verification result for
            human review.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Refresh
        </Button>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      {claims.length === 0 && !busy && (
        <Card>
          <CardContent className="p-12 text-center text-sm text-slate-500">
            <FileSearch className="mx-auto mb-2 h-8 w-8 text-slate-300" />
            No claims recorded yet. Run an investigation or RAG query to generate evidence-backed
            claims.
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {claims.map((c) => (
          <Card key={c.claim_id}>
            <CardHeader className="flex flex-row items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-5 w-5 text-accent" />
                Claim #{c.claim_id}
              </CardTitle>
              <div className="flex items-center gap-2">
                {statusTone(c.status)}
                <Badge variant={c.claim_type === "OBSERVATION" ? "default" : "muted"}>
                  {c.claim_type}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-sm leading-relaxed text-slate-800">{c.claim_text}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
                  {c.investigation_id != null && (
                    <Link
                      href={`/investigations/${c.investigation_id}`}
                      className="inline-flex items-center gap-1 text-accent hover:underline"
                    >
                      Investigation #{c.investigation_id} <ExternalLink className="h-3 w-3" />
                    </Link>
                  )}
                  {c.created_at && (
                    <span>{new Date(c.created_at).toLocaleString()}</span>
                  )}
                  {c.confidence != null && (
                    <span>Confidence: {c.confidence.toFixed(2)}</span>
                  )}
                </div>
              </div>

              {/* Verification */}
              {c.verification && (
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <p className="mb-1 text-sm font-medium text-navy">Verification Result</p>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    {statusTone(c.verification.result || c.status)}
                    {c.verification.verifier_version && (
                      <Badge variant="muted">{c.verification.verifier_version}</Badge>
                    )}
                  </div>
                  {c.verification.reason && (
                    <p className="mt-1 text-xs text-slate-500">{c.verification.reason}</p>
                  )}
                  {c.verification.checks && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(c.verification.checks).map(([k, v]) => {
                        const val = v as { passed?: boolean };
                        return (
                          <Badge key={k} variant={val?.passed ? "success" : "danger"}>
                            {k}: {val?.passed ? "PASS" : "FAIL"}
                          </Badge>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Evidence links */}
              {c.evidence.length > 0 && (
                <div>
                  <p className="mb-2 text-sm font-medium text-navy">
                    Evidence ({c.evidence.length})
                  </p>
                  <ul className="space-y-2">
                    {c.evidence.map((ev) => (
                      <li
                        key={ev.evidence_id}
                        className="rounded-md border border-slate-200 p-3 text-sm"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-xs font-semibold text-navy">
                            EVID-{ev.evidence_id}
                          </span>
                          <Badge variant="muted">{ev.evidence_type || "clip"}</Badge>
                          <Badge variant="muted">
                            <Timer className="mr-1 h-3 w-3" />
                            {formatTime(ev.timestamp)}
                          </Badge>
                          {ev.relevance_score != null && (
                            <Badge variant="default">relevance {ev.relevance_score.toFixed(3)}</Badge>
                          )}
                        </div>
                        {ev.clip_public_id && (
                          <p className="mt-1 text-xs text-slate-500">
                            Clip: {ev.clip_public_id}
                            {ev.source_clip && (
                              <span>
                                {" "}
                                ({formatTime(ev.source_clip.start_time)} –{" "}
                                {formatTime(ev.source_clip.end_time)})
                              </span>
                            )}
                          </p>
                        )}
                        {ev.video_id != null && (
                          <Link
                            href={clipLink(ev.clip_id, ev.video_id, ev.timestamp)}
                            target="_blank"
                            className="mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                          >
                            <Film className="h-3 w-3" /> View source
                          </Link>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Policy references */}
              {c.policy_references.length > 0 && (
                <div>
                  <p className="mb-2 text-sm font-medium text-navy">Policy References</p>
                  <ul className="space-y-2">
                    {c.policy_references.map((p) => (
                      <li key={p.finding_id} className="rounded-md border border-slate-200 p-3 text-sm">
                        <p className="inline-flex items-center gap-1 font-medium text-accent">
                          <FileSearch className="h-3 w-3" />
                          {p.document_name}
                          <span className="text-slate-400">(POL-{p.policy_id})</span>
                          <Badge variant="muted">{p.status}</Badge>
                        </p>
                        {p.description && (
                          <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                            {p.description}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {c.evidence.length === 0 && c.policy_references.length === 0 && (
                <p className="text-xs text-slate-400">No direct evidence or policy links.</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </ProtectedShell>
  );
}

function formatTime(sec?: number | null) {
  if (sec == null || Number.isNaN(sec)) return "—";
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${ss
    .toString()
    .padStart(2, "0")}`;
}
