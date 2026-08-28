"""LangChain tool registry for the investigation agent (Part 3).

Tools wrap the read-only evidence repository and expose them with a uniform
`invoke(db, **args) -> dict` contract. Tool arguments are validated against a
simple JSON schema so invalid arguments are caught before execution.
"""

from __future__ import annotations

from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.agents import evidence_repo as repo
from app.agents.guardrails import ALLOWED_TOOLS


class Tool:
    def __init__(self, name: str, description: str, params: dict, fn: Callable):
        self.name = name
        self.description = description
        self.params = params  # {"arg": {"type": ..., "required": ...}}
        self._fn = fn

    def validate(self, args: dict) -> dict:
        cleaned: dict = {}
        for arg, spec in self.params.items():
            if arg in args:
                cleaned[arg] = args[arg]
            elif spec.get("required"):
                raise ValueError(f"tool '{self.name}' missing required argument '{arg}'")
            # optional args default to None
        # reject unknown arguments (invalid tool argument)
        unknown = set(args) - set(self.params)
        if unknown:
            raise ValueError(f"tool '{self.name}' received unknown argument(s): {sorted(unknown)}")
        return cleaned

    def invoke(self, db: Session, args: dict) -> dict:
        cleaned = self.validate(args)
        return self._fn(db, cleaned)


def _search_video(db: Session, args: dict) -> dict:
    return repo.search_video(
        db,
        args.get("query", ""),
        video_id=args.get("video_id"),
        camera_id=args.get("camera_id"),
    )


def _search_person(db: Session, args: dict) -> dict:
    return {"results": repo.search_person(db, camera_id=args.get("camera_id"), limit=args.get("limit", 5))}


def _search_object(db: Session, args: dict) -> dict:
    return {"results": repo.search_object(db, args.get("label", ""), camera_id=args.get("camera_id"), limit=args.get("limit", 5))}


def _search_event(db: Session, args: dict) -> dict:
    return {"results": repo.search_event(
        db,
        event_type=args.get("event_type"),
        video_id=args.get("video_id"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        limit=args.get("limit", 20),
    )}


def _get_clip(db: Session, args: dict) -> dict:
    return repo.get_clip_data(db, args["clip_id"])


def _get_frame(db: Session, args: dict) -> dict:
    return repo.get_frame_data(
        db,
        args["video_id"],
        frame_number=args.get("frame_number"),
        timestamp=args.get("timestamp"),
    )


def _search_policy(db: Session, args: dict) -> dict:
    return {"results": repo.search_policy(db, args.get("query", ""), limit=args.get("limit", 5))}


def _build_timeline(db: Session, args: dict) -> dict:
    events = repo.build_timeline(
        db,
        video_id=args.get("video_id"),
        start_time=args.get("start_time"),
        end_time=args.get("end_time"),
        limit=args.get("limit"),
    )
    return {"events": events, "count": len(events)}


def _verify_evidence(db: Session, args: dict) -> dict:
    from app.verification.service import verify_claim

    res = verify_claim(
        db,
        claim_text=args.get("claim_text", ""),
        investigation_id=args.get("investigation_id"),
        video_id=args.get("video_id"),
        timestamp=args.get("timestamp"),
        persist=False,
    )
    return res


TOOLS: dict[str, Tool] = {}


def _register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


_register(Tool(
    "search_video",
    "Run a natural-language search over indexed video evidence and return supporting clips, "
    "grounding them in the RAG engine. Use for broad questions about what the footage shows.",
    {
        "query": {"type": "string", "required": True},
        "video_id": {"type": "integer", "required": False},
        "camera_id": {"type": "integer", "required": False},
    },
    _search_video,
))

_register(Tool(
    "search_person",
    "Find clips where a person is detectable, grouped by tracking identifier. "
    "Never attempts identity attribution.",
    {
        "camera_id": {"type": "integer", "required": False},
        "limit": {"type": "integer", "required": False},
    },
    _search_person,
))

_register(Tool(
    "search_object",
    "Find clips/detections containing a specific object label (e.g. car, van, bag, bicycle).",
    {
        "label": {"type": "string", "required": True},
        "camera_id": {"type": "integer", "required": False},
        "limit": {"type": "integer", "required": False},
    },
    _search_object,
))

_register(Tool(
    "search_event",
    "Search recorded typed events (e.g. entered, left, alarm) within optional time bounds.",
    {
        "event_type": {"type": "string", "required": False},
        "video_id": {"type": "integer", "required": False},
        "start_time": {"type": "number", "required": False},
        "end_time": {"type": "number", "required": False},
        "limit": {"type": "integer", "required": False},
    },
    _search_event,
))

_register(Tool(
    "get_clip",
    "Fetch full detail for a single clip by database id, including detections and frames.",
    {"clip_id": {"type": "integer", "required": True}},
    _get_clip,
))

_register(Tool(
    "get_frame",
    "Fetch frame-level detection evidence for a video by frame number or source timestamp.",
    {
        "video_id": {"type": "integer", "required": True},
        "frame_number": {"type": "integer", "required": False},
        "timestamp": {"type": "number", "required": False},
    },
    _get_frame,
))

_register(Tool(
    "search_policy",
    "Retrieve relevant security policy sections verbatim. Policy text is never invented.",
    {
        "query": {"type": "string", "required": True},
        "limit": {"type": "integer", "required": False},
    },
    _search_policy,
))

_register(Tool(
    "build_timeline",
    "Build an evidence-backed chronological timeline of events and detections.",
    {
        "video_id": {"type": "integer", "required": False},
        "start_time": {"type": "number", "required": False},
        "end_time": {"type": "number", "required": False},
        "limit": {"type": "integer", "required": False},
    },
    _build_timeline,
))

_register(Tool(
    "verify_evidence",
    "Decompose a claim and verify it against available evidence, producing a "
    "VERIFIED / PARTIALLY_VERIFIED / INSUFFICIENT_EVIDENCE result.",
    {
        "claim_text": {"type": "string", "required": True},
        "investigation_id": {"type": "integer", "required": False},
        "video_id": {"type": "integer", "required": False},
        "timestamp": {"type": "number", "required": False},
    },
    _verify_evidence,
))

assert set(TOOLS.keys()) == set(ALLOWED_TOOLS), "tool registry mismatch with allowlist"


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)
