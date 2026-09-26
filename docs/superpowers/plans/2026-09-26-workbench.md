# 对账工作台（本地 Web UI + exe 启动器）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 双击 `对账工作台.exe`（薄启动器）→ 本机 FastAPI 服务（127.0.0.1:8770）→ 浏览器展示冻结评测集概览、标准答案浏览、单雷三本账对照。

**Architecture:** 四层中的工作台层——数据层只读（`data/synthetic/*.csv` + `data/olist.db`），FastAPI 提供 3 个只读 JSON 接口 + 静态页，前端 hash 路由单页应用（原生 JS + 手写 CSS，零构建链）。启动器 exe 只做"拉起 venv Python + 开浏览器"。

**Tech Stack:** Python 标准库（csv/sqlite3）+ FastAPI + uvicorn + Pydantic（契约）+ httpx（测试）+ PyInstaller（仅打包启动器）。

**Spec:** `docs/superpowers/specs/2026-09-26-workbench-design.md`（读计划前先读它）

## Global Constraints

- 只监听 `127.0.0.1`，端口基线 8770，被占则 +1 重试至 8779（spec 第 5 节）。
- 前端零依赖：无 React/Tailwind/npm/图表库；`style.css` + `app.js` + `index.html` 三件（spec 第 4 节）。
- 接口全部只读 GET；Pydantic 模型定义响应形状（spec 第 3 节）。
- 视觉常量：底 `#fafafa`、卡面 `#ffffff`、边框 `#e4e4e7`、文字 `#18181b`、次级 `#71717a`、强调 `#2563eb`；圆角 8px；正文 14px / 表格 13px；金额与 ID 等宽 + `tabular-nums`（spec 第 4 节）。
- 测试不依赖真实数据文件：`RECON_SYNTHETIC_DIR` / `RECON_DB_PATH` 环境变量可重定向数据位置（spec 第 6 节）。
- 红线：不用公司数据；密钥不进代码（本期工作台不接模型，无密钥面）。
- 本机 Python：`E:/py_anzhuang/python.exe`（venv 已在 `.venv/`，先装依赖）。

---

### Task 1: 依赖安装与数据模块 `data.py`

**Files:**
- Create: `requirements.txt`
- Create: `src/workbench/__init__.py`
- Create: `src/workbench/data.py`
- Test: `tests/test_workbench_data.py`

**Interfaces:**
- Consumes: 磁盘上的 `data/synthetic/{clean,dirty}/{platform_bills,refunds,order_payments}.csv`、`dirty/ground_truth.csv`（列：`gt_id,order_id,diff_type,variant,target_side,description`）、`data/olist.db`（orders/order_items 表）。测试用临时目录同构小文件。
- Produces（Task 2 的 API 直接调用）：
  - `load_overview() -> dict`：`{"seed": int, "clean": {"bills": int, "refunds": int, "payments": int}, "dirty": {...同形...}, "gt": {"total": int, "by_type": {类型: n}, "by_side": {侧: n}}}`
  - `load_diffs(diff_type: str|None, side: str|None, q: str|None, page: int, page_size: int) -> dict`：`{"total": int, "page": int, "page_size": int, "rows": [ {gt_id,order_id,diff_type,variant,target_side,description}, ...]}`；`q` 对 `order_id/description` 不区分大小写子串匹配；`page` 从 1 起。
  - `load_ledger(gt_id: str) -> dict|None`：`{"gt": {...}, "bills": [...], "payments": [...], "refunds": [...], "orders": [...], "items": [...]}`；查无此 gt_id 返回 `None`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workbench_data.py
import csv
import sqlite3

import pytest

from src.workbench import data as wbdata

GT_COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side", "description"]


