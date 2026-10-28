"""Local-only provider settings; secrets are persisted atomically and never echoed."""
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from .provider import ModelConfig, ModelProvider


class SettingsLocked(ValueError):
    pass


class ModelSettings:
    def __init__(self, path: Path, provider: ModelProvider | None = None, environment=None):
        self.path = Path(path)
        self._lock = threading.RLock()
        environment = os.environ if environment is None else environment
        self._environment = {key: environment[key] for key in ("RAG_BASE_URL", "RAG_MODEL", "RAG_API_KEY") if key in environment}
        self._injected = provider is not None
        self.provider = provider or ModelProvider(self._load())

    def _load(self):
        try:
            content = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
            if not isinstance(content, dict):
                raise ValueError
            values = {"base_url": content.get("base_url", "https://api.openai.com/v1"),
                      "model": content.get("model", ""), "api_key": content.get("api_key", "")}
            for key, field in (("RAG_BASE_URL", "base_url"), ("RAG_MODEL", "model"), ("RAG_API_KEY", "api_key")):
                if key in self._environment:
                    values[field] = self._environment[key]
            if not all(isinstance(value, str) for value in values.values()):
                raise ValueError
            return ModelConfig(**values)
        except (OSError, ValueError, TypeError):
            raise ValueError("模型配置无法读取或格式无效，请修复本机 model-config.json 或环境配置。") from None

    def public(self):
        config = self.provider.config
        source = "injected" if self._injected else "environment" if self._environment else "file" if self.path.exists() else "default"
        return {"base_url": config.base_url, "model": config.model, "enabled": config.enabled,
                "has_api_key": bool(config.api_key), "is_local": config.is_local,
                "configured_by": source, "editable": not self._environment and not self._injected,
                "protocol": "chat-completions-json"}

    def update(self, base_url: str, model: str, api_key: str | None = None):
        with self._lock:
            if self._environment or self._injected:
                raise SettingsLocked("当前模型由环境配置管理，请修改该配置并重启，或移除它后使用网页设置。")
            previous = self.provider.config
            same_endpoint = base_url.rstrip("/") == previous.base_url.rstrip("/")
            key = api_key if api_key is not None else previous.api_key if same_endpoint else ""
            config = ModelConfig(base_url.strip().rstrip("/"), model.strip(), key)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"base_url": config.base_url, "model": config.model, "api_key": config.api_key}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                temporary.unlink(missing_ok=True)
            self.provider = ModelProvider(config)
            return self.public()
