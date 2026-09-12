// Networking configuration.
//
// NEXT_PUBLIC_API_URL: REST API base URL (default http://127.0.0.1:8000).
//   Must be reachable from the *open browser*. On a physical-device test the
//   phone cannot reach 127.0.0.1 of the PC, so set it to the PC's LAN address,
//   e.g. http://192.168.1.100:8000 (or the HTTPS dev URL).
// NEXT_PUBLIC_API_BASE_URL: optional alias; overrides NEXT_PUBLIC_API_URL when set.
// NEXT_PUBLIC_WEBRTC_SIGNALING_URL: optional separate base for WebSocket
//   signaling/live channels. When unset, the WebSocket origin is derived from
//   the API URL (http->ws, https->wss). Used when the signaling infra lives on a
//   different host/port than the REST API.
export const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://127.0.0.1:8000";
const SIGNALING_BASE = process.env.NEXT_PUBLIC_WEBRTC_SIGNALING_URL;

function toWs(url: string): string {
  // http://... -> ws://...,  https://... -> wss://...
  return url.replace(/^http/, "ws");
}

export function wsUrl(path: string): string {
  const base = SIGNALING_BASE || API_URL;
  return `${toWs(base)}${path}`;
}

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
  camera_type?: string | null;
  stream_source?: string | null;
  is_live?: boolean;
  stream_status?: string;
  created_at?: string | null;
};

// ---- Phase 1: Live mobile camera ----

export type CameraSession = {
  id: number;
  camera_id: number;
  status: string;
  transport: string;
  fps_target?: number | null;
  started_by_user_id?: number | null;
  started_at?: string | null;
  stopped_at?: string | null;
  error?: string | null;
  frames_received: number;
  frames_sampled: number;
  frames_buffered: number;
  latest_frame_at?: string | null;
  created_at?: string | null;
};

export type LiveStatus = {
  camera_id: number;
  camera_name?: string | null;
  session_id?: number | null;
  active: boolean;
  status: string;
  transport?: string | null;
  fps_target?: number | null;
  window_seconds?: number | null;
  max_frames?: number | null;
  frames_received: number;
  frames_sampled: number;
  frames_buffered: number;
  buffer_start?: number | null;
  buffer_end?: number | null;
  started_by_user_id?: number | null;
  started_at?: string | null;
  stopped_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  detection_enabled?: boolean | null;
  detection_error?: string | null;
  detection_metrics?: LiveDetectionMetrics | null;
  detection_recent_count?: number | null;
  tracking_enabled?: boolean | null;
  active_tracks?: number | null;
  total_events?: number | null;
  vlm_enabled?: boolean | null;
  vlm_last_error?: string | null;
  vlm_requests?: number | null;
  vlm_observations?: number | null;
};

export type LiveStatusEvent = {
  type: string;
  camera_id?: number;
  session_id?: number | null;
  status?: string;
  error?: string | null;
  frames_received?: number;
  frames_sampled?: number;
  frames_buffered?: number;
};

// ---- Phase 2: live detection overlay types ----

export type LiveDetectionBbox = [number, number, number, number]; // [x1, y1, x2, y2] absolute pixels

export type LiveDetectionObject = {
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: LiveDetectionBbox;
};

export type LiveDetectionFrame = {
  type: "detection";
  session_id: number | null;
  camera_id: number;
  frame_id: number | null;
  timestamp: number;
  frame_width: number | null;
  frame_height: number | null;
  detections: LiveDetectionObject[];
};

export type LiveDetectionMetrics = {
  total_input: number;
  total_sampled: number;
  total_processed: number;
  total_detections: number;
  total_dropped: number;
  inference_errors: number;
  input_fps: number;
  sampled_fps: number;
  processed_fps: number;
  detection_fps: number;
  inference_latency_avg_ms: number;
  inference_latency_max_ms: number;
  queue_depth: number;
};

export type LiveDetectionStatusEvent = {
  type: "detection_status" | "detection_keepalive";
  camera_id: number;
  detection_enabled: boolean;
  detection_error?: string | null;
  detection_metrics?: LiveDetectionMetrics | null;
  recent?: LiveDetectionFrame[];
};

