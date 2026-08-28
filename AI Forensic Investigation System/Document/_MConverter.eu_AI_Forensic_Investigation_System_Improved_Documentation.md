**AI FORENSIC INVESTIGATION SYSTEM**

**Improved Project Documentation --- Prototype v1.1**

*Natural-Language Investigation over CCTV Footage using Multimodal GenAI\*
GenAI Capstone Project --- Semester 5\
Status: Prototype / Academic Capstone\
Revision: Technical, Architectural, GenAI, Evaluation and Feasibility Improvements

Document purpose: This version preserves the original project idea while making the system implementation-ready, evidence-grounded, testable, and explicit about limitations.

# Table of Contents

1\. Executive Summary

2\. Problem Statement

3\. Proposed Solution

4\. Goals and Non-Goals

5\. Users and Use Cases

6\. Core GenAI Capabilities

7\. Finding Status Model

8\. System Architecture

9\. Video Processing Pipeline

10\. Video RAG Architecture

11\. Security Policy RAG

12\. Investigation Agent

13\. Evidence Verification

14\. Human-in-the-Loop Review

15\. Claim-to-Evidence Traceability

16\. Timeline Reasoning

17\. Incident Report Generation

18\. Technology Stack

19\. Data Model

20\. API Specification

21\. Project Structure

22\. Security, Privacy and Audit

23\. Known Limitations

24\. Evaluation and Benchmark

25\. Development Roadmap and Integration Gates

26\. Testing Strategy

27\. MVP and Final Prototype

28\. Demonstration Scenario

29\. Success Criteria

30\. Glossary

# 1. Executive Summary {#executive-summary}

The AI Forensic Investigation System is an AI-powered surveillance investigation assistant that allows security personnel to investigate CCTV footage using natural-language queries instead of manually reviewing large volumes of video. The system combines computer vision, multimodal generative AI, Video RAG, agentic AI, security-policy RAG, evidence verification, timeline reasoning, and structured report generation.

The investigator can ask questions such as when an observed event occurred, which video segments support a finding, what sequence of events occurred, and whether the observed behavior is consistent with a documented security policy. The system returns evidence-backed findings with timestamps, clips or frames, retrieval information, verification status, and a structured incident report.

The system is an investigation-assistance prototype. It does not autonomously determine human intent, establish real-world identity, make final security decisions, or replace trained security personnel.

# 2. Problem Statement {#problem-statement}

Security personnel often need to manually review large volumes of surveillance footage after an incident. Manual review is time-consuming, difficult to search semantically, prone to missed evidence, dependent on manual investigation, and slow when creating structured reports.

Traditional surveillance systems can detect predefined objects or events, but they generally provide limited semantic and temporal reasoning. They may flag a person or vehicle without providing a flexible natural-language investigation workflow.

The project addresses this gap by converting surveillance footage into a searchable multimodal evidence store and adding a GenAI investigation layer that retrieves, reasons over, verifies, and reports observable evidence.

# 2.1 Problem Boundaries {#problem-boundaries}

- The system focuses on observable visual and audio evidence rather than psychological intent.

- Policy conclusions are limited to whether observed behavior is consistent with retrieved organizational rules.

- Visual subject tracking is not equivalent to real-world identity recognition.

- AI-generated conclusions remain subject to human review.

# 3. Proposed Solution {#proposed-solution}

1.  Process CCTV footage and extract metadata, scenes, clips, frames, and audio.

2.  Detect and track people and relevant objects using pretrained computer-vision models.

3.  Transcribe speech and retain temporal information.

4.  Generate semantic descriptions for selected clips using a multimodal VLM.

5.  Index semantic representations and metadata for retrieval.

6.  Use hybrid Video RAG combining semantic retrieval with time/object/event metadata filters and reranking.

7.  Use an Investigation Agent to call retrieval, evidence, timeline, policy, and verification tools.

8.  Retrieve security policies through a separate RAG pipeline.

9.  Verify claims against original video evidence, timestamps, and applicable policy.

10. Present findings with explicit status and traceable evidence.

11. Require human review before a report is finalized.

12. Generate a structured incident report from verified evidence.

# 4. Goals and Non-Goals {#goals-and-non-goals}

## 4.1 Goals {#goals}

- Natural-language investigation over indexed CCTV footage.

- Semantic and temporal retrieval of relevant clips.

- Multimodal reasoning over video, audio, and text.

