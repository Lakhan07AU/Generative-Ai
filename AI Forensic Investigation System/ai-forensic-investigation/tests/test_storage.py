import io

from helpers import minio_available


@minio_available
def test_minio_buckets_exist():
    from app.storage.service import storage

    storage.ensure_buckets()
    names = {b.name for b in storage.client.list_buckets()}
    for bucket in storage.buckets.values():
        assert bucket in names


@minio_available
def test_put_and_get_bytes():
    from app.storage.service import storage

    storage.ensure_buckets()
    data = b"hello forensic payload"
    path = storage.put_bytes("frames", data, "unit-test-frame.jpg", content_type="image/jpeg")
    assert path
    got = storage.get_bytes(path)
    assert got == data


@minio_available
def test_presigned_url_generation():
    from app.storage.service import storage

    storage.ensure_buckets()
    path = storage.put_bytes("thumbnails", b"thumb", "unit-test-thumb.jpg", content_type="image/jpeg")
    url = storage.presigned_url(path)
    assert url and url.startswith("http")
