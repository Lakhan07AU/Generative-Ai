const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  Header, Footer, PageNumber, TabStopType, TabStopPosition,
  LevelFormat, PageBreak, TableOfContents, VerticalAlign, PageOrientation
} = require("docx");
const fs = require("fs");

const NAVY = "1F3864";
const ACCENT = "2E74B5";
const LIGHT = "EDF2F8";
const GREY = "595959";

// ---------- helpers ----------
function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 420, after: 200 },
    border: { bottom: { color: ACCENT, space: 4, style: BorderStyle.SINGLE, size: 6 } },
    children: [new TextRun({ text, bold: true, color: NAVY, size: 30 })],
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 320, after: 140 },
    children: [new TextRun({ text, bold: true, color: ACCENT, size: 24 })],
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 220, after: 100 },
    children: [new TextRun({ text, bold: true, color: NAVY, size: 21 })],
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 160, line: 300 },
    children: [new TextRun({ text, size: 22, color: "222222", ...opts })],
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullet-list", level },
    spacing: { after: 80, line: 280 },
    children: [new TextRun({ text, size: 22, color: "222222" })],
  });
}
let numListCounter = 0;
const numListConfigs = [];
function numberedList(items) {
  numListCounter += 1;
  const ref = "num-list-" + numListCounter;
  numListConfigs.push({
    reference: ref,
    levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 300 } } } },
    ],
  });
  return items.map((text) =>
    new Paragraph({
      numbering: { reference: ref, level: 0 },
      spacing: { after: 80, line: 280 },
      children: [new TextRun({ text, size: 22, color: "222222" })],
    })
  );
}
function quoteLine(text) {
  return new Paragraph({
    indent: { left: 400 },
    spacing: { after: 120 },
    border: { left: { color: ACCENT, space: 8, style: BorderStyle.SINGLE, size: 18 } },
    children: [new TextRun({ text, italics: true, size: 22, color: "333333" })],
  });
}
function codeBlock(lines) {
  const arr = Array.isArray(lines) ? lines : lines.split("\n");
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
      left: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
      right: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" },
    },
    rows: [
      new TableRow({
        children: [
          new TableCell({
            shading: { type: ShadingType.CLEAR, fill: "F5F5F5" },
            margins: { top: 160, bottom: 160, left: 200, right: 200 },
            children: arr.map((line) =>
              new Paragraph({
                spacing: { after: 0 },
                children: [new TextRun({ text: line.length ? line : " ", font: "Consolas", size: 18, color: "2B2B2B" })],
              })
            ),
          }),
        ],
      }),
    ],
  });
}
function spacer(h = 120) {
  return new Paragraph({ spacing: { after: h }, children: [] });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}
function cell(text, opts = {}) {
  const { header = false, width, shade } = opts;
  return new TableCell({
    width: width ? { size: width, type: WidthType.DXA } : undefined,
    shading: shade ? { type: ShadingType.CLEAR, fill: shade } : (header ? { type: ShadingType.CLEAR, fill: NAVY } : undefined),
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 100, bottom: 100, left: 120, right: 120 },
    children: [
      new Paragraph({
        children: [new TextRun({ text, bold: header, color: header ? "FFFFFF" : "222222", size: 20 })],
      }),
    ],
  });
}
function table(headerRow, rows, widths) {
  const colWidths = widths || headerRow.map(() => Math.floor(9350 / headerRow.length));
  return new Table({
    width: { size: 9350, type: WidthType.DXA },
    columnWidths: colWidths,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      left: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      right: { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: "D9D9D9" },
      insideVertical: { style: BorderStyle.SINGLE, size: 4, color: "D9D9D9" },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headerRow.map((t, i) => cell(t, { header: true, width: colWidths[i] })),
      }),
      ...rows.map((r, ri) =>
        new TableRow({
          children: r.map((t, i) => cell(t, { width: colWidths[i], shade: ri % 2 === 1 ? LIGHT : undefined })),
        })
      ),
    ],
  });
}
function checklist(items) {
  return items.map((it) =>
    new Paragraph({
      numbering: { reference: "bullet-list", level: 0 },
      spacing: { after: 60 },
      children: [new TextRun({ text: "☐  " + it, size: 22, color: "222222" })],
    })
  );
}

