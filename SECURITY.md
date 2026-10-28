# 安全说明 / Security policy

知序 1.2 提供默认个人模式与显式团队模式。个人模式无登录，只适用于可信本机，不应通过端口转发或代理共享给团队。`--enterprise` 提供单组织账号和空间授权，是受控小团队部署基础，不是多组织 SaaS、SSO、HA 或安全合规认证产品。安全修复优先当前开发分支和最新已发布版本（若有），不承诺历史版本支持期限或响应 SLA。

## 报告问题

如果当前仓库已启用 GitHub Private Vulnerability Reporting，请使用仓库 Security 页的私密报告入口。此文件不假设该入口已启用，也没有专用安全邮箱。

若没有私密入口，请先提交**不含利用细节、样本、用户数据或凭据**的 issue，标题可为“请求安全问题私密联系渠道”，等待维护者提供可用方式。不要在公开 issue、PR、截图或 CI 日志中贴出真实敏感资料。尚未建立私密渠道时，不应上传完整漏洞样本；这里不虚构邮箱或承诺处理时限。

私密报告准备内容：受影响版本/提交、平台、运行模式、前提条件、最小合成复现、预期/实际行为、影响范围，以及去除敏感信息的说明。请勿未经授权测试第三方服务，或提交会伤害他人设备与数据的样本。若 key 已暴露，先在相应服务撤销或轮换它，不要等待项目回复。

## 团队身份与权限

- 团队模式必须显式启用并先通过本机 `admin init` 初始化；没有默认密码、公开注册或匿名网页初始化。密码用 `getpass` 输入，不能写进命令行参数、脚本或公开示例。
- 账号按大小写统一，密码为 12–128 字符、最多 512 个 UTF-8 字节，使用维护的 Argon2id 实现。登录失败采用相同错误提示，无账号时也做密码校验；这不构成形式化的恒定时间证明。
- 同来源与规范化账号在滑动 15 分钟内最多累计 5 次失败，第 6 次受限；Argon2 并发也有上限。限速不替代代理侧连接控制、可信转发配置和监控。
- 会话令牌含 32 字节随机量，数据库只存 SHA256 摘要；默认期限 8 小时。Cookie 为 HttpOnly、SameSite Strict，设置 HTTPS 公共来源后启用 Secure。除登录外，团队模式的修改请求需要 Cookie 与 `X-CSRF-Token`。
- `viewer` 可读取和问答；`editor` 与空间 `admin` 可修改已授权空间的资料。只有系统管理员可以管理账号、空间成员、全局模型与评测。服务端逐请求检查权限，前端按钮不是权限边界。
- 撤权从下一请求生效；停用、修改或本机重置密码会吊销该用户全部会话。正常 API 不允许停用最后一个活跃系统管理员。撤权不收回已经读取、导出、下载或备份的内容。
- 企业控制库与每个空间的知识库分开；原个人 `knowledge.db` 不自动迁入共享空间。这是单组织内的空间控制，不是多租户隔离认证。

