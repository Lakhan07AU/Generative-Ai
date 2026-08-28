import io
import uuid
from minio import Minio
from minio.error import S3Error

from app.core.config import settings


class StorageService:
    """Wrapper around MinIO (S3-compatible) object storage.

    Buckets:
      - videos: original immutable uploads
      - clips: extracted clip segments
      - frames: extracted keyframes
      - thumbnails: clip/probe thumbnails
    """

    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.buckets = {
            "videos": settings.MINIO_BUCKET_VIDEOS,
            "clips": settings.MINIO_BUCKET_CLIPS,
            "frames": settings.MINIO_BUCKET_FRAMES,
            "thumbnails": settings.MINIO_BUCKET_THUMBNAILS,
            "policies": settings.MINIO_BUCKET_POLICIES,
            "reports": settings.MINIO_BUCKET_REPORTS,
        }

    def ensure_buckets(self) -> None:
        for bucket in self.buckets.values():
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)

    def put_bytes(self, bucket_key: str, data: bytes, object_name: str, content_type: str = "application/octet-stream", lock: bool = False) -> str:
        """Upload bytes. Returns storage path like bucket/object."""
        bucket = self.buckets[bucket_key]
        obj = object_name
        self.client.put_object(
            bucket,
            obj,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        if lock:
            try:
                self.client.enable_object_retention(bucket, obj, mode="COMPLIANCE")
            except Exception:
                pass
        return f"{bucket}/{obj}"

    def put_file(self, bucket_key: str, local_path: str, object_name: str, content_type: str = "application/octet-stream", lock: bool = False) -> str:
        import os
        size = os.path.getsize(local_path)
        with open(local_path, "rb") as f:
            self.client.put_object(
                self.buckets[bucket_key],
                object_name,
                f,
                length=size,
                content_type=content_type,
            )
        if lock:
            try:
                self.client.enable_object_retention(self.buckets[bucket_key], object_name, mode="COMPLIANCE")
            except Exception:
                pass
        return f"{self.buckets[bucket_key]}/{object_name}"

    def get_bytes(self, storage_path: str) -> bytes:
        bucket, _, obj = storage_path.partition("/")
        response = self.client.get_object(bucket, obj)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, storage_path: str) -> bool:
        bucket, _, obj = storage_path.partition("/")
        try:
            return self.client.stat_object(bucket, obj) is not None
        except S3Error:
            return False

    def presigned_url(self, storage_path: str, expires_seconds: int = 3600) -> str:
        bucket, sep, obj = storage_path.partition("/")
        if not sep:
            return storage_path
        try:
            return self.client.presigned_get_object(bucket, obj, expires=timedelta_seconds(expires_seconds))
        except S3Error:
            return ""

    def unique_name(self, prefix: str, ext: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}{ext}"


def timedelta_seconds(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


storage = StorageService()
