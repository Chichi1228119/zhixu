# 知序检索评测报告

生成时间：2026-10-27T04:20:48.465939+00:00

固定题集：36 题；开发 0 / 留出 36。
题集 SHA256：`28e93a13c40c5edbd6b56b8f73f4aa43c9186eee940464666f7c1c2ac78833c8`

## 指标

| 划分 | 策略 | Hit@5 | Recall@5 | 完整来源@5 | MRR | 无依据拒答率 | 有依据误拒答率 | P95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev | hybrid | 未测 | 未测 | 未测 | 0.000 | 未测 | 未测 | 0.000 |
| dev | semantic | 未测 | 未测 | 未测 | 0.000 | 未测 | 未测 | 0.000 |
| holdout | hybrid | 64.3% | 62.5% | 60.7% | 0.643 | 62.5% | 35.7% | 2.097 |
| holdout | semantic | 60.7% | 58.9% | 57.1% | 0.607 | 100.0% | 39.3% | 11.390 |

## 指标边界

- 这是同一虚构业务域的固定合成题集，不代表真实企业数据上的泛化能力。
- Hit@5 表示至少命中一个预期文件，Recall@5 为召回预期文件比例的逐题平均；完整来源@5 要求所有预期文件均命中。三者按文件名计算，命中同文件的错误段落也可能得分，需逐题看原文。
- 关键词覆盖仅为参考答案词项是否出现在摘录中，不是语义正确率或人工核验结果。
- 引用有效性只检查原文与编号，不判断原文是否支持每个结论。
- 拒答、缺失说明和数字冲突使用启发式规则；报告保留误接受与误拒答。
- 默认三种策略共享 TF-IDF 相似度与词项覆盖候选门限；BM25 行是同门限下的排序消融，不是独立纯 BM25 基线。
- 延迟为预热后本地 Python 编排耗时，不含 HTTP、外部模型或真实企业规模负载。
- 本次模型 API 调用为 0，生成质量、真实 Token 费用及生产性能未测。
- 如含 semantic：使用本机 BGE-small-zh-v1.5、512维、固定0.65余弦门限；门限未在确认集调参，语义相似不保证答案充分，长文本可能截断。

## 失败或需复核题

### hybrid / confirm-002 / holdout / 拆开 SN200 包装后会拿到哪些供电配件，它要求的电压电流是多少？

参考：SN200 使用 USB-C 接口、5V / 2A 供电，包装内附数据线和电源适配器。

预期来源：products.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-003 / holdout / 要把采集结果接入自己的表格程序，导出 CSV 的四个列名分别是什么？

参考：两款设备导出的四个 CSV 字段均为 device_id、timestamp、temperature_c、humidity_pct。

预期来源：products.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-005 / holdout / 只想插线把数据拿出来，SN100 和 SN200 都能做吗？哪一款另外还能通过无线网同步？

参考：两款都可以 USB 有线导出 CSV；SN100 不支持 Wi-Fi，SN200 另外支持 2.4GHz Wi-Fi 同步到控制台，不支持 5GHz。

预期来源：products.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-011 / holdout / 机器已经送检了，我想追问进度并补一张图，要另开一张售后单吗？在哪里看？

参考：在星河控制台“支持中心—我的工单”查看维修进度；检测期间不要求重复新建工单，补充材料追加到原工单。

预期来源：service.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-014 / holdout / 人工首响已经超出规定目标，还没等来回复，我怎样要求升级处理，得重新填一遍单吗？

参考：在原工单点击“申请升级”，由当班支持负责人核查；无需重新提交相同工单。

预期来源：tickets.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-017 / holdout / 这周一天都没申请居家办公，下周能把没用的名额攒着一起用吗？

参考：不能。常规远程办公未用天数不能累计到下一周，每周最多 2 天。

预期来源：remote.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-018 / holdout / 在家上班时公司电脑坏到没法干活，我先做哪两件事？别把它当成卖给客户的设备报修。

参考：先通过内部 IT 服务单报障并通知直属主管；这与面向客户设备的支持工单不同。

预期来源：remote.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-019 / holdout / 新人领工作电脑的当天，除了机器还要拿到什么编号，并完成什么清单动作？

参考：首日领取公司电脑和资产编号，并核对资产清单、签收。

预期来源：onboarding.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-026 / holdout / 一台 SN200 放在试用团队里，它自身能存的条数与整个团队云上能存的条数分别是多少，是同一个限制吗？

参考：SN200 本地最多保存 50000 条，试用团队总云端配额为 20000 条、最多 3 台共享；本地与云端不是同一容量限制。

预期来源：products.md, trial.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-027 / holdout / 我从公司借 SN100 做现场演示，借出时台账填哪些信息，带走包装后还得自己准备电源适配器吗？

参考：台账登记设备序列号、借用人和预计归还日期；SN100 包装不附电源适配器，只附数据线，需准备符合 USB-C、5V / 1A 要求的供电。

预期来源：onboarding.md, products.md

实际来源：products.md, products.md；实际状态：answered

### hybrid / confirm-028 / holdout / 新人第一次要出差，导师说没问题就能直接订票吗？正式流程由谁批，至少提前几天交？

