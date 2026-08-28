"""Tests for the Security Policy RAG module (Part 2)."""

import os

from app.rag.policy_rag import chunk_text, extract_text, search_policies
from app.ai.qdrant_service import qdrant
from app.ai.embeddings import embeddings


def test_chunk_text_respects_section_headings():
    text = (
        "Policy 1 Access Control\n"
        "Employees must badge into the server room at all times.\n"
        "No tailgating is permitted.\n"
        "Policy 2 Visitor Escorts\n"
        "Visitors must be escorted by authorized staff while on premises.\n"
        "Violations must be reported immediately.\n"
    )
    chunks = chunk_text(text)
    sections = [c["section"] for c in chunks]
    assert any("Policy 1" in s for s in sections)
    assert any("Policy 2" in s for s in sections)
    assert all(c["text"] for c in chunks)


def test_extract_text_unsupported_file_type_raises():
    import pytest

    with pytest.raises(ValueError):
        extract_text("notes.exe", b"%MZbinary")


def test_extract_text_txt():
    fmt, text = extract_text("policy.txt", b"Rule 1 No entry after hours.")
    assert fmt == "txt"
    assert "No entry" in text


def test_index_and_search_policy_roundtrip():
    # Index a policy chunk directly into the (offline in-memory) vector store.
    qdrant.ensure_collections()
    text = "Contractors require badge access for the restricted zone after 18:00."
    vec = embeddings.embed_text(text)
    qdrant.index_policy(
        point_id="pmem-test-1",
        vector=vec,
        payload={
            "policy_id": 999,
            "document_name": "Site Security Policy",
            "section": "Rule 5 Access Hours",
            "page": 2,
            "chunk_index": 0,
            "text": text,
        },
    )
    hits = search_policies("restricted zone badge access contractors", limit=5)
    assert hits, "expected at least one policy hit"
    top = hits[0]
    assert top["document_name"] == "Site Security Policy"
    assert "restricted" in top["text"].lower()
    assert "score" in top
