"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Search,
  ShieldAlert,
  Loader2,
  Play,
  Frame,
  FileSearch,
  ListChecks,
  Camera,
  Timer,
  MapPin,
  ExternalLink,
} from "lucide-react";
import {
  api,
  RAGResult,
  PolicyQuestion,
  EvidenceCard,
  Finding,
  Video,
} from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function InvestigatePage() {
  const [query, setQuery] = useState("");
  const [videoId, setVideoId] = useState<string>("");
  const [videos, setVideos] = useState<Video[]>([]);
  const [busy, setBusy] = useState<"rag" | "policy" | null>(null);
  const [rag, setRag] = useState<RAGResult | null>(null);
  const [policy, setPolicy] = useState<PolicyQuestion | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.videos().then(setVideos).catch(() => {});
    api.findings().then(setFindings).catch(() => {});
  }, []);

  async function runRag() {
    setError("");
    if (!query.trim()) return;
    setBusy("rag");
    try {
      setPolicy(null);
      const res = await api.ragQuery({
        query: query.trim(),
        video_id: videoId ? Number(videoId) : null,
      });
      setRag(res);
      api.findings().then(setFindings).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function runPolicy() {
    setError("");
    if (!query.trim()) return;
    setBusy("policy");
    try {
      setRag(null);
      const res = await api.policyQuestion({
        question: query.trim(),
        video_id: videoId ? Number(videoId) : null,
      });
      setPolicy(res);
      api.findings().then(setFindings).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function openClip(e: EvidenceCard) {
    if (e.clip_id == null) return;
    try {
      const m = await api.clipMedia(e.clip_id);
      window.open(m.url, "_blank");
    } catch {
      /* ignore */
    }
  }

  function frameLink(e: EvidenceCard) {
    if (e.video_id == null) return "#";
    return `/videos/${e.video_id}?t=${Math.floor(e.start_time || e.timestamp || 0)}`;
  }

  function statusTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "UNKNOWN") return <Badge variant="danger">UNKNOWN</Badge>;
    if (s === "POLICY-ASSESSED") return <Badge variant="warning">POLICY-ASSESSED</Badge>;
    if (s === "OBSERVED" || s === "VERIFIED") return <Badge variant="success">{status}</Badge>;
    if (s === "INFERRED") return <Badge>INFERRED</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">AI Investigation</h1>
        <p className="text-sm text-slate-500">
          Ask a natural-language question about captured video evidence and/or the security policy.
        </p>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      <Card className="mb-6">
        <CardContent className="p-5">
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runRag()}
              placeholder="e.g. Did anyone enter the restricted zone between 14:30 and 15:00?"
              className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <select
              value={videoId}
              onChange={(e) => setVideoId(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">All videos</option>
              {videos.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.filename}
                </option>
              ))}
            </select>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={runRag} disabled={busy != null || !query.trim()}>
              {busy === "rag" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Video Evidence Search
            </Button>
            <Button
              variant="outline"
              onClick={runPolicy}
              disabled={busy != null || !query.trim()}
            >
              {busy === "policy" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ShieldAlert className="h-4 w-4" />
              )}
              Policy Assessment
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Main result column */}
        <div className="space-y-6 lg:col-span-2">
          {rag && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <Search className="h-5 w-5 text-accent" /> Video RAG Result
                  </span>
                  {statusTone(rag.status)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="text-sm">
                  <p>
                    <span className="font-medium text-slate-600">Query:</span>{" "}
                    <span className="text-navy">{rag.query}</span>
                  </p>
                  {rag.analysis.entities.length > 0 && (
                    <p className="mt-1 text-slate-500">
                      <span className="font-medium">Entities:</span>{" "}
                      {rag.analysis.entities.join(", ")}
                    </p>
                  )}
                  {rag.analysis.events.length > 0 && (
                    <p className="mt-1 text-slate-500">
                      <span className="font-medium">Events:</span>{" "}
                      {rag.analysis.events.join(", ")}
                    </p>
                  )}
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800">
                  {rag.answer}
                </div>
                {rag.evidence.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-sm font-medium text-navy">
                      Supporting Evidence ({rag.evidence.length})
                    </p>
                    {rag.evidence.map((e) => (
                      <EvidenceCardView key={e.evidence_id} e={e} onClip={openClip} frameLink={frameLink} />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {policy && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2">
                    <ShieldAlert className="h-5 w-5 text-accent" /> Policy Assessment
                  </span>
                  {statusTone(policy.status)}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm text-slate-600">
                  <span className="font-medium">Question:</span>{" "}
                  <span className="text-navy">{policy.question}</span>
                </p>
                <div className="whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800">
                  {policy.description}
                </div>
                {policy.policy_sections.length > 0 && (
                  <div>
                    <p className="mb-2 text-sm font-medium text-navy">Policy Sections</p>
                    <ul className="space-y-2 text-sm">
                      {policy.policy_sections.map((p, i) => (
                        <li key={i} className="rounded-md border border-slate-200 p-3">
                          <p className="mb-1 inline-flex items-center gap-1 font-medium text-accent">
                            <FileSearch className="h-3 w-3" /> {p.document_name} · {p.section}
                            <span className="text-slate-400">({p.score.toFixed(3)})</span>
                          </p>
                          <p className="line-clamp-3 text-slate-600">{p.text}</p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {policy.evidence.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-sm font-medium text-navy">
                      Matched Evidence ({policy.evidence.length})
                    </p>
                    {policy.evidence.map((e) => (
                      <EvidenceCardView key={e.evidence_id} e={e} onClip={openClip} frameLink={frameLink} />
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {!rag && !policy && (
            <Card>
              <CardContent className="p-10 text-center text-sm text-slate-500">
                <FileSearch className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                Enter a question and choose a search mode to begin.
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar: findings */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ListChecks className="h-5 w-5 text-accent" /> Findings
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {findings.length === 0 && (
                <p className="py-6 text-center text-sm text-slate-500">No findings yet.</p>
              )}
              <ul className="space-y-2">
                {findings.map((f) => (
                  <li key={f.id} className="rounded-md border border-slate-200 p-3 text-sm">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-medium text-navy">{f.finding_status}</span>
                      <span className="text-xs text-slate-400">
                        {f.created_at ? new Date(f.created_at).toLocaleString() : ""}
                      </span>
                    </div>
                    {f.question && <p className="text-xs text-slate-500">Q: {f.question}</p>}
                    <p className="mt-1 line-clamp-3 text-xs text-slate-600">{f.description}</p>
                    {f.video_id != null && (
                      <Link
                        href={`/videos/${f.video_id}`}
                        className="mt-1 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                      >
                        Open video <ExternalLink className="h-3 w-3" />
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </ProtectedShell>
  );
}

function EvidenceCardView({
  e,
  onClip,
  frameLink,
}: {
  e: EvidenceCard;
  onClip: (e: EvidenceCard) => void;
  frameLink: (e: EvidenceCard) => string;
}) {
  const verified = e.verification?.verified;
  return (
    <div className="rounded-md border border-slate-200 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-semibold text-navy">{e.evidence_id}</span>
          {e.camera_name && (
            <Badge variant="muted">
              <Camera className="mr-1 h-3 w-3" /> {e.camera_name}
            </Badge>
          )}
          <Badge variant="muted">
            <Timer className="mr-1 h-3 w-3" /> {formatTime(e.timestamp ?? e.start_time)}
          </Badge>
          <Badge variant="default">
            score {e.retrieval_score.toFixed(3)}
          </Badge>
          {e.verification ? (
            <Badge variant={verified ? "success" : "danger"}>
              {verified ? "VERIFIED" : "UNVERIFIED"}
            </Badge>
          ) : (
            <Badge variant="muted">no verify</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Link href={frameLink(e)} target="_blank">
            <Button size="sm" variant="outline">
              <Frame className="h-3 w-3" /> Frame
            </Button>
          </Link>
          <Button size="sm" variant="outline" onClick={() => onClip(e)}>
            <Play className="h-3 w-3" /> Clip
          </Button>
        </div>
      </div>
      {e.description && (
        <p className="text-sm text-slate-700">
          <MapPin className="mr-1 inline h-3 w-3 text-accent" /> {e.description}
        </p>
      )}
      {e.objects.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          Objects: {e.objects.join(", ")}
        </p>
      )}
      {e.transcript && (
        <p className="mt-1 text-xs italic text-slate-500">Transcript: {e.transcript}</p>
      )}
      {e.verification?.reason && (
        <p className="mt-1 text-xs text-slate-500">Verify: {e.verification.reason}</p>
      )}
    </div>
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
