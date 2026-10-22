# ecom-settlement-recon（电商多平台结算对账 Agent）

对"平台账单 × 业务订单 × 支付流水"三方数据做确定性核对 + 差异归因的受约束 Agent。
选题决策、数据三层方案、技术架构与里程碑见 [handoff.md](handoff.md)（唯一事实源，先读它）。
量化结论看 [评测总报告](docs/reports/evaluation-report.md)；怎么向面试官讲这个项目看 [叙事稿](docs/interview-narrative.md)。

## 当前状态（2026-09-26）

| 里程碑 | 状态 | 产出 |
|---|---|---|
| P0 数据底座 | ✅ 完成 | `data/olist.db`（9 表，177MB）+ [自然差异盘点报告](docs/natural-diff-report.md) |
| P1 评测集冻结 | ✅ 完成 | [注入规范 v1](docs/injection-spec-v1.md) + `data/synthetic/`（干净/脏三本账 + 1,750 条标准答案） |
| 工作台 v1（2026-09-26 新增） | ✅ 完成 | `src/workbench/`（FastAPI 只读接口 + 静态前端）+ `对账工作台.exe` 薄启动器 |
| P2 确定性匹配引擎 | ✅ 完成 | `src/engine/`（分类器/验证器/审计链）+ `evals/score.py` 判分 + [P2 成绩单](docs/reports/p2-engine-report.md)（召回/精确均 100%）|
| P3 Agent 壳（自研受约束循环 + DeepSeek） | ✅ 完成 | `src/agent/`（attribute/ask 两出口 + 五件套护栏）+ 工作台 AI 问答/归因 |
| P4 全量评测 + BenchRec 跨域 | ✅ 完成 | [BenchRec 跨域成绩单](docs/reports/p4-benchrec-report.md)（精度 99.67%，超官方 ChatGPT 基线）+ [P2 成绩单](docs/reports/p2-engine-report.md) |

P1 关键数字：冻结考卷 = 六类雷共 **1,750** 颗（单边账 700 / 金额不符 500 / 状态不一致 150 /
退款遗漏 200 / 重复结算 100 / 版本差异 100），全部带标准答案；造数模块 22 个 pytest 全绿。

P2 关键数字：确定性引擎约 2.5 秒跑完 9.9 万单全量对账——标准答案 1,750 颗雷**全部命中**
（召回 100%），**真误报 0**；另报出 575 条数据自带的自然差异（与 P0 盘点口径吻合），与人工雷互不混淆。
考卷在首跑后重冻结为 v1.1（漏运费雷避开零运费单，见注入规范修订记录），数量口径不变。

P4 跨域对比（BenchRec 银行现金对账，32,048 笔银行流水，同一套确定性匹配思想）：

| 提交 | 精度 | 覆盖率 | 总判对率 |
|---|---|---|---|
| **确定性引擎（本项目）** | **99.67%** | **84.6%** | **90.4%** |
| 官方 ChatGPT 基线 | 95.20% | 64.9% | 65.2% |

1 秒判完（纯标准库）；竞赛硬门槛 99.8%，当前差 0.13pp（错配归因与改进方向见成绩单）。

P3 关键数字：Agent 壳上线——模型**只许组织语言不许算账**：答案中的每个数字/编号都过
事实单白名单校验，违规自动降级为确定性模板（真模型实测：缺失信息如实回答"事实单未提供"，
未出现编造）。无 API key 时全链路降级为模板，98 个 pytest 全程离线。

P0 关键数字：两侧齐全订单金额一致率 **99.42%**（98089/98665），自然不一致 576 单（多付 367 / 少付 209）；
单边账自然样本：无明细 775 单、已送达但无支付 1 单；canceled/unavailable 已付 1234 单（269,735 BRL，
状态不一致/退款遗漏的 ground truth 种子）；重复结算与版本差异为零（纯注入区）。

## 对账工作台（本地网页）

双击项目根目录的 **`对账工作台.exe`**（或 `启动对账工作台.bat`）→ 自动启动本机服务并打开浏览器
（`http://127.0.0.1:8770`，只监听本机）。四个页面：概览（冻结评测集数字 + 六类差异分布）、
差异列表（1,750 颗雷筛选/搜索/翻页，点行看该订单在六本账的原始记录；**数据源可切换为
"引擎判定"**——2,325 条引擎发现带置信度，非标准答案订单的弹层会注明属自然差异）、
账本浏览（六本账逐本分页检索，点行看同一份证据）、关于（架构与口径）。
配了 key 时（环境变量 `DEEPSEEK_API_KEY`）概览出现 **AI 问答框**、每条差异弹层出现 **AI 归因解释**按钮——
受约束出口，答案里的数字必须来自引擎与账本，截图 `docs/assets/workbench-agent.png`。
关闭服务控制台窗口即退出。exe 只有 7MB，只是启动器——代码与数据都在项目目录，改完刷新浏览器即生效。

```bash
# 首次或依赖变更后：安装 Web 层依赖（数据管道本身仍是纯标准库）
E:/py_anzhuang/python.exe -m venv .venv        # 已有 .venv 可跳过
.venv/Scripts/python.exe -m pip install -r requirements.txt
# 重新构建启动器 exe（仅启动逻辑，需要 requirements 里的 pyinstaller）
.venv/Scripts/python.exe scripts/build_launcher.py
```

