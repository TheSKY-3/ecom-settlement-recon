import json

import pytest
from fastapi.testclient import TestClient

from src.workbench.app import app
from tests.test_workbench_data import env  # 复用数据夹具

FINDINGS = [
    {"finding_id": "F000001", "order_id": "o2", "diff_type": "单边账", "variant": "删账单",
     "target_side": "bills", "confidence": 1.0, "description": "账单缺失", "verified": True},
    {"finding_id": "F000002", "order_id": "o3", "diff_type": "金额不符", "variant": "费率错误",
     "target_side": "bills", "confidence": 1.0, "description": "佣金费率错误", "verified": True},
]


@pytest.fixture()
def client(env, tmp_path, monkeypatch):
    out = tmp_path / "engine"
    out.mkdir()
    (out / "findings.json").write_text(
        json.dumps({"audit": {}, "findings": FINDINGS}), encoding="utf-8")
    (out / "score.json").write_text(json.dumps(
        {"gt_total": 2, "tp": 2, "fn": 0, "fp": 0, "recall": 1.0,
         "precision_other": 1.0, "by_type": {}}), encoding="utf-8")
    monkeypatch.setenv("RECON_ENGINE_DIR", str(out))
    return TestClient(app)


def test_engine_available(client):
    body = client.get("/api/engine").json()
    assert body["available"] is True and body["score"]["tp"] == 2


def test_engine_findings_page(client):
    body = client.get("/api/engine/findings", params={"type": "单边账"}).json()
    assert body["total"] == 1
    assert body["rows"][0]["confidence"] == 1.0 and body["rows"][0]["verified"] is True


def test_engine_missing_returns_unavailable(client, env, tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_ENGINE_DIR", str(tmp_path / "nope"))
    c = TestClient(app)
    body = c.get("/api/engine").json()
    assert body["available"] is False and "run_engine" in body["hint"]
    assert c.get("/api/engine/findings").status_code == 404


def test_ledger_by_order(client):
    r = client.get("/api/ledger/order/o1")   # gt GT000001 的订单
    assert r.status_code == 200
    body = r.json()
    assert body["gt"]["gt_id"] == "GT000001"
    assert body["payments"][0]["payment_value"] == "15.00"


def test_ledger_by_order_without_gt(client):
    r = client.get("/api/ledger/order/o9")   # 不在标准答案里的订单 → gt 为 null
    assert r.status_code == 200
    assert r.json()["gt"] is None


def test_ledger_by_order_unknown(client):
    assert client.get("/api/ledger/order/zzz").status_code == 404
