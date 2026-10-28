# 团队模式部署与恢复

这是单组织、小团队部署的基础版本，不是 SSO 平台、合规认证产品或高可用集群。使用企业模式时，必须先创建管理员；没有默认密码和公开注册。原个人模式仍可单机使用，不能把匿名个人模式代理给团队。

## 本机初始化和启动

先按 README 安装源码或本地发行 wheel。Windows PowerShell：

```powershell
.\.venv\Scripts\zhixu.exe admin init --data-dir .\team-data --username owner
# 交互输入并确认至少12字符的强密码；密码不会作为命令行参数。
.\.venv\Scripts\zhixu.exe serve --enterprise --data-dir .\team-data --model-dir .\models --port 18769 --no-browser
```

Linux/macOS 使用 `.venv/bin/zhixu` 执行相同子命令。打开 `http://127.0.0.1:18769` 登录，管理员从管理入口创建账号和知识空间，再为账号授予空间角色。不要把私人资料上传到演示用空间。账户停用会撤销现有会话；空间撤权从下一请求生效。忘记密码时，在拥有数据目录权限的可信本机执行 `zhixu admin reset-password --data-dir PATH --username owner`；这会吊销该账户所有会话。

| 身份 | 获准空间的读取/问答 | 导入/删除/示例 | 管理账号与空间授权 | 模型设置/全局评测 |
| --- | --- | --- | --- | --- |
| viewer | 是 | 否 | 否 | 否 |
| editor / 空间 admin | 是 | 是 | 否 | 否 |
| 系统管理员 | 所有空间 | 是 | 是 | 是 |

空间 admin 当前与 editor 拥有相同的资料操作权限；授权集中由系统管理员执行。成员权限在 API 层校验，前端禁用按钮只用于解释。无空间的用户登录后等待管理员授权。切换空间清除页面中的旧会话与引用；用户此前下载或复制的内容不会自动收回。

企业模式目录：

```text
team-data/
  control.db                         # 用户、会话、成员、审计
  workspaces/<server-generated-id>/knowledge.db
  model-config.json                  # 可选服务配置，可能含明文API key
```

原 `data/knowledge.db` 不自动迁入任何团队空间。需要共享时，由管理员明确导入获准材料。密码使用 Argon2id，服务会话有期限；浏览器 cookie 为 HttpOnly/SameSite Strict，修改请求还需要会话 CSRF 令牌。登录失败限速不能替代组织的网络边界和监控。审计保存身份、动作、对象和结果，不保存密码、密钥或问题/文档原文；同一机器的文件系统管理员仍能修改 SQLite，不能称为不可篡改审计。

## HTTPS 反向代理

应用继续监听 `127.0.0.1`。团队从 HTTPS 代理访问，并将 `ZHIXU_PUBLIC_URL` 设置为实际 HTTPS 来源；该值决定允许的 Host 和 Secure cookie。不要将 uvicorn 改为公开监听、添加任意 Host 通配符或关闭证书校验。

提供 [Caddy 示例](../deploy/Caddyfile.example) 和 [systemd 示例](../deploy/zhixu.service.example)。它们是待部署者按实际域名、服务用户和目录配置的模板；当前 Windows 验证不等于这些 Linux 服务配置已运行。Caddy 可为配置的域名管理 HTTPS，前提是 DNS、端口、网络和证书条件满足：[官方 HTTPS 文档](https://caddyserver.com/docs/automatic-https)、[反向代理说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。systemd 的目录和文件系统保护参考[官方执行环境文档](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)。

安装服务前，以专用非管理员系统账号准备目录和虚拟环境，先前台验证初始化、登录和权限，再配置进程管理。只启一个应用 worker；当前内存索引缓存不是跨进程同步索引。密钥文件、控制库和备份必须只对服务账号/维护者可读，Windows 使用 NTFS ACL，POSIX 使用受限目录与文件权限。不要复制开发机的登录 Cookie 或模型设置到公开仓库。

## 备份与恢复演练

```powershell
.\.venv\Scripts\zhixu.exe backup create --data-dir .\team-data --output .\backups\team-2026-10-27.zip
.\.venv\Scripts\zhixu.exe backup restore --archive .\backups\team-2026-10-27.zip --destination .\restored-team
.\.venv\Scripts\zhixu.exe serve --enterprise --data-dir .\restored-team --port 18770 --no-browser
```

归档不覆盖同名备份，恢复只接受不存在或为空的目标。它只收集允许的 SQLite、模型配置和清单；逐文件核验大小/SHA256，数据库执行完整性检查，不包含模型权重和日志。模型、运行依赖与部署配置需要另行保存。控制库快照会清空活动会话，源库不变，因此恢复后必须重新登录。备份仍可能包含资料、账号密码哈希和 API key，**不是加密归档**；应置于受控加密存储，并限制保留/传输权限。

SQLite 在线备份提供**逐数据库一致性**，不提供控制库与多个空间在同一瞬间的跨库事务快照。对授权与资料必须严格同时点一致的恢复点，应在停止应用后创建备份。恢复演练至少验证：管理员登录、空间列表、成员权限、资料数量、选定事实问答、随机原文片段，以及备份外的模型路径。不要用一次 ZIP 成功代替演练。

## 运维边界

- `/api/health` 可用于存活检查，匿名响应不含目录、进程或资料数量；它不证明生成服务可用或所有数据库完好。管理员连接测试只发送固定合成文本。
- 响应带 `X-Request-ID` 便于关联一次请求；审计按动作记录，不包含用户问题。进程访问日志、数据库增长、磁盘余量和备份失败需要部署者接入自己的监控。
- 限制代理请求大小、连接数和超时；根据实际硬件测量文档规模与并发。解析器预算不是进程隔离，恶意文件还需要组织的接入策略。
- 升级前先停止服务并备份，在新的数据目录验证新版本与恢复，再切换。当前没有自动数据库降级；不要让旧程序写新版本控制库。
- 本版本不包含 SSO/SCIM、MFA、KMS、跨区域备援、多 worker 索引同步、容器隔离或第三方渗透测试。部署模板没有替你完成上线、安全审查和合规责任。
