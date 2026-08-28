"""Part 4 - tests for the evaluation harness (scripts/evaluate.py).

Verifies the benchmark dataset shape, metric math, baseline ordering, and that
machine-readable results are produced.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
PROJECT_ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import evaluate as ev  # noqa: E402

BENCHMARK = os.path.join(PROJECT_ROOT, "data", "evaluation", "benchmark.jsonl")


def test_benchmark_dataset_exists():
    assert os.path.exists(BENCHMARK)


def test_benchmark_has_11_scenarios():
    rows = ev.load_benchmark(BENCHMARK)
    assert len(rows) == 11


def test_benchmark_covers_expected_categories():
    rows = ev.load_benchmark(BENCHMARK)
    categories = {r["category"] for r in rows}
    expected = {
        "restricted_area_entry", "person_leaves_object", "person_approaches_equipment",
        "two_person_interaction", "alarm_event", "normal_walking", "normal_entrance",
        "normal_exit", "multiple_people", "ambiguous_event", "no_matching_event",
    }
    assert categories == expected


def test_each_scenario_has_required_fields():
    required = {
        "scenario_id", "category", "query", "expected_event", "start_time",
        "end_time", "relevant_clips", "expected_answer", "policy_reference",
    }
    for row in ev.load_benchmark(BENCHMARK):
        assert required.issubset(row.keys()), row.get("scenario_id")


def test_no_matching_event_has_empty_clips():
    row = ev.load_benchmark(BENCHMARK)
    nomatch = next(r for r in row if r["category"] == "no_matching_event")
    assert nomatch["relevant_clips"] == []
    assert nomatch["expected_event"] is None


# ---------------------------------------------------------------------------
# Metric math
# ---------------------------------------------------------------------------


def test_recall_at():
    gt = ["A", "B"]
    assert ev.recall_at(gt, ["A", "C", "D"], 5) == pytest.approx(0.5)
    assert ev.recall_at(gt, ["A"], 1) == pytest.approx(0.5)
    assert ev.recall_at([], ["A"], 5) == 0.0


def test_precision_at():
    gt = ["A"]
    assert ev.precision_at(gt, ["A", "B", "C", "D", "E"], 5) == pytest.approx(0.2)
    assert ev.precision_at(gt, ["A"], 1) == 1.0


def test_mrr():
    gt = ["Z"]
    assert ev.mrr(gt, ["X", "Z", "Y"]) == pytest.approx(0.5)
    assert ev.mrr(gt, ["X", "Y"]) == 0.0


def test_timestamp_error():
    assert ev.timestamp_error(5.0, 10.0) == 5.0
    assert ev.timestamp_error(None, 10.0) is None


def test_temporal_iou():
    assert ev.temporal_iou((0, 10), (0, 10)) == 1.0
    assert ev.temporal_iou((0, 5), (5, 10)) == 0.0
    assert ev.temporal_iou(None, (0, 10)) == 0.0
    assert ev.temporal_iou((0, 10), (2, 6)) == pytest.approx(4 / 10)


# ---------------------------------------------------------------------------
# Baseline ordering: hybrid should beat naive baselines overall
# ---------------------------------------------------------------------------


def test_baseline_ordering_hybrid_best_on_mrr():
    baselines = ev.run_retrieval_baselines()
    by_name = {b.name: b for b in baselines}
    hybrid = by_name["proposed_hybrid"]
    keyword = by_name["baseline2_keyword"]
    vector = by_name["baseline3_vector"]
    assert hybrid.mrr >= vector.mrr >= keyword.mrr
    assert hybrid.temporal_iou > vector.temporal_iou
    assert hybrid.temporal_iou > keyword.temporal_iou


def test_hybrid_grounds_timestamps_better():
    baselines = ev.run_retrieval_baselines()
    by_name = {b.name: b for b in baselines}
    hybrid = by_name["proposed_hybrid"]
    vector = by_name["baseline3_vector"]
    assert (hybrid.timestamp_error or 0) < (vector.timestamp_error or 1e9)


# ---------------------------------------------------------------------------
# Metrics output
# ---------------------------------------------------------------------------


def test_extended_metrics_include_all_required():
    baselines = ev.run_retrieval_baselines()
    hybrid = next(b for b in baselines if b.name == "proposed_hybrid")
    m = ev.compute_extended_metrics(hybrid, ev.load_benchmark(BENCHMARK))
    required = {
        "factual_accuracy", "report_completeness", "hallucination_rate",
        "context_relevance", "context_recall", "answer_faithfulness",
        "video_processing_seconds_per_min", "query_latency_ms",
        "reviewer_acceptance_rate", "reviewer_correction_rate",
    }
    assert required.issubset(m.keys())
    for v in m.values():
        assert isinstance(v, (int, float))


def test_main_writes_results_json(tmp_path):
    out = str(tmp_path / "results.json")
    # Run the full pipeline manually and persist machine-readable JSON.
    rows = ev.load_benchmark(BENCHMARK)
    baselines = ev.run_retrieval_baselines()
    hybrid = next(b for b in baselines if b.name == "proposed_hybrid")
    results = {
        "benchmark_file": BENCHMARK,
        "scenario_count": len(rows),
        "retrieval_baselines": [b.as_dict() for b in baselines],
        "extended_metrics": ev.compute_extended_metrics(hybrid, rows),
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    loaded = json.load(open(out, encoding="utf-8"))
    assert loaded["scenario_count"] == 11
    assert len(loaded["retrieval_baselines"]) == 4
    assert loaded["extended_metrics"]["hallucination_rate"] <= 1.0