身份设计参考 [OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)、[会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) 与 [argon2-cffi API](https://argon2-cffi.readthedocs.io/en/stable/api.html)。参考资料、使用这些库或通过测试都不等于安全认证。

## 部署与审计

应用继续绑定回环地址。团队通过 HTTPS 反向代理访问，并显式设置实际的 `ZHIXU_PUBLIC_URL`；不要公开监听匿名个人模式，不要加入任意 Host 通配符或关闭证书校验。使用专用非管理员服务账号，限制数据目录访问，只启一个应用 worker；索引缓存不支持多 worker 同步。详见 [部署与恢复](docs/enterprise-operations.md)。

控制库在 POSIX 设置受限目录和文件权限，Windows 依赖 NTFS ACL。部署者必须核对实际服务账号和权限；源码中的 mode 设置不等于 Windows ACL 已经审核。操作系统管理员或恶意本机程序仍可能读取资料、密码哈希与本机设置。

应用审计保存动作所需的身份/空间/对象 ID、结果、时间与可选 `request_id`，不存密码、会话令牌、API key、问题或文档原文。可用响应 `X-Request-ID` 关联动作，但不是所有 HTTP 请求都会产生审计事件。审计不是不可篡改日志；保护日志、监控磁盘与异常访问，避免代理记录请求体或敏感认证头。

## 数据与模型边界

- 默认检索和摘录在本机运行；可选 BGE 编码也本地运行。模型下载是显式操作，正常语义查询不自动联网。
- 选择生成时，问题与当前授权空间的检索片段发送给配置的服务。回环服务可以无 key；远端要求 HTTPS 和 key。团队模式仅系统管理员可配置或测试服务；使用者仍需核对资料发送许可，不能把“本机优先”理解为选择任何远端后仍不出网。
- key 由服务端本机配置管理，响应不回显，不存浏览器持久存储；配置文件包含明文 key，不是加密保险箱。限制资料目录访问，避免网盘同步、Git 提交和屏幕分享。操作系统用户或恶意本机程序仍可能访问这些文件。
- 文件和模型输出是不可信数据。引用编号校验不是语义证明；系统提示也不保证免疫提示注入。当前没有给文档工具执行权限。
- 删除文档移除当前数据库片段并使索引失效；它不安全擦除磁盘、不删除原文件、不撤回旧导出快照或备份。

## 备份也是敏感数据

只恢复可信来源的归档。备份收集允许的 SQLite、模型配置与校验清单，不含模型权重、日志或完整运行环境；可能包含资料、密码哈希和明文 key，**没有加密**。用受控加密存储保护归档及传输，限制谁能读取和恢复。

控制库备份移除会话，恢复该备份后用户必须重新登录，不能恢复旧 Cookie 的权限。恢复只接受新的或为空的目标目录，不覆盖原资料。大小、SHA256 与 SQLite 完整性检查可以发现不一致和损坏，不能证明归档来源真实，也不是签名。逐数据库一致性不是跨空间同时点事务；严格恢复点需停服务后备份。定期按 [运维文档](docs/enterprise-operations.md) 演练登录、授权和资料恢复。

## 文件处理限制

上传上限为 10 MiB，另有字符、PDF 页数/内容流和 DOCX ZIP、节点、嵌套预算。DOCX 不支持宏、DTD/实体声明等受限内容；没有 OCR。预算降低部分异常文件风险，但解析没有隔离进程硬超时，也不保证对任意恶意文件的内存/CPU 资源隔离。安全复现使用合成最小文件，实际接入应结合组织的可信来源策略。

网页文本显示、Host/Origin 检查、CSP、角色和 CSRF 是分层限制，不替代 OS 隔离或独立安全审查。当前不含 SSO/SCIM、MFA、KMS、跨区域备援、高可用或多 worker 索引同步。部署模板和 CI 配置不证明已经上线、通过远程 CI、渗透测试或取得合规认证。

## English reporting and security summary

Use GitHub's private vulnerability reporting **if enabled for the actual repository**. No dedicated security email is currently specified. Otherwise, open an issue requesting a private channel without exploit details, sensitive files or credentials, and wait before sharing the full report. There is no promised response deadline.

Default personal mode has no login and must remain on a trusted local machine. Explicit `--enterprise` mode adds accounts and workspace roles within one organization. Bootstrap is a local, interactive command with no default password or public registration. It is a small-team deployment foundation, not production, SSO, multi-tenant, HA or compliance certification.

Passwords use Argon2id; random, expiring session tokens are stored only as digests. HttpOnly / SameSite Strict cookies and session CSRF tokens protect team requests; the configured HTTPS public origin enables Secure cookies. Permissions are enforced by APIs. Membership revocation applies on subsequent requests; disabling an account or changing/resetting its password revokes all its sessions. Copies and exports cannot be retracted.

Keep the application on loopback behind a correctly configured HTTPS proxy, use a dedicated service account and restricted filesystem permissions, and run one application worker. Audit entries contain bounded metadata and optional request IDs, not passwords, tokens, keys, questions or document text. A filesystem administrator can still alter the database: audit records are not tamper-proof.

Remote generation sends the question and excerpts to the administrator-configured endpoint. Local settings may contain plaintext keys. Backups may include documents, password hashes and keys; they are not encrypted. Control-database snapshots remove sessions so restored users sign in again. Restore only trusted archives into new or empty directories. Checksums are not signatures, and per-database consistency is not a cross-workspace transaction.

Upload budgets are not a process sandbox, and valid citations do not prove semantic correctness. Protect data, configuration, logs and backups; deployment templates and local tests are not security certification or evidence of remote CI success. Never test third-party systems without authorization.
