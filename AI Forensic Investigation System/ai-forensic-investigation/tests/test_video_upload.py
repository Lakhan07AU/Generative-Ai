import os
import io

from helpers import make_test_video, minio_available


def test_upload_rejects_invalid_extension(client, auth_headers):
    res = client.post(
        "/videos/upload",
        headers=auth_headers,
        files={"file": ("evil.pdf", io.BytesIO(b"not a video"), "application/pdf")},
        data={},
    )
    assert res.status_code == 400


def test_upload_requires_auth(client):
    res = client.post(
        "/videos/upload",
        files={"file": ("x.mp4", io.BytesIO(b"x"), "video/mp4")},
        data={},
    )
    assert res.status_code in (401, 403)


@minio_available
def test_upload_success(client, auth_headers, tmp_path):
    video = make_test_video(str(tmp_path / "upload.mp4"), duration_sec=1.0)
    with open(video, "rb") as f:
        res = client.post(
            "/videos/upload",
            headers=auth_headers,
            files={"file": ("upload.mp4", f, "video/mp4")},
            data={"camera_name": "CAM-01", "location": "Lobby"},
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["processing_job_id"]
    assert body["status"] == "UPLOADED"


@minio_available
def test_original_video_immutable_in_minio(client, auth_headers, tmp_path, db):
    """Verify the uploaded original resides in MinIO videos bucket."""
    from app.storage.service import storage
    from app.database.models import Video

    video = make_test_video(str(tmp_path / "orig.mp4"), duration_sec=1.0)
    with open(video, "rb") as f:
        res = client.post(
            "/videos/upload",
            headers=auth_headers,
            files={"file": ("orig.mp4", f, "video/mp4")},
            data={"camera_name": "CAM-02", "location": "Lobby"},
        )
    assert res.status_code == 201, res.text
    vid = res.json()["video_id"]

    v = db.query(Video).filter(Video.id == vid).first()
    assert v is not None
    assert v.storage_path.startswith(storage.buckets["videos"])
    assert storage.exists(v.storage_path)
