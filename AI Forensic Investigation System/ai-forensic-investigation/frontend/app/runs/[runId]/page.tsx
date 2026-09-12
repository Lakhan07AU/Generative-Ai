"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Loader2,
  Bot,
  Clock,
  ShieldCheck,
  AlertTriangle,
  SearchCheck,
  FileText,
  Download,
  GitBranch,
  ListChecks,
  Camera,
  CheckCircle2,
  XCircle,
  MinusCircle,
} from "lucide-react";
import {
  api,
  InvestigationRun,
  ForensicAnalysis,
  ForensicTimelineEntry,
  ForensicFinding,
  FindingReview,
  RunReview,
} from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function fmtTime(sec?: number | null): string {
  if (sec === null || sec === undefined) return "—";
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return [h, m, r].map((n) => String(n).padStart(2, "0")).join(":");
}

function confPct(conf?: number): string {
  if (conf === null || conf === undefined) return "—";
  return `${Math.round(conf * 100)}%`;
}

const REVIEW_ACTIONS = [
  { value: "ACCEPTED", label: "Accept" },
  { value: "REJECTED", label: "Reject" },
  { value: "MARKED_UNCERTAIN", label: "Uncertain" },
  { value: "REQUESTED_MORE_EVIDENCE", label: "Request more evidence" },
] as const;

