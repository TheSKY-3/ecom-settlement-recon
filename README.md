# ecom-settlement-recon（电商多平台结算对账 Agent）

对"平台账单 × 业务订单 × 支付流水"三方数据做确定性核对 + 差异归因的受约束 Agent。
选题决策、数据三层方案、技术架构与里程碑见 [handoff.md](handoff.md)（唯一事实源，先读它）。

## 当前状态（2026-09-26）

| 里程碑 | 状态 | 产出 |
|---|---|---|
| P0 数据底座 | ✅ 完成 | `data/olist.db`（9 表，177MB）+ [自然差异盘点报告](docs/natural-diff-report.md) |
| P1 评测集冻结 | ✅ 完成 | [注入规范 v1](docs/injection-spec-v1.md) + `data/synthetic/`（干净/脏三本账 + 1,750 条标准答案） |
| 工作台 v1（2026-09-26 新增） | ✅ 完成 | `src/workbench/`（FastAPI 只读接口 + 静态前端）+ `对账工作台.exe` 薄启动器 |
| P2 确定性匹配引擎 | ⏳ 未开始 | — |
| P3 Agent 壳（自研受约束循环 + DeepSeek） | 未开始 | — |
| P4 全量评测 + BenchRec 跨域 | 未开始 | BenchRec 数据已落位 `data/raw/benchrec/` |

P1 关键数字：冻结考卷 = 六类雷共 **1,750** 颗（单边账 700 / 金额不符 500 / 状态不一致 150 /
退款遗漏 200 / 重复结算 100 / 版本差异 100），全部带标准答案；造数模块 22 个 pytest 全绿。

P0 关键数字：两侧齐全订单金额一致率 **99.42%**（98089/98665），自然不一致 576 单（多付 367 / 少付 209）；
单边账自然样本：无明细 775 单、已送达但无支付 1 单；canceled/unavailable 已付 1234 单（269,735 BRL，
状态不一致/退款遗漏的 ground truth 种子）；重复结算与版本差异为零（纯注入区）。

## 对账工作台（本地网页）

双击项目根目录的 **`对账工作台.exe`**（或 `启动对账工作台.bat`）→ 自动启动本机服务并打开浏览器
（`http://127.0.0.1:8770`，只监听本机）。三个页面：概览（冻结评测集数字 + 六类差异分布）、
标准答案（1,750 颗雷筛选/搜索/翻页，点行看该订单在五本账的原始记录）、关于（架构与口径）。
关闭服务控制台窗口即退出。exe 只有 7MB，只是启动器——代码与数据都在项目目录，改完刷新浏览器即生效。

```bash
# 首次或依赖变更后：安装 Web 层依赖（数据管道本身仍是纯标准库）
E:/py_anzhuang/python.exe -m venv .venv        # 已有 .venv 可跳过
.venv/Scripts/python.exe -m pip install -r requirements.txt
# 重新构建启动器 exe（仅启动逻辑，需要 requirements 里的 pyinstaller）
.venv/Scripts/python.exe scripts/build_launcher.py
```

界面截图见 `docs/assets/workbench-*.png`；设计与风格依据见
[工作台设计文档](docs/superpowers/specs/2026-09-26-workbench-design.md)
（视觉谱系：[shadcn/ui](https://shadcncraft.com) 一脉的低装饰密集数据表 +
[2026 设计系统盘点](https://www.themasterly.com) 里 Carbon/Polaris 类企业工具风格 +
[对账类界面参考](https://dribbble.com/search/data-reconciliation)）。

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
- `src/workbench/` — 对账工作台（FastAPI 只读接口 + 静态前端；`src/synth` 与后续引擎仍是纯标准库）
- `launcher/` + `scripts/build_launcher.py` — exe 薄启动器及其构建脚本
- `src/matcher/`、`src/agent/`、`evals/` —（P2+）确定性匹配引擎、Agent 壳、评测

## 红线（handoff 第 3 节，不可违反）

1. 一律不用公司数据；`D:\eng_project\对账自动化\` 下全部为真实账单。
2. `对账自动化\如祺对账工具包\样例数据\` 里与真实账单同名的"样例"是**真实数据副本**，任何提交/演示不得包含。
3. 对外措辞只说"本地原型 + 合成数据评测"，不声称上线或真实业务 ROI。
