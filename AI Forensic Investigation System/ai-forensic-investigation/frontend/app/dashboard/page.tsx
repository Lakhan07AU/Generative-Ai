"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Video, Loader2, CheckCircle2, Box, ArrowRight } from "lucide-react";
import { api, DashboardStats } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { statusBadge } from "@/components/ui/badge";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .dashboard()
      .then(setStats)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <ProtectedShell>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-navy">Investigation Dashboard</h1>
        <Link
          href="/videos"
          className="inline-flex items-center gap-2 rounded-md bg-navy px-4 py-2 text-sm font-medium text-white hover:bg-navy/90"
        >
          <Video className="h-4 w-4" /> Upload Video
        </Link>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Videos" value={stats?.total_videos} icon={<Video className="h-5 w-5" />} />
        <StatCard label="Active Processing" value={stats?.processing_jobs} icon={<Loader2 className="h-5 w-5 animate-spin" />} />
        <StatCard label="Completed Videos" value={stats?.completed_videos} icon={<CheckCircle2 className="h-5 w-5" />} />
        <StatCard label="Detected Objects" value={stats?.total_detections} icon={<Box className="h-5 w-5" />} />
      </div>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Recent Uploads</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {!stats ||
            (stats.recent_videos.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-500">
                No videos uploaded yet.
              </p>
            ))}
          {stats && stats.recent_videos.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-slate-500">
                    <th className="py-2 pr-4">Filename</th>
                    <th className="py-2 pr-4">Camera</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-4">Uploaded</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_videos.slice(0, 5).map((v) => (
                    <tr key={v.id} className="border-b last:border-0">
                      <td className="py-2 pr-4 font-medium">{v.filename}</td>
                      <td className="py-2 pr-4">{v.camera_name || "—"}</td>
                      <td className="py-2 pr-4">{statusBadge(v.status)}</td>
                      <td className="py-2 pr-4 text-slate-500">
                        {v.uploaded_at ? new Date(v.uploaded_at).toLocaleString() : "—"}
                      </td>
                      <td className="py-2 text-right">
                        <Link
                          href={`/videos/${v.id}`}
                          className="inline-flex items-center gap-1 text-accent hover:underline"
                        >
                          View <ArrowRight className="h-3 w-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </ProtectedShell>
  );
}

function StatCard({
  label,
  value,
  icon,
}: {
  label: string;
  value?: number;
  icon: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="text-3xl font-bold text-navy">{value ?? "—"}</p>
        </div>
        <div className="rounded-md bg-accent/10 p-3 text-accent">{icon}</div>
      </CardContent>
    </Card>
  );
}