- Evidence-grounded answers and reports.

- Policy-grounded assessment using organization-provided documents.

- Agentic tool calling with bounded execution.

- Transparent verification and uncertainty handling.

- Measurable evaluation against a labelled benchmark.

## 4.2 Non-Goals {#non-goals}

- Predicting or proving human intent.

- Autonomous security decisions.

- Production facial recognition or real-world identity determination.

- Real-time production CCTV deployment.

- Large-scale multi-camera enterprise infrastructure.

- Training a large language model from scratch.

- Replacing security investigators.

# 5. Users and Use Cases {#users-and-use-cases}

| **User** | **Primary Tasks** |
|----|----|
| Security Officer / Investigator | Upload footage, ask questions, inspect evidence, review timelines, generate reports. |
| Security Administrator | Manage cameras, upload policies, review investigations, manage system configuration. |
| Reviewer / Supervisor | Review AI findings, approve or reject reports, inspect evidence and audit history. |

# 5.1 Example Use Cases {#example-use-cases}

- Find when a person entered a restricted area.

- Find a visually described subject such as a person carrying a red backpack.

- Find all clips containing a specified event.

- Explain the sequence of observable events between two timestamps.

- Determine whether an observed event is consistent with a supplied security policy.

- Generate a report containing only evidence-supported findings.

# 6. Core GenAI Capabilities {#core-genai-capabilities}

| **Concept** | **Implementation in the System** |
|----|----|
| LLM | Investigation reasoning, structured generation, report drafting. |
| Multimodal AI | Joint reasoning over video-derived visual evidence, audio/transcripts and text. |
| VLM | Semantic understanding of selected video clips and frames. |
| Prompt Engineering | Controlled prompts for query interpretation, evidence analysis and reporting. |
| Embeddings | Semantic representations of clips, events, transcripts and policy chunks. |
| Vector Database | Qdrant for semantic retrieval. |
| RAG | Retrieval-grounded reasoning over video evidence and policies. |
| Video RAG | Natural-language retrieval of semantically indexed video segments. |
| Agentic AI | Bounded investigation workflow with tool selection. |
| Tool Calling | Search, clip/frame retrieval, policy retrieval, timeline and verification tools. |
| Structured Generation | Schema-constrained claims, findings and incident reports. |
| Grounding | Claims linked to inspectable clips, frames and timestamps. |
| Hallucination Mitigation | Evidence verification, uncertainty states and human review. |
| Evaluation | Retrieval, temporal, RAG faithfulness, hallucination and latency metrics. |

# 7. Finding Status Model {#finding-status-model}

Every important AI finding must have an explicit semantic status. This avoids presenting inference as direct observation.

| **Status** | **Meaning** | **Example** |
|----|----|----|
| OBSERVED | Directly supported by visible or audible evidence. | A person enters a marked restricted area. |
| INFERRED | A model-generated interpretation that is not directly observable as a fact. | The person may have been attempting to access equipment. |
| POLICY-ASSESSED | Observed behavior compared against retrieved organizational policy. | The observed entry is inconsistent with the supplied restricted-area rule. |
| VERIFIED | A claim has passed the configured evidence and consistency checks. | The entry event and timestamp are supported by the source clip. |
| UNKNOWN | The available evidence is insufficient to establish the claim. | Authorization status cannot be determined from the footage. |

The system must not convert INFERRED or UNKNOWN information into a definitive factual statement.

# 8. System Architecture {#system-architecture}

> ┌───────────────────────────┐\
> │ Next.js UI │\
> │ Dashboard / Video / Chat │\
> └─────────────┬─────────────┘\
> │\
> ▼\
> ┌───────────────────────────┐\
> │ FastAPI │\
> │ API + Auth + Orchestration│\
> └─────────────┬─────────────┘\
> │\
> ┌──────────────────┼──────────────────┐\
> ▼ ▼ ▼\
> Video Job Layer RAG Layer Agent Layer\
> │ │ │\
> FFmpeg/OpenCV Qdrant + LangGraph +\
> YOLO + Tracker Embeddings Tool Calling\
> Whisper + VLM │ │\
> │ │ │\
> └──────────────┬───┴──────────────┬───┘\
> ▼ │\
> Multimodal LLM/VLM │\
> │ │\
> ▼ │\
> Evidence Verification ◄────┘\
> │\
> ▼\
> Human Review\
> │\
> ┌───────────┴───────────┐\
> ▼ ▼\
> Timeline Report\
> │ │\
> └───────────┬───────────┘\
> ▼\
> PostgreSQL + MinIO\
> │\
> Audit Logs

