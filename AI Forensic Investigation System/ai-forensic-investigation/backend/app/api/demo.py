"""Demo Investigation Dataset API.

Exposes the demo dataset manifest, videos, scenarios, thumbnail images, cases
and per-video processing status for the frontend demo mode. All responses
clearly label data as DEMO DATA.
"""

import json
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.core.config import settings

router = APIRouter(tags=["demo"])

DEMO_ROOT = os.path.abspath(settings.DEMO_DATA_DIR)

DISCLAIMER = "DEMO DATA — NOT REAL FORENSIC EVIDENCE"


def _load_json(relative_path: str) -> dict | list:
    path = os.path.join(DEMO_ROOT, relative_path)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Demo file not found: {relative_path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _abs(root: str, rel: str) -> str:
    path = os.path.join(root, rel)
    if not os.path.isfile(path):
        return ""
    return path


def _video_status(video_filename: str) -> dict:
    """Look up processing status from the DB for an uploaded demo video."""
    try:
        from app.database.session import SessionLocal
        from app.database.models import Video
        import sqlalchemy as sa

        db = SessionLocal()
        try:
            row = (
                db.execute(
                    sa.select(Video).where(
                        sa.or_(Video.filename == video_filename, Video.storage_path.ilike(f"%{video_filename}"))
                    )
                )
                .scalars()
                .first()
            )
            if row is None:
                return {"uploaded": False, "status": "NOT_UPLOADED", "video_id": None}
            return {
                "uploaded": True,
                "status": row.status,
                "video_id": row.id,
            }
        finally:
            db.close()
    except Exception:
        # DB/infra unavailable — report unknown status rather than fail the API.
        return {"uploaded": None, "status": "UNKNOWN", "video_id": None}


@router.get("/demo/disclaimer")
def demo_disclaimer():
    return {"disclaimer": DISCLAIMER, "dataset_root": DEMO_ROOT}


@router.get("/demo/dataset")
def demo_dataset():
    """Return the demo manifest with absolute local file paths + DB status."""
    manifest = _load_json("metadata/manifest.json")
    for v in manifest.get("videos", []):
        v["abs_path"] = os.path.join(DEMO_ROOT, v.get("path", ""))
        v["thumbnail_path"] = os.path.join(DEMO_ROOT, f"thumbnails/{v.get('demo_id')}.jpg")
        v.update(_video_status(v.get("filename", "")))
    for k in manifest.get("keyframes", []):
        k["abs_path"] = os.path.join(DEMO_ROOT, k.get("path", ""))
    for f in manifest.get("fixtures", []):
        f["abs_path"] = os.path.join(DEMO_ROOT, f.get("path", ""))
    for t in manifest.get("thumbnails", []):
        t["abs_path"] = os.path.join(DEMO_ROOT, t.get("path", ""))
    return manifest


@router.get("/demo/scenarios")
def demo_scenarios():
    """List all 12 demo scenario definitions (with backing demo videos)."""
    scenarios = []
    if not os.path.isdir(os.path.join(DEMO_ROOT, "scenarios")):
        return scenarios
    for name in sorted(os.listdir(os.path.join(DEMO_ROOT, "scenarios"))):
        if not name.endswith(".json"):
            continue
        path = os.path.join(DEMO_ROOT, "scenarios", name)
        with open(path, "r", encoding="utf-8") as fh:
            scenarios.append(json.load(fh))
    return scenarios


@router.get("/demo/scenarios/{scenario_id}")
def demo_scenario(scenario_id: str):
    path = os.path.join(DEMO_ROOT, "scenarios", f"{scenario_id}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Scenario not found: {scenario_id}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/demo/thumbnails/{demo_id}.jpg")
def demo_thumbnail(demo_id: str):
    """Serve a demo video thumbnail image."""
    path = os.path.join(DEMO_ROOT, "thumbnails", f"{demo_id}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Thumbnail not found: {demo_id}")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/demo/videos/{demo_id}/keyframe/{index}.jpg")
def demo_keyframe(demo_id: str, index: int):
    """Serve a demo keyframe image (used for video selector previews)."""
    path = os.path.join(DEMO_ROOT, "images", f"keyframe_{demo_id}_{index}.jpg")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Keyframe not found: {demo_id}/{index}")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/demo/cases")
def demo_cases():
    return _load_json("cases.json")


@router.get("/demo/cases/{case_id}")
def demo_case(case_id: str):
    cases = _load_json("cases.json")
    for c in cases:
        if c.get("case_id") == case_id:
            return c
    raise HTTPException(status_code=404, detail=f"Case not found: {case_id}")


@router.get("/demo/investigation_queries/{scenario_id}")
def demo_investigation_queries(scenario_id: str):
    """Return the ungrounded / grounded / UNKNOWN query set for a scenario."""
    path = os.path.join(DEMO_ROOT, "investigation_queries", f"{scenario_id}.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Query set not found: {scenario_id}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)