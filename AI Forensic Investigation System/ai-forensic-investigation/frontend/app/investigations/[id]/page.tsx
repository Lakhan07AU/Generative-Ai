"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Send,
  Scale,
  CheckCircle2,
  XCircle,
  Loader2,
  Bot,
  ShieldCheck,
  FileSearch,
  ListChecks,
  GitBranch,
  Clock,
  AlertTriangle,
} from "lucide-react";
import { api, Investigation, Claim, TimelineEvent, AgentAnswer } from "@/lib/api";
import { ProtectedShell } from "@/components/protected-shell";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

type ChatMsg = {
  id: number;
  role: "user" | "assistant";
  text: string;
  agent?: AgentAnswer | null;
  pending?: boolean;
  error?: boolean;
};

export default function InvestigationDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const investigationId = Number(params.id);
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState("");

  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const msgCounter = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  async function loadDetail() {
    try {
      const [inv, tl] = await Promise.all([
        api.investigation(investigationId),
        api.investigationTimeline(investigationId).catch(() => []),
      ]);
      setInvestigation(inv);
      setClaims(inv.claims || []);
      setTimeline(tl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load investigation");
    }
  }

  useEffect(() => {
    loadDetail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [investigationId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const nextId = useCallback(() => ++msgCounter.current, []);

  async function send(message?: string) {
    const text = (message ?? input).trim();
    if (!text || running) return;
    setInput("");
    const userMsg: ChatMsg = { id: nextId(), role: "user", text };
    const pendingMsg: ChatMsg = {
      id: nextId(),
      role: "assistant",
      text: "Running agentic investigation...",
      pending: true,
    };
    setMessages((prev) => [...prev, userMsg, pendingMsg]);
    setRunning(true);
    try {
      const res = await api.investigationChat(investigationId, text);
      const agent = res.agent_result;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id ? { ...m, text: agent.answer, agent, pending: false } : m
        )
      );
      loadDetail();
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingMsg.id
            ? { ...m, text: "Investigation step failed.", pending: false, error: true }
            : m
        )
      );
      loadDetail();
    } finally {
      setRunning(false);
    }
  }

  async function quickQuery(q: string) {
    await send(q);
  }

  function statusTone(status: string) {
    switch (status) {
      case "VERIFIED":
      case "CONFIRMED":
      case "TRUE":
        return "bg-green-100 text-green-700";
      case "REFUTED":
      case "FALSE":
      case "CONTRADICTED":
        return "bg-red-100 text-red-700";
      case "UNVERIFIED":
      case "PENDING":
      case "UNRESOLVED":
        return "bg-amber-100 text-amber-700";
      case "IN_PROGRESS":
      case "PROCESSING":
        return "bg-blue-100 text-blue-700";
      default:
        return "bg-slate-100 text-slate-600";
    }
  }

  return (
    <ProtectedShell>
      <Link
        href="/investigations"
        className="mb-4 inline-flex items-center gap-1 text-sm text-accent hover:underline"
      >
        <ArrowLeft className="h-4 w-4" /> Back to investigations
      </Link>

      {error && (
        <p className="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}

      {!investigation && !error && <p className="text-slate-500">Loading...</p>}

      {investigation && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-navy">{investigation.title}</h1>
              <p className="text-sm text-slate-500">{investigation.query}</p>
            </div>
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone(
                investigation.status
              )}`}
            >
              {investigation.status}
            </span>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            {/* Conversation */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Bot className="h-5 w-5 text-accent" /> Investigative Agent
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <div
                  ref={scrollRef}
                  className="max-h-[520px] space-y-4 overflow-y-auto pb-2 pr-1"
                >
                  <div className="rounded-lg bg-navy/5 p-4 text-sm text-slate-600">
                    <p className="mb-2 font-medium text-navy">How this works</p>
                    <p>
                      Ask the agent to investigate something related to this case. It will
                      search policies, query video detections and events, verify claims
                      against evidence, and build a timeline. Every answer is grounded in
                      retrieved evidence with citations.
                    </p>
                  </div>

                  {messages.length === 0 && (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {[
                        "Summarize the incident timeline",
                        "Who entered the vault and when?",
                        "Verify that the suspect was present at 22:40",
                        "What policy sections are relevant?",
                      ].map((q) => (
                        <button
                          key={q}
                          disabled={running}
                          onClick={() => quickQuery(q)}
                          className="rounded-md border border-slate-200 p-3 text-left text-sm text-slate-600 transition hover:border-accent hover:bg-accent/5 disabled:opacity-50"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  )}

                  {messages.map((m) =>
                    m.role === "user" ? (
                      <div key={m.id} className="flex justify-end">
                        <div className="max-w-[85%] rounded-lg bg-navy px-4 py-2 text-sm text-white">
                          {m.text}
                        </div>
                      </div>
                    ) : (
                      <div key={m.id} className="flex flex-col gap-2">
                        <div className="flex items-start gap-2">
                          <div className="mt-0.5 rounded-full bg-accent/10 p-1.5 text-accent">
                            <Bot className="h-4 w-4" />
                          </div>
                          <div className="w-full space-y-2">
                            {m.pending ? (
                              <div className="flex items-center gap-2 rounded-lg border border-slate-200 p-3 text-sm text-slate-500">
                                <Loader2 className="h-4 w-4 animate-spin text-accent" />
                                {m.text}
                              </div>
                            ) : (
                              <div
                                className={`whitespace-pre-wrap rounded-lg border p-3 text-sm ${
                                  m.error
                                    ? "border-red-200 bg-red-50 text-red-700"
                                    : "border-slate-200 bg-slate-50 text-slate-700"
                                }`}
                              >
                                {m.text}
                              </div>
                            )}
                            {m.agent && !m.error && (
                              <AgentTrace agent={m.agent} />
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  )}
                </div>

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    send();
                  }}
                  className="mt-3 flex items-end gap-2"
                >
                  <Textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Ask the agent to investigate..."
                    rows={2}
                    className="flex-1 resize-none"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        send();
                      }
                    }}
                  />
                  <Button type="submit" disabled={running || !input.trim()}>
                    {running ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="h-4 w-4" />
                    )}
                    Send
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* Sidebar: claims + timeline */}
            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <ListChecks className="h-5 w-5 text-accent" /> Claims Verified
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 pt-0">
                  {claims.length === 0 && (
                    <p className="text-sm text-slate-500">
                      Verified claims will appear here.
                    </p>
                  )}
                  {claims.map((c) => (
                    <div
                      key={c.id}
                      className="rounded-md border border-slate-200 p-3"
                    >
                      <div className="mb-1 flex items-center justify-between gap-2">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusTone(
                            c.status
                          )}`}
                        >
                          {c.status}
                        </span>
                        {c.confidence != null && (
                          <span className="text-xs text-slate-500">
                            {(c.confidence * 100).toFixed(0)}%
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-700">{c.claim_text}</p>
                      {c.verifications?.[0]?.result && (
                        <p className="mt-1 text-xs text-slate-500">
                          {c.verifications[0].result}
                        </p>
                      )}
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Clock className="h-5 w-5 text-accent" /> Reconstructed Timeline
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 pt-0">
                  {timeline.length === 0 && (
                    <p className="text-sm text-slate-500">
                      Timeline events will appear here.
                    </p>
                  )}
                  <div className="relative space-y-3 border-l border-slate-200 pl-4">
                    {timeline.map((ev, idx) => (
                      <div key={ev.id || idx} className="relative">
                        <span className="absolute -left-[21px] mt-1 h-2.5 w-2.5 rounded-full bg-accent" />
                        <p className="font-mono text-xs text-accent">
                          {formatTime(ev.timestamp)}
                        </p>
                        <p className="text-sm text-slate-700">{ev.description}</p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      )}
    </ProtectedShell>
  );
}

function AgentTrace({ agent }: { agent: AgentAnswer }) {
  return (
    <div className="space-y-2">
      {agent.claims.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <p className="mb-2 flex items-center gap-1 text-xs font-semibold text-navy">
            <ShieldCheck className="h-3.5 w-3.5 text-accent" /> Verified Claims
          </p>
          <div className="space-y-2">
            {agent.claims.map((c, i) => (
              <div key={i} className="flex items-start gap-2">
                {c.status === "VERIFIED" || c.status === "TRUE" ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                ) : c.status === "REFUTED" || c.status === "FALSE" ? (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                ) : (
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                )}
                <div>
                  <p className="text-sm text-slate-700">{c.claim_text}</p>
                  <p className="text-xs text-slate-500">
                    {c.status}
                    {c.reason ? ` — ${c.reason}` : ""}
                  </p>
                  {c.evidence.length > 0 && (
                    <p className="mt-1 text-xs text-slate-400">
                      Evidence: {c.evidence.length} link(s)
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {agent.steps.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <p className="mb-2 flex items-center gap-1 text-xs font-semibold text-navy">
            <FileSearch className="h-3.5 w-3.5 text-accent" /> Agent Steps
          </p>
          <ol className="space-y-1">
            {agent.steps.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-slate-600">
                <GitBranch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
                <span>
                  <span className="font-medium">{i + 1}.</span> {s.node}
                  {s.summary && Object.keys(s.summary).length > 0 && (
                    <span className="text-slate-400">
                      {" "}
                      · {Object.keys(s.summary).join(", ")}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {agent.tool_calls.length > 0 && (
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <p className="mb-2 text-xs font-semibold text-navy">Tool Calls</p>
          <div className="flex flex-wrap gap-1.5">
            {agent.tool_calls.map((t, i) => (
              <span
                key={i}
                className="rounded bg-slate-100 px-2 py-0.5 font-mono text-xs text-slate-600"
              >
                {t.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function formatTime(sec: number) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s
    .toString()
    .padStart(2, "0")}`;
}