export default function ForensicRunWorkspace({ params }: { params: { runId: string } }) {
  const runId = Number(params.runId);
  const [run, setRun] = useState<InvestigationRun | null>(null);
  const [forensic, setForensic] = useState<ForensicAnalysis | null>(null);
  const [reviews, setReviews] = useState<RunReview[]>([]);
  const [findingReviews, setFindingReviews] = useState<FindingReview[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [reviewFindingId, setReviewFindingId] = useState("");
  const [reportInfo, setReportInfo] = useState<string>("");

  async function load() {
    try {
      const [detail, fc] = await Promise.all([
        api.investigationRun(runId),
        api.forensicOfRun(runId).catch(() => null),
      ]);
      setRun(detail);
      if (fc) {
        setForensic(fc);
        setReportInfo(fc.status === "COMPLETED" ? "" : "Forensic analysis is still in progress.");
      }
      await loadReviews();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load run");
    }
  }

  async function loadReviews() {
    try {
      const r = await api.runReviews(runId);
      setReviews(r.run_reviews || []);
      setFindingReviews(r.finding_reviews || []);
    } catch {
      /* reviews are best-effort */
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function analyze() {
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      const fc = await api.forensicAnalyze(runId);
      setForensic(fc);
      setReportInfo("");
      await loadReviews();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Forensic analysis failed");
    } finally {
      setBusy(false);
    }
  }

  async function review(findingId: string, action: (typeof REVIEW_ACTIONS)[number]["value"]) {
    setError("");
    setReviewFindingId(findingId);
    try {
      await api.reviewFinding(runId, findingId, {
        action,
        comment: reviewComment.trim() || undefined,
      });
      setReviewComment("");
      await loadReviews();
      const fc = await api.forensicOfRun(runId).catch(() => null);
      if (fc) setForensic(fc);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    } finally {
      setReviewFindingId("");
    }
  }

  async function generateReport() {
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      const res = await api.generateForensicReport(runId);
      setReportInfo(`Report v${res.version} generated (${res.file_format}).`);
      await loadReviews();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Report generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport() {
    setError("");
    try {
      const file = await api.forensicReportFile(runId);
      const a = document.createElement("a");
      a.href = file.url;
      a.download = file.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    }
  }

  const sortedTimeline = useMemo(() => {
    if (!forensic) return [];
    return [...forensic.timeline].sort((a, b) => a.timestamp - b.timestamp);
  }, [forensic]);

  const findingReview = (findingId: string) =>
    findingReviews.filter((r) => r.finding_id === findingId).sort((a, b) => b.id - a.id)[0];

  function toneFor(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "COMPLETED" || s === "OBSERVED" || s === "VERIFIED" || s === "ACCEPTED")
      return <Badge variant="success">{status}</Badge>;
    if (s === "UNVERIFIED" || s === "INFERRED" || s === "UNKNOWN" || s === "REJECTED")
      return <Badge variant="danger">{status}</Badge>;
    if (s === "PENDING" || s === "PARTIAL")
      return <Badge variant="warning">{status}</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  function timelineRow(entry: ForensicTimelineEntry, i: number) {
    return (
      <div key={entry.timeline_event_id} className="flex gap-3">
        <div className="flex flex-col items-center">
          <span className="rounded bg-navy/10 px-2 py-0.5 font-mono text-xs text-navy">
            {fmtTime(entry.timestamp)}
          </span>
          {i < sortedTimeline.length - 1 && <span className="my-1 w-px flex-1 bg-slate-200" />}
        </div>
        <div className="mb-3 flex-1 rounded-md border border-slate-200 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-slate-500">{entry.timeline_event_id}</span>
            {toneFor(entry.verification_status)}
            <Badge variant="muted">{entry.classification}</Badge>
            {entry.camera_name && (
              <Badge variant="muted">
                <Camera className="mr-1 h-3 w-3" /> {entry.camera_name}
              </Badge>
            )}
            <span className="ml-auto text-xs text-slate-400">
              confidence {confPct(entry.confidence)} · source {entry.source ?? "?"}
            </span>
          </div>
          {entry.description && (
            <p className="mt-1 text-sm text-slate-700">{entry.description}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1 text-xs">
            {entry.track_id && (
              <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">track {entry.track_id}</span>
            )}
            {entry.object_class && (
              <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">{entry.object_class}</span>
            )}
            {entry.event_type && (
              <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">{entry.event_type}</span>
            )}
            {entry.evidence_ids?.map((eid) => (
              <span key={entry.timeline_event_id + eid} className="font-mono rounded bg-navy/5 px-2 py-0.5 text-slate-600">
                {eid}
              </span>
            ))}
          </div>
          {entry.end_timestamp !== null && entry.end_timestamp !== undefined && entry.end_timestamp !== entry.timestamp && (
            <p className="mt-1 text-xs text-slate-400">until {fmtTime(entry.end_timestamp)}</p>
          )}
          {entry.quality_flags?.map((q) => (
            <p key={entry.timeline_event_id + q} className="mt-0.5 text-xs text-amber-600">
              ⚠ {q}
            </p>
          ))}
          {entry.conflicts?.map((c) => (
            <p key={entry.timeline_event_id + c} className="mt-0.5 text-xs text-amber-700">
              ⚠ conflict: {c}
            </p>
          ))}
        </div>
      </div>
    );
  }

  function findingCard(f: ForensicFinding) {
    const reviewEntry = findingReview(f.finding_id);
    return (
      <div key={f.finding_id} className="rounded-md border border-slate-200 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs font-semibold text-slate-500">{f.finding_id}</span>
          {toneFor(f.verification_status)}
          <Badge variant="muted">{f.classification}</Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-slate-400">
            <ShieldCheck className="h-3 w-3" /> support {confPct(f.evidence_support)}
            {!f.causality_safe && (
              <span className="ml-2 inline-flex items-center gap-1 text-amber-600">
                <AlertTriangle className="h-3 w-3" /> no causal claim
              </span>
            )}
          </span>
        </div>
        <p className="mt-2 text-sm text-slate-700">{f.text}</p>
        {f.support_factors?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {f.support_factors.map((sf, i) => (
              <span
                key={i}
                title={`weight ${sf.weight}`}
                className={`rounded px-2 py-0.5 text-xs ${
                  sf.matched ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-400"
                }`}
              >
                {sf.label} {sf.matched ? "✓" : "✗"}
              </span>
            ))}
          </div>
        )}
        <p className="mt-2 text-xs text-slate-500">{f.support_reason}</p>
        {f.supporting_evidence?.length > 0 && (
          <p className="mt-1 text-xs text-slate-400">
            evidence: {f.supporting_evidence.join(", ")}
          </p>
        )}
        {f.limitations?.map((l) => (
          <p key={f.finding_id + l} className="mt-0.5 text-xs text-slate-400">limitation: {l}</p>
        ))}
        {reviewEntry && (
          <p className="mt-2 text-xs">
            <Badge variant={reviewEntry.action === "ACCEPTED" ? "success" : reviewEntry.action === "REJECTED" ? "danger" : "warning"}>
              {reviewEntry.action}
            </Badge>
            <span className="ml-2 text-slate-400">
              by {reviewEntry.reviewer_name ?? `user#${reviewEntry.reviewer_user_id ?? "?"}`}
              {reviewEntry.comment ? ` — ${reviewEntry.comment}` : ""}
            </span>
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {REVIEW_ACTIONS.map((ra) => (
            <Button
              key={ra.value}
              variant="outline"
              size="sm"
              disabled={!!reviewFindingId && reviewFindingId !== f.finding_id}
              onClick={() => review(f.finding_id, ra.value)}
            >
              {reviewFindingId === f.finding_id ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : null}
              {ra.label}
            </Button>
          ))}
          <input
            value={reviewComment}
            onChange={(e) => setReviewComment(e.target.value)}
            placeholder="Review note (optional)"
            className="ml-auto w-56 rounded-md border border-slate-300 px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-navy/40"
          />
        </div>
      </div>
    );
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <Link
          href={run ? `/investigations/${run.investigation_id}/investigate` : "/dashboard"}
          className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-navy"
        >
          <ArrowLeft className="h-4 w-4" /> Back to investigation
        </Link>
        <h1 className="text-2xl font-bold text-navy">
          Forensic workspace {run ? `#${run.id}` : ""}
        </h1>
        <p className="text-sm text-slate-500">
          Verified timeline, findings with evidence support, contradictions and gaps surfaced
          (never resolved), and a signed investigation report. No identity or causality is ever
          invented from observations.
        </p>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {reportInfo && <p className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-800">{reportInfo}</p>}

      <div className="mb-6 flex flex-wrap items-center gap-3">
        {run && (
          <span className="flex items-center gap-2 text-sm text-slate-500">
            <Clock className="h-4 w-4" /> {run.metrics?.elapsed_s?.toFixed(2)}s
            <GitBranch className="ml-2 h-4 w-4" /> {run.metrics?.steps_used ?? "-"} steps
            <ListChecks className="ml-2 h-4 w-4" /> {run.metrics?.tool_calls ?? "-"} tool calls
          </span>
        )}
        <Button className="ml-auto" onClick={analyze} disabled={busy}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <SearchCheck className="mr-2 h-4 w-4" />}
          {forensic ? "Re-run forensic analysis" : "Run forensic analysis"}
        </Button>
        <Button variant="outline" onClick={generateReport} disabled={busy || !forensic}>
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileText className="mr-2 h-4 w-4" />}
          Generate report
        </Button>
        <Button variant="outline" onClick={downloadReport} disabled={busy}>
          <Download className="mr-2 h-4 w-4" /> Download report
        </Button>
      </div>

      {!forensic && !busy && (
        <Card>
          <CardContent className="flex items-center gap-3 p-8 text-sm text-slate-500">
            <Bot className="h-5 w-5" /> {reportInfo || "No forensic analysis yet for this run."}
          </CardContent>
        </Card>
      )}

      {forensic && (
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-4 w-4" /> Forensic summary
                {toneFor(forensic.status)}
                <span className="ml-auto text-xs text-slate-400">
                  stages: {Object.entries(forensic.metrics || {}).map(([k, v]) => `${k} ${v?.toFixed?.(2) ?? v}s`).join(" · ") || "—"}
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-line text-sm text-slate-700">{forensic.summary}</p>
              <p className="mt-2 text-xs text-slate-400">{forensic.investigation_title ?? ""}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Clock className="h-4 w-4" /> Reconstructed timeline
                <span className="text-xs text-slate-400">({forensic.timeline.length} events)</span>
              </CardTitle>
            </CardHeader>
            <CardContent>{sortedTimeline.map(timelineRow)}</CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-4 w-4" /> Verified findings
                <span className="text-xs text-slate-400">({forensic.findings.length})</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">{forensic.findings.map(findingCard)}</CardContent>
          </Card>

          {forensic.correlations?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Evidence correlations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-slate-600">
                  {forensic.correlations.map((c, i) => (
                    <li key={i}>
                      {String(c.evidence_a)} → {String(c.evidence_b)}: {String(c.relation)}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {forensic.contradictions?.length > 0 && (
            <Card className="border-amber-300">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-amber-800">
                  <AlertTriangle className="h-4 w-4" /> Contradictions (reported, never resolved)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-amber-900">
                  {forensic.contradictions.map((c, i) => (
                    <li key={i}>
                      {String(c.evidence_a)} vs {String(c.evidence_b)} — {String(c.reason ?? c.type ?? "conflict")}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {forensic.gaps?.gaps?.length > 0 && (
            <Card className="border-amber-300">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base text-amber-800">
                  <MinusCircle className="h-4 w-4" /> Evidence gaps ({forensic.gaps.gaps.length})
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-amber-900">
                  {forensic.gaps.gaps.map((g, i) => (
                    <li key={i}>
                      {String(g.kind)}
                      {g.note ? ` — ${String(g.note)}` : ""}
                    </li>
                  ))}
                </ul>
                {forensic.gaps.quality && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(forensic.gaps.quality).map(([k, v]) => (
                      <span key={k} className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                        {k}: {Array.isArray(v) ? v.join(", ") : String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {forensic.relationships?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Event relationships</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-slate-600">
                  {forensic.relationships.map((r, i) => (
                    <li key={i}>
                      <span className="font-mono text-xs">{r.entry_a}</span> {r.relationship}{" "}
                      <span className="font-mono text-xs">{r.entry_b}</span>
                      {r.causal ? (
                        <CheckCircle2 className="ml-1 inline h-3 w-3 text-emerald-600" />
                      ) : (
                        <XCircle className="ml-1 inline h-3 w-3 text-slate-300" />
                      )}
                      {!r.causal && <span className="text-xs text-slate-400"> (temporal order, not causation)</span>}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {forensic.multi_camera?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Cross-camera correlation</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-slate-600">
                  {forensic.multi_camera.map((m, i) => (
                    <li key={i}>
                      {m.track_id}: {m.note} <Badge variant="muted">{m.status}</Badge>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {reviews.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Run review history</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="list-inside list-disc text-sm text-slate-600">
                  {reviews.map((r, i) => (
                    <li key={i}>
                      {r.decision}
                      {r.reviewer ? ` by ${r.reviewer}` : ""}
                      {r.details ? ` — ${r.details}` : ""}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </ProtectedShell>
  );
}