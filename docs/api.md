# 知序个人与团队 HTTP API

面向 1.2.x，默认个人模式地址 `http://127.0.0.1:18765`，无登录，只用于可信本机。显式 `--enterprise` 启用单组织账号与空间授权；须先用本机 CLI 初始化管理员，没有默认密码和公开注册。团队启动示例见 [运维文档](enterprise-operations.md)。两种模式不自动共享原个人资料库，CLI 始终只允许回环监听。

交互接口文档在 `/api/docs`，使用随包的本地 Swagger UI 资产，无需 CDN；机器定义为 `/openapi.json`。团队模式中两者都需要登录，不能通过接口文档绕过 Cookie、CSRF 或角色校验。本文示例的团队端口 `18769` 需按实际部署替换。

下列 JSON 是字段示意，不是某次真实模型质量或延迟结果。除文件上传外，修改请求使用 `Content-Type: application/json`。浏览器修改请求的 Origin 必须与 Host 同源；跨站请求返回 403。通过前置检查的常规响应带 `X-Request-ID`，可用于关联动作审计；部分请求体/Origin 前置拒绝可能没有该头，也不是每个 HTTP 请求都会产生审计事件。

## 接口总览

下表的“空间读取”包含 viewer、editor、空间 admin 和系统管理员；“空间修改”不含 viewer。系统管理员可访问所有有效空间。空间 admin 当前不具备全局账号或授权管理权限。

| 方法 | 路径 | 输入 / 行为 | 团队权限 |
| --- | --- | --- | --- |
| GET | `/api/health` | 匿名只返回存活、名称、版本、`enterprise`；登录后返回获准空间的数量和模型状态，不含进程信息或真实目录 | 匿名可读最小状态 |
| GET | `/api/auth/status` | 当前模式、登录状态、本人、CSRF 和获准空间 | 匿名可读模式状态 |
| POST | `/api/auth/login` | 账号密码换取 Cookie 和状态 | 匿名可登录，受限速 |
| POST | `/api/auth/logout` | 删除当前会话并清 Cookie | 已登录 + CSRF |
| POST | `/api/auth/password` | 验证旧密码并修改本人密码，吊销本人全部会话 | 已登录 + CSRF |
| GET | `/api/documents` | 当前空间资料列表，返回 `{"documents":[...]}` | 空间读取 |
| POST | `/api/documents` | multipart 单个 `file`；解析、去重和保存片段 | 空间修改 + CSRF |
| GET | `/api/documents/{document_id}` | 文档元数据和带位置的 `chunks` | 空间读取 |
| DELETE | `/api/documents/{document_id}` | 删除片段并使索引失效；返回 `deleted` 与 `id` | 空间修改 + CSRF |
| POST | `/api/demo/restore` | 显式添加包内虚构资料，重复字节去重 | 空间修改 + CSRF |
| POST | `/api/ask` | 问题、空间内资料范围、检索策略与回答模式 | 空间读取 + CSRF |
| GET | `/api/settings/model` | 脱敏全局配置，不返回 key | 系统管理员 |
| PUT | `/api/settings/model` | 保存模型设置，环境/注入管理时不可覆盖 | 系统管理员 + CSRF |
| POST | `/api/settings/model/test` | 只用固定合成文本测试已保存连接 | 系统管理员 + CSRF |
| GET | `/api/evaluation` | 全局合成题运行报告；可能附语义确认 | 系统管理员 |
| POST | `/api/evaluation/run` | 独立临时库运行原 64 题，不改用户资料 | 系统管理员 + CSRF |
| GET | `/api/lessons` | `{"lessons":[...]}` 学习卡 | 已登录 |
| GET | `/api/config-template` | 下载兼容环境配置示例 | 已登录 |
| GET | `/api/admin/users` | 公开账号元数据列表，不含密码哈希 | 系统管理员 |
| POST | `/api/admin/users` | 创建账号 | 系统管理员 + CSRF |
| PUT | `/api/admin/users/{user_id}/active` | 启用/停用并吊销该账号会话 | 系统管理员 + CSRF |
| POST | `/api/admin/workspaces` | 创建服务端生成 ID 的空间 | 系统管理员 + CSRF |
| PUT | `/api/admin/workspaces/{workspace_id}/members` | 添加或替换一名成员的角色 | 系统管理员 + CSRF |
| DELETE | `/api/admin/workspaces/{workspace_id}/members/{user_id}` | 撤销该空间成员关系 | 系统管理员 + CSRF |
| GET | `/api/admin/audit` | 元数据审计分页 | 系统管理员 |
| GET | `/`、`/static/{path}` | 登录页与随包静态资源 | 匿名可读 |
| GET | `/api/docs`、`/openapi.json` | 接口文档与 schema | 已登录 |

