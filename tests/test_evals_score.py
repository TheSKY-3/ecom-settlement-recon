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
