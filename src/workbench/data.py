"""工作台数据层：只读合成评测集与底座库。

路径每次调用时从环境变量读取（RECON_SYNTHETIC_DIR / RECON_DB_PATH），便于测试
重定向；文件内容按"路径+修改时间"缓存，全量 10 万行 CSV 的线性扫描在本项目
数据量下是几十毫秒级，暂不做索引（P2 接引擎后此处整体替换）。
"""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from src.synth.config import SEED

# 账本浏览：world × book 的合法组合与各账本列名（与 data/synthetic/*.csv 表头一致）
BOOK_FILES = {"platform_bills": "platform_bills",
              "order_payments": "order_payments",
              "refunds": "refunds"}
BOOK_COLUMNS = {
    "platform_bills": ["bill_id", "order_id", "seller_id", "version", "issued_date",
                       "commission_rate", "commission_fee", "freight_amount",
                       "price_amount", "settlement_amount"],
    "order_payments": ["order_id", "payment_sequential", "payment_type",
                       "payment_installments", "payment_value"],
    "refunds": ["refund_id", "order_id", "refund_amount", "refund_date",
                "refund_reason"],
}


def _synthetic_dir() -> Path:
    return Path(os.environ.get(
        "RECON_SYNTHETIC_DIR", Path(__file__).resolve().parents[2] / "data" / "synthetic"))


def _db_path() -> Path:
    return Path(os.environ.get(
        "RECON_DB_PATH", Path(__file__).resolve().parents[2] / "data" / "olist.db"))


_cache: dict = {}


def _cached(key, factory):
    hit = _cache.get(key)
    if hit is None:
        hit = factory()
        _cache[key] = hit
    return hit


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(
            f"缺少数据文件：{path}。先跑 scripts/build_synthetic.py 生成 data/synthetic/。")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _gt_rows() -> list[dict]:
    path = _synthetic_dir() / "dirty" / "ground_truth.csv"
    stat = path.stat().st_mtime if path.is_file() else 0
    return _cached(("gt", str(path), stat), lambda: _read_csv(path))


def _side_rows(world: str, name: str) -> list[dict]:
    path = _synthetic_dir() / world / f"{name}.csv"
    stat = path.stat().st_mtime if path.is_file() else 0
    return _cached((world, name, str(path), stat), lambda: _read_csv(path))


# 数据清单：工作台对外只讲这 8 份 CSV + 1 份成绩 JSON 的来历，避免“到底几份表”靠猜。
# role 只描述用途：输入=真实对账要读的账；参照=评测用干净副本；标准答案=考题答案；
# 产出=引擎跑出来的结果。
TABLE_SPECS = (
    {"key": "dirty_bills", "label": "平台账单（实际批次）", "role": "输入",
     "world": "dirty", "book": "platform_bills"},
    {"key": "dirty_payments", "label": "支付流水（实际批次）", "role": "输入",
     "world": "dirty", "book": "order_payments"},
    {"key": "dirty_refunds", "label": "退款流水（实际批次）", "role": "输入",
     "world": "dirty", "book": "refunds"},
    {"key": "clean_bills", "label": "平台账单（干净参照）", "role": "参照",
     "world": "clean", "book": "platform_bills"},
    {"key": "clean_payments", "label": "支付流水（干净参照）", "role": "参照",
     "world": "clean", "book": "order_payments"},
    {"key": "clean_refunds", "label": "退款流水（干净参照）", "role": "参照",
     "world": "clean", "book": "refunds"},
    {"key": "ground_truth", "label": "标准答案（GT）", "role": "标准答案",
     "columns": ["gt_id", "order_id", "diff_type", "variant", "target_side",
                 "description"]},
    {"key": "findings", "label": "引擎发现", "role": "产出",
     "columns": ["finding_id", "order_id", "diff_type", "variant", "target_side",
                 "confidence", "description", "verified"]},
)


def side_rows(world: str, book: str) -> list[dict]:
    """公开的源表读取（账本导出/统计用）；世界与账本非法时抛 ValueError。"""
    if world not in ("clean", "dirty"):
        raise ValueError(f"未知账本版本：{world}")
    if book not in BOOK_FILES:
        raise ValueError(f"未知账本：{book}")
    return _side_rows(world, BOOK_FILES[book])


def gt_rows() -> list[dict]:
    return _gt_rows()


def findings_rows() -> list[dict]:
    path = _engine_dir() / "findings.json"
    stat = path.stat().st_mtime if path.is_file() else 0
    return _cached(("findings", str(path), stat),
                   lambda: json.loads(path.read_text(encoding="utf-8"))["findings"])


