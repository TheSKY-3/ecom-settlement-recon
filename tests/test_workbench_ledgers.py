"""账本浏览 + 证据弹层"标准账本对照"测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.workbench import data as wbdata
from src.workbench.app import app
from tests.test_workbench_data import env  # noqa: F401  数据夹具


@pytest.fixture()
def client(env):
    return TestClient(app)


# ── 第一步：弹层对照——ledger 返回带标准账本三段 ────────────────
def test_ledger_includes_clean_counterpart(env):
    led = wbdata.load_ledger("GT000001")          # o1 删账单雷
    assert led["original_available"] is True      # 夹具里建了底座库
    assert len(led["clean_bills"]) == 1           # 标准账本里应该有这张账单
    assert led["clean_bills"][0]["bill_id"] == "B_1"
    assert led["bills"] == []                     # 实际账本里被删了
    assert len(led["clean_payments"]) == 1 and len(led["clean_refunds"]) == 0


def test_ledger_by_order_also_has_clean(env):
    led = wbdata.load_ledger_by_order("o1")
    assert len(led["clean_bills"]) == 1 and len(led["bills"]) == 0


# ── 第二步：账本浏览——通用分页接口 ─────────────────────────────
def test_load_rows_clean_bills(env):
    page = wbdata.load_rows("clean", "platform_bills", None, 1, 50)
    assert page["total"] == 1 and page["columns"][0] == "bill_id"
    assert page["rows"][0]["order_id"] == "o1"


def test_load_rows_q_filter_and_paging(env):
    assert wbdata.load_rows("dirty", "platform_bills", "o9", 1, 50)["total"] == 1
    assert wbdata.load_rows("dirty", "platform_bills", "nomatch", 1, 50)["total"] == 0
    page = wbdata.load_rows("clean", "order_payments", None, 1, 50)
    assert page["rows"][0]["payment_value"] == "15.00"


def test_load_rows_validates_inputs(env):
    with pytest.raises(ValueError):
        wbdata.load_rows("middle", "platform_bills", None, 1, 50)
    with pytest.raises(ValueError):
        wbdata.load_rows("clean", "cash_ledger", None, 1, 50)


def test_api_rows_roundtrip(client):
    body = client.get("/api/rows/clean/platform_bills", params={"q": "o1"}).json()
    assert body["total"] == 1 and body["rows"][0]["bill_id"] == "B_1"
    assert client.get("/api/rows/middle/platform_bills").status_code == 400
    assert client.get("/api/rows/clean/nope").status_code == 400


# ── 第三步：缺原始订单库（Docker 镜像默认场景）——降级而不报错 ─────
def test_ledger_without_base_db_degrades(env, monkeypatch, tmp_path):
    monkeypatch.setenv("RECON_DB_PATH", str(tmp_path / "missing.db"))
    led = wbdata.load_ledger("GT000001")
    assert led["original_available"] is False
    assert led["orders"] == [] and led["items"] == []
    assert len(led["payments"]) == 1              # 合成账本对照不受影响


def test_api_ledger_without_base_db_returns_flag(client, monkeypatch, tmp_path):
    monkeypatch.setenv("RECON_DB_PATH", str(tmp_path / "missing.db"))
    r = client.get("/api/diffs/GT000001/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["original_available"] is False and body["orders"] == []
