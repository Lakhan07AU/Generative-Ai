from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    Boolean,
    Text,
    Float,
)
from sqlalchemy.orm import relationship

from app.database.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="INVESTIGATOR")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cameras = relationship("Camera", back_populates="created_by")
    videos = relationship("Video", back_populates="uploaded_by")
    audit_logs = relationship("AuditLog", back_populates="user")


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    camera_name = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    # Phase 1: live capture metadata
    camera_type = Column(String(50), default="CCTV", nullable=False)  # CCTV | MOBILE | OTHER
    stream_source = Column(String(255), nullable=True)
    is_live = Column(Boolean, default=False, nullable=False)
    stream_status = Column(String(50), default="OFFLINE", nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = relationship("User", back_populates="cameras")
    videos = relationship("Video", back_populates="camera")
    clips = relationship("Clip", back_populates="camera")
    detections = relationship("Detection", back_populates="camera")
    live_sessions = relationship(
        "CameraSession", back_populates="camera", cascade="all, delete-orphan"
    )


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(512), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    fps = Column(Float, nullable=True)
    codec = Column(String(100), nullable=True)
    recording_date = Column(DateTime, nullable=True)
    start_time = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="UPLOADED", nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    # Original uploaded media is immutable; object lock is applied in MinIO.

    camera = relationship("Camera", back_populates="videos")
    uploaded_by = relationship("User", back_populates="videos")
    processing_jobs = relationship(
        "ProcessingJob", back_populates="video", cascade="all, delete-orphan"
    )
    clips = relationship("Clip", back_populates="video", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="video", cascade="all, delete-orphan")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    status = Column(String(50), default="QUEUED", nullable=False)
    stage = Column(String(50), nullable=True)
    progress = Column(Float, default=0.0)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="processing_jobs")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, index=True)
    # Public / UI-facing clip identifier e.g. CLIP-001
    public_id = Column(String(50), unique=True, nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    storage_path = Column(String(512), nullable=True)
    thumbnail_path = Column(String(512), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="clips")
    camera = relationship("Camera", back_populates="clips")
    detections = relationship("Detection", back_populates="clip", cascade="all, delete-orphan")
    events = relationship("Event", back_populates="clip", cascade="all, delete-orphan")
    clip_description = relationship("ClipDescription", back_populates="clip", uselist=False, cascade="all, delete-orphan")


class Detection(Base):
    __tablename__ = "detections"

    id = Column(Integer, primary_key=True, index=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    label = Column(String(100), nullable=False)
    bounding_box = Column(Text, nullable=False)  # JSON [x1,y1,x2,y2]
    frame_number = Column(Integer, nullable=True)
    timestamp = Column(Float, nullable=True)
    detection_confidence = Column(Float, nullable=True)
    tracking_id = Column(String(100), nullable=True)

    clip = relationship("Clip", back_populates="detections")
    video = relationship("Video")
    camera = relationship("Camera", back_populates="detections")


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=True)
    event_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    start_time = Column(Float, nullable=True)
    end_time = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="events")
    clip = relationship("Clip", back_populates="events")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(255), nullable=False)
    entity_type = Column(String(100), nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# Part 2 - Multimodal AI / Video RAG / Policy RAG
# ---------------------------------------------------------------------------


class ClipDescription(Base):
    """Structured VLM semantic description of an extracted clip."""

    __tablename__ = "clip_descriptions"

    id = Column(Integer, primary_key=True, index=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    summary = Column(Text, nullable=False)
    objects = Column(Text, nullable=True)  # JSON array of object labels
    observable_actions = Column(Text, nullable=True)  # JSON array of action strings
    location_context = Column(Text, nullable=True)
    transcript_reference = Column(Text, nullable=True)
    source = Column(String(50), default="simulation")  # "vlm" | "simulation"
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    clip = relationship("Clip", back_populates="clip_description")


class Transcript(Base):
    """Timestamped speech/audio transcript segment."""

    __tablename__ = "transcripts"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=True)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video")
    clip = relationship("Clip")


class PolicyDocument(Base):
    """A security policy document uploaded by an ADMIN."""

    __tablename__ = "policy_documents"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String(64), unique=True, nullable=False)  # public id e.g. POL-0001
    document_name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=True)
    storage_path = Column(String(512), nullable=True)
    source_format = Column(String(20), nullable=True)  # pdf | docx | txt
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(50), default="INDEXED", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    chunks = relationship("PolicyChunk", back_populates="document", cascade="all, delete-orphan")
    uploaded_by = relationship("User")


