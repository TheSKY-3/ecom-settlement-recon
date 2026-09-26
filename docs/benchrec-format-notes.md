# BenchRec 格式调研笔记（P1 输入，数据未到位）

> 调研日期：2026-09-26。handoff 定位：不作主战场，用于证明同一套对账引擎换域可用（跨域泛化证据）。

## 数据集身份

- 名称：**BenchRec: A Real-World Cash Reconciliation Dataset**
- 来历：Operartis 出品，ICAIF 2023（ACM International Conference on AI in Finance）基准竞赛数据
- 许可：**CC BY 4.0**（Kaggle 页面 License 栏目直接确认）
- 内容：真实 Tier 1 银行现金对账——**银行流水（B 类，外部对账单）vs 内部账（A 类，内部分录）**的交易匹配
- 规模（页面 Data Explorer 实测，Version 3，共 121.87 MB、68 列、4 个文件）：
  - `BenchRec_cash_v1.0_eval.csv`（25.85 MB，交易数据、无匹配标签）
  - `BenchRec_cash_v1.0_solution.csv`（匹配金标准）
  - `BenchRec_cash_v1.0_train.csv`
  - `MatcherByChatGPT_submission.csv`（官方示例提交）
- 交易时间范围：2023-01-20 ~ 2023-08-25；金额跨度极大（12 万 ~ 千亿级，疑似多币种含 VND 类高面值）

## 任务定义（对 P2/P4 匹配引擎设计最有价值的部分）

- 预测目标不是交易 ID，而是**分配键**：`A_allocation = currency + account + transaction attributes`
- 判对规则：预测分配集合 **等于或为真值集合的子集** 即算对（贴合真实对账"宁缺勿错"）
- 匹配形态：一对多 / 多对一均存在；B 交易允许无匹配（targetAllocation 为空）
- 评测：**精度硬门槛 99.8%**（生产要求 99.9%，因 0.2% 标签噪声下调），在达标前提下优化匹配率
- 官方建议基线：规则引擎 vs ML、Fellegi–Sunter、置信度打分、可解释匹配（审计向）
- 可见字段（eval 文件抽样）：matchId、matchDate、matchRule、matchedBy、wasPreviouslyMismatched、A_transactionType、A_id、A_allocation、A_importDate、A_debitOrCredit（DR/CR）等

## 获取渠道与状态

- 唯一公开托管：Kaggle `benchmarkteam/benchrec-real-world-cash-reconciliation-dataset`；无 HuggingFace/Zenodo/Figshare 镜像（2026-09-26 搜索确认）
- **下载状态：登录墙实测确认（2026-09-26）**——未登录访问下载链接，服务端 302 →
  `kaggle.com/account/login?titleType=dataset-downloads`（curl 与内置浏览器双重验证）。缺的只是已登录账号，不是工具能力。
- 三条解决路径（任选其一）：
  1. 在 ZCode 内置浏览器（已停在 Kaggle 登录页）登录一次 → 由我继续点下载并收文件
  2. 手动：常用浏览器登录 Kaggle 下载 zip → 放入 `data/raw/benchrec/`
  3. CLI：`pip install kaggle` + `~/.kaggle/kaggle.json` 凭证后
     `kaggle datasets download -d benchmarkteam/benchrec-real-world-cash-reconciliation-dataset -p data/raw/benchrec --unzip`

## 对本项目的关系

- 域差异：BenchRec 是两方（银行流水 vs 内部账）现金对账；本项目主战场是三方（平台账单 × 订单 × 支付）。
  复用点是**确定性匹配引擎**（金额/日期/参考号的多键匹配 + 容差策略），不复用三方拼法。
- 计划用法（P4）：在 BenchRec 上重跑核心匹配引擎，报告跨域指标（自动匹配率、误报率），与 Olist 合成评测并列成表。
- 纪律：P1 只做格式调研与接入设计，不影响主战场进度。

## 数据到位后待补

- [x] 文件清单与体量（页面实测：4 文件 121.87 MB，见上）
- [ ] 下载落盘后：各文件行数核对
- [ ] 字段字典（A 侧 / B 侧 / solution 标签表全 68 列）
- [ ] 匹配标签口径（targetAllocation 的具体格式；子集判对规则的实现）
- [ ] 与本项目匹配引擎的键映射表（金额/日期/参考号 ↔ BenchRec 字段）

## 来源

- Kaggle 数据集页（标题与公开描述）
- GitHub `baymax-afk/Pramana_RZP_buildathon_reconciliation_agent` README 的 Attribution 段（许可、规模、基率；该仓库不含 BenchRec 数据文件，仅外链）
