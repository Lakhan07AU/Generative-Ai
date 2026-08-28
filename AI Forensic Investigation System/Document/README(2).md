# AI Forensic Investigation System

> **GenAI Capstone Project --- Semester 5 \| Prototype v1.0**

An AI-powered forensic surveillance investigation assistant that enables
security personnel to investigate CCTV footage using natural-language
queries instead of manually reviewing hours of video.

The system combines **Computer Vision, Multimodal GenAI, Video RAG,
Agentic AI, Policy RAG, Evidence Verification, Timeline Reasoning, and
Automated Report Generation**.

------------------------------------------------------------------------

## 1. Problem

Security personnel often need to manually review large volumes of
surveillance footage after an incident. This is:

-   Time-consuming
-   Difficult to search semantically
-   Prone to missed evidence
-   Dependent on manual investigation
-   Slow when creating structured incident reports

Traditional surveillance systems can detect predefined objects or
events, but they generally provide limited semantic and temporal
reasoning.

### Our Solution

AI Forensic Investigation System converts surveillance footage into a
searchable multimodal knowledge base and provides an AI investigation
agent that can:

1.  Process CCTV footage.
2.  Detect people and relevant objects.
3.  Extract scenes, clips, frames, and audio.
4.  Generate semantic descriptions using multimodal AI.
5.  Index video information using embeddings.
6.  Search footage using natural-language queries.
7.  Retrieve relevant evidence using Video RAG.
8.  Reason across video evidence and security policies.
9.  Verify AI-generated findings.
10. Reconstruct incident timelines.
11. Generate evidence-grounded incident reports.

------------------------------------------------------------------------

# 2. Key Features

## Video Intelligence

-   CCTV video upload
-   Metadata extraction
-   Scene/clip detection
-   Frame extraction
-   Person/object detection
-   Person/object tracking
-   Audio extraction
-   Speech-to-text
-   Multimodal video understanding

## GenAI Investigation

-   Natural-language video search
-   Video RAG
-   Multimodal reasoning
-   Conversational investigation
-   Agentic tool calling
-   Evidence verification
-   Timeline reconstruction
-   Automated report generation

## Security Knowledge RAG

Administrators can upload:

-   Security SOPs
-   Restricted-area policies
-   Emergency procedures
-   Incident classification rules
-   Organization-specific guidelines

The system retrieves relevant policy information during an
investigation.

------------------------------------------------------------------------

# 3. Why This Is a GenAI Project

The project is intentionally designed to demonstrate multiple GenAI
concepts:

  Concept                    Usage
  -------------------------- --------------------------------------------------
  LLM                        Investigation reasoning and report generation
  Multimodal AI              Video + text + audio understanding
  Vision-Language Model      Semantic understanding of video clips
  Prompt Engineering         Investigation and report prompts
  Embeddings                 Semantic representation of clips and documents
  Vector Database            Retrieval of relevant evidence
  RAG                        Video and security-policy retrieval
  Video RAG                  Natural-language search over video
  Agentic AI                 Autonomous investigation workflow
  Tool Calling               Search, retrieve, verify, timeline tools
  Structured Generation      Consistent incident reports
  Grounding                  Linking claims to evidence
  Hallucination Mitigation   Evidence verification and uncertainty
  Evaluation                 Retrieval, temporal, RAG, and generation metrics

------------------------------------------------------------------------

# 4. System Architecture

``` text
                    ┌───────────────────┐
                    │     Next.js UI    │
                    │   Investigation   │
                    │     Dashboard     │
                    └─────────┬─────────┘
                              │
                              ▼
                       ┌─────────────┐
                       │   FastAPI   │
                       │   Backend   │
                       └──────┬──────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       Video Pipeline      RAG Layer       Agent Layer
             │                │                │
       FFmpeg/OpenCV       Qdrant          LangGraph
       YOLO/Tracker        Embeddings          │
       Whisper               │                 │
       VLM                   │                 │
             └────────────────┼────────────────┘
                              ▼
                    Multimodal LLM / VLM
                              │
                              ▼
                    Evidence Verification
                              │
                              ▼
                     Timeline Generator
                              │
                              ▼
                      Report Generator
                         /          \
                        /            \
                 PostgreSQL         MinIO
```