## 8.1 Architectural Layers {#architectural-layers}

| **Layer** | **Responsibility** | **Technology** |
|----|----|----|
| Presentation | Dashboard, video review, chat, evidence and reports | Next.js, React, Tailwind CSS, shadcn/ui |
| API / Orchestration | Authentication, requests, job creation, coordination | FastAPI, Pydantic |
| Video Worker | Decode, scene detection, sampling, detection, tracking, transcription | FFmpeg, OpenCV, PySceneDetect, YOLO, ByteTrack/BoT-SORT, Whisper |
| Multimodal Analysis | Semantic clip understanding | Primary VLM/LLM |
| RAG | Embedding, indexing, retrieval and reranking | Qdrant, BGE/E5, LangChain |
| Agent | Bounded tool-calling investigation | LangGraph + LangChain |
| Persistence | Structured data and binary files | PostgreSQL, MinIO |
| Audit | Trace user and AI actions | PostgreSQL audit tables |

# 8.2 Asynchronous Processing {#asynchronous-processing}

Video analysis must not block a normal API request. The upload endpoint creates a processing job and returns a job identifier. A background worker executes expensive operations and updates progress.

> Upload API\
> ↓\
> Create Processing Job\
> ↓\
> Background Worker\
> ├── FFmpeg\
> ├── Scene Detection\
> ├── YOLO / Tracking\
> ├── Whisper\
> ├── VLM\
> └── Embeddings\
> ↓\
> Index Complete\
> ↓\
> Video Available for Investigation

# 9. Video Processing Pipeline {#video-processing-pipeline}

> CCTV Video\
> ↓\
> Metadata Extraction\
> ↓\
> Scene / Shot Detection\
> ↓\
> Clip Segmentation\
> ↓\
> Keyframe Sampling\
> ├───────────────┐\
> ▼ ▼\
> YOLO + Tracking Audio Extraction → Whisper\
> │ │\
> └───────┬───────┘\
> ▼\
> Multimodal VLM\
> ↓\
> Semantic Event Records\
> ↓\
> Embeddings + Metadata\
> ↓\
> Qdrant + PostgreSQL\
> ↓\
> Queryable Evidence

The system should avoid sending entire long recordings to a multimodal model. Processing should first reduce the search space using scenes, clips, metadata, and computer-vision signals.

# 9.1 Event Record {#event-record}

