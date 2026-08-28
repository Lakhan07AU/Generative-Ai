"""API tests for the RAG + Policies endpoints (Part 2)."""


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
