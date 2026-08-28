**AI FORENSIC INVESTIGATION SYSTEM**

**Product Requirements Document (PRD) --- Prototype v1.0**

*GenAI Capstone Project --- Semester 5\*
Prototype Scope: Multimodal GenAI + Video RAG + Agentic Investigation

# 1. Product Vision {#product-vision}

Build an AI-powered surveillance investigation assistant that allows security personnel to upload CCTV footage and investigate it using natural-language queries instead of manually reviewing hours of video. The system combines computer vision, multimodal GenAI, Video RAG, agentic AI, policy RAG, evidence verification, timeline reconstruction, and automated reporting.

# 2. Problem Statement {#problem-statement}

Security personnel often need to investigate large volumes of surveillance footage after an incident. Manual review is slow, difficult to search semantically, and prone to missed evidence. Conventional surveillance systems commonly focus on predefined object or anomaly detection and provide limited temporal, semantic, and contextual reasoning. Incident reports are also manually written and may be inconsistent or incomplete.

The proposed system addresses these limitations by providing a natural-language forensic investigation interface that searches surveillance evidence, reasons over relevant clips, retrieves security policies, verifies claims, reconstructs timelines, and generates evidence-grounded incident reports.

# 3. Target Users {#target-users}

- Security Officer / Investigator --- searches footage, investigates incidents, verifies evidence, and generates reports.

- Security Administrator --- manages cameras, uploads security policies, and reviews investigations.

# 4. Prototype Objectives {#prototype-objectives}

1.  Allow users to upload CCTV video and associated camera metadata.

2.  Automatically process video into searchable clips, frames, events, and metadata.

3.  Detect people and relevant objects using pretrained computer-vision models.

4.  Generate semantic descriptions of important video segments using multimodal GenAI.

5.  Enable natural-language search over surveillance footage using Video RAG.

6.  Provide an agentic investigation workflow using tool calling.

7.  Support security-policy RAG for contextual policy analysis.

8.  Verify AI conclusions against retrieved evidence before presenting them as findings.

9.  Generate chronological incident timelines.

10. Generate structured, evidence-grounded incident reports.

# 5. Prototype Scope {#prototype-scope}

## 5.1 Must-Have Features {#must-have-features}

- Authentication and role-based access

- Investigation dashboard

- CCTV video upload

- Video processing status

- FFmpeg-based media processing

- Scene/clip extraction

- Person/object detection

- Object/person tracking

- Audio extraction and speech-to-text

- Multimodal clip understanding

- Embeddings and vector search

- Video RAG

- Natural-language investigation chat

- Timestamped evidence cards

- Incident timeline generation

- Security-policy RAG

- Evidence verification

- Automated incident report generation

- Investigation history

## 5.2 Should-Have Features {#should-have-features}

- Cross-camera investigation

- Evidence confidence scores

- PDF report export

- Real-time processing progress

- Evidence thumbnails and clip preview

## 5.3 Out of Scope for Prototype {#out-of-scope-for-prototype}

- Real-time production CCTV streaming

- Large-scale multi-camera deployment

- Custom training of a large language model

- Enterprise identity management

- Kubernetes/distributed infrastructure

- Production-grade facial recognition

- Mobile application

# 6. End-to-End User Journey {#end-to-end-user-journey}

> Login\
> ↓\
> Dashboard\
> ↓\
> Upload CCTV\
> ↓\
> Video Processing\
> ↓\
> AI Analysis\
> ↓\
> Video Indexing\
> ↓\
> Investigation Workspace\
> ↓\
> Natural-Language Query\
> ↓\
> Video RAG\
> ↓\
> Relevant Evidence\
> ↓\
> Investigation Agent\
> ↓\
> Evidence Verification\
> ↓\
> Incident Timeline\
> ↓\
> Generate Report

# 7. Functional Requirements {#functional-requirements}

## 7.1 Authentication {#authentication}

- User registration and login.

- Logout and session handling.

- Roles: ADMIN, SECURITY_OFFICER, INVESTIGATOR.