// ---- Phase 3: live tracking overlay types ----

export type TrackUpdate = {
  type: "track_update";
  tracking_id: string;
  frame_index: number;
  bbox?: number[];
  velocity_px_per_frame: number;
  distance_traveled_px: number;
  stationary_seconds: number;
  state: string;
  frame_timestamp?: string | null;
  session_id?: string | null;
  camera_id?: string | null;
};

export type TrackingEvent = {
  type: "track_event" | "tracking_event";
  event_id: string;
  event_type: string;
  tracking_id: string;
  frame_index: number;
  frame_timestamp?: string | null;
  description?: string | null;
  session_id?: string | null;
  camera_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at?: string | null;
};

export type TrackingMetricsOut = {
  type: "tracking_metrics";
  active_tracks: number;
  active_updates?: number | null;
  lost_tracks: number;
  removed_tracks: number;
  total_updates: number;
  total_events: number;
  events_by_type?: Record<string, number>;
  latency_avg_ms?: number | null;
  latency_max_ms?: number | null;
  started_at?: string | null;
};

export type TrackSummary = {
  tracking_id: string;
  first_seen_frame: number;
  last_seen_frame: number;
  frames_present: number;
  total_path_px: number;
  last_state: string;
  bbox_current?: LiveDetectionBbox | null;
};

export type TrackingStatusEvent = {
  type: "tracking_status" | "tracking_keepalive";
  camera_id: number;
  tracking_enabled: boolean;
  active_tracks?: number | null;
  total_events?: number | null;
};

// ---- Phase 4: live VLM observation types ----

export type VlmSourceFrame = {
  frame_id: number;
  sequence: number;
  timestamp: number;
  width?: number | null;
  height?: number | null;
};

export type VlmObservationItem = {
  item_id: string;
  statement: string;
  classification: "OBSERVED" | "INFERRED" | "UNKNOWN";
  confidence: number;
  basis?: string[];
};

export type VlmObservation = {
  type: "vlm_observation";
  observation_id: string;
  request_id: string;
  camera_id: number;
  camera_name?: string | null;
  session_id?: number | null;
  trigger: string;
  trigger_detail?: string | null;
  source_frames: VlmSourceFrame[];
  window_start?: number | null;
  window_end?: number | null;
  summary: string;
  items: VlmObservationItem[];
  notes?: string[];
  model?: string;
  provider_mode: "simulation" | "openai";
  created_at: string;
};

export type VlmRequestMessage = {
  type: "vlm_request";
  request_id: string;
  camera_id: number;
  session_id?: number | null;
  trigger: string;
  trigger_detail?: string | null;
  provider_mode: string;
  active: boolean;
  context?: Record<string, unknown>;
  created_at: string;
};

export type VlmMetricsMessage = {
  type: "vlm_metrics";
  total_requests: number;
  total_observations: number;
  total_errors: number;
  total_retries: number;
  dropped_requests: number;
  cooldown_active: boolean;
  last_error?: string | null;
  last_observation_at?: string | null;
  avg_latency_ms: number;
  max_latency_ms: number;
};

export type VlmErrorMessage = {
  type: "vlm_error";
  camera_id: number;
  request_id: string;
  detail: string;
  at: string;
};

export type VlmStatusMessage = {
  type: "vlm_status";
  camera_id: number;
  vlm_enabled: boolean;
  vlm_last_error?: string | null;
  vlm_requests?: number | null;
  vlm_observations?: number | null;
  recent?: VlmObservation[];
};

export type VlmKeepaliveMessage = {
  type: "vlm_keepalive";
  camera_id: number;
  vlm_enabled: boolean;
};

export type VlmAnalyzeResult = {
  camera_id: number;
  session_id?: number | null;
  request_id: string;
  status: string;
};