// ---------- content ----------
const children = [];

// COVER PAGE
children.push(
  new Paragraph({ spacing: { before: 1600 }, children: [] }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "AI FORENSIC INVESTIGATION SYSTEM", bold: true, color: NAVY, size: 56 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 240, after: 100 },
    children: [new TextRun({ text: "Project Documentation", color: ACCENT, size: 32, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 60 },
    children: [new TextRun({ text: "Natural-Language Investigation over CCTV Footage using Multimodal GenAI", italics: true, color: GREY, size: 22 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 800 },
    children: [new TextRun({ text: "GenAI Capstone Project — Semester 5", size: 24, color: "333333" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 800 },
    children: [new TextRun({ text: "Prototype Version 1.0", size: 24, color: "333333" })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 1600 },
    children: [new TextRun({ text: "Document Type: Full Project Documentation", size: 20, color: GREY })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
    children: [new TextRun({ text: "Status: Prototype / Academic Capstone", size: 20, color: GREY })],
  }),
  pageBreak()
);

// TOC
children.push(
  new Paragraph({
    children: [new TextRun({ text: "Table of Contents", bold: true, color: NAVY, size: 32 })],
    spacing: { after: 300 },
  }),
  new TableOfContents("Table of Contents", {
    hyperlink: true,
    headingStyleRange: "1-3",
  }),
  pageBreak()
);

// 1. EXECUTIVE SUMMARY
children.push(h1("1. Executive Summary"));
children.push(p(
  "The AI Forensic Investigation System is an AI-powered forensic surveillance investigation assistant that allows security personnel to investigate CCTV footage using natural-language queries instead of manually reviewing hours of video. The system unifies computer vision, multimodal generative AI, video retrieval-augmented generation (Video RAG), agentic AI, policy-grounded retrieval, evidence verification, timeline reasoning, and automated report generation into a single end-to-end investigation workflow."
));
children.push(p(
  "The end goal is that an investigator can upload surveillance footage and ask a single high-level question — what happened, when it happened, what evidence supports it, whether it violated policy, and to generate the incident report — and receive an evidence-grounded answer with supporting clips, frames, timestamps, a reconstructed timeline, policy analysis, confidence scores, and a structured incident report."
));

// 2. PROBLEM STATEMENT
children.push(h1("2. Problem Statement"));
children.push(p("Security personnel often need to manually review large volumes of surveillance footage after an incident. This manual process is:"));
["Time-consuming", "Difficult to search semantically", "Prone to missed evidence", "Dependent on manual investigation", "Slow when creating structured incident reports"].forEach((t) => children.push(bullet(t)));
children.push(p("Traditional surveillance systems can detect predefined objects or events, but they generally provide limited semantic and temporal reasoning — they can flag \"a person\" or \"a vehicle\" but cannot answer open-ended, natural-language investigative questions about what happened, why, and whether it was policy-compliant."));

children.push(h2("2.1 Proposed Solution"));
children.push(p("The AI Forensic Investigation System converts surveillance footage into a searchable multimodal knowledge base and provides an AI investigation agent that can:"));
[
  "Process CCTV footage",
  "Detect people and relevant objects",
  "Extract scenes, clips, frames, and audio",
  "Generate semantic descriptions using multimodal AI",
  "Index video information using embeddings",
  "Search footage using natural-language queries",
  "Retrieve relevant evidence using Video RAG",
  "Reason across video evidence and security policies",
  "Verify AI-generated findings",
  "Reconstruct incident timelines",
  "Generate evidence-grounded incident reports",
].forEach((t) => children.push(numbered(t)));

// 3. KEY FEATURES
children.push(h1("3. Key Features"));
children.push(h2("3.1 Video Intelligence"));
["CCTV video upload", "Metadata extraction", "Scene / clip detection", "Frame extraction", "Person / object detection", "Person / object tracking", "Audio extraction", "Speech-to-text", "Multimodal video understanding"].forEach((t) => children.push(bullet(t)));

children.push(h2("3.2 GenAI Investigation"));
["Natural-language video search", "Video RAG", "Multimodal reasoning", "Conversational investigation", "Agentic tool calling", "Evidence verification", "Timeline reconstruction", "Automated report generation"].forEach((t) => children.push(bullet(t)));

children.push(h2("3.3 Security Knowledge RAG"));
children.push(p("Administrators can upload organizational knowledge that the agent consults during an investigation:"));
["Security SOPs", "Restricted-area policies", "Emergency procedures", "Incident classification rules", "Organization-specific guidelines"].forEach((t) => children.push(bullet(t)));
children.push(p("The system retrieves relevant policy information during an investigation, so findings can be checked against organizational rules rather than left to unaided judgment."));

// 4. WHY GENAI
children.push(h1("4. Why This Is a GenAI Project"));
children.push(p("The project is intentionally designed to demonstrate multiple GenAI concepts within a single, coherent application:"));
children.push(table(
  ["Concept", "Usage in This System"],
  [
    ["LLM", "Investigation reasoning and report generation"],
    ["Multimodal AI", "Video + text + audio understanding"],
    ["Vision-Language Model", "Semantic understanding of video clips"],
    ["Prompt Engineering", "Investigation and report-generation prompts"],
    ["Embeddings", "Semantic representation of clips and documents"],
    ["Vector Database", "Retrieval of relevant evidence"],
    ["RAG", "Video and security-policy retrieval"],
    ["Video RAG", "Natural-language search over video"],
    ["Agentic AI", "Autonomous investigation workflow"],
    ["Tool Calling", "Search, retrieve, verify, and timeline tools"],
    ["Structured Generation", "Consistent, well-formed incident reports"],
    ["Grounding", "Linking claims to underlying evidence"],
    ["Hallucination Mitigation", "Evidence verification and explicit uncertainty"],
    ["Evaluation", "Retrieval, temporal, RAG, and generation metrics"],
  ],
  [3200, 6150]
));

// 5. ARCHITECTURE
children.push(h1("5. System Architecture"));
children.push(p("The system follows a layered architecture separating presentation, orchestration, and the three core processing layers (video pipeline, RAG layer, and agent layer), all coordinated around a multimodal LLM / VLM."));
children.push(codeBlock([
"                    ┌───────────────────┐",
"                    │     Next.js UI    │",
"                    │   Investigation   │",
"                    │     Dashboard     │",
"                    └─────────┬─────────┘",
"                              │",
"                              ▼",
"                       ┌─────────────┐",
"                       │   FastAPI   │",
"                       │   Backend   │",
"                       └──────┬──────┘",
"                              │",
"             ┌────────────────┼────────────────┐",
"             ▼                ▼                ▼",
"       Video Pipeline      RAG Layer       Agent Layer",
"             │                │                │",
"       FFmpeg/OpenCV       Qdrant          LangGraph",
"       YOLO/Tracker        Embeddings          │",
"       Whisper               │                 │",
"       VLM                   │                 │",
"             └────────────────┼────────────────┘",
"                              ▼",
"                    Multimodal LLM / VLM",
"                              │",
"                              ▼",
"                    Evidence Verification",
"                              │",
"                              ▼",
"                     Timeline Generator",
"                              │",
"                              ▼",
"                      Report Generator",
"                         /          \\",
"                        /            \\",
"                 PostgreSQL         MinIO",
]));

children.push(h2("5.1 Architectural Layers"));
children.push(table(
  ["Layer", "Responsibility", "Key Technologies"],
  [
    ["Presentation", "Investigation dashboard, video review, chat-style querying", "Next.js, React, Tailwind, shadcn/ui"],
    ["API / Orchestration", "Request handling, auth, coordination between layers", "FastAPI, Pydantic"],
    ["Video Pipeline", "Ingest, decode, detect, track, transcribe", "FFmpeg, OpenCV, PySceneDetect, YOLO, ByteTrack/BoT-SORT, Whisper"],
    ["RAG Layer", "Embedding, indexing, retrieval of video + policy evidence", "Qdrant, BGE/E5 embeddings, LangChain/LlamaIndex"],
    ["Agent Layer", "Autonomous tool-calling investigation workflow", "LangGraph"],
    ["Persistence", "Structured data and binary object storage", "PostgreSQL, MinIO"],
  ],
  [2100, 4200, 3050]
));

// 6. PIPELINE
children.push(h1("6. End-to-End Pipeline"));
children.push(p("A single uploaded video moves through the following stages before it becomes queryable evidence:"));
children.push(codeBlock([
"CCTV Video",
"    ↓",
"FFmpeg",
"    ↓",
"Scene Detection",
"    ↓",
"Frames / Clips",
"    ↓",
"YOLO + Tracking",
"    ↓",
"Audio + Whisper",
"    ↓",
"Multimodal VLM",
"    ↓",
"Semantic Event Descriptions",
"    ↓",
"Embeddings",
"    ↓",
"Qdrant",
"    ↓",
"Video RAG",
"    ↓",
"Investigation Agent",
"    ↓",
"Policy RAG",
"    ↓",
"Evidence Verification",
"    ↓",
"Timeline",
"    ↓",
"Structured Incident Report",
]));

// 7. TECH STACK
children.push(h1("7. Technology Stack"));
children.push(table(
  ["Layer", "Technologies"],
  [
    ["Frontend", "Next.js, React, Tailwind CSS, shadcn/ui, HTML5 Video / Video.js, Recharts"],
    ["Backend", "Python, FastAPI, Pydantic"],
    ["Video Processing", "FFmpeg, OpenCV, PySceneDetect"],
    ["Computer Vision", "YOLO, ByteTrack / BoT-SORT"],
    ["Speech", "Whisper"],
    ["GenAI", "One primary Multimodal LLM/VLM; LLM for reasoning and report generation"],
    ["RAG", "Qdrant, BGE / E5 embeddings, LangChain or LlamaIndex"],
    ["Agents", "LangGraph"],
    ["Data", "PostgreSQL, MinIO"],
    ["Deployment", "Docker, Docker Compose"],
  ],
  [2600, 6750]
));

// 8. WORKFLOW
children.push(h1("8. Core Investigation Workflow"));
children.push(p("A user can ask open-ended, natural-language investigative questions such as:"));
[
  "Find when a person entered the restricted area.",
  "What happened between 10:30 and 11:00?",
  "Find the person carrying a red backpack.",
  "Did anyone approach the person after they entered?",
  "Was the restricted-area entry against security policy?",
].forEach((t) => children.push(quoteLine(t)));
children.push(p("The system retrieves relevant video evidence and reasons over it using the following control flow:"));
children.push(codeBlock([
"User Query",
"    ↓",
"Investigation Agent",
"    ↓",
"Search Video",
"    ↓",
"Retrieve Relevant Clips",
"    ↓",
"Analyze Evidence",
"    ↓",
"Search Security Policy",
"    ↓",
"Verify Finding",
"    ↓",
"Return Answer",
]));

// 9. EVIDENCE-GROUNDED ANSWERS
children.push(h1("9. Evidence-Grounded Answers"));
children.push(p("The system is designed so that it should never rely only on an LLM's generated statement. Every important finding must be connected to underlying, inspectable evidence."));
children.push(h2("9.1 Example Finding"));
children.push(table(
  ["Field", "Value"],
  [
    ["Finding", "Person entered restricted area"],
    ["Timestamp", "10:42:17"],
    ["Camera", "CAM-03"],
    ["Confidence", "94%"],
    ["Evidence", "CLIP-023"],
  ],
  [2400, 6950]
));
children.push(p("The user can open the supporting clip or frame directly from the finding to independently confirm the AI's conclusion."));

// 10. VERIFICATION
children.push(h1("10. Evidence Verification"));
children.push(p("The verification layer is designed specifically to reduce hallucinations by re-checking every AI conclusion against the original evidence and applicable policy before it is presented as a finding."));
children.push(codeBlock([
"Initial AI Conclusion",
"        ↓",
"Retrieve Original Evidence",
"        ↓",
"Check Timestamp",
"        ↓",
"Check Relevant Frames",
"        ↓",
"Retrieve Applicable Policy",
"        ↓",
"Verify",
"        ↓",
"Verified / Partially Verified / Insufficient Evidence",
]));
children.push(p("If evidence is insufficient, the system is required to explicitly say so rather than guessing. For example:"));
children.push(quoteLine("The footage supports that a person entered the restricted area, but the person's authorization status cannot be confirmed from the available footage."));

// 11. VIDEO RAG
children.push(h1("11. Video RAG"));
children.push(p("Rather than passing an entire CCTV recording directly to an LLM — which is both expensive and imprecise — the system decomposes video into retrievable, semantically indexed units:"));
children.push(codeBlock([
"Large Video",
"    ↓",
"Scene Detection",
"    ↓",
"Relevant Clips",
"    ↓",
"Semantic Descriptions",
"    ↓",
"Embeddings",
"    ↓",
"Vector Database",
"    ↓",
"Natural Language Query",
"    ↓",
"Relevant Evidence",
"    ↓",
"Multimodal Reasoning",
]));
children.push(p("This makes long-form surveillance footage searchable by meaning rather than by manually scrubbing through a timeline."));

// 12. POLICY RAG
children.push(h1("12. Security Policy RAG"));
children.push(p("Policy documents (SOPs, restricted-area rules, emergency procedures, incident classification rules) are processed through a separate, parallel retrieval pipeline:"));
children.push(codeBlock([
"PDF / DOCX",
"    ↓",
"Text Extraction",
"    ↓",
"Chunking",
"    ↓",
"Embeddings",
"    ↓",
"Qdrant",
"    ↓",
"Policy Retrieval",
"    ↓",
"LLM Reasoning",
]));
children.push(p("Example investigative question answered via this pipeline:"));
children.push(quoteLine("Does entering this area violate the security policy?"));
children.push(p("The system retrieves the applicable policy passage before making its assessment, so policy conclusions are grounded in the organization's actual documented rules rather than generic assumptions."));

// 13. AGENT TOOLS
children.push(h1("13. Agent Tools"));
children.push(p("The Investigation Agent operates over a fixed set of callable tools, choosing the appropriate tool(s) depending on the user's question:"));
children.push(codeBlock([
"search_video()",
"search_person()",
"search_object()",
"search_event()",
"get_clip()",
"get_frame()",
"build_timeline()",
"search_policy()",
"verify_evidence()",
"generate_report()",
]));
children.push(table(
  ["Tool", "Purpose"],
  [
    ["search_video()", "Semantic search across indexed video segments"],
    ["search_person()", "Locate a specific person / description across footage"],
    ["search_object()", "Locate a specific object (e.g. bag, vehicle) across footage"],
    ["search_event()", "Locate a described event or activity"],
    ["get_clip()", "Retrieve a specific evidence clip by ID"],
    ["get_frame()", "Retrieve a specific evidence frame by ID"],
    ["build_timeline()", "Assemble a chronological sequence of related events"],
    ["search_policy()", "Retrieve relevant SOP / policy passages"],
    ["verify_evidence()", "Re-check a finding against original evidence and policy"],
    ["generate_report()", "Produce the structured incident report"],
  ],
  [2600, 6750]
));

// 14. TIMELINE
children.push(h1("14. Incident Timeline"));
children.push(p("The system automatically assembles a chronological timeline of related events from verified findings. Example:"));
children.push(codeBlock([
"10:41:52 — Person appears near entrance",
"10:42:17 — Person enters restricted area",
"10:42:31 — Person approaches equipment",
"10:43:08 — Person interacts with equipment",
"10:44:51 — Alarm detected",
"10:45:09 — Person exits",
]));
children.push(p("Each timeline event contains:"));
["Timestamp", "Description", "Evidence", "Confidence"].forEach((t) => children.push(bullet(t)));

// 15. REPORT
children.push(h1("15. Automated Incident Report"));
children.push(p("The final deliverable of an investigation is a structured incident report containing:"));
children.push(codeBlock([
"INCIDENT REPORT",
"",
"Incident ID",
"Date",
"Location",
"Camera",
"",
"1. Executive Summary",
"2. Incident Classification",
"3. Timeline",
"4. Persons / Objects Involved",
"5. Supporting Evidence",
"6. Policy Analysis",
"7. AI Findings",
"8. Confidence Scores",
"9. Unverified Claims",
"10. Recommendations",
]));
children.push(p("Every important claim in the report must be traceable back to specific evidence (a clip, frame, or timestamp)."));

// 16. PROJECT STRUCTURE
children.push(h1("16. Project Structure"));
children.push(p("Recommended repository layout for the implementation:"));
children.push(codeBlock([
"ai-forensic-investigation/",
"│",
"├── frontend/",
"│   ├── app/",
"│   ├── components/",
"│   ├── pages/",
"│   └── lib/",
"│",
"├── backend/",
"│   ├── app/",
"│   │   ├── api/",
"│   │   ├── agents/",
"│   │   ├── rag/",
"│   │   ├── video/",
"│   │   ├── vision/",
"│   │   ├── audio/",
"│   │   ├── reports/",
"│   │   ├── verification/",
"│   │   └── database/",
"│   └── requirements.txt",
"│",
"├── data/",
"│   ├── videos/",
"│   ├── clips/",
"│   ├── frames/",
"│   ├── policies/",
"│   └── reports/",
"│",
"├── models/",
"├── scripts/",
"├── tests/",
"│",
"├── docker-compose.yml",
"├── .env.example",
"└── README.md",
]));

// 17. ENV VARS
children.push(h1("17. Environment Variables"));
children.push(p("Create a .env file based on .env.example. Example configuration:"));
children.push(codeBlock([
"DATABASE_URL=",
"QDRANT_URL=",
"QDRANT_API_KEY=",
"",
"LLM_API_KEY=",
"EMBEDDING_API_KEY=",
"",
"MINIO_ENDPOINT=",
"MINIO_ACCESS_KEY=",
"MINIO_SECRET_KEY=",
"",
"WHISPER_MODEL=",
"YOLO_MODEL=",
]));
children.push(new Paragraph({
  spacing: { before: 100, after: 160 },
  children: [new TextRun({ text: "⚠ Never commit API keys or passwords to Git.", bold: true, color: "B00020", size: 22 })],
}));

// 18. RUNNING
children.push(h1("18. Running the Prototype"));
children.push(h2("18.1 Prerequisites"));
["Git", "Python 3.11+", "Node.js 20+", "Docker", "Docker Compose", "FFmpeg"].forEach((t) => children.push(bullet(t)));
children.push(p("A GPU is recommended for local computer-vision and multimodal model inference, but the prototype can use API-based models where appropriate."));

children.push(h2("18.2 Clone the Repository"));
children.push(codeBlock(["git clone <repository-url>", "cd ai-forensic-investigation"]));

children.push(h2("18.3 Start Infrastructure"));
children.push(codeBlock(["docker compose up -d"]));

children.push(h2("18.4 Backend Setup"));
children.push(codeBlock(["cd backend", "python -m venv .venv"]));
children.push(p("Activate the virtual environment:"));
children.push(codeBlock(["# Windows", ".venv\\Scripts\\activate", "", "# Linux/macOS", "source .venv/bin/activate"]));
children.push(p("Install dependencies and run the server:"));
children.push(codeBlock(["pip install -r requirements.txt", "uvicorn app.main:app --reload"]));

children.push(h2("18.5 Frontend Setup"));
children.push(codeBlock(["cd frontend", "npm install", "npm run dev"]));
children.push(p("The frontend will then be available through the local development URL shown by Next.js."));

// 19. DEMO
children.push(h1("19. Prototype Demo Walkthrough"));
children.push(p("Use a controlled or public-domain CCTV-style sample video for demonstration. Suggested demo script:"));
[
  "Login.",
  "Open Dashboard.",
  "Upload CCTV video.",
  "Enter camera metadata.",
  "Start processing.",
  "Wait for indexing.",
  "Open Investigation Workspace.",
  "Ask: \u201CFind all suspicious activity in this video.\u201D",
  "Review retrieved evidence.",
  "Ask: \u201CWhen did the person enter the restricted area?\u201D",
  "Ask: \u201CWas this a policy violation?\u201D",
  "Review retrieved security policy.",
  "Run evidence verification.",
  "Generate timeline.",
  "Generate final incident report.",
].forEach((t) => children.push(numbered(t)));

// 20. EVALUATION
children.push(h1("20. Evaluation Plan"));
children.push(p("The project should be evaluated using a labelled test set containing, for each test case: a query, the expected event, the expected timestamp, the relevant clip, and the expected answer."));
children.push(h2("20.1 Retrieval Metrics"));
["Recall@5", "Recall@10", "Precision@5", "Mean Reciprocal Rank (MRR)"].forEach((t) => children.push(bullet(t)));
children.push(h2("20.2 Temporal Metrics"));
["Timestamp error", "Temporal Intersection-over-Union (IoU)"].forEach((t) => children.push(bullet(t)));
children.push(h2("20.3 RAG Metrics"));
["Context relevance", "Context recall", "Answer faithfulness"].forEach((t) => children.push(bullet(t)));
children.push(h2("20.4 Generation Metrics"));
["Factual accuracy", "Report completeness", "Hallucination rate"].forEach((t) => children.push(bullet(t)));
children.push(h2("20.5 System Metrics"));
["Video processing time", "Query response latency"].forEach((t) => children.push(bullet(t)));

// 21. ROADMAP
children.push(h1("21. Development Roadmap"));
const phases = [
  ["Phase 1 — Foundation", ["Next.js frontend", "FastAPI backend", "PostgreSQL", "Docker", "Authentication"]],
  ["Phase 2 — Video", ["Video upload", "MinIO storage", "FFmpeg processing", "Scene detection", "Video player"]],
  ["Phase 3 — Computer Vision", ["YOLO integration", "Object detection", "Tracking", "Event metadata"]],
  ["Phase 4 — GenAI", ["VLM integration", "Clip descriptions", "Embeddings", "Qdrant", "Video RAG"]],
  ["Phase 5 — Agent", ["LangGraph", "Investigation agent", "Tool calling", "Investigation workflow"]],
  ["Phase 6 — Policy RAG", ["Policy upload", "Document processing", "Policy embeddings", "Policy retrieval", "Policy reasoning"]],
  ["Phase 7 — Verification", ["Evidence verification", "Confidence scoring", "Uncertainty handling", "Hallucination mitigation"]],
  ["Phase 8 — Reporting", ["Timeline generation", "Structured report", "PDF export", "Evidence references"]],
  ["Phase 9 — Evaluation", ["Test dataset", "Retrieval evaluation", "RAG evaluation", "Generation evaluation", "Performance evaluation"]],
];
phases.forEach(([title, items]) => {
  children.push(h2(title));
  children.push(...checklist(items));
});

// 22. MVP & FINAL
children.push(h1("22. Scope Definitions"));
children.push(h2("22.1 Minimum Viable Product (MVP)"));
children.push(p("The minimum working prototype should implement the following core loop:"));
children.push(codeBlock([
"Video Upload",
"     ↓",
"Video Processing",
"     ↓",
"Object/Event Analysis",
"     ↓",
"Semantic Clip Descriptions",
"     ↓",
"Embeddings",
"     ↓",
"Qdrant",
"     ↓",
"Natural Language Video Search",
"     ↓",
"Evidence Retrieval",
"     ↓",
"Grounded Report",
]));

children.push(h2("22.2 Final Prototype"));
children.push(p("The complete prototype should implement all of the following combined:"));
[
  "CCTV Video", "Audio", "Vision", "Video RAG", "Security Policy RAG",
  "Investigation Agent", "Tool Calling", "Evidence Verification",
  "Timeline Reasoning", "Grounded Report Generation",
].forEach((t) => children.push(bullet(t)));

// 23. DESIGN PRINCIPLES
children.push(h1("23. Design Principles"));
const principles = [
  ["Evidence First", "AI conclusions must be connected to supporting evidence."],
  ["No Fabricated Evidence", "The system must not invent timestamps, people, objects, or events."],
  ["Explicit Uncertainty", "When evidence is insufficient, the system should say so."],
  ["Modular AI", "Computer vision, retrieval, reasoning, verification, and reporting should be separate components."],
  ["Prototype First", "Prioritize an end-to-end working workflow over unnecessary production infrastructure."],
];
principles.forEach(([t, d]) => {
  children.push(h3(t));
  children.push(p(d));
});

// 24. OUT OF SCOPE
children.push(h1("24. Out of Scope"));
children.push(p("The prototype will not focus on:"));
[
  "Real-time production CCTV monitoring",
  "Large-scale multi-camera deployment",
  "Custom training of an LLM",
  "Kubernetes",
  "Enterprise IAM",
  "Mobile application",
  "Production facial-recognition infrastructure",
  "Fully autonomous real-world security decisions",
].forEach((t) => children.push(bullet(t)));
children.push(p("The system is an investigation assistance prototype, not a replacement for human security personnel."));

// 25. EXPECTED OUTCOME
children.push(h1("25. Expected Outcome"));
children.push(p("At the end of the project, a user should be able to upload surveillance footage and ask:"));
children.push(quoteLine("\u201CWhat happened, when did it happen, what evidence supports it, did it violate policy, and generate the incident report.\u201D"));
children.push(p("The system should answer with:"));
[
  "Natural-language explanation", "Relevant clips", "Relevant frames", "Exact timestamps",
  "Incident timeline", "Policy evidence", "Confidence", "Verification status", "Structured incident report",
].forEach((t) => children.push(bullet(t)));

// 26. PROJECT VALUE
children.push(h1("26. Project Value"));
children.push(p("This project demonstrates a complete modern GenAI application rather than a single AI model. It combines computer vision, multimodal AI, RAG, Video RAG, vector search, LLM reasoning, agentic AI, tool calling, knowledge RAG, evidence verification, and structured generation."));
children.push(p("The primary academic goal is to demonstrate how GenAI can transform large, unstructured surveillance footage into an interactive, searchable, and evidence-grounded investigation system."));

// 27. GLOSSARY
children.push(h1("27. Glossary"));
children.push(table(
  ["Term", "Definition"],
  [
    ["RAG", "Retrieval-Augmented Generation — grounding LLM output in retrieved documents/data"],
    ["Video RAG", "RAG applied to indexed, embedded video segments instead of text documents"],
    ["VLM", "Vision-Language Model — a model that jointly reasons over images/video and text"],
    ["Embedding", "A numerical vector representation of data used for semantic similarity search"],
    ["Vector Database", "A database optimized for storing and searching embeddings (e.g. Qdrant)"],
    ["Agentic AI", "An AI system that autonomously plans and calls tools to complete a task"],
    ["Grounding", "Tying an AI-generated claim to a specific, verifiable piece of evidence"],
    ["Hallucination", "A confident but false or unsupported statement generated by an AI model"],
    ["Temporal IoU", "Intersection-over-Union applied to time intervals, used to score timestamp accuracy"],
    ["SOP", "Standard Operating Procedure — an organization's documented security policy"],
  ],
  [2300, 7050]
));

// ---------- assemble document ----------
const doc = new Document({
  creator: "AI Forensic Investigation System — Capstone Team",
  title: "AI Forensic Investigation System — Project Documentation",
  description: "Full project documentation for the GenAI Capstone: AI Forensic Investigation System",
  numbering: {
    config: [
      {
        reference: "bullet-list",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 400, hanging: 260 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 800, hanging: 260 } } } },
        ],
      },
      {
        reference: "num-list",
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 420, hanging: 300 } } } },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 }, // US Letter
          margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
              border: { bottom: { color: "BFBFBF", space: 4, style: BorderStyle.SINGLE, size: 4 } },
              children: [
                new TextRun({ text: "AI Forensic Investigation System", size: 16, color: GREY }),
                new TextRun({ text: "\tProject Documentation", size: 16, color: GREY }),
              ],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [
                new TextRun({ text: "Page ", size: 16, color: GREY }),
                new TextRun({ children: [PageNumber.CURRENT], size: 16, color: GREY }),
                new TextRun({ text: " of ", size: 16, color: GREY }),
                new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: GREY }),
              ],
            }),
          ],
        }),
      },
      children,
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync("/home/claude/docgen/AI_Forensic_Investigation_System_Documentation.docx", buffer);
  console.log("written");
});