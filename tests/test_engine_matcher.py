from src.engine.matcher import load_world


def test_world_groups_and_natural_ids(engine_env):
    synth, db = engine_env
    w = load_world(synth, db)
    assert len(w.orders) == 11
    assert len(w.bills_by_order["o7"]) == 2
    assert len(w.bills_by_order["o8"]) == 2
    assert w.refunds_by_order["o11"][0]["refund_id"] == "R_o11"
    assert "o5" in w.natural_ids and "o1" not in w.natural_ids
    assert w.sources["platform_bills"]["rows"] == 11