个人模式只有 `/api/auth/status`，返回 `{"enabled":false,"authenticated":false}`；其他身份/管理路由仅在团队模式注册。个人资料、模型等既有接口不要求团队 Cookie 或角色，不能作为匿名团队服务使用。

## 团队登录、会话与空间

初始化在本机执行 `zhixu admin init --data-dir PATH --username owner`，用 `getpass` 输入密码，不提供 HTTP bootstrap。创建账号须为 3–64 个 ASCII 字母、数字、`_`、`.` 或 `-`；账号大小写统一。新密码为 12–128 字符、最多 512 个有效 UTF-8 字节。没有默认密码。

POST `/api/auth/login` 接收 `{"username":"实际账号","password":"交互获取的密码"}`；不要将真实密码硬编码进脚本、URL 或日志。成功设置 `zhixu_session` Cookie，并返回以下结构：

```json
{
  "enabled": true,
  "authenticated": true,
  "user": {"id": "服务端账号ID", "username": "owner", "is_admin": true, "active": true},
  "csrf_token": "当前会话的随机CSRF令牌",
  "workspaces": [{"id": "服务端空间ID", "name": "团队知识库", "created_at": "UTC时间", "role": "admin"}]
}
```

GET `/api/auth/status` 在未登录时仅返回 `{"enabled":true,"authenticated":false}`，登录后返回上述状态。Cookie 为 HttpOnly、SameSite Strict，默认有效期 8 小时；配置 HTTPS `ZHIXU_PUBLIC_URL` 后使用 Secure Cookie。服务端只存会话令牌摘要，不返回密码哈希。

除登录外，团队模式的 POST/PUT/PATCH/DELETE 均需 Cookie 与 `X-CSRF-Token`，因此 viewer 的 POST `/api/ask` 也需要 CSRF。401 表示未登录或会话失效；403 表示 CSRF、角色、空间或 Origin 不符合要求。账号不存在、密码错误和停用共用登录错误；滑动 15 分钟内同来源/账号 5 次失败后，第 6 次受限。429 也可能表示验证过载；登录失败窗口的响应含 `Retry-After: 900`。

资料接口通过 `X-Workspace-ID` 选择空间；省略时使用第一个获准空间，建议客户端始终显式指定。空间 ID 由服务端生成，客户端不能传文件系统路径。没有空间或没有成员权限时返回 403；其他空间的文档 ID 不会绕过当前空间的授权。`document_ids` 只在选定空间内部过滤。

仅个人模式的健康响应包含本机路径和实例信息。团队匿名健康响应不含这些信息或文档数量；已登录但没有任何获准空间时健康详情可能为 403，可先查询 `/api/auth/status`。

以下团队 Python 例子保留 Cookie，交互读取密码并设置 CSRF/空间头，不会连接生成服务：

```python
import getpass
import httpx

with httpx.Client(base_url="http://127.0.0.1:18769", timeout=30) as client:
    response = client.post("/api/auth/login", json={
        "username": input("账号：").strip(), "password": getpass.getpass("密码：")
    })
    response.raise_for_status()
    session = response.json()
    if not session["workspaces"]:
        raise RuntimeError("请先联系管理员授予空间权限")
    client.headers.update({
        "X-CSRF-Token": session["csrf_token"],
        "X-Workspace-ID": session["workspaces"][0]["id"],
    })
    response = client.post("/api/ask", json={"question": "资料介绍了什么？", "mode": "extractive"})
    response.raise_for_status()
    print(response.json()["answer"])
    client.post("/api/auth/logout").raise_for_status()
```

## 账号、授权和审计管理