def _write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    synth = tmp_path / "synthetic"
    bills = [{"bill_id": "B_1", "order_id": "o1", "seller_id": "s1", "version": "1",
              "issued_date": "2026-01-01", "commission_rate": "0.20", "commission_fee": "2.00",
              "freight_amount": "5.00", "price_amount": "10.00", "settlement_amount": "13.00"}]
    pays = [{"order_id": "o1", "payment_sequential": "1", "payment_type": "credit_card",
             "payment_installments": "1", "payment_value": "15.00"}]
    refs = [{"refund_id": "R_o3", "order_id": "o3", "refund_amount": "7.00",
             "refund_date": "2026-02-01"}]
    gt = [
        {"gt_id": "GT000001", "order_id": "o1", "diff_type": "单边账", "variant": "删账单",
         "target_side": "bills", "description": "账单缺失：有明细有支付但无账单"},
        {"gt_id": "GT000002", "order_id": "o2", "diff_type": "金额不符", "variant": "费率错",
         "target_side": "bills", "description": "佣金按 0.10 计算，应为 0.20"},
        {"gt_id": "GT000003", "order_id": "o3", "diff_type": "退款遗漏", "variant": "该退未退",
         "target_side": "refunds", "description": "取消单已付款但无退款记录"},
        {"gt_id": "GT000004", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
         "target_side": "bills", "description": "账单缺失：有明细有支付但无账单"},
    ]
    _write_csv(synth / "clean" / "platform_bills.csv",
               list(bills[0]), bills)
    _write_csv(synth / "clean" / "refunds.csv", list(refs[0]), refs)
    _write_csv(synth / "clean" / "order_payments.csv", list(pays[0]), pays)
    _write_csv(synth / "dirty" / "platform_bills.csv", list(bills[0]), bills)
    _write_csv(synth / "dirty" / "refunds.csv", list(refs[0]), refs)
    _write_csv(synth / "dirty" / "order_payments.csv", list(pays[0]), pays)
    _write_csv(synth / "dirty" / "ground_truth.csv", GT_COLUMNS, gt)

    db = tmp_path / "olist.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_status TEXT,"
        " order_purchase_timestamp TEXT);"
        "CREATE TABLE order_items (order_id TEXT, order_item_id INTEGER, product_id TEXT,"
        " seller_id TEXT, price REAL, freight_value REAL);"
        "CREATE INDEX idx_o ON orders(order_id);"
        "CREATE INDEX idx_i ON order_items(order_id);"
        "INSERT INTO orders VALUES ('o1','c1','delivered','2026-01-01 10:00:00');"
        "INSERT INTO order_items VALUES ('o1',1,'p1','s1',10.0,5.0);"
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("RECON_SYNTHETIC_DIR", str(synth))
    monkeypatch.setenv("RECON_DB_PATH", str(db))
    return synth


def test_overview_counts(env):
    ov = wbdata.load_overview()
    assert ov["clean"] == {"bills": 1, "refunds": 1, "payments": 1}
    assert ov["dirty"]["bills"] == 1
    assert ov["gt"]["total"] == 4
    assert ov["gt"]["by_type"] == {"单边账": 2, "金额不符": 1, "退款遗漏": 1}
    assert ov["gt"]["by_side"] == {"bills": 3, "refunds": 1}


def test_diffs_filter_and_pagination(env):
    page1 = wbdata.load_diffs(None, None, None, 1, 2)
    assert page1["total"] == 4 and page1["page"] == 1 and len(page1["rows"]) == 2
    page2 = wbdata.load_diffs(None, None, None, 2, 2)
    assert len(page2["rows"]) == 2 and page2["rows"][0]["gt_id"] == "GT000003"
    only_single = wbdata.load_diffs("单边账", None, None, 1, 50)
    assert only_single["total"] == 2
    assert all(r["diff_type"] == "单边账" for r in only_single["rows"])
    search = wbdata.load_diffs(None, None, "o2", 1, 50)
    assert {r["gt_id"] for r in search["rows"]} == {"GT000002", "GT000004"}
    side = wbdata.load_diffs(None, "refunds", None, 1, 50)
    assert [r["gt_id"] for r in side["rows"]] == ["GT000003"]


def test_ledger_assembles_five_sources(env):
    led = wbdata.load_ledger("GT000001")
    assert led is not None
    assert led["gt"]["order_id"] == "o1"
    assert led["bills"] == []          # o1 的雷是"删账单"，脏账单里无此单
    assert len(led["payments"]) == 1 and led["payments"][0]["payment_value"] == "15.00"
    assert led["orders"][0]["order_status"] == "delivered"
    assert led["items"][0]["price"] == 10.0
    assert led["refunds"] == []
    assert wbdata.load_ledger("GT999999") is None


def test_missing_data_dir_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("RECON_SYNTHETIC_DIR", str(tmp_path / "nowhere"))
    with pytest.raises(FileNotFoundError) as e:
        wbdata.load_overview()
    assert "scripts/build_synthetic.py" in str(e.value)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workbench_data.py -v`
Expected: FAIL（`ModuleNotFoundError: src.workbench`）

- [ ] **Step 3: 安装依赖 + 最小实现**

`requirements.txt`（注释注明分组）：

```
# 运行时（工作台 Web 层；数据管道仍为纯标准库）
fastapi>=0.115
uvicorn>=0.30
pydantic>=2.7