> {\
> \"event_id\": \"EV-001\",\
> \"video_id\": \"VID-001\",\
> \"clip_id\": \"CLIP-023\",\
> \"start_time\": \"00:42:17\",\
> \"end_time\": \"00:42:45\",\
> \"event_type\": \"restricted_area_entry\",\
> \"objects\": \[\"person\"\],\
> \"description\": \"A person enters the marked restricted area.\",\
> \"detection_confidence\": 0.94\
> }

# 10. Video RAG Architecture {#video-rag-architecture}

Video RAG is implemented as a hybrid retrieval system rather than vector search alone.

> User Query\
> ↓\
> Query Understanding\
> ├── semantic intent\
> ├── time constraints\
> ├── object/attribute constraints\
> └── event constraints\
> ↓\
> Candidate Retrieval\
> ├── Vector similarity search\
> └── Metadata / temporal filtering\
> ↓\
> Candidate Reranking\
> ↓\
> Top-K Evidence Clips\
> ↓\
> VLM Verification / Temporal Reasoning\
> ↓\
> Evidence Package\
> ↓\
> LLM Answer

## 10.1 Retrieval Metadata {#retrieval-metadata}

- video_id

- camera_id

- clip_id

- start_time and end_time

- object labels

- tracking IDs

- event types

- location metadata

- transcript segment

- semantic description

- embedding ID

## 10.2 Retrieval Guardrails {#retrieval-guardrails}

- Never allow the LLM to invent a timestamp; timestamps come from stored source metadata.

- Use metadata filters when the user supplies time, camera, object, or event constraints.

- Use reranking before sending evidence to the reasoning model.

- Return evidence identifiers with every major factual answer.

- If no adequate evidence is retrieved, return UNKNOWN / insufficient evidence.

# 11. Security Policy RAG {#security-policy-rag}

> Policy PDF / DOCX\
> ↓\
> Text Extraction\
> ↓\
> Section-aware Chunking + Overlap\
> ↓\
> Embeddings\
> ↓\
> Qdrant\
> ↓\
> Policy Retrieval\
> ↓\
> Policy Evidence\
> ↓\
> LLM Policy Assessment

Policy assessment must be based on retrieved organizational text. Generic model knowledge must not be treated as the organization\'s policy.

# 11.1 Policy Metadata {#policy-metadata}

- policy_id

- document_name

- section_title

- page_number

- chunk_id

- effective_date when available

- embedding_id

# 12. Investigation Agent {#investigation-agent}

The Investigation Agent is a single bounded agent rather than an unnecessary collection of independent agents. It plans a small number of tool calls, gathers evidence, and routes the case through verification.

> User Question\
> ↓\
> Investigation Agent\
> ├── search_video()\
> ├── search_person()\
> ├── search_object()\
> ├── search_event()\
> ├── get_clip()\
> ├── get_frame()\
> ├── build_timeline()\
> ├── search_policy()\
> ├── verify_evidence()\
> └── generate_report()\
> ↓\
> Verified Findings\
> ↓\
> Human Review\
> ↓\
> Final Report

## 12.1 Agent Guardrails {#agent-guardrails}

- Maximum tool-call budget per investigation.

- Maximum retrieval depth and execution time.

- No direct modification of source evidence.

- No identity claims beyond the configured visual-subject tracking capability.

- No final report approval by the agent itself.

- All tool calls recorded in the audit log.

# 13. Evidence Verification {#evidence-verification}

> Initial Claim\
> ↓\
> Claim Decomposition\
> ↓\
> Visual Evidence Check\
> ↓\
> Temporal Check\
> ↓\
> Policy Check (when applicable)\
> ↓\
> Cross-Evidence Consistency Check\
> ↓\
> Verification Result\
> ├── VERIFIED\
> ├── PARTIALLY VERIFIED\
> └── INSUFFICIENT EVIDENCE

## 13.1 Verification Dimensions {#verification-dimensions}

| **Check** | **Question** |
|----|----|
| Visual | Does the source frame/clip support the claimed observable event? |
| Temporal | Does the claimed time correspond to the source video\'s timestamp? |
| Entity/Subject | Does the evidence support the described visual subject or tracking ID? |
| Policy | Does retrieved policy actually apply to the observed event? |
| Consistency | Do multiple retrieved pieces of evidence conflict? |

# 14. Human-in-the-Loop Review {#human-in-the-loop-review}

> AI Investigation\
> ↓\
> Evidence Verification\
> ↓\
> Reviewer Workspace\
> ├── Accept finding\
> ├── Reject finding\
> ├── Edit finding\
> └── Mark uncertain\
> ↓\
> Finalized Report

The prototype must require human review before an investigation report is marked final. This preserves the role of trained personnel and prevents autonomous security decisions.

# 15. Claim-to-Evidence Traceability {#claim-to-evidence-traceability}

| **Entity** | **Key Fields** |
|----|----|
| Claim | claim_id, investigation_id, claim_text, claim_type, status, confidence/score metadata, created_at |
| ClaimEvidence | claim_id, clip_id, frame_id, timestamp, evidence_type, relevance_score |
| Verification | claim_id, verifier_version, checks, result, reason, created_at |

> Claim C-001\
> ├── Evidence E-001 → CLIP-023 → 00:42:17\
> ├── Evidence E-002 → FRAME-884 → 00:42:19\
> └── Verification V-001 → VERIFIED

A report claim must be traceable to one or more evidence records. The UI should allow the reviewer to open the supporting clip/frame.

# 16. Timeline Reasoning {#timeline-reasoning}

The timeline is assembled from verified or explicitly labelled events rather than from unconstrained narrative generation.

| **Time** | **Event**                        | **Status** | **Evidence** |
|----------|----------------------------------|------------|--------------|
| 10:41:52 | Person appears near entrance.    | OBSERVED   | CLIP-021     |
| 10:42:17 | Person enters restricted area.   | VERIFIED   | CLIP-023     |
| 10:43:08 | Person interacts with equipment. | OBSERVED   | CLIP-027     |
| 10:44:51 | Alarm sound detected.            | OBSERVED   | AUDIO-009    |

The timeline generator must preserve source timestamps and must not invent event times.

# 17. Incident Report Generation {#incident-report-generation}

The report is generated from a structured, verified case object rather than from an unconstrained prompt over the raw conversation.

> {\
> \"incident_id\": \"INV-1024\",\
> \"summary\": \"\...\",\
> \"findings\": \[\
> {\
> \"claim\": \"\...\",\
> \"status\": \"VERIFIED\",\
> \"evidence_ids\": \[\"E-001\", \"E-002\"\]\
> }\
> \],\
> \"timeline\": \[\...\],\
> \"policy_assessment\": \[\...\],\
> \"unknowns\": \[\...\],\
> \"review_status\": \"PENDING\"\
> }

## 17.1 Report Sections {#report-sections}

- Incident ID and metadata

- Executive Summary

- Incident Classification

- Verified Timeline

- Observed Persons / Objects

- Supporting Evidence

- Policy Assessment

- Inferred Information --- clearly labelled

- Unknown / Insufficient Evidence

- Recommendations for further human investigation

- Reviewer Decision

# 18. Technology Stack {#technology-stack}

| **Layer** | **Selected Technology** | **Reason** |
|----|----|----|
| Frontend | Next.js, React, Tailwind CSS, shadcn/ui | Fast prototype development and investigation UI. |
| Backend | Python, FastAPI, Pydantic | AI ecosystem and typed APIs. |
| Video | FFmpeg, OpenCV, PySceneDetect | Media processing and scene/clip preparation. |
| Detection | YOLO | Pretrained object/person detection. |
| Tracking | ByteTrack or BoT-SORT | Visual subject tracking across frames. |
| Speech | Whisper | Timestamped speech-to-text. |
| GenAI | One selected primary multimodal LLM/VLM | Reasoning and multimodal understanding. |
| Embeddings | BGE/E5 | Semantic representation. |
| Vector DB | Qdrant | Video and policy retrieval. |
| RAG | LangChain | Retrieval and model integration. |
| Agent | LangGraph | Bounded stateful agent workflow. |
| Database | PostgreSQL | Structured metadata, investigations, claims and audit logs. |
| Storage | MinIO | Video, clips, frames, audio and report files. |
| Deployment | Docker / Docker Compose | Reproducible prototype environment. |

Implementation decision: use LangChain for retrieval/model integration and LangGraph for the agent workflow. Do not keep LangChain/LlamaIndex as an unresolved alternative in the final implementation.

# 18.1 Model Configuration {#model-configuration}

The project should define one tested default model configuration while allowing model providers to be changed through environment variables.

> LLM_PROVIDER=\...\
> VISION_MODEL=\...\
> EMBEDDING_MODEL=\...\
> WHISPER_MODEL=\...\
> YOLO_MODEL=\...\
> QDRANT_URL=\...\
> DATABASE_URL=\...\
> MINIO_ENDPOINT=\...

# 19. Data Model {#data-model}

| **Table** | **Core Fields** |
|----|----|
| users | id, name, email, password_hash, role, created_at |
| cameras | id, camera_name, location, description |
| videos | id, camera_id, filename, duration, upload_date, status, storage_path |
| processing_jobs | id, video_id, status, progress, stage, error, started_at, completed_at |
| clips | id, video_id, start_time, end_time, thumbnail_path, description, embedding_id |
| detections | id, clip_id, label, tracking_id, bbox, detection_confidence, timestamp |
| transcripts | id, video_id, start_time, end_time, text, confidence |
| events | id, clip_id, event_type, description, start_time, end_time, status |
| investigations | id, title, query, status, created_by, created_at |
| claims | id, investigation_id, claim_text, claim_type, status, created_at |
| claim_evidence | id, claim_id, clip_id, frame_id, timestamp, evidence_type, relevance_score |
| verifications | id, claim_id, checks, result, reason, verifier_version, created_at |
| policies | id, name, version, source_path, uploaded_by, created_at |
| policy_chunks | id, policy_id, section, page, text, embedding_id |
| reports | id, investigation_id, content, review_status, created_at |
| audit_logs | id, user_id, investigation_id, action, tool_name, input_summary, output_summary, created_at |

# 20. API Specification {#api-specification}

| **Method** | **Endpoint** | **Purpose** |
|----|----|----|
| POST | /api/auth/login | Authenticate user. |
| POST | /api/auth/register | Register user. |
| POST | /api/videos/upload | Upload video and create processing job. |
| GET | /api/videos | List videos. |
| GET | /api/videos/{id} | Get video metadata. |
| GET | /api/videos/{id}/status | Get processing progress. |
| POST | /api/videos/{id}/process | Start/retry processing. |
| POST | /api/investigations | Create investigation. |
| POST | /api/investigations/{id}/query | Run natural-language investigation. |
| GET | /api/investigations/{id} | Get investigation state and evidence. |
| GET | /api/evidence/{id} | Retrieve evidence metadata. |
| POST | /api/evidence/{id}/verify | Run or rerun verification. |
| POST | /api/policies/upload | Upload security policy. |
| POST | /api/policies/search | Search policy knowledge base. |
| POST | /api/investigations/{id}/timeline | Build verified timeline. |
| POST | /api/investigations/{id}/report | Generate report draft. |
| POST | /api/investigations/{id}/review | Accept/reject/edit final findings. |
| GET | /api/reports/{id} | Retrieve report. |

# 21. Project Structure {#project-structure}

> ai-forensic-investigation/\
> ├── frontend/\
> │ ├── app/\
> │ ├── components/\
> │ ├── lib/\
> │ └── features/\
> ├── backend/\
> │ ├── app/\
> │ │ ├── api/\
> │ │ ├── agents/\
> │ │ ├── rag/\
> │ │ ├── video/\
> │ │ ├── vision/\
> │ │ ├── audio/\
> │ │ ├── verification/\
> │ │ ├── reports/\
> │ │ ├── database/\
> │ │ └── audit/\
> │ └── requirements.txt\
> ├── data/\
> │ ├── videos/\
> │ ├── clips/\
> │ ├── frames/\
> │ ├── audio/\
> │ ├── policies/\
> │ └── reports/\
> ├── scripts/\
> ├── tests/\
> │ ├── unit/\
> │ ├── integration/\
> │ └── evaluation/\
> ├── docker-compose.yml\
> ├── .env.example\
> └── README.md

# 22. Security, Privacy and Audit {#security-privacy-and-audit}

- Require authentication for investigation and report access.

- Use role-based authorization for administrators, investigators and reviewers.

- Validate uploaded file types and sizes.

- Store secrets only in environment configuration; never commit credentials.

- Keep source evidence immutable after ingestion.

- Record investigation actions and agent tool calls in audit logs.

- Avoid real-world identity claims and facial-recognition functionality in the prototype.

- Use controlled/public-domain/sample footage for demonstrations.

- Clearly label AI-generated content and verification status.

# 22.1 Audit Trail {#audit-trail}

> User Action\
> ↓\
> API Request\
> ↓\
> Agent Tool Call(s)\
> ↓\
> Retrieved Evidence\
> ↓\
> Verification Result\
> ↓\
> Human Review\
> ↓\
> Final Report

The audit trail should make it possible to reconstruct how a final finding was produced.

# 23. Known Limitations {#known-limitations}

| **Limitation** | **Impact / Mitigation** |
|----|----|
| Video quality | Blur, darkness, occlusion and compression can reduce detection and VLM accuracy. Use controlled footage and report evidence quality. |
| Identity | Tracking a visual subject does not establish real-world identity. Use tracking IDs/visual attributes only. |
| Intent | Intent cannot reliably be inferred from ordinary CCTV. Report observable behavior and label inference explicitly. |
| Timestamp precision | Sampling and source-video properties can affect temporal precision. Preserve source timestamps and evaluate temporal error. |
| Policy interpretation | Policy assessment depends on retrieved document quality and scope. Show policy passages and require review. |
| Hallucinations | Verification reduces unsupported claims but cannot guarantee zero hallucinations. Permit UNKNOWN outcomes. |
| Retrieval errors | Incorrect retrieval can cause incorrect answers. Use hybrid retrieval, reranking and benchmark evaluation. |
| Model dependence | Performance varies by selected VLM/LLM. Record model/version in investigation metadata. |
| Cost/latency | Repeated multimodal calls can be expensive. Cache clip analysis and use staged retrieval. |

# 24. Evaluation and Benchmark {#evaluation-and-benchmark}

Create a small labelled benchmark specifically for the prototype. It should include both event-positive and normal/negative scenarios.

## 24.1 Benchmark Structure {#benchmark-structure}

| **Field**        | **Description**                              |
|------------------|----------------------------------------------|
| video_id         | Source video identifier.                     |
| query            | Natural-language investigation question.     |
| expected_event   | Ground-truth observable event.               |
| start_time       | Expected event start.                        |
| end_time         | Expected event end.                          |
| relevant_clips   | Ground-truth relevant clips.                 |
| expected_answer  | Ground-truth answer or expected uncertainty. |
| policy_reference | Applicable policy section where relevant.    |

## 24.2 Test Scenarios {#test-scenarios}

- Restricted-area entry

- Person leaves an object

- Person approaches equipment

- Two-person interaction

- Alarm event

- Normal walking

- Normal entrance/exit

- Multiple people in scene

- Ambiguous/occluded event

- No relevant event for the query

## 24.3 Metrics {#metrics}

| **Area**     | **Metrics**                                               |
|--------------|-----------------------------------------------------------|
| Retrieval    | Recall@5, Recall@10, Precision@5, MRR                     |
| Temporal     | Timestamp error, Temporal IoU                             |
| RAG          | Context relevance, context recall, answer faithfulness    |
| Generation   | Factual accuracy, report completeness, hallucination rate |
| System       | Video processing time, query latency                      |
| Human Review | Reviewer acceptance rate, correction rate                 |

## 24.4 Baselines {#baselines}

| **Baseline** | **Description** |
|----|----|
| Manual Search | Human searches video by timeline without semantic retrieval. |
| Metadata/Keyword Search | Search using stored labels/transcripts without vector retrieval. |
| Vector-Only RAG | Semantic vector retrieval without hybrid metadata filtering/reranking. |
| Proposed System | Hybrid retrieval + reranking + VLM verification + agent + policy RAG. |

The objective is to show whether the proposed GenAI architecture improves evidence retrieval and investigation quality rather than simply demonstrating that an LLM can produce fluent text.

# 25. Development Roadmap and Integration Gates {#development-roadmap-and-integration-gates}

| **Phase** | **Deliverables** | **Integration Gate** |
|----|----|----|
| Phase 1 --- Foundation | Next.js, FastAPI, PostgreSQL, Docker, authentication | User can log in and create an investigation. |
| Phase 2 --- Video | Upload, MinIO, FFmpeg, scene detection, video player | Uploaded video produces playable clips and valid timestamps. |
| Phase 3 --- Computer Vision | YOLO, tracking, event metadata | System produces timestamped detections and tracking IDs. |
| Phase 4 --- GenAI/RAG | VLM descriptions, embeddings, Qdrant, Video RAG | A benchmark query retrieves the correct clip in Top-K. |
| Phase 5 --- Agent | LangGraph and bounded tool calling | Agent completes a multi-tool investigation within call limits. |
| Phase 6 --- Policy RAG | Policy ingestion, retrieval, assessment | Policy question retrieves the correct policy section. |
| Phase 7 --- Verification | Claim decomposition, evidence/temporal/policy checks | Unsupported claims become UNKNOWN/INSUFFICIENT rather than facts. |
| Phase 8 --- Human Review/Reporting | Review UI, timeline, structured report, PDF | Reviewer can approve/reject findings and finalize a traceable report. |
| Phase 9 --- Evaluation | Benchmark, baselines, metrics | Results are reproducible and documented. |

# 26. Testing Strategy {#testing-strategy}

| **Module** | **Tests** |
|----|----|
| Video Processing | File validation, metadata extraction, clip timestamps, scene boundaries. |
| Detection/Tracking | Expected labels, confidence ranges, tracking continuity on benchmark clips. |
| Retrieval | Recall@K, metadata filters, reranking behavior, no-result handling. |
| RAG | Context relevance, policy chunk retrieval, grounded response checks. |
| Agent | Tool selection, maximum-call limit, invalid-tool handling, timeout handling. |
| Verification | Supported claim, unsupported claim, timestamp mismatch, conflicting evidence. |
| Timeline | Chronological ordering, source timestamp preservation, duplicate event handling. |
| Reporting | Schema validity, evidence references, uncertainty section, review state. |
| Integration | Upload → processing → indexing → search → evidence → verification → review → report. |

## 26.1 Critical Failure Tests {#critical-failure-tests}

- Query has no matching evidence.

- Retrieved clips conflict with each other.

- Timestamp is outside video duration.

- Policy has no applicable rule.

- VLM produces an unsupported claim.

- Agent exceeds tool-call budget.

- Video processing fails halfway through.

- LLM/VLM API is unavailable.

- Reviewer rejects an AI finding.

# 27. MVP and Final Prototype {#mvp-and-final-prototype}

## 27.1 MVP {#mvp}

> Video Upload\
> ↓\
> Clip Extraction\
> ↓\
> YOLO / Event Analysis\
> ↓\
> VLM Semantic Descriptions\
> ↓\
> Embeddings\
> ↓\
> Qdrant\
> ↓\
> Natural-Language Video Search\
> ↓\
> Evidence Cards\
> ↓\
> Grounded Answer

## 27.2 Final Prototype {#final-prototype}

> CCTV Video + Audio\
> ↓\
> Vision + Speech\
> ↓\
> Semantic Event Index\
> ↓\
> Hybrid Video RAG + Reranking\
> ↓\
> Investigation Agent\
> ↓\
> Policy RAG\
> ↓\
> Evidence Verification\
> ↓\
> Human Review\
> ↓\
> Verified Timeline\
> ↓\
> Evidence-Grounded Report\
> ↓\
> Audit Trail

# 28. Demonstration Scenario {#demonstration-scenario}

Use a controlled or public-domain CCTV-style sample video, preferably 5--15 minutes for the prototype demonstration.

13. Login as an investigator.

14. Upload CCTV footage and camera metadata.

15. Start processing and show asynchronous progress.

16. Open the indexed investigation workspace.

17. Ask: "Find when a person entered the restricted area."

18. Show the retrieved clips, timestamp and evidence reference.

19. Ask: "What happened immediately after the entry?"

20. Ask: "Is the observed entry consistent with the supplied restricted-area policy?"

21. Show the retrieved policy section.

22. Run evidence verification.

23. Display the finding status as OBSERVED / POLICY-ASSESSED / VERIFIED or UNKNOWN as appropriate.

24. Generate the chronological timeline.

25. Open the claim-to-evidence links.

26. Generate a draft incident report.

27. Review, edit or reject findings as a human reviewer.

28. Finalize the report and show the audit trail.

# 29. Success Criteria {#success-criteria}

| **Area** | **Prototype Success Condition** |
|----|----|
| Video Ingestion | Supported sample video uploads and produces valid clips/timestamps. |
| Detection | People/objects are detected on the selected benchmark scenarios. |
| Video RAG | Relevant clips are retrieved for benchmark queries with measurable Recall@K. |
| Temporal Grounding | Retrieved event timestamps remain linked to source video. |
| Policy RAG | Applicable policy sections are retrieved for policy questions. |
| Agent | Agent completes bounded investigations using registered tools. |
| Verification | Unsupported claims can be rejected or marked insufficient. |
| Human Review | Reviewer can approve/reject/edit findings before finalization. |
| Reporting | Every major final claim links to evidence. |
| Evaluation | System is compared against at least two baselines. |

# 30. Glossary {#glossary}

| **Term** | **Definition** |
|----|----|
| RAG | Retrieval-Augmented Generation: grounding model output in retrieved information. |
| Video RAG | RAG over indexed video segments, metadata and semantic descriptions. |
| VLM | Vision-Language Model capable of reasoning over visual inputs and text. |
| Embedding | Numerical representation used for semantic similarity search. |
| Vector Database | Database optimized for storing and searching embeddings. |
| Agentic AI | AI workflow that selects and calls tools to complete a bounded task. |
| Grounding | Linking generated claims to verifiable source evidence. |
| Hallucination | A confident but unsupported or false model-generated statement. |
| Temporal IoU | Overlap measure between predicted and ground-truth time intervals. |
| SOP | Standard Operating Procedure. |
| Human-in-the-Loop | Workflow where a human reviews or approves AI-generated findings. |
| Visual Subject Tracking | Tracking a visual entity across frames without asserting real-world identity. |

# Final Architecture Principle

The project should prioritize evidence over fluent generation. The AI must retrieve and verify before making important claims, preserve source timestamps, distinguish observation from inference, use documented policies for policy assessment, and require human review before a report becomes final.

The resulting system is therefore positioned as a technically realistic GenAI capstone demonstrating Multimodal AI + Video RAG + Agentic AI + Policy RAG + Evidence Grounding + Verification + Evaluation, while explicitly controlling the project\'s claims and limitations.
