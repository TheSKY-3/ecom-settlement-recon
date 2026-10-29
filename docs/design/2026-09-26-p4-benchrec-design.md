# BenchRec 跨域接入设计（2026-09-26）

> 目的：同一套**确定性匹配思想**（多键 + 容差 + 宁缺勿错）换到银行现金对账域跑分，证明引擎不是只在自家合成数据上好用。与 Olist 主战场成绩并列成表。格式事实见 benchrec-format-notes（整理记录，未随仓库公开）。

## 1. 任务与判分（2026-09-26 实测数据确认）

- eval 文件：B 交易（银行流水）32,048 个 + A 交易（内部账）37,123 个混排，A 交易共享 22,779 个分配键（多分录同键）。
- 真值 solution.csv：每 B_id 一行；`targetAllocation` 为空（212 个）= 无匹配；以 `[` 开头 = JSON 数组（多分配，实测约 8.9%）；其余为单值串（≈95.8% 可在 A 池精确命中原值）。
- **判对 = 预测分配集合 ⊆ 真值集合（含双方皆空）**——"宁缺勿错"，与竞赛口径一致。
- 指标：精度 = 判对 / 做了匹配决策的 B；匹配率 = 做了决策的 B / 全部；总判对率 = 判对 / 全部。竞赛硬门槛：精度 ≥99.8%。

## 2. 匹配器（`src/benchrec/matcher.py`，v1 规则）

1. 索引：A 池按 `(currencyCode, account, amount)` 建桶（金额字符串原样精确相等；同键多 A 共存）。
2. 候选：B 取同桶 A；桶内按 `|A_valueDate − B_valueDate|` 升序。
3. 决策（保守）：候选为空 → 不匹配；最小日期差的候选集合若只含 1 个分配键 → 匹配之；多个分配键时若 B 参考号 token 与某候选的 A_transactionReferences 有包含关系可消歧则取之，否则**放弃匹配**（保精度）。
4. 输出：`{B_id: frozenset(分配键)}`——分配键取 A 行 `A_allocation` 原值。

## 3. 判分与对比（`src/benchrec/score.py` + `scripts/run_benchrec.py`）

- `load_solution()` 统一解析单值/数组/空三种形态。
- 同一判分器跑两个"提交"：我们的引擎输出 + 官方 `MatcherByChatGPT_submission.csv`（其 targetAllocation 列为 JSON 数组）→ 同台对比表。
- 报告 `docs/reports/p4-benchrec-report.md`：双引擎对比 + 99.8% 门槛参照 + 与 Olist 主战场指标并列。

## 4. 测试（全离线，手工小例子对拍）

- 判分：单值/数组/空真值 × 子集/相等/超集/空预测；JSON 数组真值解析。
- 匹配器：构造 3 A 2 B 的 mini eval（唯一命中 / 多键消歧 / 无候选放弃）。
- 数据未落位时测试跳过（与 Kaggle 无凭证纪律一致）。

## 5. 已知边界

- v1 只做金额精确匹配（官方基线 amt_diff=0.0 佐证足够）；金额容差、多 B 拼分配（一 B 多 A 部分分配）留待需要时再开。
- train.csv（有标签 14.9 万行）本阶段不用——评测以官方 eval+solution 为准，避免自造口径。
