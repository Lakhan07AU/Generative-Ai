"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  Loader2,
  FileText,
  Download,
  Eye,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Pencil,
  HelpCircle,
  Send,
  History,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import {
  api,
  ReportDetail,
  ReviewDecision,
  ReportAuditEntry,
} from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth-context";

export default function ReportDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const reportId = Number(id);
  const { user } = useAuth();

  const [report, setReport] = useState<ReportDetail | null>(null);
  const [audit, setAudit] = useState<ReportAuditEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editingClaim, setEditingClaim] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [editNote, setEditNote] = useState("");
  const [decisionNote, setDecisionNote] = useState("");

  const isReviewer = user?.role === "REVIEWER" || user?.role === "ADMIN";
  const canSubmitBoth =
    user?.role === "REVIEWER" || user?.role === "ADMIN" || user?.role === "INVESTIGATOR";

  async function load() {
    setBusy(true);
    setError("");
    try {
      const r = await api.report(reportId);
      setReport(r);
      try {
        const a = await api.reportAudit(reportId);
        setAudit(a);
      } catch {
        /* audit optional for non-reviewers */
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, [reportId]);

  function reportTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "APPROVED") return <Badge variant="success">APPROVED</Badge>;
    if (s === "DRAFT") return <Badge variant="default">DRAFT</Badge>;
    if (s === "PENDING_REVIEW") return <Badge variant="warning">PENDING_REVIEW</Badge>;
    if (s === "REJECTED") return <Badge variant="danger">REJECTED</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  async function transition(action: "submit" | "approve" | "reject" | "finalize") {
    setError("");
    setBusy(true);
    try {
      if (action === "submit") await api.submitReport(reportId);
      if (action === "approve") await api.reviewReport(reportId, "APPROVE", decisionNote || undefined);
      if (action === "reject") await api.reviewReport(reportId, "REJECT", decisionNote || undefined);
      if (action === "finalize") await api.finalizeReport(reportId);
      setDecisionNote("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function claimAction(claimId: number, action: string) {
    setError("");
    setBusy(true);
    try {
      const body: { action: string; edited_text?: string; note?: string } = { action };
      if (action === "EDIT" && editText.trim()) body.edited_text = editText.trim();
      if (editNote.trim()) body.note = editNote.trim();
      await api.reviewClaim(reportId, claimId, body);
      setEditingClaim(null);
      setEditText("");
      setEditNote("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const sections = (report?.content as { sections?: Record<string, any>[] } | null)?.sections || [];

  function renderValue(v: unknown, depth = 0): React.ReactNode {
    if (v == null) return <span className="text-slate-400">—</span>;
    if (Array.isArray(v)) {
      if (v.length === 0) return <span className="text-slate-400">—</span>;
      return (
        <ul className="space-y-1">
          {v.map((item, i) => (
            <li key={i} className="text-sm">
              {typeof item === "object" ? (
                <div className="rounded border border-slate-100 p-1.5">
                  {renderValue(item, depth + 1)}
                </div>
              ) : (
                <span className="text-slate-700">{String(item)}</span>
              )}
            </li>
          ))}
        </ul>
      );
    }
    if (typeof v === "object") {
      return (
        <div className="space-y-0.5">
          {Object.entries(v as Record<string, unknown>).map(([k, val]) => (
            <div key={k} className={depth === 0 ? "flex gap-2 text-sm" : "text-sm"}>
              {depth === 0 ? (
                <>
                  <span className="w-44 shrink-0 font-medium text-slate-600">{k}</span>
                  <span className="flex-1">{renderValue(val, depth + 1)}</span>
                </>
              ) : (
                <>
                  <span className="font-medium text-slate-600">{k}: </span>
                  <span>{renderValue(val, depth + 1)}</span>
                </>
              )}
            </div>
          ))}
        </div>
      );
    }
    return <span className="text-slate-700">{String(v)}</span>;
  }

  function reviewActionTone(action: string) {
    const a = (action || "").toUpperCase();
    if (a === "ACCEPT") return <Badge variant="success">ACCEPT</Badge>;
    if (a === "REJECT") return <Badge variant="danger">REJECT</Badge>;
    if (a === "EDIT") return <Badge variant="warning">EDIT</Badge>;
    if (a === "UNCERTAIN") return <Badge>UNCERTAIN</Badge>;
    return <Badge variant="muted">{action}</Badge>;
  }

  if (!report && !error) {
    return (
      <ProtectedShell>
        <div className="flex justify-center py-20">
          <Loader2 className="h-8 w-8 animate-spin text-accent" />
        </div>
      </ProtectedShell>
    );
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <div className="mb-2 text-sm text-slate-500">
          <Link href="/reports" className="text-accent hover:underline">
            Reports
          </Link>{" "}
          / #{reportId}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-navy">{report?.title}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {report && (
                <>
                  {report.is_final && <Badge variant="success">FINAL</Badge>}
                  {reportTone(report.status)}
                  <Badge variant="muted">v{report.version}</Badge>
                  <Badge variant="muted">{report.file_format?.toUpperCase() || "PDF"}</Badge>
                  {report.investigation_id != null && (
                    <Link
                      href={`/investigations/${report.investigation_id}`}
                      className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
                    >
                      <ExternalLink className="h-3 w-3" /> Investigation #{report.investigation_id}
                    </Link>
                  )}
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {report?.storage_path && (
              <>
                <a href={api.reportFileUrl(reportId, false)} target="_blank" rel="noreferrer">
                  <Button variant="outline" size="sm">
                    <Eye className="h-4 w-4" /> Preview
                  </Button>
                </a>
                <a href={api.reportFileUrl(reportId, true)}>
                  <Button variant="outline" size="sm">
                    <Download className="h-4 w-4" /> Download
                  </Button>
                </a>
              </>
            )}
          </div>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      {/* Workflow actions */}
      {report && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="text-base">Review Workflow</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            {report.status === "DRAFT" && canSubmitBoth && (
              <Button onClick={() => transition("submit")} disabled={busy}>
                <Send className="h-4 w-4" /> Submit for Review
              </Button>
            )}
            {report.status === "PENDING_REVIEW" && isReviewer && (
              <>
                <input
                  value={decisionNote}
                  onChange={(e) => setDecisionNote(e.target.value)}
                  placeholder="Reviewer note (optional)"
                  className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
                />
                <Button onClick={() => transition("approve")} disabled={busy}>
                  <CheckCircle2 className="h-4 w-4" /> Approve
                </Button>
                <Button variant="destructive" onClick={() => transition("reject")} disabled={busy}>
                  <XCircle className="h-4 w-4" /> Reject
                </Button>
              </>
            )}
            {report.status === "APPROVED" && isReviewer && (
              <Button onClick={() => transition("finalize")} disabled={busy}>
                <ShieldCheck className="h-4 w-4" /> Finalize Report
              </Button>
            )}
            {!isReviewer && (report.status === "PENDING_REVIEW" || report.status === "APPROVED") && (
              <p className="text-sm text-slate-500">
                Awaiting action by a reviewer or administrator.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Report content */}
        <div className="space-y-4 lg:col-span-2">
          {sections.map((sec, i) => (
            <Card key={i}>
              <CardHeader className="border-b border-slate-100 pb-3">
                <CardTitle className="text-base">
                  {i + 1}. {sec.title || `Section ${i + 1}`}
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-4">
                {sec.content ? renderValue(sec.content) : <p className="text-sm text-slate-400">No data.</p>}
              </CardContent>
            </Card>
          ))}
          {sections.length === 0 && (
            <Card>
              <CardContent className="p-10 text-center text-sm text-slate-500">
                <FileText className="mx-auto mb-2 h-8 w-8 text-slate-300" />
                No structured sections available for this report.
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar: per-claim review + audit */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Pencil className="h-4 w-4 text-accent" /> Claim Review
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 pt-0">
              <p className="text-xs text-slate-500">
                Records: original AI claim, edited claim, reviewer ID, and timestamp are stored for
                every decision.
              </p>
              {(report?.review_decisions || []).map((d) => (
                <div key={d.id} className="rounded-md border border-slate-200 p-3 text-sm">
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-medium text-slate-500">
                      Claim #{d.claim_id}
                    </span>
                    {reviewActionTone(d.action)}
                  </div>
                  {d.original_text && (
                    <p className="mt-1 text-xs text-slate-600">
                      <span className="font-medium">Original:</span> {d.original_text}
                    </p>
                  )}
                  {d.edited_text && (
                    <p className="mt-1 text-xs text-slate-600">
                      <span className="font-medium">Edited:</span> {d.edited_text}
                    </p>
                  )}
                  {d.note && <p className="mt-1 text-xs italic text-slate-500">Note: {d.note}</p>}
                  <p className="mt-1 text-[11px] text-slate-400">
                    {d.reviewer_name || `Reviewer #${d.reviewer_user_id}`} ·{" "}
                    {d.reviewed_at ? new Date(d.reviewed_at).toLocaleString() : ""}
                  </p>
                </div>
              ))}
              {!report?.review_decisions || report.review_decisions.length === 0
                ? (
                  <p className="text-xs text-slate-400">No per-claim review decisions recorded.</p>
                )
                : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <History className="h-4 w-4 text-accent" /> Audit Trail
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {!audit || audit.length === 0 ? (
                <p className="py-4 text-center text-xs text-slate-500">No audit entries.</p>
              ) : (
                <ol className="space-y-3">
                  {audit.map((a) => (
                    <li key={a.id} className="rounded-md border border-slate-100 p-2.5 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-navy">{a.action}</span>
                        <span className="text-slate-400">
                          {a.created_at ? new Date(a.created_at).toLocaleString() : ""}
                        </span>
                      </div>
                      {a.user_name && <p className="mt-0.5 text-slate-500">by {a.user_name}</p>}
                      {a.details && <p className="mt-0.5 text-slate-500">{a.details}</p>}
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </ProtectedShell>
  );
}