- Protect investigation and report endpoints.

## 7.2 Dashboard {#dashboard}

- Display total investigations, videos processed, incidents, and reports.

- Show recent investigations and their status.

- Provide quick actions for video upload, new investigation, evidence search, and reports.

## 7.3 Video Upload {#video-upload}

- Accept .mp4, .mov, .mkv, and .avi files.

- Capture camera ID, location, date, start time, and description.

- Display upload, queued, processing, indexed, and ready states.

## 7.4 Video Processing Pipeline {#video-processing-pipeline}

> Video\
> ↓\
> FFmpeg metadata extraction\
> ↓\
> Scene detection\
> ↓\
> Frame/clip sampling\
> ↓\
> YOLO object detection\
> ↓\
> ByteTrack/BoT-SORT tracking\
> ↓\
> Audio extraction\
> ↓\
> Whisper transcription\
> ↓\
> Multimodal AI description\
> ↓\
> Embedding generation\
> ↓\
> Qdrant indexing

## 7.5 Vision Analysis {#vision-analysis}

- Detect people and relevant objects.

- Store timestamps, bounding boxes, object labels, and confidence scores.

- Track entities across frames when possible.

## 7.6 Audio Intelligence {#audio-intelligence}

- Extract audio from video.

- Transcribe speech using Whisper.

- Store transcript segments with timestamps and confidence.

- Optionally detect relevant non-speech audio events such as alarms.

## 7.7 Multimodal Event Understanding {#multimodal-event-understanding}

For important clips, generate structured semantic descriptions containing:

- Clip ID

- Summary

- Objects

- Actions

- Location/context

- Start and end timestamps

- Model confidence

## 7.8 Video RAG {#video-rag}

> User Query\
> ↓\
> Query Embedding\
> ↓\
> Qdrant Semantic Search\
> ↓\
> Metadata/Time Filtering\
> ↓\
> Relevant Clips\
> ↓\
> Multimodal LLM/VLM Reasoning\
> ↓\
> Timestamped Evidence

Example query: "Find when a person entered the restricted area."

## 7.9 Investigation Agent {#investigation-agent}

Use an agentic workflow to select tools based on the investigator\'s question.

- search_video()

- search_person()

- search_object()

- search_event()

- get_clip()

- get_frame()

- build_timeline()

- search_policy()

- verify_evidence()

- generate_report()

## 7.10 Security Policy RAG {#security-policy-rag}

- Allow administrators to upload security SOPs and policies.

- Extract and chunk document text.

- Generate embeddings and store them in Qdrant.

- Retrieve relevant policies during investigation.

- Use retrieved policy context to classify potential violations.

## 7.11 Evidence Verification {#evidence-verification}

> Initial AI Conclusion\
> ↓\
> Retrieve original evidence\
> ↓\
> Check timestamps\
> ↓\
> Check relevant frames/clips\
> ↓\
> Retrieve applicable policy\
> ↓\
> Verification\
> ↓\
> Verified / Partially Verified / Insufficient Evidence

The system must not fabricate timestamps, evidence, identities, or conclusions. When evidence is insufficient, it should explicitly state uncertainty.

## 7.12 Incident Timeline {#incident-timeline}

- Generate chronological events from retrieved evidence.

- Each event contains timestamp, description, evidence reference, and confidence.

- Allow users to jump from timeline events to supporting video clips.

## 7.13 Automated Incident Report {#automated-incident-report}

Report structure:

- Incident ID

- Date and location

- Camera information

- Executive summary

- Incident classification

- Chronological timeline

- Persons/objects involved

- Supporting evidence

- Policy analysis

- AI findings

- Confidence scores

- Unverified/uncertain claims

- Recommendations

Major factual claims must be linked to supporting evidence and timestamps.

# 8. Investigation Workspace {#investigation-workspace}

