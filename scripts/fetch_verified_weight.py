"""Fallback transport for one fixed public model; hash checked against HF metadata."""
from pathlib import Path
import hashlib
import requests

COMMIT = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
SHA256 = "1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38"
SIZE = 94781076
ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "models--Qdrant--bge-small-zh-v1.5" / "snapshots" / COMMIT / "model_optimized.onnx"

if __name__ == "__main__":
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    for domain in ("huggingface.co", "hf-mirror.com"):
        url = f"https://{domain}/Qdrant/bge-small-zh-v1.5/resolve/{COMMIT}/model_optimized.onnx?download=true"
        part = TARGET.with_suffix(".part")
        try:
            print(f"Downloading fixed public weight from {domain} (TLS verified)", flush=True)
            with requests.get(url, stream=True, timeout=(15, 30)) as response:
                response.raise_for_status()
                digest = hashlib.sha256()
                received = 0
                with part.open("wb") as output:
                    for block in response.iter_content(1024 * 1024):
                        received += len(block)
                        if received > SIZE:
                            raise ValueError("download larger than authoritative metadata")
                        digest.update(block)
                        output.write(block)
                        if received and received % (10 * 1024 * 1024) < len(block):
                            print(f"{received / SIZE:.0%}", flush=True)
            if received != SIZE or digest.hexdigest() != SHA256:
                raise ValueError("model did not match authoritative SHA256 and byte size")
            part.replace(TARGET)
            print(f"Verified {received} bytes; SHA256 {SHA256}", flush=True)
            break
        except Exception as error:
            print(f"{domain}: {type(error).__name__}; unverified download will not be used.", flush=True)
    else:
        raise SystemExit("Could not obtain verified weights. The lexical workspace remains available.")
