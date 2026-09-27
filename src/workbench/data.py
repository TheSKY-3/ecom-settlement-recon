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
    "refunds": ["refund_id", "order_id", "refund_amount", "refund_date"],
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
                      page: int, page_size: int) -> dict | None:
    path = _engine_dir() / "findings.json"
    if not path.is_file():
        return None
    rows = json.loads(path.read_text(encoding="utf-8"))["findings"]
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


def _ledger_sections(oid: str) -> dict:
    return {
        # 标准账本（应有的账）
        "clean_bills": [r for r in _side_rows("clean", "platform_bills") if r["order_id"] == oid],
        "clean_payments": [r for r in _side_rows("clean", "order_payments") if r["order_id"] == oid],
        "clean_refunds": [r for r in _side_rows("clean", "refunds") if r["order_id"] == oid],
        # 实际账本（埋错后的账）
        "bills": [r for r in _side_rows("dirty", "platform_bills") if r["order_id"] == oid],
        "payments": [r for r in _side_rows("dirty", "order_payments") if r["order_id"] == oid],
        "refunds": [r for r in _side_rows("dirty", "refunds") if r["order_id"] == oid],
        # 原始记录（订单底座，不分世界）
        "orders": _db_query("SELECT * FROM orders WHERE order_id = ?", (oid,)),
        "items": _db_query("SELECT * FROM order_items WHERE order_id = ?", (oid,)),
    }


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
    return {"gt": gts[0], **_ledger_sections(gts[0]["order_id"])}


def load_ledger_by_order(order_id: str) -> dict | None:
    """引擎发现只有订单号；标准答案里可能没有该单（如自然差异），gt 允许为空。"""
    gts = [r for r in _gt_rows() if r["order_id"] == order_id]
    sections = _ledger_sections(order_id)
    if gts == [] and not any(sections.values()):
        return None
    return {"gt": gts[0] if gts else None, **sections}
