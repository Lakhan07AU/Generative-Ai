"use client";

import { useEffect, useState } from "react";
import {
  Search,
  Loader2,
  FileSearch,
  Camera,
  Timer,
  Fingerprint,
  Tag,
  ShieldQuestion,
} from "lucide-react";
import {
  api,
  Investigation,
  InvestigationSearchResult,
  InvestigationSearchEvidence,
} from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [caseId, setCaseId] = useState<string>("");
  const [cases, setCases] = useState<Investigation[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<InvestigationSearchResult | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.investigations().then(setCases).catch(() => {});
  }, []);

  async function runSearch() {
    setError("");
    if (!query.trim() || !caseId) return;
    setBusy(true);
    try {
      setResult(null);
      const res = await api.investigationSearch({
        query: query.trim(),
        case_id: Number(caseId),
      });
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function statusTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "ANSWERED") return <Badge variant="success">{status}</Badge>;
    if (s === "UNKNOWN") return <Badge variant="danger">{status}</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">Grounded Evidence Search</h1>
        <p className="text-sm text-slate-500">
          Ask a natural-language question about a case&apos;s live forensic evidence. Answers
          are grounded in verified evidence records only — identity, intent and
          outside-view questions are answered UNKNOWN.
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
              onKeyDown={(e) => e.key === "Enter" && caseId && runSearch()}
              placeholder="e.g. Was there a person present between 10:00 and 10:15?"
              className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
            <select
              value={caseId}
              onChange={(e) => setCaseId(e.target.value)}
              className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              <option value="">Select a case</option>
              {cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
            <Button onClick={runSearch} disabled={busy || !query.trim() || !caseId}>
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Search className="h-4 w-4" />
              )}
              Search
            </Button>
          </div>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                <ShieldQuestion className="h-5 w-5 text-accent" /> Result
              </span>
              <span className="flex items-center gap-2">
                {statusTone(result.status)}
                <span className="text-xs text-slate-400">
                  conf {result.confidence.toFixed(2)} · {result.results.length} evidence
                </span>
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-slate-600">
              <span className="font-medium">Query:</span>{" "}
              <span className="text-navy">{result.query}</span>
            </p>
            <div className="whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800">
              {result.answer}
            </div>

            {result.limitations && result.limitations.length > 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                <p className="mb-1 font-medium">Limitations</p>
                <ul className="list-inside list-disc space-y-1">
                  {result.limitations.map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
            )}

            {result.results.length > 0 && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-navy">
                  Supporting Evidence ({result.results.length})
                </p>
                {result.results.map((e) => (
                  <EvidenceRow key={e.evidence_id} e={e} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!result && !busy && (
        <Card>
          <CardContent className="p-10 text-center text-sm text-slate-500">
            <FileSearch className="mx-auto mb-2 h-8 w-8 text-slate-300" />
            Pick a case, ask a grounded question, and review the verified evidence.
          </CardContent>
        </Card>
      )}
    </ProtectedShell>
  );
}

function EvidenceRow({ e }: { e: InvestigationSearchEvidence }) {
  const [imgOpen, setImgOpen] = useState(false);
  return (
    <div className="rounded-md border border-slate-200 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-semibold text-navy">{e.evidence_id}</span>
          <Badge variant="muted">{e.evidence_type}</Badge>
          {e.camera_name && (
            <Badge variant="muted">
              <Camera className="mr-1 h-3 w-3" /> {e.camera_name}
            </Badge>
          )}
          {e.timestamp != null && (
            <Badge variant="muted">
              <Timer className="mr-1 h-3 w-3" /> {formatTime(e.timestamp)}
            </Badge>
          )}
          {e.object_class && (
            <Badge variant="default">
              <Tag className="mr-1 h-3 w-3" /> {e.object_class}
            </Badge>
          )}
          {e.tracking_id && (
            <Badge variant="warning">
              <Fingerprint className="mr-1 h-3 w-3" /> {e.tracking_id}
            </Badge>
          )}
          <Badge variant="default">score {(e.retrieval_score ?? 0).toFixed(3)}</Badge>
        </div>
        {e.storage_path && (
          <button
            onClick={() => setImgOpen((v) => !v)}
            className="rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            {imgOpen ? "Hide frame" : "Show frame"}
          </button>
        )}
      </div>

      {e.event_type && (
        <p className="text-sm text-slate-700">
          <span className="font-medium text-slate-500">event:</span> {e.event_type}
          {e.event_id ? <span className="ml-2 text-xs text-slate-400">({e.event_id})</span> : null}
        </p>
      )}
      {e.content_text && (
        <p className="mt-1 line-clamp-2 text-xs italic text-slate-500">{e.content_text}</p>
      )}
      {e.reasons && e.reasons.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          <span className="font-medium">why:</span> {e.reasons.join(", ")}
        </p>
      )}
      {imgOpen && (
        <div className="mt-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={api.liveEvidenceContentUrl(e.evidence_id)}
            alt={`evidence ${e.evidence_id}`}
            className="max-h-56 rounded-md border border-slate-200"
          />
        </div>
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