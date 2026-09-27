# 对账 Agent 项目 Handoff（新工作区启动文档）

> 生成日期：2026-09-26
> 用途：本文档自包含全部已定决策与指针。新工作区建成后把本文件放入根目录，任何新会话读完即可开工，无需重新调研。
> 状态：选题已定，尚未动工（P0 未开始）。

---

## 1. 项目一句话定义

**电商多平台结算对账 Agent**：对"平台账单 × 业务订单 × 支付流水"三方数据做确定性核对 + 差异归因的受约束 Agent。

- 定位：求职作品集项目（"流程自动化 Agent"），不是对账行业从业方向。
- 与 ECom Review Intelligence（商品侧评论证据决策）组成作品集"电商经营双引擎"：一个管商品，一个管钱。
- 英文名建议：`ecom-settlement-recon` / E-Commerce Settlement Reconciliation Agent。

## 2. 选题决策记录（为什么是对账，为什么不是泛财务）

选题五条标准：①有真实流程理解 ②数据合规可得 ③价值可量化 ④命中目标 JD ⑤与现有作品集协同不重复。

- **只有对账同时满足五条**：实习期间亲手做过如祺月度对账（匹配键、结算判据、版本兼容、15 项验证，细节真实可讲）；数据可用公开集+合成；价值口径现成（工时+检出率）；命中"AI Agent 内部提效工具""数据交叉核对+自动化"类 JD；与 ECom 项目架构直接复用。
- **泛财务（报销/发票/凭证/报税）不选**：无真实流程经验、无合规数据、成熟商业产品占位难差异化。对账是财务大类里唯一有实战资产的子场景。
- **市场判断**：GitHub 上无头部对账 Agent 开源项目（多为 2–11 star 作品集级项目）；业界主流架构收敛为"确定性优先、LLM 兜底、审计留痕"——与本项目拟复用的 ECom 受约束架构同构，是差异化优势。
- 行业佐证：对账是企业高频刚性场景；Gartner 预测 2026 年 30%+ 大企业用数字员工辅助财务核算；多平台电商每月数十万流水、20+ 种账单格式、口径互不兼容。

## 3. 数据方案（三层，全部不涉公司数据）

### 第一层：Olist 巴西电商数据集（主底座，真实公开数据）