> ┌─────────────────────────────────────────────────────┐\
> │ AI FORENSIC INVESTIGATION │\
> ├───────────────────┬─────────────────────────────────┤\
> │ VIDEO │ Investigation Chat │\
> │ │ │\
> │ \[Video Player\] │ User: Find suspicious events │\
> │ │ │\
> │ Timeline │ AI: I found 3 relevant events │\
> │ 10:41 │ │\
> │ 10:42 │ \[Evidence Cards\] │\
> │ 10:43 │ │\
> │ 10:44 │ │\
> ├───────────────────┴─────────────────────────────────┤\
> │ Evidence \| Timeline \| Policy \| Report │\
> └─────────────────────────────────────────────────────┘

# 9. Evidence Card {#evidence-card}

> Evidence \#E-023\
> Camera: CAM-03\
> Timestamp: 10:42:17\
> \
> \[Thumbnail\]\
> \
> Finding:\
> Person entered restricted area.\
> \
> Confidence: 94%\
> \
> \[View Clip\] \[View Frame\]

# 10. Technology Stack {#technology-stack}

| Layer | Recommended Technology | Purpose |
|----|----|----|
| Frontend | Next.js, React, Tailwind CSS, shadcn/ui | Dashboard and investigation UI |
| Backend | Python, FastAPI, Pydantic | APIs and orchestration |
| Video | FFmpeg, OpenCV, PySceneDetect | Video/audio processing and scene extraction |
| Computer Vision | YOLO, ByteTrack/BoT-SORT | Detection and tracking |
| Speech | Whisper | Speech-to-text |
| GenAI | One primary Multimodal LLM/VLM | Video understanding, reasoning, generation |
| Embeddings | BGE/E5 or provider embeddings | Semantic retrieval |
| Vector DB | Qdrant | Video and policy retrieval |
| RAG | LangChain or LlamaIndex | Retrieval pipelines |
| Agents | LangGraph | Agentic investigation workflow |
| Database | PostgreSQL | Structured application data |
| Object Storage | MinIO | Videos, clips, frames, reports |
| Deployment | Docker, Docker Compose | Reproducible local deployment |

# 11. Recommended Architecture {#recommended-architecture}

> ┌───────────────────┐\
> │ Next.js UI │\
> └─────────┬─────────┘\
> │\
> ▼\
> ┌─────────────┐\
> │ FastAPI │\
> └──────┬──────┘\
> │\
> ┌─────────────────┼─────────────────┐\
> ▼ ▼ ▼\
> Video Pipeline RAG Layer Agent Layer\
> │ │ │\
> FFmpeg/OpenCV Qdrant LangGraph\
> YOLO/Tracker Embeddings │\
> Whisper │ │\
> VLM │ │\
> └─────────────────┼─────────────────┘\
> ▼\
> Multimodal LLM/VLM\
> │\
> ▼\
> Evidence Verification\
> │\
> ▼\
> Report Generator\
> / \\\
> / \\\
> PostgreSQL MinIO

# 12. Database Design {#database-design}

**Users:** id, name, email, password_hash, role, created_at

**Cameras:** id, camera_name, location, description

**Videos:** id, camera_id, filename, duration, upload_date, status, storage_path

**Clips:** id, video_id, start_time, end_time, thumbnail, description, embedding_id

**Events:** id, clip_id, event_type, description, timestamp, confidence

**Investigations:** id, title, query, status, created_by, created_at

**Evidence:** id, investigation_id, clip_id, claim, confidence, verification_status

**Reports:** id, investigation_id, content, created_at

# 13. API Requirements {#api-requirements}

**Authentication**

- POST /api/auth/login

- POST /api/auth/register

**Videos**

- POST /api/videos/upload

- GET /api/videos

- GET /api/videos/{id}

- DELETE /api/videos/{id}

**Processing**

- POST /api/videos/{id}/process

- GET /api/videos/{id}/status

**Investigations**

- POST /api/investigations

- GET /api/investigations

- GET /api/investigations/{id}

- POST /api/investigations/{id}/query

**Evidence**

- GET /api/evidence/{id}

- POST /api/evidence/{id}/verify

**Reports**

- POST /api/investigations/{id}/report

- GET /api/reports/{id}

**Policies**

