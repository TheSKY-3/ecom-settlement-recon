# P3 Agent 壳设计（2026-09-26）

> 原则承接 [recon-agent-design.md](2026-09-26-recon-agent-design.md)：**步骤能提前画成流程图的用代码写死，只有"理解"的活交给模型**。本文把"五件套护栏 + 两出口"落成 v1 可实现的口径；后续 D013 在此基础上追加第三个受约束出口 `chat`（多轮 + 只读工具循环），原 `ask`/`attribute` 契约不变。

## 1. 一句话定位

Agent 壳 = **事实收集器（确定性代码）→ 一次模型调用（只许组织语言）→ 输出校验（数字/编号白名单）→ 不合格就降级**。模型全程不许算账、不许碰数据库、不许编数字。

## 2. 三个出口（接口锁死）

| 出口 | 输入 | 输出 | 用途 |
|---|---|---|---|
| `attribute(ref)` | finding_id（F 前缀）或 gt_id（GT 前缀）或订单号 | `{answer, source, refs, trace}` | 对一条差异写归因解释（单轮，D013 不改） |
| `ask(question)` | 自然语言问题 | 同上 | 自然语言查账（单轮，D013 不改） |
| `chat(session_id?, message)` | 可选会话号 + 自然语言问题 | `ChatTurnResult` | 多轮对话 + 只读工具循环（D013 新增） |

`source` 只有两值：`"llm"`（模型文案过校验）或 `"fallback"`（确定性模板）。调用方永远能分辨答案是谁写的。chat 额外有 `status=ready|unavailable`（轮数上限）与 `reason`（降级/上限原因）。

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

**D013 chat 追加口径**（不改上面两条单轮出口）：

| 护栏 | chat 的实现 |
|---|---|
| 白名单 | 每轮工具结果 + 会话历史事实合并后校验；答案里的数字/编号必须可追溯；答案里出现的编号必须全部进 `refs` |
| 预算 | 单会话最多 20 轮、TTL 2 小时、最多 100 个会话；每轮最多 4 次只读工具调用，正常以 `submit_chat_answer` 收口；模型直接给最终文本时也按同一白名单校验；单条消息最多 1000 字 |
| 可观测 | 每次工具调用生成一条 `tool_steps`（工具名、白名单参数、结果摘要、状态、耗时）；等待回复时前端每 320ms 轮询 `/api/chat/activity/{activity_id}` 逐步渲染“执行过程”，结束后保留时间线并显示“调用 N 次模型 · 对话第 X 轮”。只展示真实工具事件和结果，不展示隐藏思维链 |
| 留痕 | 每次回合追加一行到 `output/agent/chat_trace.jsonl`：会话号、轮次、source、reason、模型往返数、工具轨迹（只记 message sha256，不落原文） |
| 查引用 | `refs` 必须是本轮/历史事实里真实存在的 ID；答案中出现但漏引用的可核实 ID 自动补进 `refs`，补不齐或出现未知 ID 才降级 |
| 失败降级 | 无 key / 模型错 / 工具错 / 结构不合法 / 校验不过 / 轮数超限 → `ask()` 确定性回答；`reason` 保留 `NO_KEY`、`VALIDATION_FAILED`、`LLM_ERROR`、`MODEL_OUTPUT_INVALID`、`BAD_ANSWER_SCHEMA`、`ROUNDS_EXCEEDED`、`SESSION_LIMIT` 等代码 |

## 5. 事实单与工具（`src/agent/tools.py`）

5 个只读工具，全部参数化查询，产出 JSON"事实单"（模型只看它）：

- `order_facts(order_id)` — 订单+明细+账单+支付+退款五段（复用 `src/workbench/data.load_ledger_by_order`，同一份已测代码）
- `finding(finding_id)` — 引擎发现（读 findings.json）
- `gt(gt_id)` — 标准答案行
- `stats()` — 判分摘要（读 score.json）
- `samples_by_type(diff_type, limit=3)` — 某类差异的例子

D013 的 `ChatTools` 只对模型暴露五个只读查询（不再有自由 SQL/计算）：

- `get_overview` — 批次概览、六类数量/占比、引擎成绩
- `search_diffs(source, diff_type?, side?, q?, limit≤10)` — 差异搜索；**工具结果不回显用户输入的 `q`**，避免把未核验文本混进白名单事实
- `get_diff(ref)` — GT/F 单条的五段账本证据
- `get_order(order_id)` — 32 位订单的订单/明细/账/支付/退款
- `get_engine_score` — 召回、精确、发现数、误报数

## 6. 模型层（`src/agent/llm.py`）

