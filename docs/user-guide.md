# 完整安装与使用指南

## 先选个人模式还是团队模式

一个人整理资料、学习检索流程，使用默认个人模式即可，不需要账号或模型密钥。多人共享时选择 `--enterprise` 团队模式：先初始化管理员，再登录、分配空间和角色。两种模式的数据目录独立使用；不要把无登录的个人模式开放给同事或公网。

本项目不内置生成模型，也不要求购买 API 服务。默认答案是检索到的原文摘录；生成模型和 BGE 语义检索均为可选项。源码、wheel 不含 Python、模型权重和依赖缓存，首次安装依赖通常需要联网。

## 1. 安装环境和应用

当前实际验证环境为 64 位 Python 3.12。安装 Python 后，在终端检查 `py -3.12 --version`（Windows）或 `python3.12 --version`（macOS/Linux）。请从 [Python 官方网站](https://www.python.org/downloads/)获取运行时。

下载并解压项目源码，在包含 `pyproject.toml` 的文件夹打开终端。Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\zhixu.exe --version
```

macOS/Linux：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/zhixu --version
```

命令使用虚拟环境中 Python 的完整路径，不需要激活环境，也不需要修改 PowerShell 全局执行策略。只想运行时无需安装 `dev`；开发和测试使用 `pip install -e '.[dev]'`。

若下载的是应用 wheel，而不是源码，在新虚拟环境中安装这个具体文件：

```powershell
.\.venv\Scripts\python.exe -m pip install .\zhixu_knowledge_assistant-1.2.0-py3-none-any.whl
```

wheel 安装后无需进入源码目录。当前没有发布 PyPI 项目，不要用 `pip install zhixu` 代替上述步骤。

## 2. 启动个人工作台

```powershell
.\.venv\Scripts\zhixu.exe serve --data-dir .\my-data --model-dir .\models --no-browser
```

macOS/Linux 将可执行路径换成 `.venv/bin/zhixu`。打开 `http://127.0.0.1:18765`。终端保持运行，按 `Ctrl+C` 停止；普通重新启动会保留资料。CLI 默认不打开浏览器。

首次默认空库。点击“上传自己的资料”导入 PDF、DOCX、Markdown 或 TXT；也可点击“体验示例资料”导入 8 份清楚标为虚构的示例。`--demo` 参数仅在新资料库启动时导入示例，不会覆盖已有资料。

## 3. 完成一次资料问答

1. 在“知识文档”上传文件，等到出现文件名、类型和片段数。
2. 回到“问答工作台”，输入资料里确实有依据的问题。必要时点击“全部文档”缩小资料范围。
3. 默认选择“融合检索”和“本地摘录”，无需模型即可返回原文与来源。
4. 点击 `[1]` 等引用或右侧来源，核对原文位置和条件，再使用结论。
5. “导出 Markdown 回答”保存本次回答与来源快照。它不会随未来资料变更自动更新或撤回。

PDF 引用按页，文本按段，DOCX 按正文段落与表格行；DOCX 不提供 Word 页码。扫描 PDF、纯图片 Word 和旧 `.doc` 不支持 OCR。单文件最多 10 MiB，有解压和文字预算；限制不是进程沙箱。

完全相同字节内容会去重。同名但不同内容是两份资料，不会自动识别新旧版本；请先备份并保留自己的原文件，再整理过期资料。应用只保存提取后的文本，不保留原始 PDF/Word 二进制文件。

## 4. 配置可选生成模型

先确保你自己的模型服务已经启动。在工作台打开“模型配置”，填写实际基础地址和模型名称，再保存。

- 本机服务示例：`http://127.0.0.1:11434/v1` 或 `http://127.0.0.1:1234/v1`。预设只填地址，不会安装、下载或探测模型。
- 回环地址允许空 key；外部服务要求 HTTPS 与 key。地址不能包含用户名、密码、查询密钥或片段。
- 服务必须支持 Chat Completions 的 JSON 对象响应，并按提示返回正文引用、`source_ids` 和状态。仅支持普通聊天的服务可能无法通过校验。
- 点击“测试已保存连接”只发送固定合成文本，不发送已上传资料；外部服务可能收费。
- 问答框选择“模型生成”才会把问题和检索片段发给已配置服务。使用外部服务前核对目标和资料许可。

key 以本机配置文件保存，不回显、不写入浏览器持久存储；它不是系统钥匙串。地址改变时不继承旧 key，留空只在地址不变时保留已有 key。环境变量 `RAG_*` 或项目兼容 `.env` 存在时，网页配置为只读。

生成失败、超时或引用不合规时会显示明确警告并返回本地摘录。小模型可能漏条件或拒答错误，即使有引用也不能直接认定事实正确。

可选 BGE 的依赖与显式下载步骤见 [README](../README.md#可选本机-bge)。它只改变检索匹配，不负责生成，确认评测也没有证明它总体优于默认字面检索。

## 5. 初始化团队空间

为团队单独使用目录：

```powershell
.\.venv\Scripts\zhixu.exe admin init --data-dir .\team-data --username owner
.\.venv\Scripts\zhixu.exe serve --enterprise --data-dir .\team-data --model-dir .\models --port 18769 --no-browser
```

初始化会要求输入两次密码，至少 12 字符；输入时不回显字符是正常现象。用户名使用 3–64 位英文字母、数字、下划线、点或短横线，不含空格；用户名不区分大小写。没有默认密码，也没有网页公开注册。

管理员登录 `http://127.0.0.1:18769` 后，从“系统管理”创建普通账号和知识空间，再分配权限：

| 角色 | 可以做什么 |
| --- | --- |
| 只读成员 viewer | 查看获准空间的资料、提问与导出回答 |
| 编辑 editor / 空间管理员 admin | 上述操作，以及上传、删除和添加示例资料 |
| 系统管理员 | 访问所有空间，管理账号、空间授权、模型配置、全局评测与审计 |

空间 admin 当前不具有全局账号与授权管理权。未获任何空间的账号会看到等待授权提示。切换空间会清除页面旧答案与引用；撤销成员授权后，后续请求立即拒绝；停用账号或修改/重置密码会吊销其会话。

“修改密码”需要当前密码，成功后重新登录。忘记密码时，由有数据目录权限的维护者在本机运行：

```powershell
.\.venv\Scripts\zhixu.exe admin reset-password --data-dir .\team-data --username owner
```

不要重复 `admin init` 重置现有账号。面向其他电脑的团队部署须配置 HTTPS 反向代理；应用继续只监听回环地址。详见 [部署与恢复](enterprise-operations.md)。

## 6. 备份和恢复

```powershell
.\.venv\Scripts\zhixu.exe backup create --data-dir .\team-data --output .\backups\team-20261028.zip
.\.venv\Scripts\zhixu.exe backup restore --archive .\backups\team-20261028.zip --destination .\restored-team
.\.venv\Scripts\zhixu.exe serve --enterprise --data-dir .\restored-team --port 18770 --no-browser
```

归档应放在资料目录之外，不能覆盖同名归档；恢复只接受新的空目录。恢复包含资料和授权，活动会话被剥离，须重新登录。清单校验保证归档载荷符合记录，不证明来源可信；只恢复你信任并保管的备份。归档没有加密，可能含资料、密码哈希和模型 key，请存于受控加密存储。

在线备份只保证逐数据库一致。要求所有授权与资料位于同一停止时点时，先停止应用再备份。模型权重、Python、依赖和部署配置需要另行保管。完整恢复演练见 [运维说明](enterprise-operations.md)。

## 7. 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 找不到 `zhixu` | 确认已安装应用，并调用 `.venv` 中的完整路径；不要只装依赖后期待 CLI 自动出现 |
| 端口被占用 | 停止原服务，或用 `--port 18769` 等空闲端口；不要同时运行多个实例写同一资料目录 |
| 团队模式启动要求 bootstrap | 用同一个 `--data-dir` 完成 `admin init`，随后仍带 `--enterprise` 启动 |
| 登录成功却没有资料 | 检查管理员是否分配了空间，以及是否选择正确的空间；原个人资料不会自动共享 |
| 提示 401/403 | 会话可能过期、缺少权限或 CSRF 校验失败；重新登录，仍失败时联系管理员核对授权 |
| 模型选项未启用 | 核对实际模型名、key 和服务地址，保存后测试连接；先用本地摘录检查资料是否可检索 |
| Word 没有页码或提取为空 | DOCX 按段落/表格定位，不执行 Word 排版；纯图片、页眉页脚等不属于当前提取范围 |
| 有引用但回答不完整 | 打开原文核对条件与版本，缩小资料范围；检索命中不等于语义正确 |

开发者继续阅读 [代码注解](code-walkthrough.md)、[HTTP API](api.md)、[贡献指南](../CONTRIBUTING.md) 和 [安全边界](../SECURITY.md)。
