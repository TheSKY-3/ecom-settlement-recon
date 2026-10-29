import pytest
from fastapi.testclient import TestClient

from src.workbench.app import app
from tests.test_workbench_data import env  # 复用数据夹具


@pytest.fixture()
def client(env):
    return TestClient(app)


def test_overview_shape(client):
    r = client.get("/api/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["seed"] == 20260926
    assert body["gt"]["total"] == 4


def test_diffs_validation(client):
    r = client.get("/api/diffs", params={"page_size": 0})
    assert r.status_code == 422
    r = client.get("/api/diffs", params={"page_size": 500})
    assert r.status_code == 422


def test_diffs_filters(client):
    r = client.get("/api/diffs", params={"type": "单边账"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert {row["gt_id"] for row in body["rows"]} == {"GT000001", "GT000004"}


def test_ledger_404_and_200(client):
    assert client.get("/api/diffs/GT999999/ledger").status_code == 404
    r = client.get("/api/diffs/GT000001/ledger")
    assert r.status_code == 200
    body = r.json()
    assert body["gt"]["order_id"] == "o1"
    assert body["original_available"] is True
    assert set(body) == {"gt", "clean_bills", "clean_payments", "clean_refunds",
                            "bills", "payments", "refunds", "orders", "items",
                            "original_available"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "对账工作台" in r.text