# 开发/测试
pytest>=8.0
httpx>=0.27          # fastapi.testclient 依赖

# 打包（仅构建 exe 启动器时需要）
pyinstaller>=6.10
```

安装：`.venv/Scripts/python.exe -m pip install -r requirements.txt`（含网络，若 pyinstaller 拉取慢可先装前三组，Task 4 再补）。

`src/workbench/__init__.py`：空文件。

`src/workbench/data.py`：

```python
"""工作台数据层：只读合成评测集与底座库。路径每次调用时从环境变量读取，
便于测试重定向；查询结果按"文件路径+修改时间"缓存。"""
from __future__ import annotations

import csv
import os
import sqlite3
from collections import Counter
from pathlib import Path

from src.synth.config import SEED

GT_COLUMNS = ["gt_id", "order_id", "diff_type", "variant", "target_side", "description"]
 LedgerFiles = ("platform_bills", "refunds", "order_payments")


def _synthetic_dir() -> Path:
    return Path(os.environ.get("RECON_SYNTHETIC_DIR",
                               Path(__file__).resolve().parents[2] / "data" / "synthetic"))


def _db_path() -> Path:
    return Path(os.environ.get("RECON_DB_PATH",
                               Path(__file__).resolve().parents[2] / "data" / "olist.db"))


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(
            f"缺少数据文件：{path}。先跑 scripts/build_synthetic.py 生成 data/synthetic/。")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _cached(key: tuple, factory):
    hit = _cache.get(key)
    if hit is None:
        hit = factory()
        _cache[key] = hit
    return hit


_cache: dict = {}


def _gt_rows() -> list[dict]:
    path = _synthetic_dir() / "dirty" / "ground_truth.csv"
    stat = path.stat().st_mtime if path.is_file() else 0
    return _cached(("gt", str(path), stat), lambda: _read_csv(path))


def _side_rows(world: str, name: str) -> list[dict]:
    path = _synthetic_dir() / world / f"{name}.csv"
    stat = path.stat().st_mtime if path.is_file() else 0
    return _cached((world, name, str(path), stat), lambda: _read_csv(path))


def load_overview() -> dict:
    counts = {}
    for world in ("clean", "dirty"):
        counts[world] = {
            "bills": len(_side_rows(world, "platform_bills")),
            "refunds": len(_side_rows(world, "refunds")),
            "payments": len(_side_rows(world, "order_payments")),
        }
    rows = _gt_rows()
    if not rows:
        raise FileNotFoundError(
            f"标准答案为空：{_synthetic_dir() / 'dirty' / 'ground_truth.csv'}。"
            "先跑 scripts/build_synthetic.py。")
    return {
        "seed": SEED,
        "clean": counts["clean"],
        "dirty": counts["dirty"],
        "gt": {
            "total": len(rows),
            "by_type": dict(Counter(r["diff_type"] for r in rows)),
            "by_side": dict(Counter(r["target_side"] for r in rows)),
        },
    }


def load_diffs(diff_type: str | None, side: str | None, q: str | None,
               page: int, page_size: int) -> dict:
    rows = _gt_rows()
    if diff_type:
        rows = [r for r in rows if r["diff_type"] == diff_type]
    if side:
        rows = [r for r in rows if r["target_side"] == side]
    if q:
        needle = q.lower()
        rows = [r for r in rows
                if needle in r["order_id"].lower() or needle in r["description"].lower()]
    total = len(rows)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size,
            "rows": rows[start:start + page_size]}


def _db_query(sql: str, params: tuple) -> list[dict]:
    db = _db_path()
    if not db.is_file():
        raise FileNotFoundError(
            f"缺少底座数据库：{db}。先跑 scripts/build_db.py 生成 data/olist.db。")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def load_ledger(gt_id: str) -> dict | None:
    gts = [r for r in _gt_rows() if r["gt_id"] == gt_id]
    if not gts:
        return None
    oid = gts[0]["order_id"]
    return {
        "gt": gts[0],
        "bills": [r for r in _side_rows("dirty", "platform_bills") if r["order_id"] == oid],
        "payments": [r for r in _side_rows("dirty", "order_payments") if r["order_id"] == oid],
        "refunds": [r for r in _side_rows("dirty", "refunds") if r["order_id"] == oid],
        "orders": _db_query("SELECT * FROM orders WHERE order_id = ?", (oid,)),
        "items": _db_query("SELECT * FROM order_items WHERE order_id = ?", (oid,)),
    }
