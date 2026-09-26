# ecom-settlement-recon（电商多平台结算对账 Agent）

对"平台账单 × 业务订单 × 支付流水"三方数据做确定性核对 + 差异归因的受约束 Agent。
选题决策、数据三层方案、技术架构与里程碑见 [handoff.md](handoff.md)（唯一事实源，先读它）。

## 当前状态（2026-09-26）

| 里程碑 | 状态 | 产出 |
|---|---|---|
| P0 数据底座 | ✅ 完成 | `data/olist.db`（9 表，177MB）+ [自然差异盘点报告](docs/natural-diff-report.md) |
| P1 差异注入规范 + BenchRec | ⏳ 未开始 | BenchRec 笔记见 [docs/benchrec-format-notes.md](docs/benchrec-format-notes.md)，数据下载待 Kaggle 凭证 |
| P2 确定性匹配引擎 | 未开始 | — |

P0 关键数字：两侧齐全订单金额一致率 **99.42%**（98089/98665），自然不一致 576 单（多付 367 / 少付 209）；
单边账自然样本：无明细 775 单、已送达但无支付 1 单；canceled/unavailable 已付 1234 单（269,735 BRL，
状态不一致/退款遗漏的 ground truth 种子）；重复结算与版本差异为零（纯注入区）。

## 本机复现

```bash
# 本机 Python 3.12：E:/py_anzhuang/python.exe（不在 PATH；也可用 uv run --python 3.12）
E:/py_anzhuang/python.exe scripts/build_db.py                # data/raw/*.csv -> data/olist.db，含行数/金额校验
E:/py_anzhuang/python.exe scripts/natural_diff_inventory.py  # 重新生成 docs/natural-diff-report.md
```

两个脚本均纯标准库，无第三方依赖。

## 目录

- `data/raw/` — Olist 9 张 CSV（gitignore，121MB）。来源：本机 `E:\eng_project\baxi\olist-biz-analytics\olist-biz-analytics\data\raw`（原始出处 Kaggle `olistbr/brazilian-ecommerce`）
- `data/olist.db` — SQLite 原始层（gitignore，由脚本构建）
- `sql/01_schema.sql` — 原始层 DDL，**P0 结构冻结基线**。有意不设 PK/UNIQUE 约束：加载永不丢行，重复键是待测量的异常
- `scripts/` — 建库与自然差异盘点脚本
- `docs/` — 盘点报告与调研笔记
- `data/synthetic/` —（P1）合成差异与 ground truth
- `src/matcher/`、`src/agent/`、`evals/` —（P2+）确定性匹配引擎、Agent 壳、评测

## 红线（handoff 第 3 节，不可违反）

1. 一律不用公司数据；`D:\eng_project\对账自动化\` 下全部为真实账单。
2. `对账自动化\如祺对账工具包\样例数据\` 里与真实账单同名的"样例"是**真实数据副本**，任何提交/演示不得包含。
3. 对外措辞只说"本地原型 + 合成数据评测"，不声称上线或真实业务 ROI。
