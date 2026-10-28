import hashlib
import json

import pytest

from app.evaluation import calculate_metrics, evaluate


def row(answerable, sources, expected, status="answered", latency=10):
    expected_set = set(expected)
    return {"answerable": answerable, "retrieved_sources": sources, "expected_sources": expected,
            "status": status, "latency_ms": latency, "keyword_coverage": 1.0,
            "citation_validity": 1.0, "correct_retrieval": not answerable or expected_set.issubset(sources)}


def test_metrics_do_not_conflate_recall_completeness_and_refusal():
    result = calculate_metrics([
        row(True, ["wrong", "a"], ["a", "b"], latency=10),
        row(True, ["a"], ["a"], latency=20),
        row(False, [], [], status="insufficient", latency=30),
        row(False, ["wrong"], [], latency=40),
    ])
    assert result["hit_at_5"] == 1.0
    assert result["recall_at_5"] == 0.75
    assert result["all_sources_at_5"] == 0.5
    assert result["mrr"] == 0.75
    assert result["refusal_rate"] == 0.5
    assert result["false_accept_rate"] == 0.5
    assert result["p50_ms"] == 25


def test_empty_metric_groups_are_null_not_fake_perfect_scores():
    result = calculate_metrics([row(True, [], ["a"], status="insufficient")])
    assert result["refusal_rate"] is None
    assert result["false_refusal_rate"] == 1.0
    assert result["recall_at_5"] == 0.0


def test_temporary_evaluation_generates_traceable_report(tmp_path):
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "trial.txt").write_text("平台试用期为14天。", encoding="utf-8")
    cases = {"dataset_version": "test", "cases": [
        {"id": "dev-1", "split": "dev", "question": "试用期几天？", "category": "fact", "answerable": True,
         "expected_sources": ["trial.txt"], "expected_terms": ["14"], "reference_answer": "14天"},
        {"id": "holdout-1", "split": "holdout", "question": "火星公转周期是什么？", "category": "unanswerable", "answerable": False,
         "expected_sources": [], "expected_terms": [], "reference_answer": "资料未提供"},
    ]}
    case_path = tmp_path / "cases.json"
    case_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    path = tmp_path / "reports" / "evaluation.json"
    report = evaluate(demo, case_path, path)
    assert report["case_count"] == 2
    assert report["dataset_sha256"] == hashlib.sha256(case_path.read_bytes()).hexdigest()
    assert report["strategies"]["hybrid"]["dev"]["recall_at_5"] == 1
    assert report["strategies"]["hybrid"]["holdout"]["refusal_rate"] == 1
    assert len(report["results"]) == 6
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert path.with_suffix(".md").exists()
    assert not list(tmp_path.glob("*.db"))


def test_invalid_split_is_not_silently_dropped(tmp_path):
    demo = tmp_path / "demo"; demo.mkdir()
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"dataset_version": "test", "cases": [{"id": "1", "split": "oops"}]}))
    with pytest.raises(ValueError, match="划分"):
        evaluate(demo, path, tmp_path / "report.json")