class PolicyChunk(Base):
    """Section-aware chunk of an indexed policy document."""

    __tablename__ = "policy_chunks"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey("policy_documents.id"), nullable=False)
    section = Column(String(255), nullable=True)
    page = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("PolicyDocument", back_populates="chunks")


class Finding(Base):
    """A finding produced by video/policy analysis with an evidence status.

    Statuses:
      OBSERVED        - directly supported by video/audio
      INFERRED        - model interpretation
      POLICY-ASSESSED - observed event compared with retrieved policy
      VERIFIED        - passed evidence checks
      UNKNOWN         - insufficient evidence
    """

    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=True)
    finding_status = Column(String(30), nullable=False, default="UNKNOWN")
    finding_type = Column(String(60), nullable=True)  # video | policy_assessment
    question = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    retrieval_score = Column(Float, nullable=True)
    policy_id = Column(Integer, ForeignKey("policy_documents.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video")
    clip = relationship("Clip")
    policy = relationship("PolicyDocument")


# ---------------------------------------------------------------------------
# Part 3 - Agentic investigation / evidence verification / claim traceability
# ---------------------------------------------------------------------------


class Investigation(Base):
    """A bounded agentic investigation workspace around a user's query.

    Created by an investigator; holds a chat, generated claims, a timeline and
    an audit trail. Original evidence is never modified by the agent.
    """

    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    query = Column(Text, nullable=False)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=True)
    status = Column(String(50), default="OPEN", nullable=False)  # OPEN | COMPLETED | CLOSED
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = relationship("User")
    video = relationship("Video")
    claims = relationship("Claim", back_populates="investigation", cascade="all, delete-orphan")
    timeline_events = relationship(
        "TimelineEvent", back_populates="investigation", cascade="all, delete-orphan"
    )
    reports = relationship("Report", back_populates="investigation", cascade="all, delete-orphan")
    runs = relationship(
        "InvestigationRun", back_populates="investigation", cascade="all, delete-orphan"
    )


class Claim(Base):
    """A traceable, verifiable statement produced by or attributed to an investigation.

    claim_type: OBSERVATION | INFERENCE | POLICY_VIOLATION | QUESTION
    status:    OPEN | VERIFIED | PARTIALLY_VERIFIED | INSUFFICIENT_EVIDENCE | REJECTED
    """

    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    claim_text = Column(Text, nullable=False)
    claim_type = Column(String(60), nullable=False, default="OBSERVATION")
    status = Column(String(60), nullable=False, default="OPEN")
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    investigation = relationship("Investigation", back_populates="claims")
    evidence_links = relationship(
        "ClaimEvidence", back_populates="claim", cascade="all, delete-orphan"
    )
    verifications = relationship(
        "Verification", back_populates="claim", cascade="all, delete-orphan"
    )


class ClaimEvidence(Base):
    """Link between a claim and a piece of supporting evidence (clip / frame)."""

    __tablename__ = "claim_evidence"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=True)
    frame_id = Column(Integer, nullable=True)
    timestamp = Column(Float, nullable=True)
    evidence_type = Column(String(60), nullable=True)  # clip | frame | transcript | detection
    relevance_score = Column(Float, nullable=True)

    claim = relationship("Claim", back_populates="evidence_links")
    clip = relationship("Clip")


