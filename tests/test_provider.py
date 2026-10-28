import json

import httpx
import pytest

from app.provider import ModelConfig, ModelProvider, ProviderError


SOURCES = [
    {"id": "a", "filename": "规则.md", "location": "第 1 段", "text": "试用期为 14 天。"},
    {"id": "b", "filename": "安全.md", "location": "第 2 段", "text": "密钥不得写入日志。"},
]


def provider_with(response, status=200):
    def handler(request):
        assert str(request.url) == "https://model.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer unit-test-only"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert "试用期为 14 天" in body["messages"][1]["content"]
        return httpx.Response(status, json=response)

    config = ModelConfig("https://model.example/v1", "test-model", "unit-test-only")
    return ModelProvider(config, transport=httpx.MockTransport(handler))


def test_missing_configuration_is_not_a_fake_model():
    model = ModelProvider(ModelConfig("https://model.example/v1", "", ""))
    assert not model.config.enabled
    with pytest.raises(ProviderError, match="未配置"):
        model.generate("试用多久？", SOURCES)


def test_real_protocol_parsing_and_usage():
    model = provider_with({"choices": [{"message": {"content": json.dumps(
        {"answer": "试用期为 14 天。[1]", "source_ids": [1], "status": "answered"}, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
    result = model.generate("试用多久？", SOURCES)
    assert result["answer"] == "试用期为 14 天。[1]"
    assert result["source_ids"] == [1]
    assert result["usage"]["total_tokens"] == 120


@pytest.mark.parametrize("answer,ids", [
    ("试用 14 天。[3]", [3]),
    ("试用 14 天。", [1]),
    ("试用 14 天。[1]", []),
    ("试用 14 天。[1]", [True]),
    ("试用 14 天。[2]", [1]),
])
def test_invalid_or_missing_citations_are_rejected(answer, ids):
    model = provider_with({"choices": [{"message": {"content": json.dumps(
        {"answer": answer, "source_ids": ids, "status": "answered"}, ensure_ascii=False)}}]})
    with pytest.raises(ProviderError, match="引用"):
        model.generate("试用多久？", SOURCES)


@pytest.mark.parametrize("payload", [
    {"choices": []},
    {"choices": [{"message": {"content": "not-json"}}]},
    {"choices": [{"message": {"content": "[]"}}]},
    {"choices": [{"message": {"content": '{"answer":42,"source_ids":[1]}'}}]},
])
def test_malformed_model_output_is_understandable(payload):
    with pytest.raises(ProviderError):
        provider_with(payload).generate("试用多久？", SOURCES)


def test_provider_error_does_not_leak_service_response_or_key():
    model = provider_with({"error": {"message": "secret-unit-test-only"}}, 401)
    with pytest.raises(ProviderError) as caught:
        model.generate("试用多久？", SOURCES)
    assert "secret" not in str(caught.value)
    assert "unit-test-only" not in str(caught.value)
    assert "401" in str(caught.value)


def test_timeout_has_clear_message():
    def handler(request):
        raise httpx.ReadTimeout("contains-sensitive-request")

    model = ModelProvider(ModelConfig("https://model.example/v1", "model", "key"),
                          transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="超时"):
        model.generate("问题", SOURCES)


@pytest.mark.parametrize("url", ["http://remote.example/v1", "file:///tmp/model", "https://user:password@example.com/v1", "https://example.com/v1?key=secret"])
def test_unsafe_config_urls_are_rejected(url):
    with pytest.raises(ValueError):
        ModelConfig(url, "model", "key")


def test_loopback_http_allowed_for_local_models():
    assert ModelConfig("http://127.0.0.1:11434/v1", "local", "local-placeholder").enabled


def test_provider_preserves_explicit_insufficient_status():
    model = provider_with({"choices": [{"message": {"content": json.dumps(
        {"answer": "资料未说明该信息，无法确定。[1]", "source_ids": [1], "status": "insufficient"}, ensure_ascii=False)}}]})
    assert model.generate("试用几天？", SOURCES)["status"] == "insufficient"


@pytest.mark.parametrize('answer', ['[1]', '[1] [2]', ' 。 [1]'])
def test_citation_only_output_is_not_a_valid_answer(answer):
    ids = [1, 2] if '[2]' in answer else [1]
    model = provider_with({'choices': [{'message': {'content': json.dumps(
        {'answer': answer, 'source_ids': ids, 'status': 'answered'}, ensure_ascii=False)}}]})
    with pytest.raises(ProviderError):
        model.generate('试用几天？', SOURCES)


@pytest.mark.parametrize("status", [None, "unknown", 42])
def test_invalid_model_status_is_rejected(status):
    model = provider_with({"choices": [{"message": {"content": json.dumps(
        {"answer": "14 天。[1]", "source_ids": [1], "status": status}, ensure_ascii=False)}}]})
    with pytest.raises(ProviderError):
        model.generate("试用几天？", SOURCES)