export type LiveEvidence = {
  id: number;
  public_id: string;
  evidence_type: string;
  source: string;
  camera_id?: number | null;
  session_id?: number | null;
  event_id?: string | null;
  event_type?: string | null;
  tracking_id?: string | null;
  frame_sequence?: number | null;
  frame_timestamp?: number | null;
  window_start?: number | null;
  window_end?: number | null;
  vlm_observation_id?: string | null;
  captured_at?: string | null;
  storage_path?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  sha256?: string | null;
  size_bytes?: number | null;
  content_text?: string | null;
  index_status: string;
  index_attempts?: number | null;
  index_error?: string | null;
  indexed_at?: string | null;
};

export type LiveEvidenceDetail = LiveEvidence & {
  metadata: Record<string, unknown>;
  source_frame_ids: number[];
  provenance: {
    evidence_id: string;
    generated_by?: string;
    source?: string;
    event_type?: string;
    tracking_id?: string;
    camera_id?: number | null;
    session_id?: number | null;
    captured_at?: string | null;
    [key: string]: unknown;
  };
  observation?: {
    observation_id: string;
    request_id?: string | null;
    trigger?: string | null;
    trigger_detail?: string | null;
    summary?: string | null;
    items?: string | null;
    notes?: string | null;
    model?: string | null;
    provider_mode?: string | null;
    source_frames?: string | null;
    window_start?: number | null;
    window_end?: number | null;
    created_at?: string | null;
  } | null;
};

export type EvidenceSearchHit = {
  evidence_id?: string | null;
  score: number;
  evidence_type?: string | null;
  source?: string | null;
  camera_id?: number | null;
  session_id?: number | null;
  timestamp?: number | null;
  event_id?: string | null;
  event_type?: string | null;
  tracking_id?: string | null;
  frame_sequence?: number | null;
  vlm_observation_id?: string | null;
  storage_path?: string | null;
  sha256?: string | null;
  source_text?: string | null;
};

