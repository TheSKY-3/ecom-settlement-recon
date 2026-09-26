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
        "bills": [r for r in _side_rows("dirty", "platform_bills") if r["order_id"] == oid],
        "payments": [r for r in _side_rows("dirty", "order_payments") if r["order_id"] == oid],
        "refunds": [r for r in _side_rows("dirty", "refunds") if r["order_id"] == oid],
        "orders": _db_query("SELECT * FROM orders WHERE order_id = ?", (oid,)),
        "items": _db_query("SELECT * FROM order_items WHERE order_id = ?", (oid,)),
    }


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
