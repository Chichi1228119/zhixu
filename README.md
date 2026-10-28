# 知序 · 个人与小团队的资料检索和引用核对

![知序工作台主体的实际运行截图](docs/assets/workspace.png)

截图展示工作台主体；团队模式另有登录、空间选择和管理入口。

[English](README.en.md) · [完整安装与使用指南](docs/user-guide.md) · [代码注解](docs/code-walkthrough.md) · [团队部署与恢复](docs/enterprise-operations.md) · [HTTP API](docs/api.md) · [贡献指南](CONTRIBUTING.md) · [安全边界](SECURITY.md)

把 PDF、DOCX、Markdown 和 TXT 变成可搜索、可核对的知识空间。默认个人模式无需账号即可在本机检索和摘录；显式开启团队模式后，使用账号、空间成员和角色控制共享范围。两种模式都可选本机 BGE 语义检索，以及自己运行的生成模型或兼容服务。

知序 1.2.0 面向个人、研究者和受控小团队，重点是来源可核对、行为可解释、失败可复现。团队模式是**单组织、小团队部署基础**，不宣称生产成熟、SSO、多组织 SaaS、高可用或安全合规认证。引用存在也不代表结论正确。

## 选择运行方式

| 方式 | 使用场景 | 数据与权限 |
| --- | --- | --- |
| 默认个人模式 | 可信本机上的个人资料整理与学习 | 无登录；当前资料目录中的 `knowledge.db` |
| `--enterprise` 团队模式 | 同一组织内、经授权的小团队试部署 | 先初始化管理员；账号登录、独立空间数据库与服务端角色校验 |

不要把默认无登录的个人模式通过反向代理共享给团队。团队部署使用独立资料目录、`--enterprise` 和 HTTPS 反向代理；详见 [部署与恢复](docs/enterprise-operations.md)。原个人 `data/knowledge.db` 不会自动迁入或共享给团队空间。

## 三种能力，分别选择

| 能力 | 默认行为 | 是否需要模型或 key |
| --- | --- | --- |
| 字面检索 + 原文摘录 | BM25 与 TF-IDF 经 RRF 排序，返回真实片段 | 默认可用，无需生成模型或 key |
| 本机语义检索 | 可选 BGE-small-zh-v1.5，512 维，固定 0.65 余弦门限 | 需可选依赖与本地权重，无需外部 API key |
| 依据资料生成 | 可选兼容 Chat Completions 服务，保留引用和错误提示 | 本机 loopback 服务可无 key；远端要求 HTTPS 与 key |

检索方式和回答方式互相独立。语义检索负责匹配资料，不会自行生成答案；相似度不是正确概率。生成失败或响应不符合约定时保留原文摘录，并显示降级警告。

## 从源码启动

```sh
git clone https://github.com/Chichi1228119/zhixu.git
cd zhixu
```

要求 Python 3.12+。先下载源码并进入包含 `pyproject.toml` 的目录。当前尚未发布 PyPI 包，不使用 `pip install zhixu`。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\zhixu.exe --version
.\.venv\Scripts\zhixu.exe serve --data-dir .\data --model-dir .\models --no-browser
```

Linux / macOS：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/zhixu --version
.venv/bin/zhixu serve --data-dir ./data --model-dir ./models --no-browser
```

打开 <http://127.0.0.1:18765>，在前台终端按 `Ctrl+C` 停止。CLI 只接受回环地址，默认不打开浏览器；`--no-browser` 是兼容选项。默认不会导入示例：上传自己的无敏感资料即可开始。

需要示例时，在上述启动命令末尾增加 `--demo`；完整 CLI 形式为 `zhixu serve --data-dir ./data --model-dir ./models --demo --no-browser`。它只在新资料库导入 8 份明确标为虚构的「星河智造」资料，也可从文档页面恢复演示。演示制度不是真实公司承诺。

| 参数 | 作用 |
| --- | --- |
| `--data-dir` | 可写资料目录；个人库为 `knowledge.db`，团队库见下方；默认当前工作目录的 `data/` |
| `--model-dir` | 可选模型缓存；默认资料目录同级的 `models/` |
| `--host` / `--port` | 默认 `127.0.0.1:18765`，不接受公网监听地址 |
| `--demo` | 只为新的个人资料库导入虚构示例；团队空间由可写成员显式添加示例 |
| `--enterprise` | 启用账号和空间权限；必须先初始化管理员；也可由 `ZHIXU_ENTERPRISE=1` 启用 |

CLI 显式路径优先于 `ZHIXU_DATA_DIR` / `ZHIXU_MODEL_DIR`。评测报告默认放在资料目录同级 `reports/`，可用 `ZHIXU_REPORT_DIR` 指定。运行数据与安装资源分开，不应写入 site-packages；更换目录前先停止服务并备份自己的资料。Windows 的双击启动/停止脚本是本地便利入口，跨平台说明以 CLI 为准。

## 团队模式：先初始化，再授权

在已安装依赖的源码环境或发行 wheel 环境执行。Windows PowerShell：

