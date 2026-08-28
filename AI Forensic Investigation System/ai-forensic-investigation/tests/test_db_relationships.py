"""Tests for database relationships and the audit log."""

from app.database.models import User, Camera, Video, Clip, Detection, Event, ProcessingJob, AuditLog


def test_user_camera_video_relationship(db):
    user = User(email="rel@test.com", name="Rel", password_hash="x", role="ADMIN")
    db.add(user)
    db.flush()

    cam = Camera(camera_name="CAM-R", location="Lab", created_by_user_id=user.id)
    db.add(cam)
    db.flush()

    video = Video(
        filename="clip.mp4",
        storage_path="forensics-videos/obj",
        camera_id=cam.id,
        uploaded_by_user_id=user.id,
        status="UPLOADED",
    )
    db.add(video)
    db.flush()

    job = ProcessingJob(video_id=video.id, status="QUEUED")
    db.add(job)
    db.flush()

    clip = Clip(
        public_id="CLIP-0001",
        video_id=video.id,
        camera_id=cam.id,
        start_time=0.0,
        end_time=5.0,
    )
    db.add(clip)
    db.flush()

    detection = Detection(
        clip_id=clip.id,
        video_id=video.id,
        camera_id=cam.id,
        label="person",
        bounding_box="[0,0,10,10]",
        timestamp=2.5,
        detection_confidence=0.9,
        tracking_id="person-001",
    )
    event = Event(video_id=video.id, clip_id=clip.id, event_type="person_present", start_time=0.0)
    db.add(detection)
    db.add(event)
    db.commit()

    db.refresh(video)
    assert video.camera.camera_name == "CAM-R"
    assert video.uploaded_by.email == "rel@test.com"
    assert len(video.processing_jobs) == 1
    assert len(video.clips) == 1
    assert video.clips[0].detections[0].tracking_id == "person-001"
    assert video.events[0].event_type == "person_present"
    # Reverse relationships
    assert video.clips[0].camera.camera_name == "CAM-R"


def test_processing_job_video_relationship(db):
    video = Video(filename="j.mp4", storage_path="b/o", status="QUEUED")
    db.add(video)
    db.flush()
    job = ProcessingJob(video_id=video.id, status="PROCESSING", stage="METADATA", progress=10.0)
    db.add(job)
    db.commit()
    db.refresh(job)
    assert job.video.id == video.id
    assert job.video.status == "QUEUED"


def test_audit_log_recording(db):
    from app.audit.service import record_audit

    entry = record_audit(
        db,
        action="login",
        user_id=1,
        entity_type="user",
        entity_id=1,
        details="unit-test-unique-marker",
    )
    assert entry.action == "login"
    db.expire_all()
    # Filter on the unique marker so shared-DB state from other tests cannot collide
    fetched = (
        db.query(AuditLog)
        .filter(AuditLog.details == "unit-test-unique-marker")
        .first()
    )
    assert fetched is not None
    assert fetched.user_id == 1
