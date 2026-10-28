import json
import os
import stat

import httpx
import pytest

from app.model_settings import ModelSettings, SettingsLocked
from app.provider import ModelConfig, ModelProvider, ProviderError


def test_local_model_can_run_without_api_key():
    config = ModelConfig("http://127.0.0.1:18768/v1", "local-model", "")
    assert config.enabled
    assert config.is_local


def test_remote_model_still_requires_explicit_key():
    assert not ModelConfig("https://model.example/v1", "model", "").enabled
    with pytest.raises(ValueError):
        ModelConfig("http://model.example/v1", "model", "key")


def test_local_no_key_protocol_never_sends_an_empty_bearer():
    def handler(request):
        assert "authorization" not in request.headers
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            {"answer": "资料给出的期限为 14 天。[1]", "source_ids": [1], "status": "answered"}, ensure_ascii=False)}}]})
    model = ModelProvider(ModelConfig("http://localhost:18768/v1", "local", ""), transport=httpx.MockTransport(handler))
    assert "14" in model.generate("多久？", [{"filename": "a.txt", "location": "第 1 段", "text": "期限14天。"}])["answer"]


def test_insufficient_model_answer_can_have_no_fabricated_citation():
    model = ModelProvider(ModelConfig("http://127.0.0.1/v1", "local", ""), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content":
        '{"answer":"资料没有提供价格，无法确定。","source_ids":[],"status":"insufficient"}'}}]})))
    result = model.generate("多少钱？", [{"filename": "a.txt", "location": "第 1 段", "text": "此产品重1kg。"}])
    assert result["status"] == "insufficient" and result["source_ids"] == []


def test_settings_load_does_not_create_files(tmp_path):
    settings = ModelSettings(tmp_path / "private" / "model.json", environment={})
    assert not settings.provider.config.enabled
    assert not (tmp_path / "private").exists()


def test_saved_key_is_never_in_public_view_or_repr(tmp_path):
    settings = ModelSettings(tmp_path / "model.json", environment={})
    settings.update("https://model.example/v1", "model", "private-key-value")
    public = settings.public()
    assert public["has_api_key"] and public["enabled"]
    assert "private-key-value" not in json.dumps(public)
    assert "private-key-value" not in repr(settings.provider.config)
    restored = ModelSettings(tmp_path / "model.json", environment={})
    assert restored.provider.config.api_key == "private-key-value"
    assert restored.public()["configured_by"] == "file"


def test_blank_key_preserved_only_for_same_endpoint(tmp_path):
    settings = ModelSettings(tmp_path / "model.json", environment={})
    settings.update("https://one.example/v1", "model-a", "private-key")
    settings.update("https://one.example/v1/", "model-b", None)
    assert settings.provider.config.api_key == "private-key"
    settings.update("https://two.example/v1", "model-b", None)
    assert settings.provider.config.api_key == ""
    assert not settings.public()["enabled"]


def test_explicit_empty_key_deletes_saved_key(tmp_path):
    settings = ModelSettings(tmp_path / "model.json", environment={})
    settings.update("https://model.example/v1", "model", "private-key")
    settings.update("https://model.example/v1", "model", "")
    assert not settings.public()["has_api_key"]
    assert "private-key" not in (tmp_path / "model.json").read_text()


def test_environment_configuration_is_visible_as_read_only(tmp_path):
    settings = ModelSettings(tmp_path / "model.json", environment={"RAG_BASE_URL": "http://localhost:11434/v1", "RAG_MODEL": "local-model"})
    assert settings.public()["enabled"]
    assert settings.public()["configured_by"] == "environment"
    assert not settings.public()["editable"]
    with pytest.raises(SettingsLocked):
        settings.update("https://other.example/v1", "other", "key")
    assert not (tmp_path / "model.json").exists()


@pytest.mark.parametrize("content", ["not JSON", "[]", '{"api_key":42}', '{"base_url":"http://remote.example"}'])
def test_invalid_stored_config_has_readable_error_without_echoing_content(tmp_path, content):
    path = tmp_path / "model.json"; path.write_text(content)
    with pytest.raises(ValueError, match="配置"):
        ModelSettings(path, environment={})


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not represent Windows ACLs")
def test_secret_file_uses_owner_only_posix_permissions(tmp_path):
    path = tmp_path / "config" / "model.json"
    ModelSettings(path, environment={}).update("https://model.example/v1", "model", "private-key")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_failed_atomic_save_does_not_change_live_configuration(tmp_path, monkeypatch):
    settings = ModelSettings(tmp_path / "model.json", environment={})
    settings.update("http://127.0.0.1:11434/v1", "old-model", "")
    def fail_replace(*args):
        raise OSError("simulated disk error")
    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        settings.update("http://127.0.0.1:11434/v1", "new-model", "")
    assert settings.provider.config.model == "old-model"
    assert json.loads((tmp_path / "model.json").read_text())["model"] == "old-model"
    assert not list(tmp_path.glob("*.tmp"))
