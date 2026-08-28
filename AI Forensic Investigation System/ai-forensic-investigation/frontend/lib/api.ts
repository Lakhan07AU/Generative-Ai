export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type User = {
  id: number;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  created_at?: string | null;
};

export type Token = {
  access_token: string;
  token_type: string;
  user: User;
};

export type Camera = {
  id: number;
  camera_name: string;
  location?: string | null;
  description?: string | null;
  created_at?: string | null;
};

export type ProcessingJob = {
  id: number;
  video_id: number;
  status: string;
  stage?: string | null;
  progress: number;
  error?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type Video = {
  id: number;
  filename: string;
  storage_path: string;
  camera_id?: number | null;
  duration_seconds?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  codec?: string | null;
  recording_date?: string | null;
  start_time?: string | null;
  description?: string | null;
  status: string;
  uploaded_at?: string | null;
  camera_name?: string | null;
};

export type Clip = {
  id: number;
  public_id: string;
  video_id: number;
  camera_id?: number | null;
  start_time: number;
  end_time: number;
  storage_path?: string | null;
  thumbnail_path?: string | null;
  description?: string | null;
  detections?: Detection[];
};

export type Detection = {
  id: number;
  clip_id: number;
  video_id: number;
  camera_id?: number | null;
  label: string;
  bounding_box: string;
  frame_number?: number | null;
  timestamp?: number | null;
  detection_confidence?: number | null;
  tracking_id?: string | null;
};

export type Event = {
  id: number;
  video_id: number;
  clip_id?: number | null;
  event_type: string;
  description?: string | null;
  start_time?: number | null;
  end_time?: number | null;
  confidence?: number | null;
};

export type MedialUrl = { url: string };

export type EvidenceCard = {
  evidence_id: string;
  video_id?: number | null;
  clip_id?: number | null;
  clip_public_id?: string | null;
  camera_id?: number | null;
  camera_name?: string | null;
  timestamp: number;
  start_time: number;
  end_time?: number | null;
  description: string;
  objects: string[];
  tracking_ids: string[];
  transcript: string;
  detection_confidence?: number | null;
  retrieval_score: number;
  source_path?: string;
  verification?: {
    verified?: boolean;
    score?: number;
    reason?: string;
  } | null;
};

export type RAGAnalysis = {
  entities: string[];
  events: string[];
  temporal: Record<string, unknown>;
  raw: string;
};

export type RAGResult = {
  query: string;
  analysis: RAGAnalysis;
  status: string;
  answer: string;
  evidence: EvidenceCard[];
};

export type Policy = {
  policy_id: string;
  document_name: string;
  filename?: string | null;
  source_format?: string | null;
  status?: string | null;
  created_at?: string | null;
  chunk_count: number;
};

export type PolicyChunk = {
  id: number;
  section?: string | null;
  page?: number | null;
  chunk_index?: number | null;
  text: string;
};

export type PolicySearchHit = {
  score: number;
  policy_id?: number | null;
  document_name?: string | null;
  section?: string | null;
  page?: number | null;
  chunk_index?: number | null;
  text: string;
};

export type PolicyQuestion = {
  question: string;
  status: string;
  description: string;
  policy_sections: PolicySearchHit[];
  evidence: EvidenceCard[];
  video_id?: number | null;
  clip_id?: number | null;
  policy_id?: number | null;
};

export type Finding = {
  id: number;
  video_id?: number | null;
  clip_id?: number | null;
  finding_status: string;
  finding_type?: string | null;
  question?: string | null;
  description?: string | null;
  confidence?: number | null;
  retrieval_score?: number | null;
  policy_id?: number | null;
  created_at?: string | null;
};

export type DashboardStats = {
  total_videos: number;
  processing_jobs: number;
  completed_videos: number;
  total_detections: number;
  recent_videos: Video[];
};

// ---- Part 3: Agentic investigation ----

export type Investigation = {
  id: number;
  title: string;
  description?: string | null;
  query: string;
  video_id?: number | null;
  status: string;
  created_by_user_id?: number | null;
  created_at?: string | null;
};

export type ClaimEvidence = {
  id: number;
  claim_id: number;
  clip_id?: number | null;
  frame_id?: number | null;
  timestamp?: number | null;
  evidence_type?: string | null;
  relevance_score?: number | null;
};

export type Verification = {
  id: number;
  claim_id: number;
  checks?: Record<string, unknown> | null;
  result: string;
  reason?: string | null;
  verifier_version?: string | null;
  created_at?: string | null;
};

export type Claim = {
  id: number;
  investigation_id: number;
  claim_text: string;
  claim_type: string;
  status: string;
  confidence?: number | null;
  created_at?: string | null;
  evidence_links?: ClaimEvidence[];
  verifications?: Verification[];
};

export type TimelineEvent = {
  id: number;
  investigation_id: number;
  timestamp: number;
  description: string;
  status: string;
  evidence_ids?: string[] | null;
  created_at?: string | null;
};

export type AgentToolCall = {
  name: string;
  arguments: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  status: string;
};

export type AgentStep = {
  step: number;
  node: string;
  summary: Record<string, unknown>;
};

export type AgentClaim = {
  claim_text: string;
  claim_type: string;
  status: string;
  result: string;
  reason?: string | null;
  verifier_version?: string | null;
  evidence: Record<string, unknown>[];
};

export type AgentAnswer = {
  investigation_id?: number | null;
  query: string;
  status: string;
  answer: string;
  grounded: boolean;
  tool_calls: AgentToolCall[];
  steps: AgentStep[];
  claims: AgentClaim[];
  events: Record<string, unknown>[];
  policy_sections: Record<string, unknown>[];
};

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("token");
}

