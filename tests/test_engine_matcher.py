from src.engine.matcher import load_world


def test_world_groups_and_natural_ids(engine_env):
    synth, db = engine_env
    w = load_world(synth, db)
    assert len(w.orders) == 12
    assert len(w.bills_by_order["o7"]) == 2
    assert len(w.bills_by_order["o8"]) == 2
    assert w.refunds_by_order["o11"][0]["refund_id"] == "R_o11"
    # 自然口径 = 金额不符（o5）∪ 活跃零支付（o12）
    assert {"o5", "o12"} <= w.natural_ids and "o1" not in w.natural_ids
    assert w.sources["platform_bills"]["rows"] == 12