```

注意：`_read_csv` 里 `LedgerFiles` 常量最终未用到就删掉（保留会误导）。全量 CSV 每次过滤是 O(n) 全扫（约 10 万行、几十毫秒级），本期数据量可接受，不做索引优化（YAGNI，P2 接引擎后此处整体替换）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workbench_data.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/workbench tests/test_workbench_data.py
git commit -m "feat(workbench): 数据层——评测集统计/筛选/单雷三本账对照"
```

---

### Task 2: API 层 `app.py` + 契约 + 静态挂载

**Files:**
- Create: `src/workbench/contracts.py`
- Create: `src/workbench/app.py`
- Create: `src/workbench/static/index.html`（本任务先放含标题的最小占位，Task 3 完整化）
- Test: `tests/test_workbench_api.py`

**Interfaces:**
- Consumes: Task 1 的 `load_overview / load_diffs / load_ledger`（签名见 Task 1）。
- Produces（Task 3 前端调用、Task 4 冒烟验证）：
  - `GET /api/overview` → `Overview`
  - `GET /api/diffs?type=&side=&q=&page=&page_size=` → `DiffsPage`（`page_size` 限 1–200，`page` 限 ≥1）
  - `GET /api/diffs/{gt_id}/ledger` → `LedgerView`，未知 gt_id → 404（`{"detail": "..."}`）
  - `GET /` → `static/index.html`；`/static/*` 静态文件
  - FastAPI 实例名 `app`（serve.py 引用 `src.workbench.app:app`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_workbench_api.py
import pytest
from fastapi.testclient import TestClient

from src.workbench.app import app
from tests.test_workbench_data import env  # 复用数据夹具


@pytest.fixture()
def client(env):
    return TestClient(app)


