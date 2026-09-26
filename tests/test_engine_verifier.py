from src.engine.classifier import classify
from src.engine.matcher import load_world
from src.engine.verifier import verify


def test_all_injected_findings_verified(engine_env):
    synth, db = engine_env
    w = load_world(synth, db)
    fs = classify(w)
    verify(w, fs)
    assert all(f["verified"] for f in fs), [f for f in fs if not f["verified"]]


def test_fake_finding_fails_verification(engine_env):
    synth, db = engine_env
    w = load_world(synth, db)
    fs = classify(w)
    fs.append({"finding_id": "F999999", "order_id": "o1", "diff_type": "单边账",
               "variant": "删账单", "target_side": "bills", "confidence": 1.0,
               "description": "伪造", "evidence": {}, "verified": False})
    verify(w, fs)
    assert fs[-1]["verified"] is False