------------------------------------------------------------------------

# 5. End-to-End Pipeline

``` text
CCTV Video
    ↓
FFmpeg
    ↓
Scene Detection
    ↓
Frames / Clips
    ↓
YOLO + Tracking
    ↓
Audio + Whisper
    ↓
Multimodal VLM
    ↓
Semantic Event Descriptions
    ↓
Embeddings
    ↓
Qdrant
    ↓
Video RAG
    ↓
Investigation Agent
    ↓
Policy RAG
    ↓
Evidence Verification
    ↓
Timeline
    ↓
Structured Incident Report
```

------------------------------------------------------------------------

# 6. Technology Stack

## Frontend

-   Next.js
-   React
-   Tailwind CSS
-   shadcn/ui
-   HTML5 Video / Video.js
-   Recharts

## Backend

-   Python
-   FastAPI
-   Pydantic

## Video Processing

-   FFmpeg
-   OpenCV
-   PySceneDetect

## Computer Vision

-   YOLO
-   ByteTrack / BoT-SORT

## Speech

-   Whisper

## GenAI

-   One primary Multimodal LLM/VLM
-   LLM for reasoning and report generation

## RAG

-   Qdrant
-   BGE / E5 embeddings
-   LangChain or LlamaIndex

## Agents

-   LangGraph

## Data

-   PostgreSQL
-   MinIO

## Deployment

-   Docker
-   Docker Compose

------------------------------------------------------------------------

# 7. Core Investigation Workflow

A user can ask questions such as:

> Find when a person entered the restricted area.

> What happened between 10:30 and 11:00?

> Find the person carrying a red backpack.

> Did anyone approach the person after they entered?

> Was the restricted-area entry against security policy?

The system retrieves relevant video evidence and reasons over it.

Example:

``` text
User Query
    ↓
Investigation Agent
    ↓
Search Video
    ↓
Retrieve Relevant Clips
    ↓
Analyze Evidence
    ↓
Search Security Policy
    ↓
Verify Finding
    ↓
Return Answer
```

------------------------------------------------------------------------

# 8. Evidence-Grounded Answers

The system should never rely only on an LLM's generated statement.

Every important finding should be connected to evidence.

Example:

``` text
Finding:
Person entered restricted area.

Timestamp:
10:42:17

Camera:
CAM-03

Confidence:
94%

Evidence:
CLIP-023
```

The user can open the supporting clip or frame.

------------------------------------------------------------------------

# 9. Evidence Verification

The verification layer is designed to reduce hallucinations.

``` text
Initial AI Conclusion
        ↓
Retrieve Original Evidence
        ↓
Check Timestamp
        ↓
Check Relevant Frames
        ↓
Retrieve Applicable Policy
        ↓
Verify
        ↓
Verified
Partially Verified
or
Insufficient Evidence
```

If evidence is insufficient, the system should explicitly say so.

Example:

> The footage supports that a person entered the restricted area, but
> the person's authorization status cannot be confirmed from the
> available footage.

------------------------------------------------------------------------

# 10. Video RAG

Instead of passing an entire CCTV recording directly to an LLM:

``` text
Large Video
    ↓
Scene Detection
    ↓
Relevant Clips
    ↓
Semantic Descriptions
    ↓
Embeddings
    ↓
Vector Database
    ↓
Natural Language Query
    ↓
Relevant Evidence
    ↓
Multimodal Reasoning
```

This makes long-form surveillance footage searchable.

------------------------------------------------------------------------

# 11. Security Policy RAG

Policy documents are processed separately:

``` text
PDF / DOCX
    ↓
Text Extraction
    ↓
Chunking
    ↓
Embeddings
    ↓
Qdrant
    ↓
Policy Retrieval
    ↓
LLM Reasoning
```

Example:

> Does entering this area violate the security policy?

The system retrieves the applicable policy before making its assessment.

------------------------------------------------------------------------

# 12. Agent Tools

The Investigation Agent can use tools such as:

``` text
search_video()
search_person()
search_object()
search_event()
get_clip()
get_frame()
build_timeline()
search_policy()
verify_evidence()
generate_report()
```

The agent chooses the appropriate tools depending on the user's
question.

------------------------------------------------------------------------

