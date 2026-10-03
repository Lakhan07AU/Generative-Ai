"""Phase 9 - production-hardening verification tests.

Machine-verifiable checks for the Phase 9 audit actions:

  * credential brute-force protection (sliding-window login rate limit)
  * detailed /health + /metrics operational endpoints
  * vector-store backend honesty (backend_name / clear / point_exists on the
    deterministic in-memory fallback)
  * object-storage backend naming + clear_buckets on an isolated temp instance
  * demo-database reset helper logic (SQLite path removal + URL precedence)
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

# ---------------------------------------------------------------------------
# Credential rate limiting
# ---------------------------------------------------------------------------


def test_login_brute_force_is_blocked_then_allowed_per_identity(client):
    from app.api import auth as auth_api
    from app.auth.rate_limit import SlidingWindowRateLimiter

    auth_api._login_limiter = SlidingWindowRateLimiter(max_attempts=2, window_seconds=60.0)

    email = "bruteforce@test.com"
    res = client.post(
        "/auth/register",
        json={"email": email, "name": "Brute", "password": "password123", "role": "INVESTIGATOR"},
    )
    assert res.status_code == 201, res.text

    for _ in range(2):
        res = client.post("/auth/login", json={"email": email, "password": "wrongpass"})
        assert res.status_code == 401, res.text

    # Locked out even with the correct password, and a Retry-After header is set.
    res = client.post("/auth/login", json={"email": email, "password": "wrongpass"})
    assert res.status_code == 429, res.text
    assert "retry-after" in {k.lower() for k in res.headers.keys()}
    res = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert res.status_code == 429, "correct password must still be rate-limited while locked"

    # A different identity (per IP:email bucket) is unaffected.
    email2 = "bruteforce2@test.com"
    client.post(
        "/auth/register",
        json={"email": email2, "name": "Brute2", "password": "password123", "role": "INVESTIGATOR"},
    )
    res = client.post("/auth/login", json={"email": email2, "password": "password123"})
    assert res.status_code == 200, res.text


def test_rate_limiter_reset_on_success(client):
    from app.api import auth as auth_api
    from app.auth.rate_limit import SlidingWindowRateLimiter

    auth_api._login_limiter = SlidingWindowRateLimiter(max_attempts=5, window_seconds=60.0)
    email = "retry@test.com"
    client.post(
        "/auth/register",
        json={"email": email, "name": "Retry", "password": "password123", "role": "INVESTIGATOR"},
    )

    for _ in range(5):
        assert client.post("/auth/login", json={"email": email, "password": "wrongpass"}).status_code == 401
    # locked
    assert client.post("/auth/login", json={"email": email, "password": "password123"}).status_code == 429

    # The bucket locks on the 5th failure; the lock expires once the window slides
    # past all recorded failures (self-pruning), and reset() is admission again.
    limiter = auth_api._login_limiter
    ident = f"login:testclient:{email}"
    assert limiter.check(ident) is False
    bucket = limiter._buckets[ident]
    assert bucket.locked_until > 0.0
    # Simulate the window sliding past every failure.
    bucket.locked_until = 0.0
    bucket.hits.clear()
    assert limiter.check(ident) is True
    limiter.reset(ident)
    assert ident not in limiter._buckets
    assert limiter.check(ident) is True


# ---------------------------------------------------------------------------
# Health + metrics
# ---------------------------------------------------------------------------


def test_health_reports_all_components(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("ok", "degraded")
    for component in ("database", "qdrant", "storage", "evidence_indexer", "live"):
        assert component in data["components"], data


def test_metrics_is_prometheus_text(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    body = res.text
    assert "forensics_engine_up" in body
    assert "forensics_evidence_indexer_queue_size" in body
    assert "forensics_live_active_sessions" in body


# ---------------------------------------------------------------------------
# Vector-store backend honesty (deterministic in-memory fallback)
# ---------------------------------------------------------------------------


def test_qdrant_backend_name_and_point_lifecycle():
    from app.ai.qdrant_service import qdrant

    qdrant._backend = "memory"
    qdrant._mem = {}
    assert qdrant.backend_name() == "memory"
    health = qdrant.health()
    assert health["ok"] is True
    assert "in-memory" in health["detail"]

    qdrant.index_evidence("EVD-X1", [0.1] * qdrant.sim, {"event_type": "test"})
    assert qdrant.point_exists("video_evidence", "EVD-X1") is True
    assert qdrant.point_exists("video_evidence", "EVD-MISSING") is False

    qdrant.clear("video_evidence")
    assert qdrant.point_exists("video_evidence", "EVD-X1") is False


def test_qdrant_delete_actually_removes_a_point():
    """Regression: the in-memory store keyed ids as strings while delete passed
    the raw value, so every delete was a silent no-op ("4" != 4)."""
    from app.ai.qdrant_service import qdrant

    qdrant._backend = "memory"
    qdrant._mem = {}

    # Integer id (the policy-chunk case).
    qdrant.index("policy_chunks", 7, [0.1] * qdrant.sim, {"policy_id": 1})
    assert qdrant.point_exists("policy_chunks", 7) is True
    qdrant.delete("policy_chunks", 7)
    assert qdrant.point_exists("policy_chunks", 7) is False

    # String id (the evidence case).
    qdrant.index_evidence("EVD-D1", [0.2] * qdrant.sim, {"event_type": "test"})
    assert qdrant.point_exists("video_evidence", "EVD-D1") is True
    qdrant.delete("video_evidence", "EVD-D1")
    assert qdrant.point_exists("video_evidence", "EVD-D1") is False

    # Deleting something that is not there must not raise.
    qdrant.delete("policy_chunks", 999)


def test_storage_backend_name_and_clear(tmp_path):
    from app.storage.service import LocalStorageService

    svc = LocalStorageService(base_dir=str(tmp_path))
    svc.ensure_buckets()
    assert svc.backend_name() == "local"
    assert svc.health()["ok"] is True

    sp = svc.put_bytes("frames", b"frame-bytes", "frame-001.jpg", content_type="image/jpeg")
    assert svc.exists(sp) is True
    assert svc.get_bytes(sp) == b"frame-bytes"

    svc.clear_buckets()
    assert svc.exists(sp) is False


# ---------------------------------------------------------------------------
# Demo-database reset helpers (no external services touched)
# ---------------------------------------------------------------------------


def test_reset_script_removes_sqlite_db(tmp_path):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    import scripts.reset_demo_database as rdd

    db_file = tmp_path / "local.db"
    db_file.write_bytes(b"sqlite")
    url = f"sqlite:///{db_file.as_posix()}"
    rdd._drop_and_recreate(url)
    assert not db_file.exists()

    # Postgres/unknown schemes must raise, not silently pass.
    with pytest.raises(SystemExit):
        rdd._drop_and_recreate("mssql://host/db")


def test_reset_script_url_precedence(monkeypatch):
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    import scripts.reset_demo_database as rdd

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://from-env/db")
    assert rdd._resolve_url(None) == "postgresql+psycopg2://from-env/db"
    assert rdd._resolve_url("postgresql+psycopg2://from-arg/db") == "postgresql+psycopg2://from-arg/db"