class Verification(Base):
    """A recorded evidence-verification result for a claim.

    Result:
      VERIFIED                - all required checks passed
      PARTIALLY_VERIFIED      - some checks passed, or evidence conflicts
      INSUFFICIENT_EVIDENCE   - not enough evidence to conclude
    """

    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, index=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    checks = Column(Text, nullable=True)  # JSON dict of individual check results
    result = Column(String(60), nullable=False, default="INSUFFICIENT_EVIDENCE")
    reason = Column(Text, nullable=True)
    verifier_version = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    claim = relationship("Claim", back_populates="verifications")


class TimelineEvent(Base):
    """A single evidence-backed event on an investigation timeline.

    status: VERIFIED | PARTIALLY_VERIFIED | INFERRED | UNVERIFIED
    """

    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    timestamp = Column(Float, nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(60), nullable=False, default="UNVERIFIED")
    evidence_ids = Column(Text, nullable=True)  # JSON array of evidence ids
    created_at = Column(DateTime, default=datetime.utcnow)

    investigation = relationship("Investigation", back_populates="timeline_events")


class InvestigationRun(Base):
    """A single Phase 7 controlled investigation run over forensic evidence.

    Complements ``Investigation`` (the case workspace) with an executable,
    observable orchestration record:

      * ``status``  - the run status machine:
        CREATED -> PLANNING -> RETRIEVING -> ANALYZING -> VERIFYING ->
        BUILDING_TIMELINE -> READY_FOR_REVIEW -> COMPLETED
        (terminal: FAILED | CANCELLED)
      * ``classification`` - deterministic query classification snapshot.
      * ``plan`` - the inspectable, tool-oriented investigation plan.
      * ``steps`` - executed node history (node, tools, counts) for audit.
      * ``claims`` - claim snapshot produced by the run (OBSERVED/INFERRED/
        UNKNOWN with verification results).
      * ``result`` - final synthesized answer + limitations + conflict notes.
      * ``metrics`` - bounds usage (steps, tool calls, evidence, elapsed) so a
        run can be audited against the Phase 7 boundedness guarantees.

    Concrete Claim / Verification / TimelineEvent rows are ALSO persisted into
    the shared Part 3 workspace models so the run feeds the existing UI/API.
    """

    __tablename__ = "investigation_runs"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    status = Column(String(50), default="CREATED", nullable=False)
    query = Column(Text, nullable=False)
    classification = Column(Text, nullable=True)  # JSON
    plan = Column(Text, nullable=True)  # JSON list of planned steps
    steps = Column(Text, nullable=True)  # JSON list of executed node snapshots
    claims = Column(Text, nullable=True)  # JSON claim snapshot
    result = Column(Text, nullable=True)  # JSON final result
    metrics = Column(Text, nullable=True)  # JSON bounds usage
    error = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    investigation = relationship("Investigation", back_populates="runs")
    created_by = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InvestigationRun {self.id} status={self.status}>"


# ---------------------------------------------------------------------------
# Part 4 - Human review + report generation
# ---------------------------------------------------------------------------


class Report(Base):
    """A structured incident report generated from an investigation.

    Status flow:
      DRAFT -> PENDING_REVIEW -> APPROVED (-> FINAL when finalised)
      DRAFT -> PENDING_REVIEW -> REJECTED

    Only an APPROVED report can be set FINAL.
    The rendered PDF / markdown file is stored in MinIO (``storage_path``).
    The full structured content (11 sections, claims, timeline) is persisted as
    JSON in ``content`` so the file and metadata can be regenerated / previewed.
    """

    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    title = Column(String(255), nullable=False)
    status = Column(String(50), default="DRAFT", nullable=False)  # DRAFT | PENDING_REVIEW | APPROVED | REJECTED
    is_final = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    content = Column(Text, nullable=True)  # JSON structured report
    storage_path = Column(String(512), nullable=True)
    file_format = Column(String(20), default="pdf", nullable=False)  # pdf | markdown
    generated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    investigation = relationship("Investigation", back_populates="reports")
    generated_by = relationship("User", foreign_keys=[generated_by_user_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])
    review_decisions = relationship(
        "ReviewDecision", back_populates="report", cascade="all, delete-orphan"
    )


