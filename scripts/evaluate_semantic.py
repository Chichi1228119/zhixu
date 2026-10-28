"""Evaluate the fixed semantic confirmation set, without threshold tuning."""
from pathlib import Path
import hashlib
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.evaluation import evaluate
from app.paths import RuntimePaths

if __name__ == "__main__":
    paths = RuntimePaths.discover()
    cases_path = paths.evaluation_dir / "semantic-confirmation.json"
    expected = "28e93a13c40c5edbd6b56b8f73f4aa43c9186eee940464666f7c1c2ac78833c8"
    if hashlib.sha256(cases_path.read_bytes()).hexdigest() != expected:
        raise SystemExit("The fixed confirmation set changed; retain the original set or explicitly version a new protocol.")
    report = evaluate(paths.demo_dir, cases_path, paths.report_dir / "semantic-confirmation.json",
                      strategies=("hybrid", "semantic"), model_cache=paths.model_dir)
    print(f"Evaluated {report['case_count']} fixed confirmation cases; no threshold tuning; no external API calls.")
    for name, splits in report["strategies"].items():
        print(name, splits["holdout"])