- 端点 `https://api.deepseek.com/chat/completions`（OpenAI 兼容），**密钥只读环境变量 `DEEPSEEK_API_KEY`**，不进代码/日志
- 模型默认 `deepseek-flash`（2026-09 实测可用，V4.1-Flash，带思考，用 `effort:"low"` 控制思考量）；`RECON_AGENT_MODEL` / `RECON_AGENT_EFFORT` 可覆盖
- `chat(messages, max_tokens=2000)` 纯标准库 urllib 实现；超时 60s；错误归一为 `LLMError`
- `available()`：有 key 才 True——评测/CI 无 key 时全走 fallback，测试永不碰网络
- `chat_with_tools(messages, tools, max_tokens=1200)`：D013 新增，原生 OpenAI `tools`/`tool_calls`，`temperature=0`、`tool_choice="auto"`；单次往返只解析，不执行工具

## 7. 提示词骨架

系统提示固定一段："你是对账助手。只能使用用户消息 JSON 中的事实回答；不得引入 JSON 之外的任何数字或编号；不得计算新数字；不知道就说不知道。"

## 8. 测试策略（按 P1 设计：离线考五件套，真模型只冒烟）

- 假模型：注入 `llm.chat` 替身，返回可控文本 → 考白名单拦截、重试、降级、留痕、预算
- D013 chat：注入假 gateway 的 `tool_calls` 脚本 → 考工具参数校验、搜索不回显 `q`、多轮历史、引用补全、1.0 小数口径、直接最终答复、轮数上限、API 404/降级、结构化工具步骤、活动轮询、UI 静态契约；测试全程不碰网络
- 真模型：一条 `scripts/agent_smoke.py` 手动跑（不进 pytest），输出打印不进库；chat 已用本地 `DEEPSEEK_API_KEY` 实测概览、六类样例、GT 归因与跟进追问，工具调用和引用校验通过

## 9. 工作台接入（薄）

- `GET /api/agent/status` → `{available}`（无 key 前端藏入口）
- `POST /api/agent/ask` → ask()
- `GET /api/agent/attribute/{finding_id}` → attribute()
- D013 新增：`GET /api/chat/status`、`POST /api/chat`、`GET /api/chat/activity/{activity_id}`（回合进行中轮询执行过程）、`GET /api/chat/{session_id}`（刷新恢复）、`DELETE /api/chat/{session_id}`（新对话）；`POST /api/chat` 可带客户端生成的 `activity_id`，响应始终返回 `tool_steps`
- 前端：顶栏"AI 对话"打开右侧抽屉；多轮消息、快捷问题、20 轮计数、来源标签（AI/确定性）、等待时逐步显示"执行过程"、结束后保留步骤和"调用 N 次模型 · 对话第 X 轮"、refs 可点开账本、Enter 发送/Shift+Enter 换行、sessionStorage 恢复；账本弹层的单轮归因保持原样

## 10. 非目标与 D013 扩展

**v1 原非目标**（ask/attribute 仍然如此）：单轮独立、不做流式输出、事实收集写死、无记忆。

**D013 已放开两项**（只限 chat 出口）：

- 多轮对话：`ChatService` 内存会话，TTL 2h / 20 轮 / 100 会话；
- 只读工具循环：每轮最多 4 次查询，正常以 `submit_chat_answer` 收口；直接给最终文本时仍走同一白名单校验；工具只有上面五个，**仍不允许自由 SQL、写操作或自行计算新数**。

**仍然不做**：流式输出、跨进程/跨重启持久会话、多人共享会话、写操作（改账/冲销）、自动重试整轮（校验失败直接确定性降级，不把坏答案再喂回模型）。

## 11. 已知边界（实测冒烟后记录）

- 含统计词（"多少"等）的开放查询（如"金额最大的那笔账单是多少？"）会被统计路由接住，得到引擎整体成绩模板而非逐单查询——宁可给真数字不给编造；chat 在有 key 时可用工具循环缩小范围，无 key 时仍走同一确定性路由。
- 无 `DEEPSEEK_API_KEY` 时 chat 的"多轮"只是会话壳：底层 fallback 仍逐问调用 `ask()`，不会真正承接"那上一句呢"的上下文；界面会明确标注"确定性回答"。
- 会话只存在工作台单进程内存：刷新可用 `GET /api/chat/{id}` 恢复，重启进程即失；前端 `sessionStorage` 里的旧 session_id 遇到 404 会自动新开并清掉旧消息。
- 模型对事实单缺失的信息会如实回答"事实单未提供"（真模型实测确认），系统提示的"没有就说没有"约束生效；chat 的 `VALIDATION_FAILED` 会降级为确定性文案，不会把违规答案直接展示。
- 执行过程是**内存里的短期活动记录**（5 分钟 TTL、最多 100 条），刷新页面后历史步骤仍随 `GET /api/chat/{id}` 恢复，但活动轮询本身不跨进程；轮询只是“看得见工具在做什么”，不是 SSE/流式输出，最终答案仍等整轮校验通过后一次返回。
