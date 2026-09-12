"""Phase 7 - case camera scoping.

Derives the investigation's camera scope exactly like Phase 6 does
(investigation -> bound video -> camera) so the agent can
only ever retrieve evidence from cameras inside the case. Evidence from any
other camera is unreachable by construction.
"""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app.database import models
from app.database.models import Investigation
from app.investigation.retrieval import camera_names as _camera_names


def case_camera_ids(db: Session, investigation_id: int) -> List[int]:
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if inv is None or inv.video_id is None:
        return []
    video = db.query(models.Video).filter(models.Video.id == inv.video_id).first()
    if video is None or video.camera_id is None:
        return []
    return [int(video.camera_id)]


def case_camera_names(db: Session, camera_ids: List[int]) -> Dict[int, str]:
    return _camera_names(db, camera_ids)