class ReviewDecision(Base):
    """A human reviewer's decision on a single claim within a report.

    action: ACCEPT | REJECT | EDIT | UNCERTAIN
    For EDIT both the original AI claim text and the reviewer's edited text are
    stored, along with the reviewer id and the review timestamp (audit).
    """

    __tablename__ = "report_review_decisions"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=True)
    action = Column(String(30), nullable=False)  # ACCEPT | REJECT | EDIT | UNCERTAIN
    original_text = Column(Text, nullable=True)
    edited_text = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, default=datetime.utcnow)

    report = relationship("Report", back_populates="review_decisions")
    claim = relationship("Claim")
    reviewer = relationship("User", foreign_keys=[reviewer_user_id])


# ---------------------------------------------------------------------------
# Phase 1 - Live mobile camera streaming / session tracking
# ---------------------------------------------------------------------------


class CameraSession(Base):
    """A single live capture session for a camera (Phase 1 WebRTC ingest).

    Status flow::

      CONNECTING -> LIVE -> STOPPING -> COMPLETED
         |                                 |
         +---------- ERROR / DISCONNECTED -+

    A session is created when a live stream is started, and the same row is
    updated as frames are ingested so operators can audit live feeds.
    """

    __tablename__ = "camera_sessions"

    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=False)
    status = Column(String(50), default="CONNECTING", nullable=False)
    transport = Column(String(20), default="webrtc", nullable=False)  # webrtc | simulation
    fps_target = Column(Float, default=5.0, nullable=False)
    started_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    stopped_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    frames_received = Column(Integer, default=0, nullable=False)
    frames_sampled = Column(Integer, default=0, nullable=False)
    frames_buffered = Column(Integer, default=0, nullable=False)
    latest_frame_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    camera = relationship("Camera", back_populates="live_sessions")
    started_by = relationship("User", foreign_keys=[started_by_user_id])
    evidence = relationship(
        "ForensicEvidence", back_populates="session", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Phase 5 - Live evidence capture / durable forensic evidence + indexing
# ---------------------------------------------------------------------------


class ForensicEvidence(Base):
    """A durable, traceable piece of evidence captured from a live session.

    Two evidence kinds exist:
      * RAW_SOURCE - the stored encoded frame (JPEG) exactly as captured.
      * DERIVED    - semantic evidence built on top of source visuals (a tracking
                     event, a VLM observation) that references its source frames.

    Every row records server-generated provenance: what happened, which camera /
    session / event / track / observation it came from, where the object bytes
    live (``storage_path``), how to verify them (``sha256``) and the current
    vector-index state. Original source visuals are never modified - the stored
    object is a copy-encoded derivative and deduplicated by exact byte content.
    """

    __tablename__ = "forensic_evidence"

    id = Column(Integer, primary_key=True, index=True)
    # Public / UI-facing identifier e.g. "EVD-{uuid hex}".
    public_id = Column(String(64), unique=True, index=True, nullable=False)
    # FRAME | IMAGE | CLIP | DETECTION | TRACK_EVENT | VLM_OBSERVATION
    evidence_type = Column(String(40), nullable=False)
    # RAW_SOURCE | DERIVED
    source = Column(String(40), nullable=False, default="DERIVED")

    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    session_id = Column(Integer, ForeignKey("camera_sessions.id"), nullable=True)

    # Provenance chain links (all server-generated; never client-supplied).
    event_id = Column(String(255), nullable=True)
    event_type = Column(String(100), nullable=True)
    tracking_id = Column(String(100), nullable=True)
    frame_sequence = Column(Integer, nullable=True)
    frame_timestamp = Column(Float, nullable=True)
    window_start = Column(Float, nullable=True)
    window_end = Column(Float, nullable=True)
    vlm_observation_id = Column(String(64), nullable=True)
    source_frame_ids = Column(Text, nullable=True)  # JSON array of sequences

    captured_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Storage object + verification.
    storage_path = Column(String(512), nullable=True)
    mime_type = Column(String(100), nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    # Searchable text used for vector embedding / indexing.
    content_text = Column(Text, nullable=True)
    # JSON enrichment metadata (observable facts only).
    # Named extra_metadata (NOT "metadata"): metadata is reserved by SQLAlchemy's
    # Declarative API and cannot be used as a mapped attribute.
    extra_metadata = Column("metadata", Text, nullable=True)
    # JSON machine-readable provenance snapshot (chain-of-custody style record).
    provenance = Column(Text, nullable=True)

    # Async vector-index state machine: PENDING -> INDEXING -> INDEXED | FAILED.
    index_status = Column(String(20), nullable=False, default="PENDING")
    index_attempts = Column(Integer, nullable=False, default=0)
    last_index_attempt_at = Column(DateTime, nullable=True)
    index_error = Column(Text, nullable=True)
    indexed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    camera = relationship("Camera")
    session = relationship("CameraSession", back_populates="evidence")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ForensicEvidence {self.public_id} {self.evidence_type} {self.index_status}>"


class VlmObservationRecord(Base):
    """Durable copy of a live VLM observation (Phase 4 output, Phase 5 storage).

    Everything needed to re-create an audit trail for a grounded observation:
    provenance (camera/session/source frames), trigger, structured statements
    (OBSERVED/INFERRED/UNKNOWN), notes and provider mode. Original evidence
    frames are never stored here - only provenance references plus the text.
    """

    __tablename__ = "vlm_observation_records"

    id = Column(Integer, primary_key=True, index=True)
    observation_id = Column(String(64), unique=True, index=True, nullable=False)
    request_id = Column(String(64), nullable=True)
    camera_id = Column(Integer, nullable=True)
    session_id = Column(Integer, nullable=True)
    trigger = Column(String(40), nullable=True)  # event | manual
    trigger_detail = Column(String(100), nullable=True)
    summary = Column(Text, nullable=True)
    items = Column(Text, nullable=True)  # JSON list of statements
    notes = Column(Text, nullable=True)  # JSON list
    model = Column(String(100), nullable=True)
    provider_mode = Column(String(20), nullable=True)  # simulation | openai
    source_frames = Column(Text, nullable=True)  # JSON list of {frame_id, sequence, timestamp, width, height}
    window_start = Column(Float, nullable=True)
    window_end = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<VlmObservationRecord {self.observation_id}>"


# ---------------------------------------------------------------------------
# Phase 8 - Forensic verification / timeline reconstruction / reporting
#
# All payloads are stored as JSON text and NEVER overwrite original evidence.
# Finding reviews are stored separately from the analysis and never modify the
# underlying ForensicEvidence rows.
# ---------------------------------------------------------------------------


class ForensicTimelineEvent(Base):
    """A single forensic timeline entry reconstructed from correlated evidence.

    The entry is evidence-backed: ``evidence_ids`` lists the ForensicEvidence
    public ids that support it, and ``classification`` is the epistemic duty
    (OBSERVED / INFERRED / UNKNOWN / CONFLICTING / UNVERIFIED). The entry is
    derived data only - the original evidence rows are never modified.
    """

    __tablename__ = "forensic_timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("investigation_runs.id"), nullable=False, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    timeline_event_id = Column(String(64), nullable=False)  # e.g. TL-01
    timestamp = Column(Float, nullable=False)  # normalized event time (seconds)
    end_timestamp = Column(Float, nullable=True)
    camera_id = Column(Integer, ForeignKey("cameras.id"), nullable=True)
    session_id = Column(Integer, nullable=True)
    event_id = Column(String(64), nullable=True)
    track_id = Column(String(120), nullable=True)
    object_class = Column(String(120), nullable=True)
    event_type = Column(String(60), nullable=True)
    description = Column(Text, nullable=True)
    classification = Column(String(40), nullable=False, default="UNVERIFIED")
    confidence = Column(Float, nullable=True)
    source = Column(String(40), nullable=True)  # tracking | vlm | frame | correlated
    verification_status = Column(String(40), nullable=False, default="UNVERIFIED")
    evidence_ids = Column(Text, nullable=True)  # JSON list
    quality_flags = Column(Text, nullable=True)  # JSON list
    analytics_time = Column(DateTime, nullable=True)  # when the analysis ran
    storage_time = Column(DateTime, nullable=True)  # when evidence was stored
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ForensicTimelineEvent {self.timeline_event_id} {self.classification}>"


class ForensicAnalysis(Base):
    """A persisted, evidence-verification snapshot for a Phase 7 run.

    Holds the generated forensic timeline, verified/unverified/conﬂicting
    findings, correlations, gaps, relationships (sequencing), multi-camera
    correlation and the recorded latency metrics. ``status`` tracks whether a
    human review pass has started/finished (PENDING_REVIEW -> REVIEWED).
    """

    __tablename__ = "forensic_analyses"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("investigation_runs.id"), nullable=False, unique=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    summary = Column(Text, nullable=True)
    timeline = Column(Text, nullable=True)  # JSON list of timeline entries
    findings = Column(Text, nullable=True)  # JSON list of findings
    correlations = Column(Text, nullable=True)  # JSON list
    contradictions = Column(Text, nullable=True)  # JSON list
    gaps = Column(Text, nullable=True)  # JSON dict
    relationships = Column(Text, nullable=True)  # JSON list
    multi_camera = Column(Text, nullable=True)  # JSON list
    sources = Column(Text, nullable=True)  # JSON list of authority notes
    metrics = Column(Text, nullable=True)  # JSON dict of stage latencies
    status = Column(String(40), nullable=False, default="PENDING_REVIEW")
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    run = relationship("InvestigationRun")
    investigation = relationship("Investigation")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ForensicAnalysis run={self.run_id} status={self.status}>"


class FindingReview(Base):
    """A human reviewer's decision on one forensic finding.

    Action: ACCEPTED | REJECTED | MARKED_UNCERTAIN | REQUESTED_MORE_EVIDENCE.
    The finding snapshot is stored so the review remains auditable even if the
    analysis is later regenerated. The original analysis is never modified.
    """

    __tablename__ = "finding_reviews"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("investigation_runs.id"), nullable=False, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    finding_id = Column(String(64), nullable=False)  # e.g. FINDING-01
    action = Column(String(40), nullable=False)
    comment = Column(Text, nullable=True)
    finding_snapshot = Column(Text, nullable=True)  # JSON snapshot of the finding
    reviewer_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    reviewer = relationship("User", foreign_keys=[reviewer_user_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FindingReview {self.finding_id} {self.action}>"


class ForensicReport(Base):
    """A generated investigation report for a completed Phase 7 run.

    The structured content (15 sections) is stored as JSON in ``content``; the
    rendered PDF / markdown file is stored in storage (``storage_path``) using
    the existing report renderer. Regenerating a report bumps ``version`` and
    appends a new audit entry - previous versions are never deleted.
    """

    __tablename__ = "forensic_reports"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("investigation_runs.id"), nullable=False, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"), nullable=False)
    title = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=True)  # JSON structured report (15 sections)
    storage_path = Column(String(512), nullable=True)
    file_format = Column(String(20), nullable=False, default="pdf")  # pdf | markdown
    status = Column(String(40), nullable=False, default="GENERATED")  # GENERATED | APPROVED
    generated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    generated_by = relationship("User", foreign_keys=[generated_by_user_id])

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ForensicReport run={self.run_id} v{self.version} {self.file_format}>"