- 下载：https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce （9 张 CSV）
- 本地状态：**已解决（2026-09-26）**——全量 9 表存在于本机 `E:\eng_project\baxi\olist-biz-analytics\olist-biz-analytics\data\raw\`（121MB，行数与 Kaggle 发布版一致），已复制到本工作区 `data/raw/`，Kaggle 无需再下；旧项目 `D:\eng_project\olist-biz-analytics` 的 DDL/视图（MySQL 版）仍可参考。
- 对账三方拼法：
  - **支付流水侧** = `olist_order_payments`（单订单多行支付、分期，天然流水形态）
  - **业务单据侧** = `olist_orders` + `olist_order_items`（canceled/unavailable 状态、price + freight）
  - **平台账单侧** = 用 Olist 公开佣金/运费规则从 items 合成构造（平台账单无公开数据集，合成是唯一正路）
- 待验证：`payment_value` 与 items 总价（含运费）的自然不一致在数据集中真实存在多少，作为天然差异的第一批样本。

### 第二层：BenchRec（真实对账基准，第二域泛化验证）

- 下载：https://www.kaggle.com/datasets/benchmarkteam/benchrec-real-world-cash-reconciliation-dataset
- 来历：Operartis 出品、ICAIF 2023 基准竞赛，"Tier 1 银行现金对账（交易匹配）"，银行流水 vs 内部账。
- 用法：不作主战场；用于证明同一套对账引擎换域可用（架构泛化性证据）。

### 第三层：合成差异注入（评测集，项目价值核心）

在 Olist 底座上注入受控差异，雷区清单自实习对账框架抽象：

| 差异类型 | 说明 |
|---|---|
| 单边账 | 有支付无订单 / 有订单无支付 |
| 金额不符 | 含运费口径、拆分支付、多支付记录 |
| 状态不一致 | canceled/unavailable 但存在支付 |
| 退款遗漏 | 退款未回冲 |
| 重复结算 | 同一交易重复入账 |
| 版本差异 | 账单新旧版本（对应如祺"新版/旧版账单兼容"） |

关键优势：雷是自己埋的 → ground truth 已知 → 检出率/误报率/归因准确率可精确计算成评测表（公司数据既不能公开也无标签，合成数据在评测上反而更强）。

### 红线（不可违反）

1. **一律不用公司数据**。`D:\eng_project\对账自动化\` 下全部为真实账单（含 6/7 月结算账单、外部表）。
2. **特别注意**：`对账自动化\如祺对账工具包\样例数据\` 里文件名与真实账单一致的"样例"是**真实数据副本，不是脱敏样例**，任何公开仓库/演示不得包含。
3. 公司数据唯一可用形式：业务规则卡（匹配逻辑、结算判据可抽象写进合成设计），具体金额与字段不得带出。
4. 对外措辞：只说"本地原型 / 工程验证通过 + 合成数据评测结果"，不声称上线、不声称真实业务 ROI（与 ECom 项目口径一致）。

## 4. 技术架构（复用 ECom 已验证模式）

参考实现：`D:\eng_project\ecom-review-intelligence`（架构手册：知识库 `ECom-Review-Intelligence-KB\` 14 篇）。

- **确定性优先**：SQLite/FTS5 证据引擎 + 规则匹配引擎先跑；LLM 只做两件事——歧义单据归因、自然语言查账（如"上月 X 渠道佣金为什么比预估高 8%"）。
- **受约束单 Agent**：LangGraph + DeepSeek，工具路由 + tool ledger（预算）。
- **Verifier**：逐字段核对 + 引用校验，失败关闭、确定性降级。
- **双轨 Trace**：审计留痕（对账域必须，业界共识 hash-chained audit / cited evidence）。

## 5. 评测方法（复用 ECom P7 方法论）

- 指标：自动匹配率、差异检出率、误报率、归因准确率、对账耗时 vs 手工基线。
- 方法：与 P7 同构——同一任务集，手工基线 vs Agent 操作对比。
- 第二域：BenchRec 上重跑核心匹配引擎，报告跨域指标。

## 6. 建议里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0 | Olist 9 表下载入库（SQLite）+ 自然差异盘点 + 结构冻结 | data/raw 非空；自然差异报告 |
| P1 | 差异注入规范 v1 + ground truth 生成器；BenchRec 格式调研 | 评测集冻结，雷区清单成文 |
| P2 | 确定性匹配引擎 + 6 类差异分类器 + 验证器 | 无 LLM 情况下跑通全量对账 |
| P3 | Agent 壳（受约束规划 + 归因 + 自然语言查账） | LLM 仅出现在歧义路径 |
| P4 | 全量评测 + 评测表 + BenchRec 跨域验证 | 评测报告成文 |
| P5（可选） | 对账报告输出 / 极简工作台 | 视时间决定 |

## 7. 既有资产指针

| 资产 | 路径 | 用途 |
|---|---|---|
| 架构参考项目 | `D:\eng_project\ecom-review-intelligence` | 受约束 Agent 全套模式 |
| 架构手册 | `D:\个人知识库\个人知识库\吴柏高_个人知识库_01\ECom-Review-Intelligence-KB\` | 设计决策与复现文档 |
| Olist 旧项目 | `D:\eng_project\olist-biz-analytics`（data/raw 空，DDL/ETL 现成） | 数据底座 |
| 对账规则来源 | 知识库 `06_业务框架搭建\如祺月度对账框架.md`、`出租车抽佣计算框架.md`、`05_技能与自动化\WorkBuddy技能\ruqi-reconciliation\SKILL.md`（v2.3） | 差异类型与规则卡抽象（只取规则不取数据） |
| 简历叙事 | 知识库 `03_简历与求职\实习AI产品案例集复盘.md` 案例三 | 与本项目串联成"实习经验→Agent 作品"主线 |

## 8. 简历叙事定位（先定口径再动手）

- 主线：实习对账经验（真实细节）→ 抽象成通用对账 Agent（作品）→ 可量化评测（合成 ground truth）。
- 喂两类 JD：①"数据交叉核对 + 自动化 + AI 提效"结构；②"用 AI Agent 制作内部小工具 + 价值核算"。
- 已有实测口径（仅限实习叙述，需脱敏）："月度对账约 1 天 → 约 10 分钟（部门财务实测）"；本项目新产出一律用合成数据指标。

## 9. 开工清单（新工作区第一周）

1. 把本文件移入新工作区根目录；`git init`；建 README 与目录骨架（建议 `data/raw` gitignore、`data/synthetic`、`src/matcher`、`src/agent`、`evals/`、`docs/`）。
2. Kaggle 下载 Olist 9 张 CSV → `data/raw/`；跑自然差异盘点（payment_value vs items 总价）。
3. Kaggle 下载 BenchRec → 看格式，写一页格式调研笔记（不着急接入）。
4. 写差异注入规范 v0（雷区清单 + 注入比例 + ground truth 格式）。
5. 参照 `ecom-review-intelligence` 抄架构骨架（SQLite + FTS5 起步）。

## 10. 顺序纪律（重要）

知识库既有结论：ECom Review Intelligence 当前最重要的一步是**完成 P7 真人结构化试用**，不是开新坑。本项目排序在 P7 收尾之后（或经确认后小步并行），P0 前不写业务代码。

## 11. 进展日志

- **2026-09-26（工作台增补：账本可翻 + 用语去黑话）**：用户反馈"只能看数量、想翻账本" → ① 弹层三组对照（标准账本应有 vs 实际账本实有，红条标注埋错位置）；② "账本浏览"页签 `/api/rows/{world}/{book}` 通读六本账（搜索/分页/点行跳弹层，概览账本卡直达）；③ 界面用语去黑话（干净/脏世界 → 标准账本/实际账本）；④ 静态资源加版本参数防 Edge 缓存。96 pytest 全绿，截图两张。评测总报告与面试叙事稿见 docs/reports/evaluation-report.md、docs/interview-narrative.md。
- **2026-09-26（P4 完成，BenchRec 跨域验证）**：破译 BenchRec 真值格式后判分口径完全复刻（预测 ⊆ 真值，宁缺勿错）。`src/benchrec/` 确定性匹配器（金额精确分桶+日期贴近+参考号消歧+保守放弃）+ 判分器 + `scripts/run_benchrec.py`。**成绩：精度 99.67%/覆盖 84.6%/判对率 90.4%（1s 判完 32,048 笔）vs 官方 ChatGPT 基线 95.20%/64.9%/65.2%，全面胜出；距 99.8% 门槛差 0.13pp**。成绩单 `docs/reports/p4-benchrec-report.md`（含容差扫描与错配归因）。90 pytest 全绿。**主线 P0-P4 全部完成，可进入报告/叙事收束期。**
- **2026-09-26（P3 完成，受约束 Agent 壳）**：`src/agent/` 六件（llm/tools/guardrails/prompts/loop/attribute+ask）。护栏落地：答案数字/编号白名单校验（违规重试一次→降级模板）、预算 ≤2 次往返、trace.jsonl 留痕、无 key 全链路模板降级。ask 意图路由确定性——统计/类型例子模板直答，仅归因解释进模型。工作台接入：概览 AI 问答框 + 弹层"AI 归因解释"，答案带来源标签。**82 pytest 全绿（全离线）；真模型冒烟通过：归因过白名单、开放查询未编造、缺信息如实说"事实单未提供"**。DeepSeek key 位于 Windows 用户环境变量（已验证，V4.1 世代 flash 带 effort）。设计 spec：`docs/superpowers/specs/2026-09-26-p3-agent-design.md`（含已知边界）。**下一步：P4 全量评测 + BenchRec 跨域。**
- **2026-09-26（P2 完成，确定性匹配引擎 + 工作台接入）**：引擎四件套 `src/engine/`（audit 审计链 / matcher 装载 / classifier 六类规则树九变体 / verifier 独立复核）+ `evals/score.py` 判分 + `scripts/run_engine.py` 一键跑分；工作台差异列表数据源可切"标准答案 / 引擎判定"（置信度列 + 自然差异弹层说明），概览 KPI 卡亮起。**全量成绩：召回 100%（1,750/1,750）、真误报 0、575 条自然差异全部命中 P0 口径**（成绩单 `docs/reports/p2-engine-report.md`）。51 pytest 全绿。首跑暴露考卷缺陷：漏运费雷落在零运费单上 0→0 不可判 → 造数过滤 + 注入器硬校验，考卷重冻结 v1.1（D011），数量口径不变。**下一步：P3 Agent 壳（自研受约束循环，attribute/ask 两出口，DeepSeek key 由用户提供）。**
- **2026-09-26（对账工作台 v1 完成）**：用户拍板加界面（D005 推翻 → D009/D010 立项）。交付：`src/workbench/`（FastAPI 只读接口 + Pydantic 契约 + 静态前端，零前端构建链，视觉走 shadcn/Carbon 一脉"低装饰密集数据表"）+ `对账工作台.exe`（7MB **薄启动器**：只拉起 .venv 服务并开浏览器，不打包应用与数据）+ `启动对账工作台.bat`。三个页面：概览（KPI + 六类条形 + 三本账行数）、标准答案（筛选/搜索/翻页 + 单雷五账本证据弹层）、关于（架构/里程碑/口径）。31 pytest 全绿（+9，数据层与接口层 TDD）；接口对真实冻结数据逐位核对一致；exe 冒烟 + 浏览器实测通过，截图在 `docs/assets/workbench-*.png`。设计成文 `docs/superpowers/specs/2026-09-26-workbench-design.md`。**下一步不变：P2 确定性匹配引擎（三本账互对 + 六类归因 + 验证器），验收 = 无 LLM 全量跑通并对照标准答案出分；引擎结果将替换 `/api/diffs` 的数据源接入工作台。**
- **2026-09-26（P1 完成，评测集冻结）**：设计定稿并成文（`docs/superpowers/specs/2026-09-26-recon-agent-design.md`）：A+B 终点（管道+Agent 壳，不做 UI）、Agent 层**自研受约束循环**（不用 LangGraph，接口锁死 `attribute`/`ask` 两函数）、LLM 用 DeepSeek、时间盒 4-6 周。记录体系建立（`docs/log.md`、`decisions.md`、`open-questions.md`、`glossary.md`，写作法 = "讲明白版"四段式 + 人话（黑话））。P1 造数五件套全部 TDD 实现（`src/synth/`：rules 落在 bills/refunds/config、injectors、ground_truth、build_dataset，22 个 pytest 全绿），冻结评测集产出 `data/synthetic/`（干净账单 98,199 / 退款 1,093；脏账单 98,249 / 退款 893 / 支付 103,678；标准答案 1,750 条=单边账 700+金额不符 500+状态 150+退款遗漏 200+重复 100+版本 100），注入规范 v1 成文（`docs/injection-spec-v1.md`）。关键设计：干净世界规则卡 R1-R4（佣金 0.20）、六雷池互斥、避开 P0 自然差异 576 单、孤儿订单号 32 位十六进制。**下一步：P2 确定性匹配引擎（三本账互对 + 六类归因 + 验证器），验收 = 无 LLM 全量跑通并对照标准答案出分。**
- **2026-09-26（P0 完成）**：工作区 `D:\eng_project\智能体选题_对账` 建成（git main；骨架 `data/synthetic`、`src/matcher`、`src/agent`、`evals`、`docs`、`scripts`、`sql`）。Olist 数据源落实：本机 E 盘副本（`E:\eng_project\baxi\...`，121MB，9 表齐全，行数与 Kaggle 发布版一致），已复制到 `data/raw/` 并入库 `data/olist.db`（SQLite，177MB；行数与金额校验通过）。DDL 由旧项目 MySQL 版移植为 `sql/01_schema.sql`——原始层**有意无约束**，重复键不丢行，唯一性异常由对账层测量。自然差异盘点完成：报告 `docs/natural-diff-report.md`，可复现脚本 `scripts/natural_diff_inventory.py`（纯标准库）。核心数字：两侧齐全订单金额一致率 99.42%（98089/98665），自然不一致 576 单（多付 367/少付 209，其中 477 单 ≤10 BRL 尾差）；单边账：无明细 775（unavailable 603/canceled 164/…/shipped 1）、无支付仅 1 单且为 delivered；孤儿支付/明细 0；canceled/unavailable 已付 1234 单 269,735 BRL（1093 单曾审批）——状态不一致/退款遗漏的 ground truth 种子；支付/明细键零重复、789 条重复 review_id；多笔支付形态丰富（最高 29 笔/单）。**P1 输入**：重复结算与版本差异为纯注入区；退款遗漏需合成退款流水表；"已送达但无支付"（order bfbd0f9b…）作保留金样本。BenchRec：Kaggle 独家、CC BY 4.0、约 4 万样本；本机无 Kaggle 凭证未下载，笔记 `docs/benchrec-format-notes.md`。下一步：P1 差异注入规范 v1 + ground truth 生成器。
