"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw, ArrowRight, Scale } from "lucide-react";
import { api, Investigation, Video, ApiError } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

export default function InvestigationsPage() {
  const router = useRouter();
  const [investigations, setInvestigations] = useState<Investigation[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [error, setError] = useState("");

  // create form state
  const [title, setTitle] = useState("");
  const [query, setQuery] = useState("");
  const [videoId, setVideoId] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      const [inv, vids] = await Promise.all([
        api.investigations(),
        api.videos().catch(() => []),
      ]);
      setInvestigations(inv);
      setVideos(vids);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load investigations");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !query.trim()) {
      setError("Please provide a title and investigation query");
      return;
    }
    setError("");
    setCreating(true);
    try {
      const created = await api.createInvestigation({
        title: title.trim(),
        query: query.trim(),
        description: description.trim() || undefined,
        video_id: videoId ? Number(videoId) : null,
      });
      router.push(`/investigations/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create investigation");
      setCreating(false);
    }
  }

  function statusTone(status: string) {
    switch (status) {
      case "IN_PROGRESS":
      case "PROCESSING":
        return "bg-blue-100 text-blue-700";
      case "COMPLETE":
      case "COMPLETED":
        return "bg-green-100 text-green-700";
      case "FAILED":
      case "ERROR":
        return "bg-red-100 text-red-700";
      default:
        return "bg-slate-100 text-slate-600";
    }
  }

  return (
    <ProtectedShell>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-navy">Investigations</h1>
          <p className="text-sm text-slate-500">
            Agentic analysis of evidence to establish a grounded, audit trail.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="h-4 w-4" /> Refresh
        </Button>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* New investigation form */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5 text-accent" /> New Investigation
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={onCreate} className="space-y-3">
              <div className="space-y-1">
                <label className="text-sm font-medium">Title</label>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Theft at main entrance"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">
                  Investigation query <span className="text-slate-400">(objective)</span>
                </label>
                <textarea
                  className="flex min-h-[80px] w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="e.g. Identify the suspect and establish whether they entered the vault the night of the theft."
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Related video (optional)</label>
                <Select value={videoId} onChange={(e) => setVideoId(e.target.value)}>
                  <option value="">— no specific video —</option>
                  {videos.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.filename}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Description (optional)</label>
                <Input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Case context, goals..."
                />
              </div>

              <Button type="submit" className="w-full" disabled={creating}>
                {creating ? "Creating..." : "Create Investigation"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Investigation list */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Your investigations</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {investigations.length === 0 && (
              <p className="py-10 text-center text-sm text-slate-500">
                No investigations yet. Create one to run a grounded forensic analysis.
              </p>
            )}
            <div className="space-y-3">
              {investigations.map((inv) => (
                <Link
                  key={inv.id}
                  href={`/investigations/${inv.id}`}
                  className="flex items-center justify-between rounded-lg border border-slate-200 p-4 transition hover:bg-accent/5"
                >
                  <div className="flex items-center gap-3">
                    <div className="rounded-md bg-navy/10 p-2 text-navy">
                      <Scale className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium text-navy">{inv.title}</p>
                      <p className="text-xs text-slate-500 line-clamp-1">{inv.query}</p>
                      {inv.created_at && (
                        <p className="text-xs text-slate-400">
                          {new Date(inv.created_at).toLocaleString()}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusTone(
                        inv.status
                      )}`}
                    >
                      {inv.status}
                    </span>
                    <ArrowRight className="h-4 w-4 text-accent" />
                  </div>
                </Link>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </ProtectedShell>
  );
}