- POST /api/policies/upload

- GET /api/policies

- POST /api/policies/search

# 14. Example End-to-End Demonstration {#example-end-to-end-demonstration}

11. Upload a 5--15 minute CCTV-style sample video.

12. Enter camera metadata.

13. Start processing and show progress.

14. System detects people/objects, creates clips, extracts audio, and generates semantic descriptions.

15. System indexes clip descriptions, transcripts, and events.

16. Investigator asks: "Find all suspicious activity in this video."

17. Agent retrieves relevant clips and presents evidence.

18. Investigator asks: "Was the restricted-area entry against policy?"

19. Agent retrieves video evidence and the relevant security policy.

20. Evidence verification determines whether the finding is supported.

21. System generates a timeline.

22. System generates the final evidence-grounded incident report.

# 15. Evaluation Plan {#evaluation-plan}

| Category | Metrics | Goal |
|----|----|----|
| Video Retrieval | Recall@5, Recall@10, Precision@5 | Measure retrieval of relevant clips |
| Temporal Retrieval | Timestamp error, Temporal IoU | Measure timestamp/segment accuracy |
| RAG | Context relevance, context recall, faithfulness | Measure grounded retrieval and answers |
| Generation | Factual accuracy, completeness, hallucination rate | Measure report quality |
| System | Processing time, query latency | Measure prototype performance |

# 16. Non-Functional Requirements {#non-functional-requirements}

- Asynchronous video processing with visible progress.

- Stable API error handling.

- No fabricated timestamps or evidence.

- Evidence-grounded responses for important claims.

- Explicit uncertainty when evidence is insufficient.

- Role-based access to investigations and reports.

- Validated uploads and controlled file types.

- Dockerized local deployment for reproducibility.

# 17. Development Roadmap {#development-roadmap}

| Phase | Deliverables |
|----|----|
| Phase 1 --- Foundation | Next.js, FastAPI, PostgreSQL, Docker, authentication |
| Phase 2 --- Video | Upload, MinIO, FFmpeg, scene detection, video player |
| Phase 3 --- Computer Vision | YOLO, tracking, event metadata |
| Phase 4 --- GenAI | VLM descriptions, embeddings, Qdrant, Video RAG |
| Phase 5 --- Agent | LangGraph, tool calling, investigation workflow |
| Phase 6 --- Policy RAG | Policy ingestion, retrieval, policy reasoning |
| Phase 7 --- Verification | Evidence verification, confidence, uncertainty handling |
| Phase 8 --- Reporting | Timeline, structured report, PDF export |
| Phase 9 --- Evaluation | Test dataset, metrics, comparison, demo scenarios |

# 18. MVP Definition {#mvp-definition}

The minimum viable prototype is: video upload → preprocessing → object/event analysis → semantic clip descriptions → embeddings → Qdrant → natural-language Video RAG → evidence cards → grounded incident report.

# 19. Final Prototype Definition {#final-prototype-definition}

Input: CCTV video + security policies + investigator\'s natural-language question.

Processing: Computer Vision + Video Understanding + Embeddings + Video RAG + Investigation Agent + Policy RAG + Evidence Verification + Timeline Reasoning.

Output: Natural-language answer + relevant evidence + timestamps + incident timeline + confidence + policy analysis + evidence-grounded incident report.

# 20. Academic/GenAI Value {#academicgenai-value}

- Large Language Model usage

- Multimodal AI

- Vision-Language/Video-Language understanding

- Prompt engineering

- Embeddings

- Vector database

- Retrieval-Augmented Generation

- Video RAG

- Tool calling

- Agentic AI

- Structured generation

- Grounding and citation/evidence linkage

- Hallucination mitigation

- Evaluation of retrieval and generation

# 21. Important Design Constraint {#important-design-constraint}

The prototype should focus on the GenAI intelligence layer rather than attempting to become a production surveillance platform. Use controlled or public-domain/sample CCTV-style footage for demonstration. Avoid unnecessary features such as real-time production monitoring, large-scale deployment, and custom LLM training.
