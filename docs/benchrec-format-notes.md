# BenchRec 格式调研笔记（P1 输入，数据未到位）

> 调研日期：2026-09-26。handoff 定位：不作主战场，用于证明同一套对账引擎换域可用（跨域泛化证据）。

## 数据集身份

- 名称：**BenchRec: A Real-World Cash Reconciliation Dataset**
- 来历：Operartis 出品，ICAIF 2023（ACM International Conference on AI in Finance）基准竞赛数据
- 许可：**CC BY 4.0**（第三方项目 README 的 Attribution 明确标注，作品集使用无许可风险）
- 内容：真实 Tier 1 银行现金对账——**银行流水 vs 内部账**的交易匹配
- 规模：约 40,001 条样本；匹配对基率约 **0.202**（口径来自第三方项目用其做 Fellegi–Sunter 校准时的表述）

## 获取渠道与状态

- 唯一公开托管：Kaggle `benchmarkteam/benchrec-real-world-cash-reconciliation-dataset`（页面为动态渲染，公开摘要之外的字段字典需下载后确认）
- **下载状态：受阻（2026-09-26）** —— 本机无 Kaggle CLI、无 `~/.kaggle/kaggle.json`、无环境变量凭证。
- 两条解决路径：
  1. 手动：登录 Kaggle 页面下载 zip → 放入 `data/raw/benchrec/`（最简单）
  2. CLI：`pip install kaggle` + API token 后
     `kaggle datasets download -d benchmarkteam/benchrec-real-world-cash-reconciliation-dataset -p data/raw/benchrec --unzip`

## 对本项目的关系

- 域差异：BenchRec 是两方（银行流水 vs 内部账）现金对账；本项目主战场是三方（平台账单 × 订单 × 支付）。
  复用点是**确定性匹配引擎**（金额/日期/参考号的多键匹配 + 容差策略），不复用三方拼法。
- 计划用法（P4）：在 BenchRec 上重跑核心匹配引擎，报告跨域指标（自动匹配率、误报率），与 Olist 合成评测并列成表。
- 纪律：P1 只做格式调研与接入设计，不影响主战场进度。

## 数据到位后待补

- [ ] 文件清单与各文件行数
- [ ] 字段字典（银行流水侧 / 内部账侧 / 标签表）
- [ ] 匹配标签口径（pair 如何定义正负样本；金额容差如何处理）
- [ ] 与本项目匹配引擎的键映射表（哪些字段映射到金额/日期/参考号）

## 来源

- Kaggle 数据集页（标题与公开描述）
- GitHub `baymax-afk/Pramana_RZP_buildathon_reconciliation_agent` README 的 Attribution 段（许可、规模、基率；该仓库不含 BenchRec 数据文件，仅外链）
