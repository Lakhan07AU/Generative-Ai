"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, FileText, RefreshCw, ArrowRight, ExternalLink } from "lucide-react";
import { api, Report } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setBusy(true);
    setError("");
    try {
      setReports(await api.reports());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function reportTone(status: string) {
    const s = (status || "").toUpperCase();
    if (s === "APPROVED") return <Badge variant="success">APPROVED</Badge>;
    if (s === "DRAFT") return <Badge variant="default">DRAFT</Badge>;
    if (s === "PENDING_REVIEW") return <Badge variant="warning">PENDING_REVIEW</Badge>;
    if (s === "REJECTED") return <Badge variant="danger">REJECTED</Badge>;
    return <Badge variant="muted">{status}</Badge>;
  }

  return (
    <ProtectedShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-navy">Incident Reports</h1>
          <p className="text-sm text-slate-500">
            Generate, review, and finalize structured incident reports.
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

      <Card>
        <CardHeader>
          <CardTitle>All Reports</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {reports.length === 0 && !busy && (
            <p className="py-10 text-center text-sm text-slate-500">
              No reports generated yet. Open an investigation and generate a report, or create one
              via the{" "}
              <Link href="/investigations" className="text-accent hover:underline">
                Investigations
              </Link>{" "}
              workspace.
            </p>
          )}
          <div className="space-y-3">
            {reports.map((r) => (
              <div
                key={r.id}
                className="flex items-center justify-between rounded-lg border border-slate-200 p-4"
              >
                <div className="flex items-center gap-3">
                  <div className="rounded-md bg-navy/10 p-2 text-navy">
                    <FileText className="h-5 w-5" />
                  </div>
                  <div>
                    <p className="font-medium text-navy">{r.title}</p>
                    <p className="text-xs text-slate-500">
                      v{r.version} · {r.investigation_title || `Investigation #${r.investigation_id}`}
                      {" · "}
                      {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {r.is_final && <Badge variant="success">FINAL</Badge>}
                  {reportTone(r.status)}
                  <Link
                    href={`/reports/${r.id}`}
                    className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
                  >
                    Open <ArrowRight className="h-4 w-4" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </ProtectedShell>
  );
}
