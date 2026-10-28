# 参与知序 / Contributing

欢迎修复可复现的问题、改善资料解析和来源核对、补充边界测试或改进文档。中文和英文均可。项目聚焦个人本机资料空间，默认无 key 可检索；多人平台、OCR、Agent 和复杂服务端部署需要先讨论独立范围。

## 开始之前

先阅读 [README](README.md)、[安全边界](SECURITY.md) 与 [行为规范](CODE_OF_CONDUCT.md)。问题报告请说明当前版本、平台和最小步骤，不提交真实工作资料、数据库、key 或个人日志。安全问题走安全报告流程，避免在普通 issue 中公开利用细节。

没有现成 issue 时，可以先描述具体问题、预期行为、最小方案和验证方法。小型文档修正或明确 bug 可以直接提交 PR；较大功能先讨论使用场景，避免同时重写相邻模块。

## 开发环境

在源码根目录，Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\zhixu.exe serve --data-dir .\data --model-dir .\models --demo --no-browser
```

Linux / macOS：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/zhixu serve --data-dir ./data --model-dir ./models --demo --no-browser
```

需要本地语义检索时安装 `.[dev,semantic]` 并按 README 显式准备模型。基础测试应可在没有真实生成服务和密钥时运行；需要实际模型的检查须单独说明，不以模拟协议测试代替。构建命令为虚拟环境解释器的 `-m build`。

## 做一个容易审查的修改

1. 写清问题和验收条件，先检查现有实现、依赖和测试，复用已有路径。
2. 保持 diff 聚焦；不顺手改格式、重构无关代码或加入未请求的平台功能。
3. 行为修改增加能说明风险的回归检查；bug 尽量先复现。文档修改检查命令、相对链接和中英一致性。
4. 运行与修改相关的检查，并在 PR 中填写真实命令和结果。未运行或被环境阻断时直说，不粘贴旧版“全部通过”。
5. 检查没有加入 `.env`、`model-config.json`、数据库、用户文档、模型权重、wheel 缓存、机器专属报告或敏感截图。

变更路径、配置或包资源时，还应构建 wheel，在新虚拟环境安装并从源码目录外运行；验证静态页面、示例和题集在安装后可定位，数据不写进 site-packages。声明跨平台支持时，区分已配置 CI 与真实通过的平台。

## 评测与引用约定

`evaluation/cases.json` 是原固定开发/留出题集；`evaluation/semantic-confirmation.json` 是另一组已冻结确认题。不要根据输出删难题、重写参考答案或扫描确认门限后只报最好结果。需要新实验时保留原题及哈希，另建有明确制定方式和冻结点的数据版本。

Hit@5、来源 Recall@5、完整来源、拒答和误拒答分开报告。文件命中、关键词出现或引用编号有效都不代表答案语义正确。真实生成测试应注明服务、模型、资料、响应与人工核对范围，不编造性能提升。

## PR 与协作

PR 应说明具体问题、最终行为、验证命令、剩余限制；涉及界面附无敏感内容的截图，涉及 API 或配置说明兼容性。使用 [.github/pull_request_template.md](.github/pull_request_template.md) 的清单。维护者可能要求缩小范围、补复现或暂缓不符合定位的功能；没有承诺合并或响应时限。

AI 辅助代码和文档可以贡献，请说明工具参与的范围，并由提交者检查正确性、来源与许可证。不要把未审查的模型输出或第三方代码改名成原创。贡献者应确保有权提交内容；项目代码贡献使用 [MIT](LICENSE)，第三方材料保留原始许可和来源。

English contributors: use the same workflow—small focused changes, a non-sensitive reproduction, truthful validation, no test-set tuning, and disclosure of AI assistance or third-party code. English issues and PRs are welcome.
