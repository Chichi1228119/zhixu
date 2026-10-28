from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.provider import ModelConfig, ModelProvider


@pytest.fixture
def client(tmp_path):
    application = create_app(db_path=tmp_path / "test.db", seed_demo=False,
                             provider=ModelProvider(ModelConfig("https://example.com/v1", "", "")))
    with TestClient(application) as active:
        yield active


def upload(client, name="测试.md", text="## 试用规则\n\n星河平台试用期为 14 天，试用期间最多创建 3 个项目。"):
    response = client.post("/api/documents", files={"file": (name, text.encode("utf-8"), "text/markdown")})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_page_are_real(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["app_id"] == "zhixu-local-knowledge"
    assert health["model"]["enabled"] is False
    assert client.get("/").status_code == 200
    assert "知序" in client.get("/").text


def test_import_ask_original_delete_cycle(client):
    document = upload(client)
    listed = client.get("/api/documents").json()["documents"]
    assert len(listed) == 1
    result = client.post("/api/ask", json={"question": "平台试用期有几天？"}).json()
    assert result["mode"] == "extractive"
    assert result["status"] == "answered"
    assert "14" in result["answer"]
    assert result["sources"][0]["document_id"] == document["id"]
    original = client.get(f'/api/documents/{document["id"]}').json()
    assert "14" in original["chunks"][0]["text"]
    assert client.delete(f'/api/documents/{document["id"]}').status_code == 200
    answer = client.post("/api/ask", json={"question": "试用期几天？"}).json()
    assert answer["status"] == "insufficient"
    assert not answer["sources"]


def test_duplicate_is_idempotent(client):
    a = upload(client)
    b = upload(client)
    assert a["id"] == b["id"]
    assert b["existing"] is True
    assert len(client.get("/api/documents").json()["documents"]) == 1


@pytest.mark.parametrize("question", ["", "   ", "a" * 2001])
def test_invalid_questions_return_422(client, question):
    assert client.post("/api/ask", json={"question": question}).status_code == 422


@pytest.mark.parametrize("body", [{"question": "试用", "top_k": 0}, {"question": "试用", "top_k": 21},
    {"question": "试用", "mode": "fake"}, {"question": "试用", "strategy": "unknown"}])
def test_options_are_validated(client, body):
    assert client.post("/api/ask", json=body).status_code == 422


def test_unsupported_empty_and_corrupt_files(client):
    for name, data in [("app.exe", b"test"), ("empty.txt", b""), ("broken.pdf", b"not a PDF")]:
        result = client.post("/api/documents", files={"file": (name, data)})
        assert result.status_code == 400, result.text


def test_oversized_file_is_rejected(client):
    response = client.post("/api/documents", files={"file": ("large.txt", b"x" * (10 * 1024 * 1024 + 1))})
    assert response.status_code == 413


def test_cross_site_mutation_is_rejected(client):
    response = client.post("/api/ask", json={"question": "你好"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_untrusted_host_is_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_missing_documents_are_404(client):
    assert client.get("/api/documents/not-there").status_code == 404
    assert client.delete("/api/documents/not-there").status_code == 404


def test_llm_request_requires_configuration(client):
    upload(client)
    response = client.post("/api/ask", json={"question": "试用几天？", "mode": "llm"})
    assert response.status_code == 503
    assert "未配置" in response.json()["detail"]


def test_filter_does_not_leak_other_documents(client):
    first = upload(client)
    second = upload(client, "安全.md", "密钥轮换周期为 90 天，不得把密钥写入日志。")
    result = client.post("/api/ask", json={"question": "密钥多久轮换？", "document_ids": [second["id"]]}).json()
    assert all(s["document_id"] == second["id"] for s in result["sources"])
    assert all(s["document_id"] != first["id"] for s in result["sources"])


def test_filename_does_not_write_outside_store(client, tmp_path):
    imported = upload(client, "../../escape.md")
    assert "/" not in imported["filename"]
    assert not (tmp_path.parent / "escape.md").exists()


def test_lessons_are_available_without_model(client):
    lessons = client.get("/api/lessons").json()["lessons"]
    assert len(lessons) >= 7
    assert all(item["question"] and item["answer"] and item["exercise"] for item in lessons)


def test_missing_evaluation_is_explicit(client):
    result = client.get("/api/evaluation").json()
    assert "available" in result


def test_source_html_remains_text_in_json(client):
    document = upload(client, "html.md", "<script>alert('xss')</script>\n\n测试平台试用期为 14 天。")
    original = client.get(f'/api/documents/{document["id"]}').json()
    assert any("<script>" in c["text"] for c in original["chunks"])


def test_chunked_oversized_upload_stops_before_multipart_spooling(client, monkeypatch):
    import asyncio
    import tempfile
    import httpx
    written = []
    original = tempfile.SpooledTemporaryFile.write

    def counted(self, data):
        written.append(len(data))
        return original(self, data)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "write", counted)

    async def run():
        async def stream():
            yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="big.txt"\r\n\r\n'
            for _ in range(12):
                yield b"x" * (1024 * 1024)
            yield b"\r\n--boundary--\r\n"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://testserver") as active:
            response = await active.post("/api/documents", content=stream(), headers={"Content-Type": "multipart/form-data; boundary=boundary"})
            assert response.status_code == 413
    asyncio.run(run())
    assert sum(written) == 0


def test_multipart_rejects_extra_files_before_import(client):
    response = client.post("/api/documents", files=[("file", ("a.txt", b"hello")), ("file", ("b.txt", b"world"))])
    assert response.status_code == 400
    assert client.get("/api/documents").json()["documents"] == []


def test_llm_updates_status_and_replaces_extractive_trace(tmp_path):
    import httpx
    import json

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"answer": "资料未说明该上限，无法确定。[1]", "source_ids": [1], "status": "insufficient"}, ensure_ascii=False)}}]})

    model = ModelProvider(ModelConfig("https://example.com/v1", "test-model", "test-only"), transport=httpx.MockTransport(handler))
    with TestClient(create_app(db_path=tmp_path / "llm.db", seed_demo=False, provider=model)) as active:
        upload(active)
        response = active.post("/api/ask", json={"question": "试用期几天？", "mode": "llm"})
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "insufficient"
        assert result["mode"] == "llm"
        assert not any("没有模型生成" in step["detail"] or "逐字摘录" in step["detail"] for step in result["trace"])
