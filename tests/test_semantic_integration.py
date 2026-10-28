from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.provider import ModelConfig, ModelProvider
from app.semantic import SemanticUnavailable
from app.service import KnowledgeService


def test_semantic_index_rebuilds_after_import_and_delete(tmp_path, monkeypatch):
    builds = []

    class FakeRetriever:
        def __init__(self, chunks, cache_dir):
            self.chunks = chunks
            builds.append([chunk["id"] for chunk in chunks])

        def search(self, question, top_k=5, document_ids=None):
            selected = [c for c in self.chunks if not document_ids or c["document_id"] in document_ids]
            return [dict(c, score=0.8) for c in selected[:top_k]]

    monkeypatch.setattr("app.semantic.SemanticRetriever", FakeRetriever)
    service = KnowledgeService(tmp_path / "test.db", model_cache=tmp_path / "models")
    first = service.import_document("first.txt", "在家工作需要主管批准。".encode())
    assert service.ask("居家办公找谁审批？", strategy="semantic")["sources"]
    assert len(builds) == 1
    service.search("再次提问", strategy="semantic")
    assert len(builds) == 1
    second = service.import_document("second.txt", "实验室值班时间为周一上午。".encode())
    result = service.ask("值班", document_ids=[second["id"]], strategy="semantic")
    assert all(s["document_id"] == second["id"] for s in result["sources"])
    assert "512" in result["trace"][0]["detail"]
    assert len(builds) == 2
    service.delete_document(first["id"])
    assert all(s["document_id"] != first["id"] for s in service.search("在家工作", strategy="semantic"))
    assert len(builds) == 3


def test_missing_semantic_model_returns_explicit_503_without_downloading(tmp_path):
    model = ModelProvider(ModelConfig("https://example.com/v1", "", ""))
    application = create_app(db_path=tmp_path / "test.db", seed_demo=False, provider=model, model_cache=tmp_path / "missing-model")
    with TestClient(application) as client:
        assert client.get("/api/health").json()["semantic"]["available"] is False
        response = client.post("/api/ask", json={"question": "在家办公需要谁批准？", "strategy": "semantic"})
        assert response.status_code == 503
        assert "语义模型" in response.json()["detail"]
    assert not (tmp_path / "missing-model").exists()