# 13. Incident Timeline

The system automatically creates a chronological timeline.

Example:

``` text
10:41:52 — Person appears near entrance
10:42:17 — Person enters restricted area
10:42:31 — Person approaches equipment
10:43:08 — Person interacts with equipment
10:44:51 — Alarm detected
10:45:09 — Person exits
```

Each event should contain:

-   Timestamp
-   Description
-   Evidence
-   Confidence

------------------------------------------------------------------------

# 14. Automated Incident Report

The generated report contains:

``` text
INCIDENT REPORT

Incident ID
Date
Location
Camera

1. Executive Summary

2. Incident Classification

3. Timeline

4. Persons / Objects Involved

5. Supporting Evidence

6. Policy Analysis

7. AI Findings

8. Confidence Scores

9. Unverified Claims

10. Recommendations
```

Important claims must be traceable to evidence.

------------------------------------------------------------------------

# 15. Project Structure

A recommended implementation structure:

``` text
ai-forensic-investigation/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── pages/
│   └── lib/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── agents/
│   │   ├── rag/
│   │   ├── video/
│   │   ├── vision/
│   │   ├── audio/
│   │   ├── reports/
│   │   ├── verification/
│   │   └── database/
│   └── requirements.txt
│
├── data/
│   ├── videos/
│   ├── clips/
│   ├── frames/
│   ├── policies/
│   └── reports/
│
├── models/
│
├── scripts/
│
├── tests/
│
├── docker-compose.yml
├── .env.example
└── README.md
```

------------------------------------------------------------------------

# 16. Environment Variables

Create a `.env` file based on `.env.example`.

Example:

``` env
DATABASE_URL=
QDRANT_URL=
QDRANT_API_KEY=

LLM_API_KEY=
EMBEDDING_API_KEY=

MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=

WHISPER_MODEL=
YOLO_MODEL=
```

Never commit API keys or passwords to Git.

------------------------------------------------------------------------

# 17. Running the Prototype

## Prerequisites

Install:

-   Git
-   Python 3.11+
-   Node.js 20+
-   Docker
-   Docker Compose
-   FFmpeg

A GPU is recommended for local computer-vision and multimodal model
inference, but the prototype can use API-based models where appropriate.

## Clone

``` bash
git clone <repository-url>
cd ai-forensic-investigation
```

## Start infrastructure

``` bash
docker compose up -d
```

## Backend

``` bash
cd backend
python -m venv .venv
```

Windows:

``` bash
.venv\Scripts\activate
```

Linux/macOS:

``` bash
source .venv/bin/activate
```

Install dependencies:

``` bash
pip install -r requirements.txt
```

Run:

``` bash
uvicorn app.main:app --reload
```

## Frontend

``` bash
cd frontend
npm install
npm run dev
```

The frontend should then be available through the local development URL
shown by Next.js.

------------------------------------------------------------------------

# 18. Prototype Demo

Use a controlled or public-domain CCTV-style sample video.

### Demo Steps

1.  Login.
2.  Open Dashboard.
3.  Upload CCTV video.
4.  Enter camera metadata.
5.  Start processing.
6.  Wait for indexing.
7.  Open Investigation Workspace.
8.  Ask:

``` text
Find all suspicious activity in this video.
```

9.  Review retrieved evidence.
10. Ask:

``` text
When did the person enter the restricted area?
```

11. Ask:

``` text
Was this a policy violation?
```

12. Review retrieved security policy.
13. Run evidence verification.
14. Generate timeline.
15. Generate final incident report.

------------------------------------------------------------------------

# 19. Evaluation

The project should be evaluated using a labelled test set containing:

-   Query
-   Expected event
-   Expected timestamp
-   Relevant clip
-   Expected answer

### Retrieval Metrics

-   Recall@5
-   Recall@10
-   Precision@5
-   MRR

### Temporal Metrics

-   Timestamp error
-   Temporal IoU

### RAG Metrics

-   Context relevance
-   Context recall
-   Answer faithfulness

### Generation Metrics

-   Factual accuracy
-   Report completeness
-   Hallucination rate

### System Metrics

-   Video processing time
-   Query response latency

------------------------------------------------------------------------

# 20. Development Roadmap

