# P2 设计：确定性匹配引擎（无 AI 判卷）

> 日期：2026-09-26。上游：[recon-agent-design.md](2026-09-26-recon-agent-design.md)（组件职责）、[injection-spec-v1.md](../injection-spec-v1.md)（P2 判分约定）、决定 D001/D002（无约束原始层、容差 ±0.005）。
> 本文把"引擎怎么判"钉到字段级：九种变体的判定谓词、发现（finding）的结构、判分口径。

## 0. 一分钟版

引擎读脏三本账 + 底座库，按**与 P1 同一份规则卡代码**（`src/synth/bills.py` 的金额公式）逐单核对，输出"发现"清单（六类归属 + 证据 + 置信度），再由判分器对照标准答案出分。全程无 AI 模型；规则树能提前画成流程图，所以是工作流不是智能体。

## 1. 判定规则树（字段级，与埋雷逐条对齐）

先按订单号把三本账装进内存视图（bills/payments/refunds 三个 `order_id → 行列表` 字典 + 订单/明细查底座库），然后：

| # | 条件（按顺序短路） | 判定 | 变体 | 目标侧 | 置信度 |
|---|---|---|---|---|---|
| 1 | 账单的 order_id 不在订单表 | 单边账 | 孤儿账单 | bills | 1.0 |
| 2 | 订单状态 ∈ {canceled, unavailable} 且有账单 | 状态不一致 | 取消单被开账单 | bills | 1.0 |
| 3 | 同上状态且支付已审批（有 order_approved_at）、有支付、无退款 | 退款遗漏 | 退款缺失 | refunds | 1.0 |
| 4 | 有明细的活跃订单，无账单、有支付 | 单边账 | 删账单 | bills | 1.0 |
| 5 | 有明细的活跃订单，无账单、无支付 | 单边账 | 账与支付均缺失 | bills | 0.8 |
| 6 | 同一订单出现多个版本号 | 版本差异 | 两版并存（按最高版对账） | bills | 1.0 |
| 7 | 同一订单同版本多张账单 | 重复结算 | 整单重复 | bills | 1.0 |
| 8 | 活跃订单有账单有明细但无支付 | 单边账 | 删支付 | payments | 1.0 |
| 9 | 单张 v1 账单金额 ≠ 规则卡期望（依次查：货款→佣金→运费→结算额） | 金额不符 | 货款不符 / **费率错误**（rate=0.10）/ 费率异常（其他率） / **漏运费**（freight=0）/ 运费不符 / 结算额不符 | bills | 精确形态 1.0，模糊形态 0.7–0.8 |
| 10 | 账单侧干净但 支付合计 ≠ 明细货款+运费 | 金额不符 | 支付与单据不符 | payments | 0.9 |
| 11 | 退款金额 ≠ 已付金额（取消单），或活跃订单出现退款 | 金额不符 | 退款金额不符 / 不该有的退款 | refunds | 0.8–0.9 |

要点：
- **顺序短路**：先形态（#1–#8）后金额（#9–#10）；账单侧异常命中就不再查支付侧金额——一单至多一条金额类发现，避免把同一笔错重复归因。
- **期望值 = 同一份规则卡代码**：`amounts_from_items()` 直接从 `src/synth/bills.py` 导入，引擎与造数共用一个金额公式，杜绝"两边口径漂移"。
- 期望支付 = 明细货款 + 运费（买家付全额）；期望账单结算额 = 货款 + 运费 − 0.20×货款（卖家应收）。两者不是一回事，比对对象不同。
- 容差 ±0.005（D002）。
- 退款期望：取消/不可达 **且审批通过** 的订单应全额退款（R3）；未审批的不产生期望。

## 2. 发现（finding）结构

与标准答案同构 + 引擎自有字段：
`finding_id, order_id, diff_type, variant, target_side, confidence, description, evidence(dict), verified(bool)`
- `evidence`：判定的决定性字段（bill_id 列表、期望/实际金额、费率等），逐条可人工复核。
- `verified`：验证器（verifier）独立重推每个谓词后的标记；推不回去 = 未验证。

## 3. 审计链

每步（装载/分类/验证/写出）记录：输入文件 SHA-256 + 行数、参数、输出指纹；每步哈希含上一步哈希，成链。结果文件里带链，篡改任何一步都会断链。实现 `src/engine/audit.py`（约 70 行，纯标准库 hashlib）。

## 4. 判分口径（对齐 injection-spec-v1）

- 检出（TP）= 发现命中标准答案的 `(order_id, diff_type)`；漏检（FN）= 答案有未报；误报（FP）= 报了答案没有。
- FP 再分桶：**命中 P0 自然差异口径**（重跑 `NATURAL_MISMATCH_SQL` 等 P0 查询得到的订单集合）vs 其他。预期：FP-自然 ≈ 576+（支付与单据不符+删支付类自然单），FP-其他 = 0 才算干净。
- 指标：六类各自的 TP/FN/FP + 检出率（recall）+ 精确率（precision，对 FP-其他口径）。

## 5. 产物与目录

```
scripts/run_engine.py ──▶ output/engine/findings.json / findings.csv（gitignore，可重生成）
                        └─▶ output/engine/score.json
                        └─▶ docs/reports/p2-engine-report.md（入库的成绩单）
src/engine/{audit,matcher,classifier,verifier}.py + evals/score.py
工作台新增 GET /api/engine、/api/engine/findings（引擎未跑时返回 available:false）
```

## 6. 测试策略

每模块独立小考卷（手工造几十行 CSV/SQLite），九种变体逐个断言"判得出、判得对、置信度对"；审计链断言"篡改即断链"；判分器用手工可算的小例子对拍。全量跑通作为集成验收（不进 pytest，进成绩单）。