界面截图见 `docs/assets/workbench-*.png`；Agent 壳设计与护栏口径见
[P3 设计文档](docs/superpowers/specs/2026-09-26-p3-agent-design.md)；工作台设计与风格依据见
[工作台设计文档](docs/superpowers/specs/2026-09-26-workbench-design.md)
（视觉谱系：[shadcn/ui](https://shadcncraft.com) 一脉的低装饰密集数据表 +
[2026 设计系统盘点](https://www.themasterly.com) 里 Carbon/Polaris 类企业工具风格 +
[对账类界面参考](https://dribbble.com/search/data-reconciliation)）。

### Docker 启动（无需本机 Python 环境）

```bash
docker compose up --build     # 首次要下载依赖，几十秒到几分钟（看网络）；之后秒起
# 浏览器打开 http://127.0.0.1:8770 ，Ctrl+C 停止（或 docker compose down）
```

镜像只装 Web 层运行时依赖 + 合成评测集，**不含** `data/olist.db`（177MB，由 Kaggle 原始数据构建）：
证据弹层的"原始记录"会明确提示未加载，其余功能（概览 / 差异明细 / 六本账浏览 / 标准账本对照）正常。
按需增强，都是"本机先生成、再挂给容器"：

- **原始订单记录**：本机跑 `scripts/build_db.py` 生成 `data/olist.db`，把 `docker-compose.yml` 里
  注释掉的 `./data/olist.db:/app/data/olist.db:ro` 打开（文件必须已存在，否则 Docker 会建同名目录）。
- **引擎判定数据源**：本机跑 `scripts/run_engine.py` 生成 `output/engine/`；compose 默认已挂载 `./output`。
- **AI 问答 / 归因**：`DEEPSEEK_API_KEY=... docker compose up`；没有 key 时自动降级为确定性模板。

### 部署到服务器（一个镜像 = 一个网站）

镜像自包含：服务器只要有 Docker，不需要 Python、源码或本机依赖。本地构建一次，三种带过去的方式选一：

```bash
# A. 有镜像仓库（可反复更新）
docker tag ecom-settlement-recon:latest <registry>/<namespace>/recon:latest
docker push <registry>/<namespace>/recon:latest

# B. 没有仓库：导出再传（镜像 tar 约 60MB）
docker save -o recon-image.tar ecom-settlement-recon:latest
scp recon-image.tar user@server:/tmp/ && ssh user@server 'docker load -i /tmp/recon-image.tar'

# C. 服务器上有源码：直接在服务器构建（需要联网装依赖）
git clone <repo> && cd <repo> && docker compose up -d --build
```

服务器上运行（没有源码也能跑；`DEEPSEEK_API_KEY` 可省略，没有 key 会自动降级）：

```bash
docker run -d --name recon-workbench --restart unless-stopped \
  -p 127.0.0.1:8770:8770 \
  -e DEEPSEEK_API_KEY=... \
  ecom-settlement-recon:latest
```

运行后服务器本机的 `127.0.0.1:8770` 可访问。要对外提供服务，建议端口只绑本机、前面放反向代理
（Caddy 两行配好自动 HTTPS）：

```caddy
recon.example.com {
    reverse_proxy 127.0.0.1:8770
}
```

不想上反向代理就 `RECON_BIND=0.0.0.0 docker compose up -d`（或 `-p 0.0.0.0:8770:8770`），
同时用安全组/防火墙限制来源。注意几点：镜像默认 `linux/amd64`，ARM 服务器要用
`docker buildx build --platform linux/arm64 -t ... .` 重新构建；镜像里只有合成评测集，
要"原始记录"需另带 `data/olist.db` 并用 `-v .../olist.db:/app/data/olist.db:ro` 挂载，
要"引擎判定"需另带 `output/engine/` 挂到 `/app/output`；工作台没有登录鉴权，
里面是合成数据，别把真实账单放上去裸奔。

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
- `src/engine/` + `evals/` —（P2）确定性匹配引擎（装载/规则树分类/验证器/审计链）与判分器；`scripts/run_engine.py` 一键跑分
- `src/agent/` —（P3）受约束 Agent 壳：attribute/ask 两出口、五件套护栏、DeepSeek 薄客户端（密钥只读环境变量）
- `src/workbench/` — 对账工作台（FastAPI 只读接口 + 静态前端；数据管道本身仍是纯标准库）
- `launcher/` + `scripts/build_launcher.py` — exe 薄启动器及其构建脚本
- `Dockerfile` + `docker-compose.yml` — 容器化启动（只带合成评测集，原始订单库按需挂载）

## 红线（handoff 第 3 节，不可违反）

1. 一律不用公司数据；`D:\eng_project\对账自动化\` 下全部为真实账单。
2. `对账自动化\如祺对账工具包\样例数据\` 里与真实账单同名的"样例"是**真实数据副本**，任何提交/演示不得包含。
3. 对外措辞只说"本地原型 + 合成数据评测"，不声称上线或真实业务 ROI。
