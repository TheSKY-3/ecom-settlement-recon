from evals.score import score


def test_hand_computed_metrics():
    gt = [{"order_id": f"o{i}", "diff_type": "单边账"} for i in (1, 2, 3)] + \
         [{"order_id": "o4", "diff_type": "重复结算"}]
    finds = [{"order_id": f"o{i}", "diff_type": "单边账"} for i in (1, 2)] + \
            [{"order_id": "o9", "diff_type": "单边账"},
             {"order_id": "o4", "diff_type": "重复结算"}]
    r = score(gt, finds, natural_ids={"o9"})
    assert r["tp"] == 3 and r["fn"] == 1 and r["fp"] == 1
    assert r["fp_natural"] == 1 and r["fp_other"] == 0
    assert r["recall"] == 0.75 and r["precision_other"] == 1.0
    assert r["by_type"]["单边账"] == {"tp": 2, "fn": 1, "fp": 1, "recall": round(2 / 3, 4)}
    assert r["by_type"]["重复结算"]["tp"] == 1
    assert r["amount_consistency"] is None    # 考卷无金额列时不评金额一致性


def test_amount_consistency_per_tp():
    """考卷 v1.2：TP 逐条对账引擎复算金额 vs 注入金额；FP 不参与。"""
    gt = [{"order_id": "o1", "diff_type": "单边账", "amount": "90.00"},
          {"order_id": "o2", "diff_type": "金额不符", "amount": "10.00"},
          {"order_id": "o3", "diff_type": "退款遗漏", "amount": ""}]  # 缺金额 → 跳过
    finds = [{"order_id": "o1", "diff_type": "单边账", "amount": 90.0},
             {"order_id": "o2", "diff_type": "金额不符", "amount": 12.0},  # 对不上
             {"order_id": "o9", "diff_type": "金额不符", "amount": 5.0}]   # FP 不评
    r = score(gt, finds, natural_ids=set())
    assert r["amount_consistency"] == {
        "checked": 2, "match": 1, "mismatch_keys": [["o2", "金额不符"]]}
