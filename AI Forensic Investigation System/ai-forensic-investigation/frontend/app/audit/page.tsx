"use client";

import { useEffect, useState, useCallback } from "react";
import { ShieldAlert, RefreshCw } from "lucide-react";
import { api, AuditLogEntry } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type Row = AuditLogEntry;

export default function AuditPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";

  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const items = await api.auditLogs({ limit: 250 });
      setRows(items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!isAdmin) {
    return (
      <ProtectedShell>
        <Card>
          <CardContent className="p-6 text-sm text-slate-600">
            The audit log is restricted to administrators.
          </CardContent>
        </Card>
      </ProtectedShell>
    );
  }

  return (
    <ProtectedShell>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-navy">
            <ShieldAlert className="h-6 w-6 text-accent" /> Audit Log
          </h1>
          <p className="text-sm text-slate-500">
            Security-relevant events recorded by the backend (newest first).
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => load()} disabled={loading}>
          <RefreshCw className="mr-1 h-4 w-4" /> Refresh
        </Button>
      </div>

      {error && <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <div className="max-w-full">
        {loading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : rows.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-slate-500">
              No audit entries yet.
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-4 py-3">When</th>
                      <th className="px-4 py-3">Action</th>
                      <th className="px-4 py-3">User</th>
                      <th className="px-4 py-3">Target</th>
                      <th className="px-4 py-3">Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-b last:border-0 hover:bg-slate-50">
                        <td className="whitespace-nowrap px-4 py-3 text-slate-500">
                          {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 font-medium text-navy">
                          {r.action}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          {r.user_email || (r.user_id != null ? `user#${r.user_id}` : "system")}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                          {r.entity_type ? `${r.entity_type}${r.entity_id != null ? ` #${r.entity_id}` : ""}` : "—"}
                        </td>
                        <td className="max-w-xs truncate px-4 py-3 text-slate-600" title={r.details || ""}>
                          {r.details || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </ProtectedShell>
  );
}