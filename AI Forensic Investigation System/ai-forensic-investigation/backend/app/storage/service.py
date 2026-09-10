import io
import os
import uuid
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

USE_LOCAL_STORAGE = True  # Set to False when MinIO is available


class LocalStorageService:
    """Local filesystem storage fallback when MinIO is not available."""

    def __init__(self):
        self.base_dir = os.path.join(settings.DATA_DIR, "storage")
        os.makedirs(self.base_dir, exist_ok=True)
        self.buckets = {
            "videos": "videos",
            "clips": "clips",
            "frames": "frames",
            "thumbnails": "thumbnails",
            "policies": "policies",
            "reports": "reports",
        }

    def ensure_buckets(self) -> None:
        for bucket in self.buckets.values():
            os.makedirs(os.path.join(self.base_dir, bucket), exist_ok=True)

    def _local_path(self, bucket_key: str, object_name: str) -> str:
        bucket = self.buckets.get(bucket_key, bucket_key)
        full_dir = os.path.join(self.base_dir, bucket)
        os.makedirs(full_dir, exist_ok=True)
        return os.path.join(full_dir, object_name)

    def put_bytes(self, bucket_key: str, data: bytes, object_name: str, content_type: str = "application/octet-stream", lock: bool = False) -> str:
        path = self._local_path(bucket_key, object_name)
        with open(path, "wb") as f:
            f.write(data)
        bucket = self.buckets.get(bucket_key, bucket_key)
        return f"{bucket}/{object_name}"

    def put_file(self, bucket_key: str, local_path: str, object_name: str, content_type: str = "application/octet-stream", lock: bool = False) -> str:
        import shutil
        dest = self._local_path(bucket_key, object_name)
        shutil.copy2(local_path, dest)
        bucket = self.buckets.get(bucket_key, bucket_key)
        return f"{bucket}/{object_name}"

    def get_bytes(self, storage_path: str) -> bytes:
        bucket, _, obj = storage_path.partition("/")
        path = os.path.join(self.base_dir, bucket, obj)
        with open(path, "rb") as f:
            return f.read()

    def exists(self, storage_path: str) -> bool:
        bucket, _, obj = storage_path.partition("/")
        path = os.path.join(self.base_dir, bucket, obj)
        return os.path.exists(path)

    def presigned_url(self, storage_path: str, expires_seconds: int = 3600) -> str:
        return storage_path

    def unique_name(self, prefix: str, ext: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}{ext}"


def _create_storage():
    global USE_LOCAL_STORAGE
    try:
        from minio import Minio
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.list_buckets()
        USE_LOCAL_STORAGE = False

        class MinIOStorageService:
            def __init__(self, client):
                self.client = client
                self.buckets = {
                    "videos": settings.MINIO_BUCKET_VIDEOS,
                    "clips": settings.MINIO_BUCKET_CLIPS,
                    "frames": settings.MINIO_BUCKET_FRAMES,
                    "thumbnails": settings.MINIO_BUCKET_THUMBNAILS,
                    "policies": settings.MINIO_BUCKET_POLICIES,
                    "reports": settings.MINIO_BUCKET_REPORTS,
                }

            def ensure_buckets(self):
                for bucket in self.buckets.values():
                    if not self.client.bucket_exists(bucket):
                        self.client.make_bucket(bucket)

            def put_bytes(self, bucket_key, data, object_name, content_type="application/octet-stream", lock=False):
                bucket = self.buckets[bucket_key]
                self.client.put_object(bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
                return f"{bucket}/{object_name}"

            def put_file(self, bucket_key, local_path, object_name, content_type="application/octet-stream", lock=False):
                import os as _os
                size = _os.path.getsize(local_path)
                with open(local_path, "rb") as f:
                    self.client.put_object(self.buckets[bucket_key], object_name, f, length=size, content_type=content_type)
                return f"{self.buckets[bucket_key]}/{object_name}"

            def get_bytes(self, storage_path):
                bucket, _, obj = storage_path.partition("/")
                response = self.client.get_object(bucket, obj)
                try:
                    return response.read()
                finally:
                    response.close()
                    response.release_conn()

            def exists(self, storage_path):
                from minio.error import S3Error
                bucket, _, obj = storage_path.partition("/")
                try:
                    return self.client.stat_object(bucket, obj) is not None
                except S3Error:
                    return False

            def presigned_url(self, storage_path, expires_seconds=3600):
                from datetime import timedelta
                bucket, sep, obj = storage_path.partition("/")
                if not sep:
                    return storage_path
                from minio.error import S3Error
                try:
                    return self.client.presigned_get_object(bucket, obj, expires=timedelta(seconds=expires_seconds))
                except S3Error:
                    return ""

            def unique_name(self, prefix, ext):
                return f"{prefix}-{uuid.uuid4().hex[:12]}{ext}"

        return MinIOStorageService(client)
    except Exception as exc:
        logger.warning("MinIO not available, using local filesystem storage: %s", exc)
        USE_LOCAL_STORAGE = True
        return LocalStorageService()


storage = _create_storage()
