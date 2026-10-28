"""Run the fixed development/holdout retrieval evaluation from any working directory."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.evaluation import evaluate
from app.paths import RuntimePaths

if __name__ == "__main__":
    paths = RuntimePaths.discover()
    report = evaluate(paths.demo_dir, paths.evaluation_dir / "cases.json", paths.report_dir / "evaluation.json")
    print(f"Completed {report['case_count']} fixed cases x 3 strategies. Report: {paths.report_dir / 'evaluation.md'}")
    for strategy, splits in report["strategies"].items():
        print(strategy, "holdout:", splits["holdout"])
