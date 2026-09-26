# BenchRec 格式调研笔记（P1 输入，数据未到位）

> 调研日期：2026-09-26。handoff 定位：不作主战场，用于证明同一套对账引擎换域可用（跨域泛化证据）。

## 数据集身份

- 名称：**BenchRec: A Real-World Cash Reconciliation Dataset**
- 来历：Operartis 出品，ICAIF 2023（ACM International Conference on AI in Finance）基准竞赛数据
- 许可：**CC BY 4.0**（Kaggle 页面 License 栏目直接确认）
- 内容：真实 Tier 1 银行现金对账——**银行流水（B 类，外部对账单）vs 内部账（A 类，内部分录）**的交易匹配
- 规模（2026-09-26 本地核验，共 117 MB，4 个 CSV，各 27 列）：
  - `BenchRec_cash_v1.0_eval.csv`（25.85 MB，69,171 行数据，交易数据、无匹配标签）
  - `BenchRec_cash_v1.0_train.csv`（78.77 MB，149,854 行，含匹配标签）
  - `BenchRec_cash_v1.0_solution.csv`（6.72 MB，32,048 行：B_id → targetAllocation 金标准，Usage=Public）
  - `MatcherByChatGPT_submission.csv`（10.54 MB，32,048 行，官方示例提交：B_id, A_id, A_allocation, confidence, tfidf_cos, amt_diff, date_diff, explanation——提交格式现成范本）
- 交易时间范围：2023-01-20 ~ 2023-08-25；金额跨度极大（12 万 ~ 千亿级，疑似多币种含 VND 类高面值）
- 字段（train/eval 的 27 列）：matchId, matchDate, matchRule, matchedBy, wasPreviouslyMismatched,
  A_transactionType, A_id, A_allocation, A_importDate, A_debitOrCredit, A_amount, A_valueDate,
  A_currencyCode, A_account, A_transactionReferences, A_transactionAttributes,
  B_transactionType, B_id, B_importDate, B_debitOrCredit, B_amount, B_valueDate, B_currencyCode,
  B_account, B_transactionReferences, B_transactionAttributes, targetAllocation
  （A 侧=内部账，B 侧=银行流水；A/B 同列名成对出现，天然适合"同一引擎处理两侧"）

## 任务定义（对 P2/P4 匹配引擎设计最有价值的部分）

- 预测目标不是交易 ID，而是**分配键**：`A_allocation = currency + account + transaction attributes`
- 判对规则：预测分配集合 **等于或为真值集合的子集** 即算对（贴合真实对账"宁缺勿错"）
- 匹配形态：一对多 / 多对一均存在；B 交易允许无匹配（targetAllocation 为空）
- 评测：**精度硬门槛 99.8%**（生产要求 99.9%，因 0.2% 标签噪声下调），在达标前提下优化匹配率
- 官方建议基线：规则引擎 vs ML、Fellegi–Sunter、置信度打分、可解释匹配（审计向）
- 可见字段（eval 文件抽样）：matchId、matchDate、matchRule、matchedBy、wasPreviouslyMismatched、A_transactionType、A_id、A_allocation、A_importDate、A_debitOrCredit（DR/CR）等

## 获取渠道与状态

- 唯一公开托管：Kaggle `benchmarkteam/benchrec-real-world-cash-reconciliation-dataset`；无 HuggingFace/Zenodo/Figshare 镜像（2026-09-26 搜索确认）
- **下载状态：已解决（2026-09-26，用户手动下载并解压）**，落位 `data/raw/benchrec/`（gitignore，不入库）。
- 备查：未登录访问下载链接会被 302 重定向到 `kaggle.com/account/login?titleType=dataset-downloads`
  （curl 与内置浏览器双重验证）——Kaggle 数据集下载硬性要求登录账号。

## 对本项目的关系

- 域差异：BenchRec 是两方（银行流水 vs 内部账）现金对账；本项目主战场是三方（平台账单 × 订单 × 支付）。
  复用点是**确定性匹配引擎**（金额/日期/参考号的多键匹配 + 容差策略），不复用三方拼法。
- 计划用法（P4）：在 BenchRec 上重跑核心匹配引擎，报告跨域指标（自动匹配率、误报率），与 Olist 合成评测并列成表。
- 纪律：P1 只做格式调研与接入设计，不影响主战场进度。

## 数据到位后待补

- [x] 文件清单与体量（4 文件 117 MB）
- [x] 各文件行数核对（eval 69,171 / train 149,854 / solution 32,048 / submission 32,048）
- [x] 字段字典（train/eval 27 列表头已录；solution 仅 B_id→targetAllocation）
- [x] 匹配标签口径（targetAllocation = 分配键字符串：币种_日期_账户 + 参考号序列；
      判对规则 = 预测分配集合为真值集合的子集或相等，见"任务定义"）
- [ ] 与本项目匹配引擎的键映射表（P4 接入时做：金额↔A/B_amount、日期↔A/B_valueDate、
      参考号↔A/B_transactionReferences、币种↔A/B_currencyCode）

## 来源

- Kaggle 数据集页（标题与公开描述）
- GitHub `baymax-afk/Pramana_RZP_buildathon_reconciliation_agent` README 的 Attribution 段（许可、规模、基率；该仓库不含 BenchRec 数据文件，仅外链）