export function setToken(token: string) {
  localStorage.setItem("token", token);
}

export function clearToken() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("user");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function setUser(user: User) {
  localStorage.setItem("user", JSON.stringify(user));
}

// ---- Part 4: Evidence workspace + reports ----

export type EvidenceClip = {
  id: number;
  public_id: string;
  video_id: number;
  camera_id?: number | null;
  camera_name?: string | null;
  start_time: number;
  end_time: number;
  description?: string | null;
  storage_path?: string | null;
  detections: {
    id: number;
    label: string;
    timestamp?: number | null;
    tracking_id?: string | null;
    detection_confidence?: number | null;
  }[];
};

export type EvidenceSourceClip = {
  id: number;
  public_id: string;
  start_time: number;
  end_time: number;
  storage_path?: string | null;
};

export type EvidenceClaimLink = {
  evidence_id: number;
  clip_id?: number | null;
  clip_public_id?: string | null;
  video_id?: number | null;
  timestamp?: number | null;
  evidence_type?: string | null;
  relevance_score?: number | null;
  source_clip?: EvidenceSourceClip | null;
};

export type PolicyReference = {
  finding_id: number;
  policy_id?: number | null;
  document_name?: string | null;
  description?: string | null;
  status?: string | null;
};

export type EvidenceClaimRow = {
  claim_id: number;
  investigation_id: number;
  claim_text: string;
  claim_type: string;
  status: string;
  confidence?: number | null;
  created_at?: string | null;
  evidence: EvidenceClaimLink[];
  verification?: {
    result?: string | null;
    reason?: string | null;
    verifier_version?: string | null;
    checks?: Record<string, unknown> | null;
  } | null;
  policy_references: PolicyReference[];
};

export type Report = {
  id: number;
  investigation_id: number;
  title: string;
  status: string;
  is_final: boolean;
  version: number;
  storage_path?: string | null;
  file_format?: string | null;
  generated_by_user_id?: number | null;
  reviewed_by_user_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  investigation_title?: string | null;
};

export type ReviewDecision = {
  id: number;
  report_id: number;
  claim_id?: number | null;
  action: string;
  original_text?: string | null;
  edited_text?: string | null;
  note?: string | null;
  reviewer_user_id?: number | null;
  reviewer_name?: string | null;
  reviewed_at?: string | null;
};

export type ReportDetail = Report & {
  content?: Record<string, unknown> | null;
  review_decisions?: ReviewDecision[];
};

