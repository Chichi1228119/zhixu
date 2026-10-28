"""Explicit, one-time optional download. Normal app usage never downloads a model."""
from pathlib import Path
import hashlib
import json
import os
import time
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.paths import RuntimePaths
CACHE = RuntimePaths.discover().model_dir
os.environ["HF_HOME"] = str(CACHE / "huggingface")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"

if __name__ == "__main__":
    from fastembed import TextEmbedding
    CACHE.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    revision_path = CACHE / "models--Qdrant--bge-small-zh-v1.5" / "refs" / "main"
    local_snapshot = None
    if revision_path.exists():
        candidate = revision_path.parent.parent / "snapshots" / revision_path.read_text().strip()
        if (candidate / "model_optimized.onnx").exists():
            local_snapshot = candidate
    arguments = {"specific_model_path": str(local_snapshot), "local_files_only": True} if local_snapshot else {}
    model = TextEmbedding(model_name="BAAI/bge-small-zh-v1.5", cache_dir=str(CACHE), threads=2,
                          providers=["CPUExecutionProvider"], **arguments)
    vectors = list(model.embed(["设备断网后继续本地记录。", "入职培训在五个工作日内完成。"], batch_size=8))
    assert len(vectors) == 2 and vectors[0].shape == (512,)
    files = [{"path": str(path.relative_to(CACHE)), "bytes": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in CACHE.rglob("*.onnx")]
    manifest = {"model": "BAAI/bge-small-zh-v1.5", "dimensions": 512, "license": "MIT",
                "source": "https://huggingface.co/Qdrant/bge-small-zh-v1.5", "provider": "CPUExecutionProvider",
                "verified": True, "elapsed_seconds": round(time.perf_counter() - started, 2), "weights": files}
    (CACHE / "semantic-ready.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
