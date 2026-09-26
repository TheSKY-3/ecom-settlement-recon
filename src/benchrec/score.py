"""BenchRec 判分器：真值三种形态统一解析，预测 ⊆ 真值 即判对。"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def _parse_target(raw: str) -> frozenset[str]:
    s = raw.strip()
    if not s:
        return frozenset()
    if s.startswith("["):
        try:
            return frozenset(x for x in json.loads(s) if x)
        except json.JSONDecodeError:
            return frozenset()
    return frozenset({s})


def load_solution(path: Path) -> dict[str, frozenset[str]]:
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["B_id"]] = _parse_target(row["targetAllocation"])
    return out


def load_submission(path: Path) -> dict[str, frozenset[str]]:
    """官方提交格式（我们的引擎也按此落盘）：targetAllocation 列为 JSON 数组。"""
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["B_id"]] = _parse_target(row["targetAllocation"])
    return out


def score(pred: dict[str, frozenset[str]],
          truth: dict[str, frozenset[str]]) -> dict:
    total = len(truth)
    correct = attempted = attempted_correct = 0
    for b_id, t in truth.items():
        p = pred.get(b_id, frozenset())
        if p:
            attempted += 1
            if p <= t:
                attempted_correct += 1
            correct += p <= t
        else:
            correct += not t          # 双空判对；真值有分配而预测空 = 漏配
    return {
        "total": total,
        "correct": correct,
        "attempted": attempted,
        "precision": round(attempted_correct / attempted, 6) if attempted else 0.0,
        "coverage": round(attempted / total, 6) if total else 0.0,
        "accuracy": round(correct / total, 6) if total else 0.0,
    }
