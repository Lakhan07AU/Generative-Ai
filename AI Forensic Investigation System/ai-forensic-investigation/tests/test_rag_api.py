"""API tests for the RAG + Policies endpoints (Part 2)."""

import os

import pytest


def test_rag_query_returns_unknown_when_no_data(client, auth_headers):
    res = client.post(
        "/rag/query",
        json={"query": "Did anyone enter the building?"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "UNKNOWN"
    assert body["query"]
    assert "evidence" in body


def test_policy_question_unknown_when_no_policy(client, auth_headers):
    res = client.post(
        "/rag/policy-question",
        json={"question": "Is badge access required after hours?"},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "UNKNOWN"


def test_findings_recorded_after_query(client, auth_headers):
    client.post(
        "/rag/query",
        json={"query": "Did a car approach the gate?"},
        headers=auth_headers,
    )
    res = client.get("/findings", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()) >= 1


def test_policy_upload_forbidden_for_investigator(client, auth_headers):
    data = {"file": ("policy.txt", b"Rule 1 No entry after hours.", "text/plain")}
    res = client.post("/policies/upload", files=data, headers=auth_headers)
    assert res.status_code == 403


def test_policy_upload_and_list_admin(client, admin_headers):
    data = {
        "file": (
            "access-policy.txt",
            b"Policy 1 Access Control\nBadges required for the restricted zone after 18:00.",
            "text/plain",
        )
    }
    res = client.post("/policies/upload", files=data, headers=admin_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["policy_id"].startswith("POL-")
    assert body["chunk_count"] >= 1

    listing = client.get("/policies", headers=admin_headers)
    assert listing.status_code == 200
    assert any(p["policy_id"] == body["policy_id"] for p in listing.json())


def test_policy_sections_view(client, admin_headers):
    data = {"file": ("site-policy.txt", b"Section 1 Safety\nAll staff must wear badges.", "text/plain")}
    up = client.post("/policies/upload", files=data, headers=admin_headers)
    assert up.status_code == 201, up.text
    pid = up.json()["policy_id"]

    sections = client.get(f"/policies/{pid}/sections", headers=admin_headers)
    assert sections.status_code == 200
    assert len(sections.json()) >= 1
    assert sections.json()[0]["text"]


def test_policy_search_endpoint(client, admin_headers):
    data = {"file": ("zonepolicy.txt", b"Policy 1 Restricted Zone\nNo unauthorized entry after hours.", "text/plain")}
    up = client.post("/policies/upload", files=data, headers=admin_headers)
    assert up.status_code == 201, up.text

    res = client.post(
        "/policies/search",
        json={"query": "restricted zone unauthorized entry"},
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert len(res.json()) >= 1


# ---------------------------------------------------------------- policy delete


def _upload_policy(client, headers, name="deletable-policy.txt"):
    """Upload a small policy and return (policy_id, chunk_ids)."""
    data = {
        "file": (
            name,
            b"Policy 1 Restricted Zone\nNo unauthorized entry after hours.\n"
            b"Policy 2 Evacuation\nAll staff must wear badges during a drill.",
            "text/plain",
        )
    }
    res = client.post("/policies/upload", files=data, headers=headers)
    assert res.status_code == 201, res.text
    pid = res.json()["policy_id"]
    sections = client.get(f"/policies/{pid}/sections", headers=headers).json()
    return pid, [c["id"] for c in sections]


def test_policy_delete_forbidden_for_investigator(client, auth_headers, admin_headers):
    """Deleting a policy is an admin action, same as uploading one."""
    # Upload as an admin (only an ADMIN may upload), then try to delete as an
    # INVESTIGATOR.
    pid, _ = _upload_policy(client, admin_headers, "not-deletable.txt")
    res = client.delete(f"/policies/{pid}", headers=auth_headers)
    assert res.status_code == 403
    # The policy must survive the rejected attempt.
    assert client.get(f"/policies/{pid}", headers=auth_headers).status_code == 200


def test_policy_delete_requires_authentication(client):
    res = client.delete("/policies/POL-0001")
    assert res.status_code == 401


def test_policy_delete_unknown_id_is_404(client, admin_headers):
    res = client.delete("/policies/POL-9999", headers=admin_headers)
    assert res.status_code == 404


def test_policy_delete_removes_document_chunks_and_vectors(client, admin_headers):
    """The row, its chunks and its Qdrant points must all disappear."""
    from app.ai.qdrant_service import qdrant
    from app.core.config import settings

    pid, chunk_ids = _upload_policy(client, admin_headers)
    assert chunk_ids, "upload produced no chunks to delete"
    for cid in chunk_ids:
        assert qdrant.point_exists(settings.QDRANT_COLLECTION_POLICY, cid)

    res = client.delete(f"/policies/{pid}", headers=admin_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["policy_id"] == pid
    assert body["deleted_chunks"] == len(chunk_ids)
    assert body["deleted_vectors"] == len(chunk_ids)

    assert client.get(f"/policies/{pid}", headers=admin_headers).status_code == 404
    assert client.get(f"/policies/{pid}/sections", headers=admin_headers).status_code == 404
    assert not any(
        p["policy_id"] == pid for p in client.get("/policies", headers=admin_headers).json()
    )
    for cid in chunk_ids:
        assert not qdrant.point_exists(settings.QDRANT_COLLECTION_POLICY, cid)


def test_policy_delete_removes_the_stored_file(client, admin_headers, monkeypatch, tmp_path):
    """The stored original must be deleted, not orphaned in the bucket."""
    from app.rag import policy_rag
    from app.storage.service import LocalStorageService

    local = LocalStorageService(base_dir=str(tmp_path))
    # The upload endpoint and the delete path must use the same backend object.
    monkeypatch.setattr(policy_rag, "storage", local)
    monkeypatch.setattr("app.api.policies.storage", local)

    pid, _ = _upload_policy(client, admin_headers, "stored-file-policy.txt")

    # Exactly one stored object, and it exists before the delete.
    stored = [
        os.path.join(root, name)
        for root, _dirs, files in os.walk(tmp_path)
        for name in files
    ]
    assert stored, "upload stored no file to delete"

    res = client.delete(f"/policies/{pid}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["file_deleted"] is True

    remaining = [
        os.path.join(root, name)
        for root, _dirs, files in os.walk(tmp_path)
        for name in files
    ]
    assert remaining == [], f"stored files survived the delete: {remaining}"


def test_policy_delete_succeeds_when_the_file_is_already_gone(client, admin_headers):
    """A missing stored file must not block deleting the policy."""
    from app.database import models
    from app.database.session import SessionLocal

    pid, _ = _upload_policy(client, admin_headers, "file-less-policy.txt")

    session = SessionLocal()
    try:
        policy = (
            session.query(models.PolicyDocument)
            .filter(models.PolicyDocument.policy_id == pid)
            .first()
        )
        policy.storage_path = None
        session.commit()
    finally:
        session.close()

    res = client.delete(f"/policies/{pid}", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert res.json()["file_deleted"] is False
    assert client.get(f"/policies/{pid}", headers=admin_headers).status_code == 404


def test_local_storage_delete_is_idempotent_and_contained(tmp_path):
    """Storage delete: a missing path is fine, escaping the root is refused."""
    from app.storage.service import LocalStorageService

    local = LocalStorageService(base_dir=str(tmp_path))
    path = local.put_bytes("policies", b"secret", "policy-abc.txt", "text/plain")

    assert local.exists(path) is True
    assert local.delete(path) is True
    assert local.exists(path) is False
    assert local.delete(path) is False  # idempotent
    assert local.delete("") is False

    with pytest.raises(ValueError):
        local.delete("../../etc/passwd")


def test_policy_delete_is_audited(client, admin_headers):
    pid, _ = _upload_policy(client, admin_headers, "audited-policy.txt")
    assert client.delete(f"/policies/{pid}", headers=admin_headers).status_code == 200

    res = client.get("/audit/logs", headers=admin_headers)
    assert res.status_code == 200
    rows = res.json()
    rows = rows if isinstance(rows, list) else rows.get("items", [])
    entries = [r for r in rows if r.get("action") == "policy_delete"]
    assert entries, "policy_delete was not recorded in the audit log"
    assert pid in (entries[0].get("details") or "")