```powershell
.\.venv\Scripts\zhixu.exe admin init --data-dir .\team-data --username owner
.\.venv\Scripts\zhixu.exe serve --enterprise --data-dir .\team-data --model-dir .\models --port 18769 --no-browser
```

Linux / macOS：

```sh
.venv/bin/zhixu admin init --data-dir ./team-data --username owner
.venv/bin/zhixu serve --enterprise --data-dir ./team-data --model-dir ./models --port 18769 --no-browser
```

`admin init` 用 `getpass` 交互输入并确认 12–128 字符密码，不接受命令行密码；账号须为 3–64 个 ASCII 字母、数字、`_`、`.` 或 `-`，大小写统一。没有默认密码、公开注册或网页初始化管理员。初始化会创建首位系统管理员和默认知识空间；已有账号时不会重新 bootstrap。

打开 <http://127.0.0.1:18769> 登录。系统管理员创建账号、空间并授权；没有空间成员关系的用户需等待授权。团队资料保存在 `team-data/workspaces/<服务端生成的空间ID>/knowledge.db`，身份、会话和审计在 `team-data/control.db`，不读取原个人库作为共享资料。

| 身份 | 获准空间读取、问答 | 导入、删除、添加示例 | 账号与成员授权 | 模型配置、全局评测 |
| --- | --- | --- | --- | --- |
| viewer | 是 | 否 | 否 | 否 |
| editor / 空间 admin | 是 | 是 | 否 | 否 |
| 系统管理员 | 所有空间 | 是 | 是 | 是 |

空间 admin 当前与 editor 的资料权限相同，不能管理全局账号。权限由 API 检查，禁用按钮不是安全边界。撤销成员关系从下一请求生效；停用、改密码或本机重置密码会吊销该账号全部会话。切换空间清空当前页面的旧问答与引用，不能撤回此前复制、下载或备份的内容。

审计只保存身份、空间、动作、对象、结果、时间和请求 ID，可通过响应 `X-Request-ID` 关联动作；不保存密码、密钥、问题或文档原文。本机文件系统管理员仍能改动 SQLite，因此它不是不可篡改审计。

忘记密码时，由掌握资料目录权限的可信维护者执行以下命令，再交互输入新密码：

```text
zhixu admin reset-password --data-dir ./team-data --username owner
```

这里的 `zhixu` 指上述虚拟环境入口；普通用户也可在登录后验证旧密码并修改自己的密码，成功后需重新登录。密码使用 Argon2id；服务会话为有期限的随机令牌，数据库只保存令牌摘要。浏览器使用 HttpOnly / SameSite Strict Cookie，修改请求还要会话 CSRF 令牌。

团队对外使用继续让应用监听回环地址，配置 HTTPS 代理及实际的 `ZHIXU_PUBLIC_URL`；不要开放匿名个人端口、添加任意 Host 通配符或关闭证书校验。只启一个应用 worker，当前索引缓存不跨 worker 同步。[运维文档](docs/enterprise-operations.md) 提供部署模板和适用边界；模板存在不代表已在你的服务器验收。

## 备份与恢复

以下命令使用虚拟环境中的 `zhixu`：

```text
zhixu backup create --data-dir ./team-data --output ./backups/team-snapshot.zip
zhixu backup restore --archive ./backups/team-snapshot.zip --destination ./restored-team
zhixu serve --enterprise --data-dir ./restored-team --port 18770 --no-browser
```

备份拒绝覆盖同名归档，恢复只接受新的或为空的目录。归档包含允许的 SQLite、可选模型配置及大小/SHA256 清单，逐库检查完整性；模型权重、日志和运行依赖不在其中。控制库备份移除会话，恢复后所有用户重新登录，不复用原 Cookie；创建备份不会退出源服务的用户。

这是**逐数据库一致性**，不是控制库与所有空间的同时点事务快照。需要严格同时点恢复时，先停止应用再备份。归档可能含资料、密码哈希和明文 API key，**没有加密**，必须放入受控加密存储。恢复后验证登录、成员权限、文档和原文问答；一次 ZIP 成功不能替代恢复演练。详见 [恢复步骤和边界](docs/enterprise-operations.md)。

## 使用与模型设置

1. 在「知识文档」上传文件；重复字节内容去重。
2. 在问答页选择资料范围并提问，点引用核对文件和原文位置。
3. 可下载本次问答的 Markdown 快照。文档更新或删除后重新提问，旧快照不会自动撤回。

个人模式可直接打开模型设置；团队模式仅系统管理员可以配置或测试全局模型服务。填写你已运行服务的基础地址和实际模型名。服务必须支持 OpenAI 兼容 `/chat/completions`、`response_format: {"type":"json_object"}`，并能按要求返回 `answer`、`source_ids`、`status`；仅宣称“兼容聊天 API”不保证完全符合本项目协议。

