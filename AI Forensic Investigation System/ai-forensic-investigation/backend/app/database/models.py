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
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by = relationship("User", back_populates="cameras")
    videos = relationship("Video", back_populates="camera")
    clips = relationship("Clip", back_populates="camera")
    detections = relationship("Detection", back_populates="camera")


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