- POST `/api/admin/users`：`{username,password,is_admin:false}`，返回 `id,username,is_admin,active,created_at`。仅系统管理员可创建；不会公开注册。
- PUT `/api/admin/users/{user_id}/active`：`{"active":false}`，返回 `{"ok":true}` 并吊销该账号所有会话。不能停用最后一个活跃系统管理员，冲突返回 409。
- POST `/api/admin/workspaces`：`{"name":"研究空间"}`，返回 `id,name,created_at`，名称 1–128 字符。没有客户端自选空间 ID 参数。
- PUT `/api/admin/workspaces/{workspace_id}/members`：`{"user_id":"实际账号ID","role":"viewer"}`。角色严格为 viewer/editor/admin，空间和用户须存在。返回 `{"ok":true}`；给成员空间 admin 不会将其升为系统管理员。
- DELETE `/api/admin/workspaces/{workspace_id}/members/{user_id}`：返回 `{"ok":true}`。撤权从下一请求生效；不撤回旧下载，系统管理员对有效空间仍保留访问权。
- POST `/api/auth/password`：`{current_password,new_password}`，成功返回 `{"ok":true}`、清当前 Cookie 并吊销本人全部会话；旧密码或新密码不符合要求返回 400。忘记密码由可信维护者运行 `zhixu admin reset-password --data-dir PATH --username NAME`，不提供无权限 HTTP 重置。

GET `/api/admin/audit?limit=50&offset=0` 返回 `{"events":[...]}`，按最新在前排序；limit 为 1–200，offset 为 0–1000000。事件字段为 `id,created_at,actor_id,action,workspace_id,target_id,outcome,request_id`；`id` 为递增整数，身份/空间/对象 ID 和 request_id 可为空，request_id 可与响应头关联。这里只存有界元数据，不存密码、会话令牌、API key、问题或文档原文；不构成不可篡改审计。

## 文档生命周期

上传 `file` 支持 PDF、DOCX、MD、TXT，单文件最多 10 MiB；multipart 请求另有小额封装预算，其他修改请求总量上限 32 KiB。解析失败为 400，超出请求/文件大小为 413；资源细限见 [架构](architecture.md)。相同字节 SHA256 返回已有文档并设 `existing=true`，不是按文件名覆盖。

文档元数据包含 `id, filename, kind, byte_size, chunk_count, created_at, sha256`。查看详情还包含 `chunks`：片段 `id`、`document_id`、文件名、`location`、`text`。PDF location 为页码，TXT/MD 为解析段落；DOCX 为正文段落或表格行，不是 Word 页码。

在有权限的当前空间中，不存在/已删除的文档 GET 或 DELETE 返回 404。删除不安全擦除磁盘，不撤回旧问答快照，不删除原电脑文件。新空库默认无示例；`--demo` 只在新的个人数据库播种。团队空间由有修改权限的成员显式调用示例恢复接口，不自动读取个人数据。

个人模式的跨平台 Python 请求示例（团队请求另需上节的会话和请求头）：

```python
from pathlib import Path
import httpx

with httpx.Client(base_url="http://127.0.0.1:18765", timeout=30) as client:
    with Path("demo.txt").open("rb") as stream:
        response = client.post("/api/documents", files={"file": ("demo.txt", stream, "text/plain")})
    response.raise_for_status()
    document_id = response.json()["id"]
    response = client.post("/api/ask", json={
        "question": "演示代号是什么？", "document_ids": [document_id], "mode": "extractive"
    })
    response.raise_for_status()
    print(response.json()["answer"])
```

先自行创建无敏感内容的 `demo.txt`。例子不会连接生成服务。

## 问答参数与响应

```json
{
  "question": "演示代号是什么？",
  "top_k": 5,
  "document_ids": [],
  "strategy": "hybrid",
  "mode": "extractive"
}
```

| 字段 | 约束与默认值 |
| --- | --- |
| `question` | 必填字符串，去首尾空白，1–2000 字符；纯空白无效 |
| `top_k` | 整数 1–20，默认 5 |
| `document_ids` | 默认空数组表示全部；最多 50 个非空 ID，每个最多 100 字符；未匹配的 ID 不产生来源 |
| `strategy` | `hybrid`（默认）、`bm25`、`tfidf`、`semantic`；semantic 需本机模型就绪 |
| `mode` | `extractive`（默认）或 `llm`；未启用生成配置请求 llm 为 503 |

通常响应含 `id, question, answer, status, mode, sources, metrics, trace, warning, usage`。来源含片段和文档 ID、文件名、位置、原文与检索分数；不同策略分数不是同一量纲，也不是正确概率。`metrics` 区分检索、生成与总耗时，模型失败的尝试也可能计入 `generation_ms`。

`status` 为 `answered`、`insufficient`、`conflict`；它是程序/模型判定，不是人工语义核验。没检索到来源直接返回 `insufficient` 和空来源，不调用生成模型。若有来源且选择 llm，模型输出必须是 JSON object，含正文 `answer`、合法 `source_ids` 和状态；正文引用集合需一致，不能仅含编号。无引用的 `insufficient` 允许空 `source_ids`。编号校验不证明事实蕴含。