export type ReportAuditEntry = {
  id: number;
  action: string;
  user_id: number | null;
  user_name?: string | null;
  details?: string | null;
  created_at?: string | null;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<Token>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }, false),
  register: (data: { email: string; name: string; password: string; role?: string }) =>
    request<User>("/auth/register", { method: "POST", body: JSON.stringify(data) }, false),
  me: () => request<User>("/auth/me"),
  logout: () => request<{ message: string }>("/auth/logout", { method: "POST" }),

  dashboard: () => request<DashboardStats>("/dashboard/stats"),

  cameras: () => request<Camera[]>("/cameras"),
  createCamera: (data: { camera_name: string; location?: string; description?: string }) =>
    request<Camera>("/cameras", { method: "POST", body: JSON.stringify(data) }),

  videos: () => request<Video[]>("/videos"),
  video: (id: number) => request<Video>(`/videos/${id}`),
  videoStatus: (id: number) => request<ProcessingJob>(`/videos/${id}/status`),
  uploadVideo: (form: FormData) =>
    request<{ video_id: number; processing_job_id: number; status: string; filename: string }>(
      "/videos/upload",
      { method: "POST", body: form }
    ),
  processVideo: (id: number) =>
    request<ProcessingJob>(`/videos/${id}/process`, { method: "POST" }),

  clips: (id: number) => request<Clip[]>(`/videos/${id}/clips`),
  detections: (id: number) => request<Detection[]>(`/videos/${id}/detections`),
  events: (id: number) => request<Event[]>(`/videos/${id}/events`),

  clipMedia: (clipId: number) => request<MedialUrl>(`/media/clips/${clipId}`),
  thumbnailMedia: (clipId: number) => request<MedialUrl>(`/media/thumbnails/${clipId}`),
  originalMedia: (videoId: number) => request<MedialUrl>(`/media/original/${videoId}`),

  enrichVideo: (id: number) =>
    request<{ detail: string; video_id: number }>(`/videos/${id}/enrich`, { method: "POST" }),

  ragQuery: (body: { query: string; video_id?: number | null; camera_id?: number | null }) =>
    request<RAGResult>("/rag/query", { method: "POST", body: JSON.stringify(body) }),

  policyQuestion: (body: { question: string; video_id?: number | null }) =>
    request<PolicyQuestion>("/rag/policy-question", { method: "POST", body: JSON.stringify(body) }),

  findings: () => request<Finding[]>("/findings"),

  policies: () => request<Policy[]>("/policies"),
  policy: (policyId: string) =>
    request<Policy & { chunks: PolicyChunk[] }>(`/policies/${policyId}`),
  policySections: (policyId: string) => request<PolicyChunk[]>(`/policies/${policyId}/sections`),
  uploadPolicy: (form: FormData) =>
    request<Policy>("/policies/upload", { method: "POST", body: form }),
  searchPolicies: (query: string) =>
    request<PolicySearchHit[]>("/policies/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  // ---- Part 3: Agentic investigation ----

  investigations: () => request<Investigation[]>("/investigations"),
  investigation: (id: number) =>
    request<Investigation & { claims: Claim[]; timeline_events: TimelineEvent[] }>(
      `/investigations/${id}`
    ),
  createInvestigation: (data: {
    title: string;
    query: string;
    description?: string;
    video_id?: number | null;
  }) =>
    request<Investigation>("/investigations", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  investigationChat: (id: number, message: string) =>
    request<{ agent_result: AgentAnswer }>(`/investigations/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
  investigationTimeline: (id: number) =>
    request<TimelineEvent[]>(`/investigations/${id}/timeline`),
  investigationAudit: (id: number) =>
    request<{ id: number; action: string; user_id: number | null; details: string | null; created_at: string | null }[]>(
      `/investigations/${id}/audit`
    ),
  verifyClaim: (data: {
    claim_text: string;
    investigation_id: number;
    video_id?: number | null;
    timestamp?: number | null;
    persist?: boolean;
  }) =>
    request<Verification>(`/investigations/${data.investigation_id}/verify`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  claims: () => request<Claim[]>("/claims"),

  // ---- Part 4: Evidence workspace ----

  evidenceClaims: () => request<EvidenceClaimRow[]>("/evidence/claims"),
  evidenceClips: (videoId?: number) =>
    request<EvidenceClip[]>(
      `/evidence/clips${videoId ? `?video_id=${videoId}` : ""}`
    ),

  // ---- Part 4: Reports ----

  reports: () => request<Report[]>("/reports"),
  report: (id: number) => request<ReportDetail>(`/reports/${id}`),
  generateReport: (investigationId: number, title?: string) =>
    request<ReportDetail>(`/investigations/${investigationId}/report/generate`, {
      method: "POST",
      body: JSON.stringify(title ? { title } : {}),
    }),
  submitReport: (id: number) =>
    request<Report>(`/reports/${id}/submit`, { method: "POST" }),
  reviewReport: (id: number, decision: string, note?: string) =>
    request<Report>(`/reports/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  finalizeReport: (id: number) =>
    request<Report>(`/reports/${id}/finalize`, { method: "POST" }),
  reviewClaim: (reportId: number, claimId: number, data: {
    action: string;
    edited_text?: string;
    note?: string;
  }) =>
    request<ReviewDecision>(`/reports/${reportId}/claims/${claimId}/review`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  reportAudit: (id: number) => request<ReportAuditEntry[]>(`/reports/${id}/audit`),
  reportFileUrl: (id: number, download = false) =>
    `${API_URL}/reports/${id}/file?download=${download}`,
};