def test_overview_shape(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 20260926
    assert body["gt"]["total"] == 4


def test_diffs_validation(client):
    r = client.get("/api/diffs", params={"page_size": 0})
    assert r.status_code == 422
    r = client.get("/api/diffs", params={"page_size": 500})
    assert r.status_code == 422


def test_diffs_filters(client):
    r = client.get("/api/diffs", params={"type": "单边账"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {row["gt_id"] for row in body["rows"]} == {"GT000001", "GT000004"}


def test_ledger_404_and_200(client):
    assert client.get("/api/diffs/GT999999/ledger").status_code == 404
    r = client.get("/api/diffs/GT000001/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["gt"]["order_id"] == "o1"
    assert set(body) == {"gt", "bills", "payments", "refunds", "orders", "items"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "对账工作台" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workbench_api.py -v`
Expected: FAIL（`ModuleNotFoundError: src.workbench.app`）

- [ ] **Step 3: 实现**

`src/workbench/contracts.py`：

```python
"""对外 JSON 契约：响应形状在这里定义，前端与后续 Agent 出口共用同一套口径。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DiffRow(BaseModel):
    gt_id: str
    order_id: str
    diff_type: str
    variant: str
    target_side: str
    description: str


class DiffsPage(BaseModel):
    total: int
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=200)
    rows: list[DiffRow]


class LedgerView(BaseModel):
    gt: DiffRow
    bills: list[dict]
    payments: list[dict]
    refunds: list[dict]
    orders: list[dict]
    items: list[dict]


class Overview(BaseModel):
    seed: int
    clean: dict[str, int]
    dirty: dict[str, int]
    gt: dict
```

`src/workbench/app.py`：

```python
"""工作台服务：只读 JSON 接口 + 静态页。不写任何数据，不做任何计算性判断——
结论一律来自数据层/引擎层。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.workbench import data
from src.workbench.contracts import DiffsPage, LedgerView, Overview

app = FastAPI(title="对账工作台", docs_url="/api/docs")
_STATIC = Path(__file__).resolve().parent / "static"


@app.get("/api/overview", response_model=Overview)
def api_overview() -> dict:
    return data.load_overview()


@app.get("/api/diffs", response_model=DiffsPage)
def api_diffs(
    type: str | None = Query(None, description="差异类型，如：单边账"),
    side: str | None = Query(None, description="目标侧：bills/payments/refunds"),
    q: str | None = Query(None, description="搜订单号或描述"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    return data.load_diffs(type, side, q, page, page_size)


@app.get("/api/diffs/{gt_id}/ledger", response_model=LedgerView)
def api_ledger(gt_id: str) -> dict:
    led = data.load_ledger(gt_id)
    if led is None:
        raise HTTPException(status_code=404, detail=f"标准答案里没有 {gt_id}")
    return led


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
```

`src/workbench/static/index.html`（占位，Task 3 替换为完整版）：

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>对账工作台</title>
</head>
<body>
  <h1>对账工作台</h1>
</body>
</html>
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_workbench_api.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/workbench/contracts.py src/workbench/app.py src/workbench/static tests/test_workbench_api.py
git commit -m "feat(workbench): FastAPI 只读接口 + Pydantic 契约 + 静态挂载"
```

---

### Task 3: 前端三件套（视觉风格落地）

**Files:**
- Modify: `src/workbench/static/index.html`（完整版）
- Create: `src/workbench/static/style.css`
- Create: `src/workbench/static/app.js`

**Interfaces:**
- Consumes: Task 2 的三个 GET 接口。
- Produces: 用户可见页面。无新接口。

- [ ] **Step 1: `index.html`**——结构：顶栏（站名 + 页签：概览/标准答案/关于）+ 三个 `<section data-view>` + 底部口径说明。视图由 `app.js` 按 `location.hash` 切换。

- [ ] **Step 2: `style.css`**——按 spec 第 4 节常量实现：CSS 变量定义色板；`.card`（白底 1px 边框 8px 圆角）；KPI 行（`display:grid` 自适应）；六类徽章 `.badge--单边账` 等（低饱和底色 + 深色文字）；表格（表头吸顶、行 hover、数字列右对齐等宽）；条形图（`.bar` 宽度百分比内联样式）；弹层 `.modal`（行点击后显示三本账对照，五段各一张小表）；响应式 720px 断点。

- [ ] **Step 3: `app.js`**——`fetchJSON(url)` 封装（非 2xx 抛出 `detail`）；三个渲染函数 `renderOverview/renderDiffs/renderAbout`；hashchange 路由；差异表状态（筛选值/页码）存内存，翻页与筛选触发重取；行点击 `GET /api/diffs/{gt_id}/ledger` 填充弹层，Esc/点击遮罩关闭；金额等数值列加 `num` class。

- [ ] **Step 4: 浏览器人工验证（自动测试只覆盖接口层）**

启动：`.venv/Scripts/python.exe -m src.workbench.serve --open-browser`（serve.py 在 Task 4 实现；本步骤可临时用 `uvicorn src.workbench.app:app --port 8770` 起服务）。检查项：
1. 概览 KPI 与 `scripts/build_synthetic.py` 摘要一致（clean bills 98,199 / dirty bills 98,249 / gt 1,750）。
2. 六类条形比例与 700/500/150/200/100/100 一致。
3. 筛选"单边账"总数 = 700；翻页可到末页（1,750/50 = 35 页）。
4. 任一行点开弹层，五段数据显示且删账单类雷 bills 段为空（并注明"该单在账单侧无记录"）。
5. 窗口缩到 720px 以下无横向滚动条。

- [ ] **Step 5: Commit**

```bash
git add src/workbench/static
git commit -m "feat(workbench): 前端三件套——概览/标准答案/关于，中性密集数据台风格"
```

---

### Task 4: 启动链路（serve + bat + exe 启动器）

**Files:**
- Create: `src/workbench/serve.py`
- Create: `启动对账工作台.bat`
- Create: `launcher/launcher.py`
- Create: `scripts/build_launcher.py`
- Modify: `.gitignore`（追加 `tmp/`、`*.exe`、`build/`、`dist/`）

**Interfaces:**
- Consumes: `src.workbench.app:app`。
- Produces: 双击入口两个（bat 与 exe）；`python -m src.workbench.serve [--port 8770] [--open-browser]`。

- [ ] **Step 1: `serve.py`**

```python
"""工作台服务入口：python -m src.workbench.serve [--port 8770] [--open-browser]"""
from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from src.workbench.app import app  # noqa: F401  uvicorn 用


def pick_port(start: int, stop: int = 8779) -> int:
    for port in range(start, stop + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"{start}~{stop} 端口都被占用")


def main() -> None:
    ap = argparse.ArgumentParser(description="对账工作台本地服务")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--open-browser", action="store_true")
    args = ap.parse_args()
    port = pick_port(args.port)
    url = f"http://127.0.0.1:{port}"
    if args.open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"对账工作台：{url}（关闭本窗口即停止服务）")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: `启动对账工作台.bat`**

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [对账工作台] 找不到 .venv\Scripts\python.exe，请先在项目根目录创建虚拟环境。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m src.workbench.serve --open-browser
```

- [ ] **Step 3: `launcher/launcher.py`（exe 的唯一内容）**

```python
"""对账工作台启动器：只负责拉起 venv 的 Python 服务并打开浏览器。
应用代码与数据不打包进 exe——换机器/改代码无需重新打包。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):          # PyInstaller 打包后，exe 所在目录即项目根
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def main() -> None:
    root = project_root()
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        print(f"[对账工作台] 找不到 {python}")
        print("请把本 exe 放在项目根目录，或先创建虚拟环境并安装 requirements.txt。")
        input("按回车退出……")
        raise SystemExit(1)
    env = {**os.environ, "PYTHONUTF8": "1"}
    subprocess.Popen(
        [str(python), "-m", "src.workbench.serve", "--open-browser"],
        cwd=str(root), env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,   # 服务在独立控制台窗口，关窗即停
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: `scripts/build_launcher.py`**

```python
"""构建 exe 启动器：.venv/Scripts/python.exe -m scripts.build_launcher 后直接跑
`python scripts/build_launcher.py`。产物：项目根目录/对账工作台.exe"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "对账工作台.exe"


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--console", "--name", "对账工作台",
        "--distpath", str(ROOT), "--workpath", str(ROOT / "tmp" / "pyinstaller"),
        "--specpath", str(ROOT / "tmp" / "pyinstaller"),
        str(ROOT / "launcher" / "launcher.py"),
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    if not EXE.is_file():
        raise SystemExit("构建完成但找不到产物 对账工作台.exe")
    print(f"OK: {EXE}")


if __name__ == "__main__":
    main()
```

`.gitignore` 追加：

```
# 工作台构建产物
tmp/
*.exe
```

- [ ] **Step 5: 构建并冒烟**

1. `python scripts/build_launcher.py` → 生成 `对账工作台.exe`。
2. 双击 exe（或 `start 对账工作台.exe`）→ 应弹出服务控制台并自动开浏览器。
3. `curl -s http://127.0.0.1:8770/api/overview` → 返回 JSON 且 `gt.total == 1750`。
4. 关闭服务控制台窗口 → 再 `curl` 同地址应连接失败（服务确已停止）。

- [ ] **Step 6: Commit**

```bash
git add src/workbench/serve.py launcher scripts/build_launcher.py 启动对账工作台.bat .gitignore
git commit -m "feat(workbench): 启动链路——serve 入口 + bat + exe 薄启动器与构建脚本"
```

---

### Task 5: 收尾——全量回归、文档、提交

**Files:**
- Modify: `README.md`（工作台使用方式 + 参考链接）
- Modify: `docs/glossary.md`（工作台/FastAPI/启动器/服务端口 四条）
- Modify: `docs/log.md`（本次条目，四栏）
- Modify: `docs/open-questions.md`（若生成新问题）
- Modify: `handoff.md`（第 11 节进展日志追加）

**Interfaces:** 无代码接口；文档口径与 decisions D009/D010、workbench spec 一致。

- [ ] **Step 1: 全量回归** `.venv/Scripts/python.exe -m pytest` → 全绿（22 旧 + 9 新 = 31）。
- [ ] **Step 2: 文档更新**（内容按本次实际结果写，数字不许抄计划里的预期值）。
- [ ] **Step 3: 提交** `git add -A && git commit -m "docs: 工作台收尾——README/术语卡/日志/handoff"`。

---

## Self-Review 记录

- Spec 覆盖：第 2 节架构 → Task 1-4；第 3 节页面与契约 → Task 2/3；第 4 节视觉 → Task 3；第 5 节启动链路与失败处理 → Task 4（缺数据文件的报错文案在 Task 1 `_read_csv/_db_query`）；第 6 节测试 → 各 Task + Task 4 冒烟；第 7 节红线 → Global Constraints。无缺口。
- 占位符扫描：Task 3 的 Step 1-3 是"描述性"步骤（HTML/CSS/JS 全文太长不适合写进计划），属有意取舍——该任务无自动化验收，人工验证清单已列全 5 项。其余任务代码完整。
- 类型一致性：`load_overview/load_diffs/load_ledger` 签名在 Task 1 定义、Task 2 消费一致；`app` 实例名在 Task 2/4 一致；数据文件名（platform_bills/refunds/order_payments/ground_truth）与 P1 实际产物一致（已 `ls` 核对）。
