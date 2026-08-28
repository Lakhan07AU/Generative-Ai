"""Tests for the Video RAG module (Part 2)."""

from app.rag.video_rag import analyze_query, video_rag_answer


def test_analyze_query_extracts_entities_and_events():
    analysis = analyze_query("Did a person enter the restricted zone?")
    assert "person" in analysis["entities"]
    assert "restricted" in analysis["events"]


def test_analyze_query_temporal_between():
    analysis = analyze_query("Who crossed the gate between 14:30 and 15:00?")
    t = analysis["temporal"]
    assert t.get("start") == 14 * 3600 + 30 * 60
    assert t.get("end") == 15 * 3600


def test_analyze_query_car_detected():
    analysis = analyze_query("A van stopped near the entrance")
    assert "car" in analysis["entities"]
    assert "stopped" in analysis["events"]


def test_video_rag_answer_unknown_when_no_data(db):
    result = video_rag_answer(db, "Did anyone enter the building?")
    assert result["status"] == "UNKNOWN"
    assert result["evidence"] == []
    assert "INSUFFICIENT EVIDENCE" in result["answer"].upper()