## Phase 1 --- Foundation

-   [ ] Next.js frontend
-   [ ] FastAPI backend
-   [ ] PostgreSQL
-   [ ] Docker
-   [ ] Authentication

## Phase 2 --- Video

-   [ ] Video upload
-   [ ] MinIO storage
-   [ ] FFmpeg processing
-   [ ] Scene detection
-   [ ] Video player

## Phase 3 --- Computer Vision

-   [ ] YOLO integration
-   [ ] Object detection
-   [ ] Tracking
-   [ ] Event metadata

## Phase 4 --- GenAI

-   [ ] VLM integration
-   [ ] Clip descriptions
-   [ ] Embeddings
-   [ ] Qdrant
-   [ ] Video RAG

## Phase 5 --- Agent

-   [ ] LangGraph
-   [ ] Investigation agent
-   [ ] Tool calling
-   [ ] Investigation workflow

## Phase 6 --- Policy RAG

-   [ ] Policy upload
-   [ ] Document processing
-   [ ] Policy embeddings
-   [ ] Policy retrieval
-   [ ] Policy reasoning

## Phase 7 --- Verification

-   [ ] Evidence verification
-   [ ] Confidence scoring
-   [ ] Uncertainty handling
-   [ ] Hallucination mitigation

## Phase 8 --- Reporting

-   [ ] Timeline generation
-   [ ] Structured report
-   [ ] PDF export
-   [ ] Evidence references

## Phase 9 --- Evaluation

-   [ ] Test dataset
-   [ ] Retrieval evaluation
-   [ ] RAG evaluation
-   [ ] Generation evaluation
-   [ ] Performance evaluation

------------------------------------------------------------------------

# 21. MVP

The minimum working prototype should implement:

``` text
Video Upload
     ↓
Video Processing
     ↓
Object/Event Analysis
     ↓
Semantic Clip Descriptions
     ↓
Embeddings
     ↓
Qdrant
     ↓
Natural Language Video Search
     ↓
Evidence Retrieval
     ↓
Grounded Report
```

------------------------------------------------------------------------

# 22. Final Prototype

The complete prototype should implement:

``` text
CCTV Video
   +
Audio
   +
Vision
   +
Video RAG
   +
Security Policy RAG
   +
Investigation Agent
   +
Tool Calling
   +
Evidence Verification
   +
Timeline Reasoning
   +
Grounded Report Generation
```

------------------------------------------------------------------------

# 23. Design Principles

### Evidence First

AI conclusions must be connected to supporting evidence.

### No Fabricated Evidence

The system must not invent timestamps, people, objects, or events.

### Explicit Uncertainty

When evidence is insufficient, the system should say so.

### Modular AI

Computer vision, retrieval, reasoning, verification, and reporting
should be separate components.

### Prototype First

Prioritize an end-to-end working workflow over unnecessary production
infrastructure.

------------------------------------------------------------------------

# 24. Out of Scope

The prototype will not focus on:

-   Real-time production CCTV monitoring
-   Large-scale multi-camera deployment
-   Custom training of an LLM
-   Kubernetes
-   Enterprise IAM
-   Mobile application
-   Production facial-recognition infrastructure
-   Fully autonomous real-world security decisions

The system is an **investigation assistance prototype**, not a
replacement for human security personnel.

------------------------------------------------------------------------

# 25. Expected Outcome

At the end of the project, a user should be able to upload surveillance
footage and ask:

> **"What happened, when did it happen, what evidence supports it, did
> it violate policy, and generate the incident report."**

The system should answer with:

-   Natural-language explanation
-   Relevant clips
-   Relevant frames
-   Exact timestamps
-   Incident timeline
-   Policy evidence
-   Confidence
-   Verification status
-   Structured incident report

------------------------------------------------------------------------

# 26. Project Value

This project demonstrates a complete modern GenAI application rather
than a single AI model.

It combines:

**Computer Vision + Multimodal AI + RAG + Video RAG + Vector Search +
LLM Reasoning + Agentic AI + Tool Calling + Knowledge RAG + Evidence
Verification + Structured Generation.**

The primary academic goal is to demonstrate how GenAI can transform
large, unstructured surveillance footage into an interactive,
searchable, and evidence-grounded investigation system.
