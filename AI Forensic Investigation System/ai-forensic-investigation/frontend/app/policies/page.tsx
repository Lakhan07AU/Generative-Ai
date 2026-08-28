"use client";

import { useEffect, useState, useRef } from "react";
import { Upload, FileText, Search, Loader2, FileSearch, ChevronDown } from "lucide-react";
import { api, Policy, PolicyChunk, PolicySearchHit } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export default function PoliciesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";

  const [policies, setPolicies] = useState<Policy[]>([]);
  const [expanded, setExpanded] = useState<Record<string, PolicyChunk[]>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hits, setHits] = useState<PolicySearchHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadPolicies() {
    try {
      setPolicies(await api.policies());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    loadPolicies();
  }, []);

  async function doUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    setOk("");
    const form = new FormData();
    form.append("file", file);
    try {
      await api.uploadPolicy(form);
      setOk(`Uploaded and indexed "${file.name}".`);
      if (fileRef.current) fileRef.current.value = "";
      await loadPolicies();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function toggleSection(p: Policy) {
    if (openId === p.policy_id) {
      setOpenId(null);
      return;
    }
    try {
      const sections =
        expanded[p.policy_id] ?? (await api.policySections(p.policy_id));
      setExpanded((prev) => ({ ...prev, [p.policy_id]: sections }));
      setOpenId(p.policy_id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function doSearch() {
    if (!search.trim()) {
      setHits([]);
      return;
    }
    setSearching(true);
    setError("");
    try {
      setHits(await api.searchPolicies(search.trim()));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSearching(false);
    }
  }

  return (
    <ProtectedShell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-navy">Security Policy Library</h1>
        <p className="text-sm text-slate-500">
          Upload organizational security policies (PDF / DOCX / TXT) to power policy-aware
          assessments during investigations.
        </p>
      </div>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}
      {ok && (
        <p className="mb-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">{ok}</p>
      )}

      {isAdmin && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5 text-accent" /> Upload Policy
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt"
              className="flex-1 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
            />
            <Button onClick={doUpload} disabled={uploading}>
              {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {uploading ? "Indexing..." : "Upload & Index"}
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSearch()}
              placeholder="Semantic search across policy documents..."
              className="w-full rounded-md border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          <Button variant="outline" onClick={doSearch} disabled={searching}>
            {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
            Search
          </Button>
        </CardContent>
        {hits.length > 0 && (
          <CardContent className="space-y-2 border-t border-slate-200">
            <p className="text-sm font-medium text-navy">Search results ({hits.length})</p>
            {hits.map((h, i) => (
              <div key={i} className="rounded-md border border-slate-200 p-3 text-sm">
                <p className="mb-1 font-medium text-accent">
                  {h.document_name} · {h.section} <span className="text-slate-400">({h.score.toFixed(3)})</span>
                </p>
                <p className="line-clamp-3 text-slate-600">{h.text}</p>
              </div>
            ))}
          </CardContent>
        )}
      </Card>

      <div className="space-y-3">
        {policies.length === 0 && (
          <Card>
            <CardContent className="p-10 text-center text-sm text-slate-500">
              <FileText className="mx-auto mb-2 h-8 w-8 text-slate-300" />
              No policies uploaded yet.
            </CardContent>
          </Card>
        )}
        {policies.map((p) => (
          <Card key={p.policy_id}>
            <div className="flex cursor-pointer items-center gap-3 p-5" onClick={() => toggleSection(p)}>
              <FileText className="h-5 w-5 text-accent" />
              <div className="flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-navy">
                  {p.policy_id} · {p.document_name}
                </p>
                <p className="text-xs text-slate-500">
                  {p.filename} · {p.source_format?.toUpperCase()} · {p.chunk_count} chunks ·{" "}
                  {p.status}
                </p>
              </div>
              <Badge variant={openId === p.policy_id ? "default" : "muted"}>
                {openId === p.policy_id ? "Hide" : "Sections"}
              </Badge>
              <ChevronDown
                className={`h-4 w-4 text-slate-400 transition-transform ${
                  openId === p.policy_id ? "rotate-180" : ""
                }`}
              />
            </div>
            {openId === p.policy_id && (
              <CardContent className="border-t border-slate-200 pt-4">
                {(expanded[p.policy_id] ?? []).length === 0 && (
                  <p className="text-sm text-slate-500">No sections found.</p>
                )}
                {(expanded[p.policy_id] ?? []).map((c) => (
                  <div key={c.id} className="mb-2 rounded-md border border-slate-200 p-3 text-sm">
                    <p className="mb-1 text-xs font-semibold text-accent">
                      {c.section} · chunk {c.chunk_index}
                    </p>
                    <p className="whitespace-pre-wrap text-slate-700">{c.text}</p>
                  </div>
                ))}
              </CardContent>
            )}
          </Card>
        ))}
      </div>
    </ProtectedShell>
  );
}
