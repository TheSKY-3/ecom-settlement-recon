"""P4 BenchRec 跨域测试：全离线，手工小例子对拍。数据未落位时整体跳过。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.benchrec import matcher, score

pytestmark = pytest.mark.skipif(
    not Path("data/raw/benchrec/BenchRec_cash_v1.0_eval.csv").is_file(),
    reason="BenchRec 数据未落位")


# ── 判分器：真值三种形态 × 预测子集/相等/超集/空 ────────────────
def test_solution_parses_three_shapes(tmp_path):
    import csv
    p = tmp_path / "solution.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["B_id", "targetAllocation", "Usage"])
        w.writerow(["b1", "USD_2023-01-01_ACC#1_x", "Public"])
        w.writerow(["b2", '["USD_2023-01-01_ACC#1_x","USD_2023-01-02_ACC#1_y"]', "Public"])
        w.writerow(["b3", "", "Public"])
    sol = score.load_solution(p)
    assert sol["b1"] == frozenset({"USD_2023-01-01_ACC#1_x"})
    assert sol["b2"] == frozenset({"USD_2023-01-01_ACC#1_x", "USD_2023-01-02_ACC#1_y"})
    assert sol["b3"] == frozenset()


def test_score_subset_counts_as_correct():
    truth = {"b1": frozenset({"A", "B"}), "b2": frozenset({"C"}), "b3": frozenset()}
    pred = {"b1": frozenset({"A"}), "b2": frozenset({"C"}), "b3": frozenset()}
    out = score.score(pred, truth)
    # b1 预测子集 → 判对且算匹配决策；b2 相等 → 对；b3 双空 → 对但非匹配决策
    assert out["total"] == 3 and out["correct"] == 3
    assert out["attempted"] == 2
    assert out["precision"] == 1.0 and out["coverage"] == pytest.approx(2 / 3)


def test_score_superset_or_wrong_value_is_wrong():
    truth = {"b1": frozenset({"A"})}
    out = score.score({"b1": frozenset({"A", "B"})}, truth)
    assert out["correct"] == 0 and out["attempted"] == 1
    out2 = score.score({"b1": frozenset({"X"})}, truth)
    assert out2["correct"] == 0


def test_score_missing_prediction_treated_as_empty():
    truth = {"b1": frozenset({"A"}), "b2": frozenset()}
    out = score.score({}, truth)          # 没预测 = 全空：b2 对，b1 错
    assert out["correct"] == 1 and out["attempted"] == 0
    assert out["total"] == 2


# ── 匹配器：mini eval（唯一命中 / 多键消歧 / 无候选放弃）────────
A_ROWS = [
    {"A_id": "a1", "A_allocation": "USD_2023-03-01_ACC#1_k1", "A_currencyCode": "USD",
     "A_account": "ACC#1", "A_amount": "100.00", "A_valueDate": "2023-03-01",
     "A_transactionReferences": "REF 111"},
    {"A_id": "a2", "A_allocation": "USD_2023-03-01_ACC#1_k2", "A_currencyCode": "USD",
     "A_account": "ACC#1", "A_amount": "200.00", "A_valueDate": "2023-03-01",
     "A_transactionReferences": "REF 222"},
    {"A_id": "a3", "A_allocation": "USD_2023-03-05_ACC#1_k3", "A_currencyCode": "USD",
     "A_account": "ACC#1", "A_amount": "300.00", "A_valueDate": "2023-03-05",
     "A_transactionReferences": "REF 333"},
]

B_ROWS = [
    {"B_id": "b1", "B_currencyCode": "USD", "B_account": "ACC#1",
     "B_amount": "100.00", "B_valueDate": "2023-03-01", "B_transactionReferences": "REF 111"},
    {"B_id": "b2", "B_currencyCode": "USD", "B_account": "ACC#1",
     "B_amount": "200.00", "B_valueDate": "2023-03-02", "B_transactionReferences": "REF 999"},
    {"B_id": "b3", "B_currencyCode": "USD", "B_account": "ACC#1",
     "B_amount": "999.00", "B_valueDate": "2023-03-01", "B_transactionReferences": "REF X"},
]


def test_matcher_unique_hit_and_disambiguation_and_giveup():
    pred = matcher.match(B_ROWS, A_ROWS)
    assert pred["b1"] == frozenset({"USD_2023-03-01_ACC#1_k1"})   # 唯一命中
    assert pred["b3"] == frozenset()                              # 无候选 → 放弃


def test_matcher_date_prefers_closest():
    # a2 日期差 1 天是唯一候选 → 匹配（金额 200 只有 a2）
    pred = matcher.match(B_ROWS, A_ROWS)
    assert pred["b2"] == frozenset({"USD_2023-03-01_ACC#1_k2"})


def test_matcher_same_allocation_multiple_rows_is_one_key():
    a_dup = dict(A_ROWS[0], A_id="a1b")   # 同分配键的第二条分录
    pred = matcher.match(B_ROWS, A_ROWS + [a_dup])
    assert pred["b1"] == frozenset({"USD_2023-03-01_ACC#1_k1"})


def test_matcher_reference_disambiguates_or_gives_up():
    a4 = {"A_id": "a4", "A_allocation": "USD_2023-03-01_ACC#1_k4", "A_currencyCode": "USD",
          "A_account": "ACC#1", "A_amount": "200.00", "A_valueDate": "2023-03-01",
          "A_transactionReferences": "REF 555 EXTRA"}
    pred = matcher.match(B_ROWS, A_ROWS + [a4])
    # b2 参考号 REF 999 与两个候选（a2: REF 222 / a4: REF 555 EXTRA）都无包含 → 放弃（保精度）
    assert pred["b2"] == frozenset()
    # b4 参考号 REF 555 只被 a4 的参考号包含 → 消歧到 k4
    b4 = {"B_id": "b4", "B_currencyCode": "USD", "B_account": "ACC#1",
          "B_amount": "200.00", "B_valueDate": "2023-03-01", "B_transactionReferences": "REF 555"}
    pred2 = matcher.match([b4], A_ROWS + [a4])
    assert pred2["b4"] == frozenset({"USD_2023-03-01_ACC#1_k4"})