参考：不能以导师同意代替审批，导师不代替直属主管审批出差；出发前至少 2 个工作日提交申请，由直属主管批准后再预订交通和住宿。

预期来源：onboarding.md, travel.md

实际来源：无；实际状态：insufficient

### hybrid / confirm-030 / holdout / SN200 与控制台同步数据时具体用哪种传输加密算法，是 AES-256 吗？

参考：资料提供 Wi-Fi 同步能力，但没有传输加密协议或算法规格，不能确认 AES-256。

预期来源：无，应该拒答

实际来源：products.md, trial.md, trial.md；实际状态：answered

### hybrid / confirm-032 / holdout / 买到 SN100 后如果不喜欢，按这份服务约定能在多少天内无理由退货？

参考：服务约定没有列出退货期限，不能把保修期或到货异常时限当作退货期限。

预期来源：无，应该拒答

实际来源：service.md；实际状态：answered

### hybrid / confirm-034 / holdout / 星河智造员工申请育儿假要走哪个系统，直属主管最多几天内批准？

参考：当前员工资料没有育儿假系统或审批时限规定，不能用出差或远程办公流程代替。

预期来源：无，应该拒答

实际来源：onboarding.md, onboarding.md, remote.md, products.md, travel.md；实际状态：answered

### semantic / confirm-002 / holdout / 拆开 SN200 包装后会拿到哪些供电配件，它要求的电压电流是多少？

参考：SN200 使用 USB-C 接口、5V / 2A 供电，包装内附数据线和电源适配器。

预期来源：products.md

实际来源：无；实际状态：insufficient

### semantic / confirm-003 / holdout / 要把采集结果接入自己的表格程序，导出 CSV 的四个列名分别是什么？

参考：两款设备导出的四个 CSV 字段均为 device_id、timestamp、temperature_c、humidity_pct。

预期来源：products.md

实际来源：无；实际状态：insufficient

### semantic / confirm-004 / holdout / 实验桌边经常溅水，SN100 和 SN200 哪一个有防水能力？

参考：两款设备都不防水，使用环境须保持室内干燥，资料没有一款具备防水能力。

预期来源：products.md

实际来源：无；实际状态：insufficient

### semantic / confirm-005 / holdout / 只想插线把数据拿出来，SN100 和 SN200 都能做吗？哪一款另外还能通过无线网同步？

参考：两款都可以 USB 有线导出 CSV；SN100 不支持 Wi-Fi，SN200 另外支持 2.4GHz Wi-Fi 同步到控制台，不支持 5GHz。

预期来源：products.md

实际来源：无；实际状态：insufficient

### semantic / confirm-006 / holdout / 同一个团队之前领过试用，重新注册一下就能再领一轮吗？

参考：不能按该做法认定能再领；规则规定每个团队只能领取一次试用。

预期来源：trial.md

实际来源：无；实际状态：insufficient

### semantic / confirm-009 / holdout / 团队里谁有权拉人进来、把人移出，并导出全团队的数据？

参考：这些操作由管理员执行；观察员没有邀请成员或导出全团队记录的权限。

预期来源：trial.md

实际来源：无；实际状态：insufficient

### semantic / confirm-012 / holdout / 客户支持允许上传哪些附件格式？视频 MP4 在列出的格式里吗？

参考：列出的支持格式为 PNG、JPG、PDF、TXT；MP4 不在列出的支持格式中。

预期来源：tickets.md

实际来源：无；实际状态：insufficient

### semantic / confirm-017 / holdout / 这周一天都没申请居家办公，下周能把没用的名额攒着一起用吗？

参考：不能。常规远程办公未用天数不能累计到下一周，每周最多 2 天。

预期来源：remote.md

实际来源：无；实际状态：insufficient

### semantic / confirm-018 / holdout / 在家上班时公司电脑坏到没法干活，我先做哪两件事？别把它当成卖给客户的设备报修。

参考：先通过内部 IT 服务单报障并通知直属主管；这与面向客户设备的支持工单不同。

预期来源：remote.md

实际来源：无；实际状态：insufficient

### semantic / confirm-019 / holdout / 新人领工作电脑的当天，除了机器还要拿到什么编号，并完成什么清单动作？

参考：首日领取公司电脑和资产编号，并核对资产清单、签收。

预期来源：onboarding.md

实际来源：无；实际状态：insufficient

### semantic / confirm-026 / holdout / 一台 SN200 放在试用团队里，它自身能存的条数与整个团队云上能存的条数分别是多少，是同一个限制吗？

参考：SN200 本地最多保存 50000 条，试用团队总云端配额为 20000 条、最多 3 台共享；本地与云端不是同一容量限制。

预期来源：products.md, trial.md

实际来源：trial.md；实际状态：answered

### semantic / confirm-027 / holdout / 我从公司借 SN100 做现场演示，借出时台账填哪些信息，带走包装后还得自己准备电源适配器吗？

参考：台账登记设备序列号、借用人和预计归还日期；SN100 包装不附电源适配器，只附数据线，需准备符合 USB-C、5V / 1A 要求的供电。

预期来源：onboarding.md, products.md

实际来源：无；实际状态：insufficient