生成请求失败后，问答接口以 HTTP 200 返回原摘录和明确警告；不要把 HTTP 200 等同于生成成功。响应节选：

```json
{
  "answer": "以下为检索到的原文摘录：\n\n[1] 演示代号为星舟。",
  "status": "answered",
  "mode": "extractive",
  "generation_error": "模型服务请求超时，请稍后重试或切换本地摘录。",
  "warning": "模型生成未通过，已返回本地原文摘录。请核对来源后使用。",
  "usage": null
}
```

此处 status 保留摘录的状态，不额外伪造 `fallback=true` 字段；客户端用 `mode`、`generation_error` 和 warning 区分降级。未配置模型、语义模型未就绪等 503 则是调用前的错误，不属于这个 200 降级路径。

## 模型设置与密钥

GET `/api/settings/model` 的状态示意：

```json
{
  "base_url": "http://127.0.0.1:1234/v1",
  "model": "your-local-model",
  "enabled": true,
  "has_api_key": false,
  "is_local": true,
  "configured_by": "file",
  "editable": true,
  "protocol": "chat-completions-json"
}
```

PUT 示例（本机服务、无需 key）：

```json
{
  "base_url": "http://127.0.0.1:1234/v1",
  "model": "your-local-model",
  "clear_api_key": true
}
```

- `base_url` 最多 2048 字符，`model` 最多 200，`api_key` 可省略/null、最多 4096；额外字段不接受。基础地址不能夹带用户名、密码、query 或 fragment。
- 本机回环地址允许 HTTP 或 HTTPS，无 key 也可启用；远端地址须 HTTPS，且有非空 key 才启用。保存一个未满足启用条件的配置可能返回 `enabled=false`，不代表连接已通过。
- 地址未变且省略/null key 时保留旧值；地址变化时不转移旧 key。传空字符串或 `clear_api_key=true` 清除。GUI 默认不回填旧 key。
- 配置存 data 目录 `model-config.json`，为本机明文文件；响应不回显 key，不存浏览器持久存储。团队中这是系统管理员管理的全局配置，供各授权空间使用；保护目录权限，不提交配置。
- 有 `RAG_*` 环境覆盖或注入 provider 时 `editable=false`，PUT 返回 409；启动读取的 `.env` 也作为环境管理。环境变更需重启，GUI 文件设置保存后即时生效。

POST `/api/settings/model/test` 不接收用户资料，使用已保存配置发送固定合成事实，并核对指定回答与引用。成功返回 `ok, model, latency_ms, message`；失败返回 502，即使服务能回复普通聊天也可能不通过协议。测试外部服务可能产生费用；一次通过不是广泛质量保证。

## 常见错误

| HTTP | 例子与处理 |
| --- | --- |
| 400 | 不支持/损坏文件、无效模型地址或配置；错误说明在 `detail` |
| 401 | 团队模式未登录、会话过期/吊销，或登录凭据错误 |
| 403 | 跨站 Origin、CSRF、角色或当前空间成员权限不符合要求 |
| 404 | 文档不存在或已删除 |
| 409 | 模型配置由环境管理、评测正在进行，或试图停用最后一个活跃系统管理员 |
| 413 | 文件/请求体超限 |
| 422 | 缺必填字段、问题太长、非法模式/策略、设置含额外字段；只返回位置、类型、消息，不回显提交值 |
| 429 | 登录失败限速或身份验证繁忙；按响应提示稍后重试 |
| 500 | 无法保存本机模型设置；检查可写目录 |
| 502 | 模型连接测试失败；问答中的生成失败采用上文摘录降级 |
| 503 | 生成未配置，或本机 semantic 不可用 |

例如空问题的参数错误结构：

```json
{
  "detail": [
    {"loc": ["body", "question"], "type": "string_too_short", "msg": "String should have at least 1 character"}
  ]
}
```

具体文字可能随依赖版本变化，客户端优先检查 HTTP、`detail` 与字段位置；不应将用户输入、密码、CSRF 或 key 写进日志。个人健康响应含本机路径与实例信息，公开报告前应脱敏。团队认证也不替代部署安全：通过 HTTPS 代理访问、限制服务账号权限、保护明文模型设置，并按 [备份恢复步骤](enterprise-operations.md) 维护逐库一致的备份。标准控制库备份移除会话，恢复后重新登录，原个人资料不会自动变成团队共享资料。
