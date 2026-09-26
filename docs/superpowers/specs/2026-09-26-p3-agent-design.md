# P3 Agent 壳设计（2026-09-26）

> 原则承接 [recon-agent-design.md](2026-09-26-recon-agent-design.md)：**步骤能提前画成流程图的用代码写死，只有"理解"的活交给模型**。本文把"五件套护栏 + 两出口"落成 v1 可实现的口径。

## 1. 一句话定位

Agent 壳 = **事实收集器（确定性代码）→ 一次模型调用（只许组织语言）→ 输出校验（数字/编号白名单）→ 不合格就降级**。模型全程不许算账、不许碰数据库、不许编数字。

## 2. 两出口（接口锁死）

| 出口 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `attribute(ref)` | finding_id（F 前缀）或 gt_id（GT 前缀）或订单号 | `{answer, source, refs, trace}` | 对一条差异写归因解释 |
| `ask(question)` | 自然语言问题 | 同上 | 自然语言查账 |

`source` 只有两值：`"llm"`（模型文案过校验）或 `"fallback"`（确定性模板）。调用方永远能分辨答案是谁写的。

## 3. ask 的意图路由（确定性，不花模型调用）

1. 含 32 位十六进制订单号 → 订单事实卡
2. 含 `F\d{6}` / `GT\d+` 编号 → 对应引擎发现 / 标准答案行
3. 命中六类差异名 → 该类统计 + 3 个例子
4. 统计类关键词（多少/几条/统计/分布/成绩/召回）→ 判分摘要
5. 都没命中 → 固定话术列出能力范围（**不调模型**——问题本身不含可查事实，模型编不出来）

## 4. 五件套护栏（v1 口径）

| 护栏 | 实现 |
|---|---|
| 白名单 | 模型输出里的每个金额/计数数字、每个订单号/编号，必须能在本次喂给它的"事实单"里找到；违规则带违规清单重试一次，再违规则降级 |
| 预算 | 每次出口调用：模型往返 ≤2（初答+重试），事实收集 ≤1 轮；超预算立即降级 |
| 留痕 | 每次调用追加一行 JSON 到 `output/agent/trace.jsonl`（时间/出口/输入/事实单 sha256/模型响应/校验结果/最终路径）；output/ 已 gitignore |
| 查引用 | 答案里的订单号/编号逐一核对事实单（同白名单，针对标识符） |
| 失败降级 | 无 key / 超时 / API 错 / 校验不过 → 确定性模板文案（内容同样来自事实单），说明"AI 解释暂不可用"；绝不阻塞、绝不编造 |

## 5. 事实单与工具（`src/agent/tools.py`）

5 个只读工具，全部参数化查询，产出 JSON"事实单"（模型只看它）：

- `order_facts(order_id)` — 订单+明细+账单+支付+退款五段（复用 `src/workbench/data.load_ledger_by_order`，同一份已测代码）
- `finding(finding_id)` — 引擎发现（读 findings.json）
- `gt(gt_id)` — 标准答案行
- `stats()` — 判分摘要（读 score.json）
- `samples_by_type(diff_type, limit=3)` — 某类差异的例子

## 6. 模型层（`src/agent/llm.py`）

- 端点 `https://api.deepseek.com/chat/completions`（OpenAI 兼容），**密钥只读环境变量 `DEEPSEEK_API_KEY`**，不进代码/日志
- 模型默认 `deepseek-flash`（2026-09 实测可用，V4.1-Flash，带思考，用 `effort:"low"` 控制思考量）；`RECON_AGENT_MODEL` / `RECON_AGENT_EFFORT` 可覆盖
- `chat(messages, max_tokens=2000)` 纯标准库 urllib 实现；超时 60s；错误归一为 `LLMError`
- `available()`：有 key 才 True——评测/CI 无 key 时全走 fallback，测试永不碰网络

## 7. 提示词骨架

系统提示固定一段："你是对账助手。只能使用用户消息 JSON 中的事实回答；不得引入 JSON 之外的任何数字或编号；不得计算新数字；不知道就说不知道。"

## 8. 测试策略（按 P1 设计：离线考五件套，真模型只冒烟）

- 假模型：注入 `llm.chat` 替身，返回可控文本 → 考白名单拦截、重试、降级、留痕、预算
- 真模型：一条 `scripts/agent_smoke.py` 手动跑（不进 pytest），输出打印不进库

## 9. 工作台接入（薄）

- `GET /api/agent/status` → `{available}`（无 key 前端藏入口）
- `POST /api/agent/ask` → ask()
- `GET /api/agent/attribute/{finding_id}` → attribute()
- 前端：引擎判定行点"归因"看解释；概览加一个问答框；source=fallback 时文案照常显示

## 10. 非目标（v1）

- 不做多轮对话（每次 ask 独立）；不做流式输出；不做工具自主循环（事实收集是写死的单轮）；不做记忆。