- 本机地址，例如 `http://127.0.0.1:1234/v1`，允许留空 key；知序不负责安装或启动生成模型服务。
- 非回环地址要求 HTTPS 和 key。选择生成时，问题和检索片段会发送给设置的服务，请先核对目标并获得资料使用许可。
- key 保存在本机资料目录的配置文件中，不回显到配置响应，不存入浏览器持久存储或问答快照。它是本机明文配置，不是系统钥匙串；不要提交、同步或共享该文件。
- `RAG_BASE_URL`、`RAG_MODEL`、`RAG_API_KEY` 可由服务进程环境配置；环境管理时网页设置不可覆盖，修改后需重启。
- 「测试已保存连接」会真实请求已保存的服务，只发送固定合成文本；远端可能收费。一次连接测试通过不代表所有问题都能正确回答。

无来源时提示资料不足。模型错误、超时或非法引用不会被包装成成功生成；降级后应读警告并核对原文。小模型可能忽略条件或无法稳定输出协议，真实质量取决于模型、资料和任务；本项目不作跨模型保证。

## 可选本机 BGE

源码环境安装 semantic extra：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -e ".[dev,semantic]"
.\.venv\Scripts\python.exe scripts/download_model.py
```

```sh
# Linux / macOS
.venv/bin/python -m pip install -e '.[dev,semantic]'
.venv/bin/python scripts/download_model.py
```

下载是显式联网操作。脚本遵循运行路径设置；在源码根目录、无环境覆盖时写 `./models/`，与上述 `--model-dir ./models` 对应。自定义缓存时可设置 `ZHIXU_MODEL_DIR`，确保下载与服务指向同一目录。正常问答以 `local_files_only=True` 加载、CPU 2 线程，不自动下载。权重不随源码或 wheel 分发；来源和许可见 [第三方说明](docs/third-party.md)。

## 文件边界

单文件最多 10 MiB；提取文字最多 200 万字符。PDF 最多 200 页，内容流解压有 8 MiB 单流、24 MiB 累计预算及 Form 嵌套限制；不支持加密 PDF 或扫描 OCR。DOCX 提取正文段落和表格行，以段落/表格位置引用，**不提供 Word 页码**；有 ZIP 成员与解压预算，空文档、仅图片或宏文件不支持。旧 `.doc` 不能靠改扩展名转成 DOCX。

这些限制不是进程沙箱，没有解析进程硬超时。个人模式仍无登录；团队模式提供单组织的账号和空间授权，但不提供多组织租户隔离、SSO/SCIM、MFA、HA、联网搜索或 Agent 工具执行。可信部署、监控、目录权限和恢复演练仍由操作者负责。详见 [SECURITY.md](SECURITY.md)。

## 测试、构建与评测

在源码目录运行：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe scripts/evaluate.py
```

```sh
# Linux / macOS
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/python scripts/evaluate.py
```

wheel 输出在 `dist/`，可安装具体的本地 wheel 文件；不代表已经发布到 PyPI。CI 配置、实际平台验证和测试数量应以当前提交的真实执行结果为准，历史测试总数不代替 1.2.0 的发布验收。不要把本机通过冒充远程 CI 绿灯或生产认证。

已有历史合成检索实验如下，均按文件来源统计，未衡量真实生成答案正确率：

| 题集与策略 | Hit@5 | 来源 Recall@5 | 完整来源@5 | 无依据拒答 | 有依据误拒答 |
| --- | --- | --- | --- | --- | --- |
| 原 64 题中的 44 题 holdout，三种字面策略结果相同 | 91.2% | 88.2% | 85.3% | 7/10 | 3/34 |
| 另 36 题 confirmation，hybrid | 64.3% | 62.5% | 60.7% | 5/8 | 10/28 |
| 另 36 题 confirmation，semantic | 60.7% | 58.9% | 57.1% | 8/8 | 11/28 |

Hit 表示至少命中一份预期文件；Recall 是逐题计算已召回预期文件比例后取平均；完整来源要求全部参考文件出现。错段落仍可能得文件分。44 题 holdout 含 34 道有依据与 10 道无依据题；36 题 confirmation 含 28 道有依据与 8 道无依据题，两组不能直接当同一次优化前后对比。

三种字面策略共享候选门限，没有融合质量提升证据。BGE 在确认组更保守，也漏答更多，不能说总体更好。题集是同一虚构业务域的人工合成问题，不是严格统计独立或外部生产基准；引用存在和词项覆盖不等于语义正确。见 [确认协议](docs/semantic-confirmation-protocol.md)。复现 semantic 确认可运行 `scripts/evaluate_semantic.py`，须先准备模型；保留首次确认，不按结果调题或挑最好一次。

## 参与项目

从 [贡献指南](CONTRIBUTING.md) 开始；报告问题请用无敏感信息的最小样例，安全问题按 [安全说明](SECURITY.md) 处理。社区遵循 [行为规范](CODE_OF_CONDUCT.md)。代码采用 [MIT License](LICENSE)，依赖与模型各自许可见 [第三方说明](docs/third-party.md)。

学习代码可看 [架构说明](docs/architecture.md)、[9 课学习手册](docs/learning-guide.md) 和 [面试练习](docs/interview-guide.md)。部分材料记录早期教学版本，阅读时以当前源码和 CLI 为准。AI 辅助实现应如实说明，不把项目包装成真实企业上线经历。
