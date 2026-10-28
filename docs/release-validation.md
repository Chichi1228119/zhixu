# 1.2.0 发行验收

验证日期：2026-10-28。以下记录实际完成的范围，不是“无未知缺陷”或生产认证声明。

| 检查 | 实际结果 |
| --- | --- |
| 主环境单元、API、解析和安全回归 | Windows / Python 3.12.14：317 passed、3 skipped、0 failed |
| 跳过项 | 3 项 POSIX 文件权限检查在 Windows 跳过；不计作通过 |
| 安装依赖一致性 | `python -m pip check` 无冲突 |
| 发行包 | 实际构建源码分发与 `py3-none-any` wheel，含资源、CLI 和第三方许可 |
| 独立安装 | 新建并保留独立 venv，仅从本地 wheelhouse 安装应用及依赖；运行目录在源码之外 |
| 独立包 HTTP 验收 | 实际进程验证个人模式、包内示例、CLI 版本、企业初始化/登录、401、CSRF、viewer 403、空间隔离与授权问答；断言应用从新 venv 导入 |
| 安装后备份恢复 | 用安装包 CLI 实际创建/恢复，再启动恢复库 HTTP；旧 Cookie 确认随请求发送且被 401 拒绝，新登录和资料/权限检查通过 |
| 实际团队恢复演练 | 2 个空间、9 份资料（8 示例、1 DOCX），载荷哈希、原文/位置与权限一致；完整轮 39 项及 5 项只读复核通过 |
| 浏览器 | 实际验证管理员登录、空间切换清空旧答案、DOCX 上传/段落表格定位、只读账号仅见获准空间、上传/删除禁用及授权问答 |
| 本地 API 文档 | 浏览器实际加载随包 Swagger UI，显示 1.2.0 接口与模型；无需 CDN |
| 代码审查 | 修复合并单元格放大、配置 Host 与 CLI 不一致、HTTPS Origin scheme 边界和旧备份会话复活，并保留回归 |
| 公开资料 | 检查运行数据、模型、密钥、日志与个人目录不进入公开树；原始机器相关测试报告留在本地 |

主要复核命令：

```sh
python -m pytest -q
python -m pip check
python -m build --no-isolation
python scripts/verify_wheel.py --wheel-dir dist --find-links vendor/wheels
```

最后一条在提供 wheelhouse 时离线安装；公开仓库不附带本机依赖缓存，没有该目录时省略 `--find-links`，从正常索引安装。实际发行验收还保留了新 venv，用同一安装包分别执行 HTTP 与 CLI 检查，防止从源码误导入。

## 保留失败与边界

早期验收辅助脚本曾因安装/就绪等待上限、Windows launcher 与 worker PID 不同，以及清理时端口释放时序而中断。这些未完成轮次没有被写成通过。之后保留独立环境、核对导入来源、修正辅助脚本并完成真实 HTTP 验收。恢复演练保留全部三轮及归档，前两轮的辅助程序中断和在线期间控制库变化都有记录。

当前本机实际测试不等于另一台物理机器或公开生产部署。三平台 GitHub Actions 配置已经提供，远程运行状态以仓库 Actions 的实际结果为准，不用本机通过代替。Caddy/systemd 是部署模板，当前 Windows 验收没有执行 Linux 服务安装、真实域名证书签发、SSO、集群、并发容量或第三方渗透测试。

本机生成模型做过真实合成请求，早期小模型严格 JSON/引用契约失败记录保留；加入通用格式示例后仍只完成少量冒烟验证。不能将其说成跨模型正确率或稳定事实验证。历史检索数据的指标与失败见 [字面基线](benchmarks/evaluation.md)、[语义确认](benchmarks/semantic-confirmation.md) 和 [冻结协议](semantic-confirmation-protocol.md)。

备份仅逐数据库一致、不加密；哈希不是数字签名或来源认证。需要跨库严格同一时点时先停止服务。导入预算不是进程沙箱，运行约束与责任见 [安全说明](../SECURITY.md) 和 [团队运维](enterprise-operations.md)。
