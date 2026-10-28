"""Reproducible, document-level retrieval evaluation; never grades model correctness."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import tempfile
import time
from uuid import uuid4

import numpy as np

from .service import KnowledgeService


def mean(values):
    return round(sum(values) / len(values), 6) if values else None


def calculate_metrics(rows):
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    ranks = []
    for row in answerable:
        expected = set(row["expected_sources"])
        rank = next((index for index, name in enumerate(row["retrieved_sources"][:5], 1) if name in expected), None)
        ranks.append(1 / rank if rank else 0)
    latencies = [row["latency_ms"] for row in rows]
    return {"count": len(rows), "answerable_count": len(answerable), "unanswerable_count": len(unanswerable),
            "hit_at_5": mean([bool(set(r["expected_sources"]) & set(r["retrieved_sources"][:5])) for r in answerable]),
            "recall_at_5": mean([len(set(r["expected_sources"]) & set(r["retrieved_sources"][:5])) / len(set(r["expected_sources"])) for r in answerable]),
            "all_sources_at_5": mean([set(r["expected_sources"]).issubset(r["retrieved_sources"][:5]) for r in answerable]),
            "mrr": mean(ranks),
            "refusal_rate": mean([r["status"] == "insufficient" for r in unanswerable]),
            "false_accept_rate": mean([r["status"] != "insufficient" for r in unanswerable]),
            "false_refusal_rate": mean([r["status"] == "insufficient" for r in answerable]),
            "citation_validity": mean([r["citation_validity"] for r in rows if r["citation_validity"] is not None]),
            "keyword_coverage": mean([r["keyword_coverage"] for r in answerable]),
            "p50_ms": round(float(np.percentile(latencies, 50)), 3) if latencies else 0,
            "p95_ms": round(float(np.percentile(latencies, 95)), 3) if latencies else 0}


def validate_cases(dataset, demo_dir):
    cases = dataset.get("cases", [])
    if not cases:
        raise ValueError("评测题集为空。")
    ids = set()
    for case in cases:
        if case.get("split") not in {"dev", "holdout"}:
            raise ValueError("评测划分只能为 dev 或 holdout。")
        if case.get("id") in ids or not case.get("id"):
            raise ValueError("评测题目编号必须唯一且非空。")
        ids.add(case["id"])
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            raise ValueError("评测问题不能为空。")
        if type(case.get("answerable")) is not bool:
            raise ValueError("answerable 必须为布尔值。")
        sources = case.get("expected_sources", [])
        if case["answerable"] and not sources:
            raise ValueError("有依据题必须提供参考来源。")
        if not case["answerable"] and sources:
            raise ValueError("无依据题不能填写参考来源。")
        for source in sources:
            if Path(source).name != source or not (demo_dir / source).is_file():
                raise ValueError("评测参考来源不存在或路径无效。")
    return cases


def evaluate(demo_dir: Path, cases_path: Path, output_path: Path,
             strategies=("bm25", "tfidf", "hybrid"), model_cache: Path | None = None):
    demo_dir, cases_path, output_path = Path(demo_dir), Path(cases_path), Path(output_path)
    raw = cases_path.read_bytes()
    dataset = json.loads(raw.decode("utf-8-sig"))
    cases = validate_cases(dataset, demo_dir)
    results = []
    with tempfile.TemporaryDirectory(prefix="zhixu-evaluation-") as directory:
        service = KnowledgeService(Path(directory) / "evaluation.db", model_cache=model_cache)
        for path in sorted(demo_dir.iterdir()):
            if path.suffix.lower() in {".md", ".txt", ".pdf"}:
                service.import_document(path.name, path.read_bytes())
        documents = service.documents()
        actual_chunks = {chunk["id"]: chunk["text"] for doc in documents for chunk in service.document(doc["id"])["chunks"]}
        # Build the index once, outside latency measurement; all strategies share it.
        cold_started = time.perf_counter()
        warmup = {}
        for strategy in strategies:
            warm_started = time.perf_counter()
            service.search(cases[0]["question"], strategy=strategy)
            warmup[strategy] = round((time.perf_counter() - warm_started) * 1000, 3)
        cold_ms = round((time.perf_counter() - cold_started) * 1000, 3)
        for strategy in strategies:
            for case in cases:
                started = time.perf_counter()
                answer = service.ask(case["question"], top_k=5, strategy=strategy)
                latency_ms = round((time.perf_counter() - started) * 1000, 3)
                source_names = [source["filename"] for source in answer["sources"]]
                expected = set(case["expected_sources"])
                terms = case.get("expected_terms", [])
                refs = [int(i) for i in re.findall(r"\[(\d+)\]", answer["answer"])]
                valid_sources = all(actual_chunks.get(s["id"]) == s["text"] for s in answer["sources"])
                valid_refs = all(1 <= index <= len(answer["sources"]) for index in refs)
                citation_validity = float(valid_sources and valid_refs and bool(refs)) if answer["sources"] else None
                results.append({"id": case["id"], "split": case["split"], "category": case["category"],
                                "question": case["question"], "reference_answer": case["reference_answer"],
                                "answerable": case["answerable"], "expected_sources": case["expected_sources"],
                                "expected_terms": terms, "strategy": strategy, "status": answer["status"],
                                "answer": answer["answer"], "retrieved_sources": source_names,
                                "correct_retrieval": not case["answerable"] or expected.issubset(source_names[:5]),
                                "correct_refusal": (answer["status"] == "insufficient") == (not case["answerable"]),
                                "keyword_coverage": mean([term in answer["answer"] for term in terms]) if terms else None,
                                "citation_validity": citation_validity, "latency_ms": latency_ms})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "dataset_version": dataset.get("dataset_version", "unknown"),
              "dataset_sha256": hashlib.sha256(raw).hexdigest(), "case_count": len(cases), "document_count": len(documents),
              "splits": dict(Counter(case["split"] for case in cases)),
              "categories": dict(Counter(case["category"] for case in cases)),
              "cold_index_build_ms": cold_ms, "strategy_warmup_ms": warmup,
              "semantic_cutoff": 0.65 if "semantic" in strategies else None,
              "environment": {"python": platform.python_version(), "platform": platform.platform()},
              "strategies": {strategy: {split: calculate_metrics([row for row in results if row["strategy"] == strategy and row["split"] == split])
                                        for split in ("dev", "holdout")} for strategy in strategies},
              "results": results,
              "limitations": [
                  "这是同一虚构业务域的固定合成题集，不代表真实企业数据上的泛化能力。",
                  "Hit@5 表示至少命中一个预期文件，Recall@5 为召回预期文件比例的逐题平均；完整来源@5 要求所有预期文件均命中。三者按文件名计算，命中同文件的错误段落也可能得分，需逐题看原文。",
                  "关键词覆盖仅为参考答案词项是否出现在摘录中，不是语义正确率或人工核验结果。",
                  "引用有效性只检查原文与编号，不判断原文是否支持每个结论。",
                  "拒答、缺失说明和数字冲突使用启发式规则；报告保留误接受与误拒答。",
                  "默认三种策略共享 TF-IDF 相似度与词项覆盖候选门限；BM25 行是同门限下的排序消融，不是独立纯 BM25 基线。",
                  "延迟为预热后本地 Python 编排耗时，不含 HTTP、外部模型或真实企业规模负载。",
                  "本次模型 API 调用为 0，生成质量、真实 Token 费用及生产性能未测。",
                  "如含 semantic：使用本机 BGE-small-zh-v1.5、512维、固定0.65余弦门限；门限未在确认集调参，语义相似不保证答案充分，长文本可能截断。",
              ]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    output_path.with_suffix(".md").write_text(report_markdown(report), encoding="utf-8")
    return report


def report_markdown(report):
    lines = ["# 知序检索评测报告", "", f"生成时间：{report['generated_at']}", "",
             f"固定题集：{report['case_count']} 题；开发 {report['splits'].get('dev', 0)} / 留出 {report['splits'].get('holdout', 0)}。",
             f"题集 SHA256：`{report['dataset_sha256']}`", "", "## 指标", "",
             "| 划分 | 策略 | Hit@5 | Recall@5 | 完整来源@5 | MRR | 无依据拒答率 | 有依据误拒答率 | P95 ms |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    percent = lambda value: f"{value * 100:.1f}%" if value is not None else "未测"
    for split in ("dev", "holdout"):
        for strategy in report["strategies"]:
            m = report["strategies"][strategy][split]
            lines.append(f"| {split} | {strategy} | {percent(m['hit_at_5'])} | {percent(m['recall_at_5'])} | {percent(m['all_sources_at_5'])} | {m['mrr'] or 0:.3f} | {percent(m['refusal_rate'])} | {percent(m['false_refusal_rate'])} | {m['p95_ms']:.3f} |")
    lines.extend(["", "## 指标边界", "", *[f"- {text}" for text in report["limitations"]], "", "## 失败或需复核题", ""])
    for result in report["results"]:
        if (result["correct_retrieval"] and result["correct_refusal"]):
            continue
        lines.extend([f"### {result['strategy']} / {result['id']} / {result['split']} / {result['question']}", "",
                      f"参考：{result['reference_answer']}", "",
                      f"预期来源：{', '.join(result['expected_sources']) or '无，应该拒答'}", "",
                      f"实际来源：{', '.join(result['retrieved_sources']) or '无'}；实际状态：{result['status']}", ""])
    return "\n".join(lines) + "\n"
