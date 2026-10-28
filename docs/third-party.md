# 第三方组件与模型来源

知序的应用代码采用 [MIT](../LICENSE)。依赖、模型与运行时保留各自许可；本项目没有自行实现 PDF/DOCX 引擎、BM25、TF-IDF 或神经网络推理框架。实际依赖范围见 `pyproject.toml`，本地锁定版本另见 `requirements-lock.txt`。

## 应用与文档组件

| 用途 | 组件 | 官方来源 / 许可说明 |
| --- | --- | --- |
| HTTP 与服务 | FastAPI、Starlette、uvicorn | [FastAPI](https://fastapi.tiangolo.com/)、[Starlette](https://www.starlette.io/)、[uvicorn](https://www.uvicorn.org/) |
| PDF 文字提取 | pypdf | [官方文档](https://pypdf.readthedocs.io/) |
| DOCX 正文与表格 | python-docx | [官方文档](https://python-docx.readthedocs.io/en/latest/)、[MIT LICENSE](https://github.com/python-openxml/python-docx/blob/master/LICENSE) |
| DOCX XML 依赖 | lxml | 主项目 [BSD-3-Clause LICENSE](https://github.com/lxml/lxml/blob/master/LICENSE.txt)；二进制中相关组件按其 [LICENSES](https://github.com/lxml/lxml/blob/master/LICENSES.txt) 保留声明 |
| 账号密码哈希 | argon2-cffi、argon2-cffi-bindings | [官方文档](https://argon2-cffi.readthedocs.io/en/stable/)、[MIT LICENSE](https://github.com/hynek/argon2-cffi/blob/main/LICENSE)；底层 Argon2 与 CFFI 保留各自许可 |
| 字面检索 | rank-bm25、scikit-learn、NumPy、SciPy | [rank-bm25](https://github.com/dorianbrown/rank_bm25)、[scikit-learn](https://scikit-learn.org/)、[NumPy](https://numpy.org/)、[SciPy](https://scipy.org/) |
| 可选语义推理 | FastEmbed、ONNX Runtime、tokenizers | [FastEmbed](https://github.com/qdrant/fastembed)、[ONNX Runtime](https://onnxruntime.ai/)、[tokenizers](https://github.com/huggingface/tokenizers) |
| 模型 HTTP | httpx | [官方文档](https://www.python-httpx.org/) |
| 测试与打包 | pytest、setuptools、build | [pytest](https://docs.pytest.org/)、[setuptools](https://setuptools.pypa.io/)、[build](https://build.pypa.io/) |

上表是组件归属，不是将所有依赖重新许可为 MIT。安装的第三方 wheel 应保留原 LICENSE/NOTICE；自行重新分发依赖时需检查具体发行物及其传递依赖。

## 随包的本地 API 文档资产

`app/static/swagger/` 包含官方 `swagger-ui-dist` **5.34.0** 的 JS、CSS、LICENSE 与 NOTICE，许可为 Apache-2.0。来源是官方 npm 包，`scripts/vendor_swagger.py` 可重新获取并校验包 integrity；[provenance.json](../app/static/swagger/provenance.json) 记录包 SHA512 integrity 与各资产 SHA256。

保留的 [LICENSE](../app/static/swagger/LICENSE) 和 [NOTICE](../app/static/swagger/NOTICE) 随资产分发。接口页面使用这些本地资产，不依赖 CDN；这与可选生成模型是否联网是不同边界。

## 可选本地 BGE embedding

中文检索模型是 `BAAI/bge-small-zh-v1.5` 的 Qdrant ONNX 版本，模型卡标示 MIT；[原始模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[ONNX 来源](https://huggingface.co/Qdrant/bge-small-zh-v1.5)。原始项目许可副本为 [FlagEmbedding-MIT.txt](licenses/FlagEmbedding-MIT.txt)。

已核对的 ONNX 修订为 `46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59`，权重 94,781,076 字节，SHA256 为 `1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38`。它生成 512 维检索向量，不生成聊天答案。正常问答只从本机缓存加载，下载需显式运行安装脚本。

## 本机生成冒烟验证使用的外部模型与运行时

下列文件由维护者另行下载到本机用于真实 CPU 合成请求，不随公开源码或 wheel 打包，不代表内置模型或推荐质量等级：

| 项目 | 本机使用版本 | 官方来源与许可 |
| --- | --- | --- |
| Qwen3 | `Qwen3-0.6B-Q8_0.gguf`；修订 `23749fefcc72300e3a2ad315e1317431b06b590a` | [Qwen/Qwen3-0.6B-GGUF](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF)，Apache-2.0 |
| Qwen2.5 | `qwen2.5-1.5b-instruct-q4_k_m.gguf`；修订 `91cad51170dc346986eccefdc2dd33a9da36ead9` | [Qwen/Qwen2.5-1.5B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF)，Apache-2.0 |
| llama.cpp | 官方 Windows CPU x64 构建 `b11669`，提交 `620d2225cc436ab0b001e3200e590e3b286ef9ab` | [官方发布](https://github.com/ggml-org/llama.cpp/releases/tag/b11669)、[MIT LICENSE](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE)；所带 OpenMP 等二进制保留各自声明 |

权重与运行时已做来源/哈希核对。真实请求不等于质量通过：早期严格 JSON/引用契约存在失败，失败记录保留；后续通用格式示例下，1.5B 在两道合成题的实际 provider 调用中通过所检查的协议与事实。这只是冒烟验证，没有稳定性、跨模型、生产质量或性能保证。

## 公开发行边界

公开源码和应用 wheel 含应用、静态资源、虚构示例、题集与文档；不含 BGE/Qwen 权重、llama.cpp/Python 运行时二进制、依赖 wheel 缓存、个人资料库或模型密钥。历史 Windows 离线资源包继续保留在本地，但不是本次公开发行包，不能据此声称公开包提供了所有模型或跨平台运行时。

演示资料和固定题集是原创模拟内容，不使用真实公司资料。公开合成检索报告见 [字面基线](benchmarks/evaluation.md) 与 [语义确认](benchmarks/semantic-confirmation.md)；本机原始运行日志可能含路径，不直接作为公共发布材料。
