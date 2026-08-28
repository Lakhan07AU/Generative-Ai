from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.database.models import Camera, User
from app.schemas.video import CameraCreate, CameraOut
from app.auth.deps import get_current_user, require_roles
from app.audit.service import record_audit

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=list[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Camera).order_by(Camera.id).all()


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles("ADMIN", "SECURITY_OFFICER", "INVESTIGATOR")),
):
    camera = Camera(
        camera_name=payload.camera_name,
        location=payload.location,
        description=payload.description,
        created_by_user_id=current_user.id,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    record_audit(db, "camera_create", user_id=current_user.id, entity_type="camera", entity_id=camera.id)
    return camera


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera
