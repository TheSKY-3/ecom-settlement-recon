import json

from src.engine.audit import AuditChain, verify_chain


def test_chain_links_and_verifies():
    c = AuditChain("R1")
    c.add_step("load", inputs=[{"name": "a", "sha256": "x", "rows": 1}])
    c.add_step("classify", params={"rules": "v1"}, outputs=[{"name": "f", "rows": 2}])
    d = c.to_dict()
    assert len(d["steps"]) == 2
    assert d["steps"][1]["prev_hash"] == d["steps"][0]["step_hash"]
    assert verify_chain(d) is True


def test_tamper_breaks_chain():
    c = AuditChain("R1")
    c.add_step("load", inputs=[{"name": "a", "sha256": "x"}])
    c.add_step("classify")
    d = c.to_dict()
    d["steps"][0]["action"] = "tampered"
    assert verify_chain(d) is False


def test_roundtrip_json():
    c = AuditChain("R1")
    c.add_step("load")
    assert verify_chain(json.loads(json.dumps(c.to_dict()))) is True