def load_tables() -> dict:
    """数据清单：每份表的角色、行数、列名与浏览入口（前端数据源条 + 对话工具共用）。"""
    overview = load_overview()
    tables = []
    for spec in TABLE_SPECS:
        if "world" in spec:
            rows = side_rows(spec["world"], spec["book"])
            columns = BOOK_COLUMNS[spec["book"]]
            browse = f"/api/rows/{spec['world']}/{spec['book']}"
        elif spec["key"] == "ground_truth":
            rows = gt_rows()
            columns = list(spec["columns"])
            browse = "/api/diffs"
        else:
            rows = findings_rows()
            columns = list(spec["columns"])
            browse = "/api/engine/findings"
        tables.append({
            "key": spec["key"], "label": spec["label"], "role": spec["role"],
            "rows": len(rows), "columns": columns, "browse": browse,
        })
    summary = load_engine_summary()
    return {"seed": SEED, "tables": tables,
            "gt_total": overview["gt"]["total"],
            "engine_available": summary is not None,
            "engine_run_id": (summary or {}).get("run_id")}


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


def _filter_page(rows: list[dict], diff_type: str | None, side: str | None,
                 q: str | None, page: int, page_size: int) -> dict:
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


def load_diffs(diff_type: str | None, side: str | None, q: str | None,
               page: int, page_size: int) -> dict:
    return _filter_page(_gt_rows(), diff_type, side, q, page, page_size)


def _engine_dir() -> Path:
    return Path(os.environ.get(
        "RECON_ENGINE_DIR", Path(__file__).resolve().parents[2] / "output" / "engine"))


def load_engine_summary() -> dict | None:
    path = _engine_dir() / "score.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_engine_diffs(diff_type: str | None, side: str | None, q: str | None,
                      page: int, page_size: int, *,
                      min_confidence: float | None = None,
                      max_confidence: float | None = None,
                      verified: bool | None = None,
                      natural_only: bool = False) -> dict | None:
    """引擎发现列表；可选过滤（D014 给对话工具用，默认不过滤，老调用不受影响）。

    natural_only=True 只留"订单在标准答案里完全没有记录"的发现，即自然差异口径
    （与 evals/score.py 的 fp_natural 一致：本评测集 575 条 FP 全部落在 GT 之外）。
    """
    path = _engine_dir() / "findings.json"
    if not path.is_file():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))["findings"]
    if min_confidence is not None:
        rows = [r for r in rows
                if float(r.get("confidence") or 0) >= float(min_confidence)]
    if max_confidence is not None:
        rows = [r for r in rows
                if float(r.get("confidence") or 0) <= float(max_confidence)]
    if verified is not None:
        rows = [r for r in rows if bool(r.get("verified")) is bool(verified)]
    if natural_only:
        gt_orders = {r["order_id"] for r in _gt_rows()}
        rows = [r for r in rows if r["order_id"] not in gt_orders]
    return _filter_page(rows, diff_type, side, q, page, page_size)


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


def _db_available() -> bool:
    """原始订单库是否存在：Docker 镜像默认只带合成评测集，不带 data/olist.db。"""
    return _db_path().is_file()


def _ledger_sections(oid: str) -> dict:
    sections = {
        # 标准账本（应有的账）
        "clean_bills": [r for r in _side_rows("clean", "platform_bills") if r["order_id"] == oid],
        "clean_payments": [r for r in _side_rows("clean", "order_payments") if r["order_id"] == oid],
        "clean_refunds": [r for r in _side_rows("clean", "refunds") if r["order_id"] == oid],
        # 实际账本（埋错后的账）
        "bills": [r for r in _side_rows("dirty", "platform_bills") if r["order_id"] == oid],
        "payments": [r for r in _side_rows("dirty", "order_payments") if r["order_id"] == oid],
        "refunds": [r for r in _side_rows("dirty", "refunds") if r["order_id"] == oid],
    }
    # 原始记录（订单底座，不分世界）：底座库缺失时留空，由前端提示原因（Docker 镜像即此场景）
    sections["orders"] = (_db_query("SELECT * FROM orders WHERE order_id = ?", (oid,))
                          if _db_available() else [])
    sections["items"] = (_db_query("SELECT * FROM order_items WHERE order_id = ?", (oid,))
                         if _db_available() else [])
    return sections


def load_rows(world: str, book: str, q: str | None, page: int, page_size: int) -> dict:
    """账本浏览：任一世界任一账本的全字段分页浏览。"""
    if world not in ("clean", "dirty"):
        raise ValueError(f"未知账本版本：{world}")
    if book not in BOOK_FILES:
        raise ValueError(f"未知账本：{book}")
    rows = _side_rows(world, BOOK_FILES[book])
    if q:
        needle = q.lower()
        rows = [r for r in rows if any(needle in str(v).lower() for v in r.values())]
    total = len(rows)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size,
            "columns": BOOK_COLUMNS[book], "rows": rows[start:start + page_size]}


def load_ledger(gt_id: str) -> dict | None:
    gts = [r for r in _gt_rows() if r["gt_id"] == gt_id]
    if not gts:
        return None
    return {"gt": gts[0], "original_available": _db_available(),
            **_ledger_sections(gts[0]["order_id"])}


def load_ledger_by_order(order_id: str) -> dict | None:
    """引擎发现只有订单号；标准答案里可能没有该单（如自然差异），gt 允许为空。"""
    gts = [r for r in _gt_rows() if r["order_id"] == order_id]
    sections = _ledger_sections(order_id)
    if gts == [] and not any(sections.values()):
        return None
    return {"gt": gts[0] if gts else None, "original_available": _db_available(), **sections}
