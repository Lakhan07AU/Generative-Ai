"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Loader2,
  Bot,
  ListChecks,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  ShieldCheck,
  GitBranch,
} from "lucide-react";
import { api, Investigation, InvestigationRun, RunRow } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function InvestigateWorkspace({ params }: { params: { id: string } }) {
  const investigationId = Number(params.id);
  const [inv, setInv] = useState<Investigation | null>(null);
  const [query, setQuery] = useState("");
  const [requireReview, setRequireReview] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [run, setRun] = useState<InvestigationRun | null>(null);
  const [history, setHistory] = useState<RunRow[]>([]);
  const [reviewing, setReviewing] = useState(false);

  async function load() {
    try {
      const [detail, runs] = await Promise.all([
        api.investigation(investigationId),
        api.investigationRuns(investigationId).catch(() => ({ runs: [] })),
      ]);
      setInv(detail);
      setHistory(runs.runs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load investigation");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigationId]);

  async function runInvestigation() {
    if (!query.trim() || busy) return;
    setError("");
    setBusy(true);
    setRun(null);
    try {
      const res = await api.startInvestigationRun(investigationId, {
        query: query.trim(),
        require_review: requireReview,
      });
      setRun(res);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(false);
    }
  }

  async function viewRun(row: RunRow) {
    setError("");
    setBusy(true);
    try {
      setRun(await api.investigationRun(row.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load run");
    } finally {
      setBusy(false);
    }
  }

  async function review(decision: "APPROVE" | "REJECT") {
    if (!run || reviewing) return;
    setReviewing(true);
    setError("");
    try {
      setRun(await api.reviewInvestigationRun(run.id, { decision }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Review failed");
    } finally {
      setReviewing(false);
    }
  }

  function runTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "COMPLETED") return <Badge variant="success">{status}</Badge>;
    if (s === "READY_FOR_REVIEW") return <Badge variant="warning">{status}</Badge>;
    if (s === "FAILED" || s === "CANCELLED") return <Badge variant="danger">{status}</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  const answerTone = (status: string) => {
    const s = (status || "").toUpperCase();
    if (s === "ANSWERED") return <Badge variant="success">ANSWERED</Badge>;
    if (s === "UNKNOWN") return <Badge variant="danger">UNKNOWN</Badge>;
    return <Badge variant="muted">{s}</Badge>;
  };

  return (
    <ProtectedShell>
      <div className="mb-6">
        <Link
          href={`/investigations/${investigationId}`}
          className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-navy"
        >
          <ArrowLeft className="h-4 w-4" /> Back to investigation
        </Link>
        <h1 className="text-2xl font-bold text-navy">Controlled Investigation</h1>
        <p className="text-sm text-slate-500">
          Run a bounded, deterministic investigation agent against the case&apos;s forensic
          evidence. Evidence is scoped to the case&apos;s cameras; findings are verified,
          conflicts are reported (never resolved), and only [OBSERVED] statements may be cited.
        </p>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <Card className="mb-6">
        <CardContent className="p-5">
          <div className="flex flex-col gap-3">
            <label className="text-sm font-medium text-slate-700">
              Question{inv ? ` for "${inv.title}"` : ""}
            </label>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Find all evidence for track T-100"
              rows={2}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy/40"
            />
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={requireReview}
                  onChange={(e) => setRequireReview(e.target.checked)}
                  className="h-4 w-4"
                />
                Require human review before results are final
              </label>
              <Button onClick={runInvestigation} disabled={busy || !query.trim()}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                {busy ? "Running agent..." : "Run investigation"}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {history.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ListChecks className="h-4 w-4" /> Run history
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-2">
              {history.slice(0, 6).map((row) => (
                <button
                  key={row.id}
                  onClick={() => viewRun(row)}
                  className={`flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm ${
                    run?.id === row.id ? "border-navy bg-navy/5" : "border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <span className="truncate text-slate-700">{row.query}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {runTone(row.status)}
                    <span className="text-xs text-slate-400">#{row.id}</span>
                  </span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {busy && !run && (
        <Card>
          <CardContent className="flex items-center gap-3 p-8 text-sm text-slate-500">
            <Loader2 className="h-5 w-5 animate-spin" /> Running bounded agent run…
          </CardContent>
        </Card>
      )}

      {run && (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
              <span className="flex items-center gap-2">
                <Bot className="h-4 w-4" /> Run #{run.id}
                {runTone(run.status)}
                {run.result && answerTone(run.result.status)}
              </span>
              <span className="flex items-center gap-3 text-xs text-slate-400">
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3 w-3" /> {run.metrics?.elapsed_s?.toFixed(2)}s
                </span>
                <span className="inline-flex items-center gap-1">
                  <GitBranch className="h-3 w-3" /> {run.metrics?.steps_used ?? "-"} steps
                </span>
                <span className="inline-flex items-center gap-1">
                  <ListChecks className="h-3 w-3" /> {run.metrics?.tool_calls ?? "-"} tool calls
                </span>
                <span className="inline-flex items-center gap-1">
                  <ShieldCheck className="h-3 w-3" /> {run.metrics?.evidence_used ?? "-"} evidence
                </span>
              </span>
              <Link
                href={`/runs/${run.id}`}
                className="inline-flex items-center gap-1 rounded-md border border-navy/30 px-3 py-1.5 text-xs font-medium text-navy hover:bg-navy/5"
              >
                <ShieldCheck className="h-3 w-3" /> Forensic workspace
              </Link>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="rounded-md bg-slate-50 p-4 text-sm">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Classification
              </p>
              <p className="text-slate-700">
                <Badge variant="muted">{run.classification?.category ?? "OTHER"}</Badge>
                <span className="ml-2">{run.classification?.category_reason}</span>
              </p>
            </div>

            {run.result && (
              <>
                <div className="rounded-md bg-emerald-50 p-4 text-sm text-emerald-900">
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-600">
                    Summary
                  </p>
                  <p className="whitespace-pre-line">{run.result.summary}</p>
                </div>

                {run.result.conflicts.length > 0 && (
                  <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
                    <p className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-amber-700">
                      <AlertTriangle className="h-4 w-4" /> Conflicting evidence — reported, not resolved
                    </p>
                    <ul className="list-inside list-disc space-y-1">
                      {run.result.conflicts.map((c, i) => (
                        <li key={i}>
                          {c.reason} ({" "}
                          {c.evidence_a} vs {c.evidence_b})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div>
                  <p className="mb-2 text-sm font-semibold text-slate-700">Findings</p>
                  <div className="flex flex-col gap-2">
                    {run.result.findings.map((f, i) => (
                      <div
                        key={i}
                        className="rounded-md border border-slate-200 p-3 text-sm"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-slate-700">{f.text}</p>
                          <Badge variant={f.status === "VERIFIED" ? "success" : "muted"}>
                            {f.status}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-slate-400">
                          confidence {f.confidence} · {f.claim_type}
                        </p>
                        {f.evidence.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {f.evidence.map((e, j) => (
                              <span
                                key={j}
                                className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
                              >
                                {e.camera_name ?? `cam-${e.camera_id ?? "?"}`} · {e.evidence_id}
                                {e.tracking_id ? ` · ${e.tracking_id}` : ""}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {run.result.timeline.length > 0 && (
                  <div>
                    <p className="mb-2 text-sm font-semibold text-slate-700">Timeline</p>
                    <div className="flex flex-col gap-1 text-sm">
                      {run.result.timeline.map((t, i) => (
                        <div key={i} className="flex items-center justify-between gap-2 rounded-md bg-slate-50 px-3 py-1.5">
                          <span className="font-mono text-xs text-slate-500">{t.timestamp}s</span>
                          <span className="flex-1 text-slate-700">{t.description}</span>
                          {t.status === "VERIFIED" ? (
                            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                          ) : (
                            <XCircle className="h-4 w-4 text-slate-300" />
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {run.result.limitations.length > 0 && (
                  <div className="text-xs text-slate-400">
                    <p className="mb-1 font-semibold uppercase tracking-wide">Limitations</p>
                    <ul className="list-inside list-disc space-y-0.5">
                      {run.result.limitations.map((l, i) => (
                        <li key={i}>{l}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}

            {run.error && (
              <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">{run.error}</p>
            )}

            {run.status === "READY_FOR_REVIEW" && (
              <div className="flex items-center gap-3 rounded-md border border-amber-200 bg-amber-50 p-4">
                <span className="text-sm text-amber-900">
                  Awaiting human review before these findings can be treated as final.
                </span>
                <div className="ml-auto flex gap-2">
                  <Button onClick={() => review("APPROVE")} disabled={reviewing}>
                    {reviewing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}
                    Approve
                  </Button>
                  <Button variant="outline" onClick={() => review("REJECT")} disabled={reviewing}>
                    <XCircle className="mr-2 h-4 w-4" /> Reject
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </ProtectedShell>
  );
}