"""Loopback-only HTTP interface. Launch with uvicorn app.main:create_app --factory."""
from pathlib import Path
import ipaddress
import json
import os
import re
import threading
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool

from .lessons import LESSONS
from .limits import BodyLimitMiddleware
from .provider import ProviderError
from .model_settings import ModelSettings, SettingsLocked
from .paths import RuntimePaths
from .origins import canonical_origin
from .version import __version__
from .service import KnowledgeService
from .semantic import semantic_available, SemanticUnavailable

MAX_UPLOAD = 10 * 1024 * 1024


def load_local_env(path: Path):
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key in {"RAG_BASE_URL", "RAG_MODEL", "RAG_API_KEY"}:
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    mode: Literal["extractive", "llm"] = "extractive"
    strategy: Literal["hybrid", "bm25", "tfidf", "semantic"] = "hybrid"

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("请输入问题")
        return value.strip()

    @field_validator("document_ids")
    @classmethod
    def bounded_ids(cls, value):
        if any(not item or len(item) > 100 for item in value):
            raise ValueError("文档编号无效")
        return value


class ModelSettingsRequest(BaseModel):
    model_config = {"extra": "forbid"}
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=200)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False


def create_app(db_path: Path | None = None, seed_demo: bool | None = None, provider=None,
               report_path: Path | None = None, model_cache: Path | None = None,
               enterprise: bool | None = None):
    paths = RuntimePaths.discover(data_dir=Path(db_path).parent if db_path is not None else None,
                                  model_dir=model_cache)
    db_path = Path(db_path) if db_path is not None else paths.data_dir / "knowledge.db"
    fresh = not db_path.exists()
    model_cache = paths.model_dir
    if enterprise is None:
        enterprise = os.getenv('ZHIXU_ENTERPRISE', '0') == '1'
    security = None
    if enterprise:
        from .enterprise import EnterpriseBoundary
        security = EnterpriseBoundary(paths.data_dir, model_cache)
    service = None if security else KnowledgeService(db_path, model_cache=model_cache)
    instance_id = uuid4().hex
    if provider is None:
        load_local_env(paths.data_dir.parent / ".env")
    settings = ModelSettings(paths.data_dir / "model-config.json", provider=provider)
    if seed_demo is None:
        seed_demo = os.getenv("ZHIXU_SEED_DEMO", "0") == "1"
    if seed_demo and fresh and not security:
        for path in sorted(paths.demo_dir.glob("*")):
            if path.suffix in {".md", ".txt"}:
                service.import_document(path.name, path.read_bytes())
    application = FastAPI(title="知序 · 本地知识工作台", version=__version__, docs_url=None, redoc_url=None)
    application.state.service = service
    application.state.model_settings = settings
    application.state.enterprise = security
    if security:
        application.include_router(security.router())
    else:
        @application.get('/api/auth/status')
        def auth_status():
            return {'enabled': False, 'authenticated': False}
    allowed_hosts = ["127.0.0.1", "localhost", "[::1]", "testserver"]
    if security and security.public_host:
        allowed_hosts.append(security.public_host)
    bound_host = os.getenv("ZHIXU_HOST", "127.0.0.1")
    try:
        address = ipaddress.ip_address(bound_host)
        if address.is_loopback:
            allowed_hosts.append(f"[{address}]" if address.version == 6 else str(address))
    except ValueError:
        pass
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    report_path = Path(report_path) if report_path else paths.report_dir / "evaluation.json"
    evaluation_lock = threading.Lock()

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Pydantic includes submitted values by default; never echo a submitted API key.
        errors = [{"loc": item["loc"], "type": item["type"], "msg": item["msg"]} for item in error.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @application.middleware("http")
    async def local_boundary(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        if request.method in {"POST", "DELETE", "PUT", "PATCH"}:
            origin = request.headers.get("origin")
            if origin:
                expected_origin = security.public_origin if security and security.public_origin else canonical_origin(
                    f'{request.url.scheme}://{request.headers.get("host", "")}')
                if expected_origin is None or canonical_origin(origin) != expected_origin:
                    return JSONResponse({"detail": "已阻止跨站修改请求，请在本机工作台操作。"}, status_code=403)
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "请求长度无效。"}, status_code=400)
            if length > MAX_UPLOAD + 128 * 1024:
                return JSONResponse({"detail": "单个文件不能超过 10 MB。"}, status_code=413)
        if security:
            rejected = await run_in_threadpool(security.authorize, request)
            if rejected is not None:
                rejected.headers['Cache-Control'] = 'no-store'
                rejected.headers['X-Request-ID'] = request_id
                return rejected
        response = await call_next(request)
        if security:
            await run_in_threadpool(security.audit_response, request, response.status_code)
        response.headers['X-Request-ID'] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        if request.url.path == "/api/docs":
            response.headers["Content-Security-Policy"] = response.headers["Content-Security-Policy"].replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
        return response

    @application.get("/api/health")
    def health(request: Request):
        provider = settings.provider
        if security:
            user = getattr(request.state, 'user', None)
            if not user:
                return {'status': 'ok', 'name': '知序', 'version': __version__, 'enterprise': True}
            spaces = security.identity.workspaces_for(user['id'])
            selected = request.headers.get('X-Workspace-ID') or (spaces[0]['id'] if spaces else '')
            if not security.identity.membership(user['id'], selected):
                raise HTTPException(403, '当前没有可访问的知识空间。')
            current = security.service(selected)
        else:
            current = service
        documents = current.documents()
        result = {"status": "ok", "app_id": "zhixu-local-knowledge", "name": "知序", "version": __version__, "document_count": len(documents),
                "process_id": os.getpid(), "instance_id": instance_id,
                "chunk_count": sum(d["chunk_count"] for d in documents),
                "model": {"enabled": provider.config.enabled, "name": provider.config.model or None},
                "retrieval": "BM25 + TF-IDF · RRF", "data_location": str(db_path.parent),
                "semantic": {"available": semantic_available(model_cache), "model": "BAAI/bge-small-zh-v1.5", "dimensions": 512},
                "limits": {"file_mb": 10, "question_chars": 2000}, "demo": "星河智造（虚构资料，仅供项目演示）"}
        if security:
            result.pop('process_id')
            result.pop('instance_id')
            result['data_location'] = '当前授权的知识空间'
            result['enterprise'] = True
        return result

    @application.get("/api/settings/model")
    def model_settings():
        return settings.public()

    @application.put("/api/settings/model")
    def save_model_settings(body: ModelSettingsRequest):
        try:
            return settings.update(body.base_url, body.model, "" if body.clear_api_key else body.api_key)
        except SettingsLocked as error:
            raise HTTPException(409, str(error)) from None
        except ValueError:
            raise HTTPException(400, "模型配置无效。远程服务须使用 HTTPS；请勿在地址中包含密钥，并检查端口和密钥格式。") from None
        except OSError:
            raise HTTPException(500, "无法保存模型设置，请检查数据目录是否可写。") from None

    @application.post("/api/settings/model/test")
    def test_model_connection():
        provider = settings.provider
        started = time.perf_counter()
        try:
            result = provider.generate("连接测试代号是什么？", [{"filename": "连接测试.txt", "location": "第 1 段", "text": "连接测试代号为星舟。"}])
            if result["status"] != "answered" or "星舟" not in result["answer"]:
                raise ProviderError("服务已响应，但未通过固定资料的回答校验。请检查模型是否支持 JSON 对象和引用格式。")
        except ProviderError as error:
            raise HTTPException(502, str(error)) from None
        return {"ok": True, "model": provider.config.model, "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "message": "连接与固定资料回答校验通过；这不代表所有问题都能正确回答。"}

    @application.get("/api/documents")
    def documents(request: Request):
        current = request.state.knowledge_service if security else service
        return {"documents": current.documents()}

    @application.post("/api/documents", openapi_extra={"requestBody": {"content": {"multipart/form-data": {"schema": {
        "type": "object", "properties": {"file": {"type": "string", "format": "binary"}}, "required": ["file"]}}}}})
    async def upload_document(request: Request):
        async with request.form(max_files=1, max_fields=0, max_part_size=MAX_UPLOAD) as form:
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise HTTPException(400, "请选择一份文件上传。")
            try:
                content = await file.read(MAX_UPLOAD + 1)
                if len(content) > MAX_UPLOAD:
                    raise HTTPException(413, "单个文件不能超过 10 MB。")
                filename = (file.filename or "资料.txt").replace("\\", "/").split("/")[-1]
                current = request.state.knowledge_service if security else service
                result = await run_in_threadpool(current.import_document, filename, content)
                request.state.audit_target = result['id']
                return result
            except ValueError as error:
                raise HTTPException(400, str(error)) from None

    @application.get("/api/documents/{document_id}")
    def original_document(document_id: str, request: Request):
        try:
            return (request.state.knowledge_service if security else service).document(document_id)
        except KeyError:
            raise HTTPException(404, "文档不存在或已删除。") from None

    @application.delete("/api/documents/{document_id}")
    def delete_document(document_id: str, request: Request):
        request.state.audit_target = document_id if re.fullmatch('[a-f0-9]{32}', document_id) else None
        if not (request.state.knowledge_service if security else service).delete_document(document_id):
            raise HTTPException(404, "文档不存在或已删除。")
        return {"deleted": True, "id": document_id}

    @application.post("/api/demo/restore")
    def restore_demo(request: Request):
        current = request.state.knowledge_service if security else service
        imported = [current.import_document(p.name, p.read_bytes()) for p in sorted(paths.demo_dir.glob("*"))
                    if p.suffix in {".md", ".txt"}]
        return {"documents": imported}

    @application.post("/api/ask")
    def ask(body: AskRequest, request: Request):
        started = time.perf_counter()
        provider = settings.provider
        if body.mode == "llm" and not provider.config.enabled:
            raise HTTPException(503, "大模型未配置。当前可使用本地摘录；在模型设置中保存配置后可启用生成。")
        try:
            current = request.state.knowledge_service if security else service
            result = current.ask(body.question, top_k=body.top_k, document_ids=body.document_ids or None,
                                 strategy=body.strategy)
        except SemanticUnavailable as error:
            raise HTTPException(503, str(error)) from None
        result["id"] = uuid4().hex
        request.state.audit_target = result['id']
        if body.mode == "llm" and result["sources"]:
            generation_start = time.perf_counter()
            try:
                generated = provider.generate(body.question, result["sources"])
            except ProviderError as error:
                result["generation_error"] = str(error)
                result["warning"] = "模型生成未通过，已返回本地原文摘录。请核对来源后使用。"
                result["trace"].append({"label": "生成降级", "detail": str(error)})
            else:
                result.update(answer=generated["answer"], usage=generated["usage"], mode="llm", status=generated["status"])
                result["warning"] = "引用编号已校验；仍需核对资料是否支持每个结论。"
                result["trace"] = [step for step in result["trace"] if step["label"] != "回答方式"]
                result["trace"].append({"label": "依据资料生成", "detail": f"{provider.config.model} · 引用编号已校验 · 状态 {generated['status']}"})
            result["metrics"]["generation_ms"] = round((time.perf_counter() - generation_start) * 1000, 2)
        result["metrics"]["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    @application.get("/api/lessons")
    def lessons():
        return {"lessons": LESSONS}

    @application.get("/api/evaluation")
    def evaluation():
        if not report_path.exists():
            return {"available": False, "message": "尚无评测报告。点击运行评测，使用独立临时资料库生成。"}
        result = {"available": True, "report": json.loads(report_path.read_text(encoding="utf-8"))}
        semantic_report = paths.report_dir / "semantic-confirmation.json"
        if semantic_report.exists():
            result["semantic_confirmation"] = json.loads(semantic_report.read_text(encoding="utf-8"))
        return result

    @application.post("/api/evaluation/run")
    def run_evaluation():
        if not evaluation_lock.acquire(blocking=False):
            raise HTTPException(409, "评测正在进行，请稍后刷新。")
        try:
            from .evaluation import evaluate
            report = evaluate(paths.demo_dir, paths.evaluation_dir / "cases.json", report_path)
            return {"available": True, "report": report}
        finally:
            evaluation_lock.release()

    @application.get("/api/config-template")
    def config_template():
        return FileResponse(paths.config_template_path, media_type="text/plain", filename="env-example.txt")

    @application.get("/api/docs", include_in_schema=False)
    def api_docs():
        return FileResponse(paths.static_dir / "api-docs.html")

    @application.get("/")
    def index():
        return FileResponse(paths.static_dir / "index.html")

    application.mount("/static", StaticFiles(directory=paths.static_dir), name="static")
    application.add_middleware(BodyLimitMiddleware)
    return application