export type EvidenceSearchResult = {
  query: string;
  count: number;
  results: EvidenceSearchHit[];
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

// ---- Demo Investigation Dataset ----

export type DemoVideoAsset = {
  demo_id: string;
  filename: string;
  path: string;
  abs_path: string;
  thumbnail_path?: string | null;
  duration?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  size_bytes?: number | null;
  sha256?: string | null;
  license?: string | null;
  source_repo?: string | null;
  source_url?: string | null;
  scene_archetype?: string | null;
  description?: string | null;
  stable_name?: string | null;
  scenario_keys?: string[];
  uploaded?: boolean | null;
  status?: string | null;
  video_id?: number | null;
};

export type DemoScenario = {
  scenario_id: string;
  key: string;
  stable_name?: string | null;
  title?: string | null;
  purpose?: string | null;
  labels?: string[];
  event_expectation?: string | null;
  videos?: { demo_id: string; filename: string; stable_name?: string }[];
  observed_questions?: string[];
  unknown_questions?: string[];
  disclaimer?: string | null;
};

export type DemoManifest = {
  dataset_name?: string;
  version?: string;
  disclaimer?: string;
  scenario_catalog?: { key: string; stable_name: string; demo_ids: string[] }[];
  videos: DemoVideoAsset[];
  keyframes: { filename: string; path: string; abs_path: string; source_demo_id: string }[];
  thumbnails?: { demo_id: string; filename: string; path: string; abs_path?: string; sha256?: string }[];
  fixtures: { filename: string; path: string; abs_path: string; kind: string }[];
};

export type DemoCase = {
  case_id: string;
  title?: string | null;
  description?: string | null;
  video_file: string;
  video_demo_id?: string | null;
  expected_events_file?: string | null;
  expected_observations_file?: string | null;
  query?: string | null;
  priority?: string | null;
  status?: string | null;
  scenario_ids?: string[] | null;
  [key: string]: unknown;
};

export type DemoDisclaimer = {
  disclaimer: string;
  dataset_root: string;
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

// ---- Phase 6: Grounded investigation search over live forensic evidence ----

export type InvestigationSearchEvidence = {
  rank: number;
  evidence_id: string;
  evidence_type?: string | null;
  source?: string | null;
  camera_id?: number | null;
  camera_name?: string | null;
  session_id?: number | null;
  timestamp?: number | null;
  start_time?: number | null;
  end_time?: number | null;
  event_id?: string | null;
  event_type?: string | null;
  tracking_id?: string | null;
  object_class?: string | null;
  vlm_observation_id?: string | null;
  storage_path?: string | null;
  sha256?: string | null;
  content_text?: string;
  retrieval_score?: number | null;
  reasons?: string[];
  verified?: boolean;
};

export type InvestigationSearchResult = {
  query: string;
  status: string;
  answer: string;
  confidence: number;
  results: InvestigationSearchEvidence[];
  sources: Record<string, unknown>;
  limitations?: string[];
  analysis?: Record<string, unknown>;
};

// ---- Phase 7: Controlled investigation runs (bounded agent) ----

export type RunClassification = {
  category: string;
  category_reason: string;
  unanswerable: boolean;
  temporal?: boolean;
  query?: string;
  tracking_id?: string | null;
  evidence_ids?: string[];
};

export type RunPlanStep = {
  tool: string;
  args: Record<string, unknown>;
  description: string;
};

export type RunStep = {
  node: string;
  input?: string;
  output: string;
};

export type RunFinding = {
  text: string;
  status: string;
  claim_type: string;
  confidence: number;
  verification: {
    result: string;
    reason: string;
    checks: Record<string, boolean>;
  };
  conflicts: Array<{
    kind: string;
    reason: string;
    evidence_a: string;
    evidence_b: string;
  }>;
  evidence: Array<{
    evidence_id: string | null;
    camera_id?: number | null;
    timestamp?: number | null;
    event_type?: string | null;
    tracking_id?: string | null;
    object_class?: string | null;
    camera_name?: string | null;
    score?: number | null;
    verified?: boolean | null;
  }>;
};

export type RunResult = {
  query: string;
  status: string;
  summary: string;
  findings: RunFinding[];
  conflicts: RunFinding["conflicts"];
  timeline: Array<{
    timestamp: number;
    description: string;
    status: string;
    evidence_ids: string[];
  }>;
  evidence_used: RunFinding["evidence"];
  limitations: string[];
};

export type RunMetrics = {
  steps_used: number;
  tool_calls: number;
  evidence_used: number;
  elapsed_s: number;
  expansions: number;
  reviewable: boolean;
  require_review: boolean;
};

export type InvestigationRun = {
  id: number;
  investigation_id: number;
  status: string;
  query: string;
  classification: RunClassification;
  plan: { steps: RunPlanStep[] } | null;
  steps: RunStep[];
  claims: Array<{
    text: string;
    status: string;
    confidence: number;
    verification: { result: string; reason: string };
  }>;
  result: RunResult;
  metrics: RunMetrics;
  error?: string | null;
  created_by_user_id: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type RunRow = {
  id: number;
  investigation_id: number;
  status: string;
  query: string;
  metrics: Partial<RunMetrics>;
  error?: string | null;
  created_at: string;
  completed_at?: string | null;
};

// ---- Phase 8: Forensic verification / timeline / reporting types ----

export type ForensicTimelineEntry = {
  timeline_event_id: string;
  timestamp: number;
  end_timestamp?: number | null;
  camera_id?: number | null;
  camera_name?: string | null;
  track_id?: string | null;
  object_class?: string | null;
  event_type?: string | null;
  evidence_ids: string[];
  description: string;
  classification: string;
  confidence?: number;
  source?: string;
  verification_status: string;
  quality_flags: string[];
  conflicts: string[];
  event_time?: number | null;
  analysis_time?: string | null;
  storage_time?: string | null;
};

export type ForensicFinding = {
  finding_id: string;
  timeline_event_id: string;
  text: string;
  classification: string;
  verification_status: string;
  evidence_support: number;
  support_factors: Array<{ label: string; weight: number; matched: boolean }>;
  support_reason: string;
  supporting_evidence: string[];
  limitations: string[];
  causality_safe: boolean;
  discovered_conflicts?: string[];
  review_status?: string;
};

export type ForensicAnalysis = {
  run_id: number;
  investigation_id: number;
  investigation_title?: string;
  status: string;
  summary: string;
  timeline: ForensicTimelineEntry[];
  findings: ForensicFinding[];
  correlations: Array<{ evidence_a: string; evidence_b: string; relation: string }>;
  contradictions: Array<{ evidence_a: string; evidence_b: string; type?: string; reason?: string }>;
  gaps: { gaps: Array<{ kind: string; detail?: unknown; note?: string }>; quality: Record<string, string[]>; coverage: { cameras: string[] } };
  relationships: Array<{ relationship: string; entry_a: string; entry_b: string; causal: boolean }>;
  multi_camera: Array<{ track_id: string; cameras: unknown[]; status: string; note: string }>;
  metrics: Record<string, number>;
};

export type FindingReview = {
  id: number;
  run_id: number;
  finding_id: string;
  action: string;
  comment?: string | null;
  reviewer_user_id?: number | null;
  reviewer_name?: string | null;
  reviewed_at?: string | null;
};

export type RunReview = {
  decision: string;
  reviewer?: string | null;
  details?: string | null;
  created_at?: string | null;
};

export type ForensicReportMeta = {
  report_id: number;
  run_id: number;
  title?: string;
  version: number;
  file_format: string;
  storage_path?: string;
  status?: string;
  generated_at?: string | null;
};

export type ForensicReportPayload = ForensicReportMeta & {
  content: Record<string, unknown>;
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

async function downloadBlob(path: string): Promise<{ filename: string; url: string }> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_URL}${path}`, { headers });
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
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = match ? match[1] : "forensic-report.bin";
  const blob = await res.blob();
  return { filename, url: URL.createObjectURL(blob) };
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
  createCamera: (data: {
    camera_name: string;
    location?: string;
    description?: string;
    camera_type?: string;
    stream_source?: string;
  }) => request<Camera>("/cameras", { method: "POST", body: JSON.stringify(data) }),

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

// ---- Demo Investigation Dataset ----

  demoDisclaimer: () => request<DemoDisclaimer>("/demo/disclaimer"),
  demoDataset: () => request<DemoManifest>("/demo/dataset"),
  demoScenarios: () => request<DemoScenario[]>("/demo/scenarios"),
  demoScenario: (scenarioId: string) => request<DemoScenario>(`/demo/scenarios/${scenarioId}`),
  demoThumbnailUrl: (demoId: string) => `${API_URL}/demo/thumbnails/${demoId}.jpg`,
  demoKeyframeUrl: (demoId: string, index: number) => `${API_URL}/demo/videos/${demoId}/keyframe/${index}.jpg`,
  demoCases: () => request<DemoCase[]>("/demo/cases"),
  demoCase: (caseId: string) => request<DemoCase>(`/demo/cases/${caseId}`),
  demoInvestigationQueries: (scenarioId: string) =>
    request<{ scenario_id: string; key: string; queries: { ungrounded: string[]; grounded: string[]; unknown: string[] } }>(
      `/demo/investigation_queries/${scenarioId}`
    ),

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

  // ---- Phase 1: Live mobile camera ----

  liveStart: (
    cameraId: number,
    opts?: {
      transport?: string;
      fps_target?: number;
      buffer_window_seconds?: number;
      buffer_max_frames?: number;
      video_path?: string;
    }
  ) =>
    request<CameraSession>(`/live/cameras/${cameraId}/start`, {
      method: "POST",
      body: JSON.stringify(opts || {}),
    }),
  liveStop: (cameraId: number) =>
    request<CameraSession>(`/live/cameras/${cameraId}/stop`, {
      method: "POST",
    }),
  liveStatus: (cameraId: number) =>
    request<LiveStatus>(`/live/cameras/${cameraId}/status`),
  liveSessions: () => request<LiveStatus[]>("/live/sessions"),
  liveVlmAnalyze: (cameraId: number) =>
    request<VlmAnalyzeResult>(`/live/cameras/${cameraId}/vlm/analyze`, {
      method: "POST",
      body: JSON.stringify({ trigger: "manual" }),
    }),

  // ---- Phase 5: Live forensic evidence ----

  liveEvidenceList: (params?: {
    camera_id?: number;
    session_id?: number;
    evidence_type?: string;
    index_status?: string;
    limit?: number;
  }) => {
    const qp = new URLSearchParams();
    if (params?.camera_id) qp.set("camera_id", String(params.camera_id));
    if (params?.session_id) qp.set("session_id", String(params.session_id));
    if (params?.evidence_type) qp.set("evidence_type", params.evidence_type);
    if (params?.index_status) qp.set("index_status", params.index_status);
    if (params?.limit) qp.set("limit", String(params.limit));
    const qs = qp.toString();
    return request<LiveEvidence[]>(`/evidence/live${qs ? `?${qs}` : ""}`);
  },
  liveEvidenceDetail: (publicId: string) =>
    request<LiveEvidenceDetail>(`/evidence/live/${publicId}`),
  liveEvidenceContentUrl: (publicId: string) =>
    `${API_URL}/evidence/live/${publicId}/content`,
  liveEvidenceContent: async (publicId: string): Promise<Blob> => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(api.liveEvidenceContentUrl(publicId), { headers });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return res.blob();
  },
  liveEvidenceReindex: (publicId: string) =>
    request<LiveEvidence & { reindexed: boolean; queue_size: number }>(
      `/evidence/live/${publicId}/reindex`,
      { method: "POST" }
    ),
  liveEvidenceSearch: (
    query: string,
    evidenceType?: string,
    limit?: number
  ) => {
    const qp = new URLSearchParams();
    if (evidenceType) qp.set("evidence_type", evidenceType);
    if (limit) qp.set("limit", String(limit));
    const qs = qp.toString();
    return request<EvidenceSearchResult>(
      `/evidence/live/search${qs ? `?${qs}` : ""}`,
      {
        method: "POST",
        body: JSON.stringify({ query }),
      }
    );
  },

  // ---- Phase 6: Grounded investigation search ----

  investigationSearch: (body: {
    query: string;
    case_id: number;
    top_k?: number;
  }) =>
    request<InvestigationSearchResult>("/investigation/search", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- Phase 7: Controlled investigation runs ----

  startInvestigationRun: (investigationId: number, body: {
    query: string;
    require_review?: boolean;
  }) =>
    request<InvestigationRun>(`/investigations/${investigationId}/investigate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  investigationRuns: (investigationId: number) =>
    request<{ runs: RunRow[] }>(`/investigations/${investigationId}/runs`),
  investigationRun: (runId: number) =>
    request<InvestigationRun>(`/runs/${runId}`),
  reviewInvestigationRun: (runId: number, body: {
    decision: "APPROVE" | "REJECT";
    note?: string;
  }) =>
    request<InvestigationRun>(`/runs/${runId}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ---- Phase 8: Forensic verification / timeline / reporting ----

  forensicAnalyze: (runId: number) =>
    request<ForensicAnalysis>(`/runs/${runId}/forensic/analyze`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  forensicOfRun: (runId: number) =>
    request<ForensicAnalysis & { timeline_rows?: unknown[] }>(`/runs/${runId}/forensic`),
  reviewFinding: (runId: number, findingId: string, body: {
    action: "ACCEPTED" | "REJECTED" | "MARKED_UNCERTAIN" | "REQUESTED_MORE_EVIDENCE";
    comment?: string;
  }) =>
    request<FindingReview>(`/runs/${runId}/findings/${findingId}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  runReviews: (runId: number) =>
    request<{ run_id: number; run_status: string; run_reviews: RunReview[]; finding_reviews: FindingReview[] }>(`/runs/${runId}/reviews`),
  generateForensicReport: (runId: number) =>
    request<ForensicReportMeta>(`/runs/${runId}/report`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  forensicReport: (runId: number) =>
    request<ForensicReportMeta & { content: Record<string, unknown> }>(`/runs/${runId}/report`),
  forensicReportFile: (runId: number) => downloadBlob(`/runs/${runId}/report/file`),
};
