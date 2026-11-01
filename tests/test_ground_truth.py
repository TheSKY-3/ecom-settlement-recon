import pytest

from src.synth.ground_truth import COLUMNS, make_row, read, write


def test_make_row_fields_and_sequence():
    row = make_row("abc123", "单边账", "删账单", "bills", "描述", seq=7)
    assert row["gt_id"] == "GT000007"
    assert row["order_id"] == "abc123"
    assert row["diff_type"] == "单边账"
    assert row["variant"] == "删账单"
    assert row["target_side"] == "bills"
    assert list(row.keys()) == COLUMNS


def test_make_row_amount_format():
    row = make_row("abc", "单边账", "删账单", "bills", "d", seq=1, amount=90.0)
    assert row["amount"] == "90.00"
    row2 = make_row("abc", "重复结算", "整单重复", "bills", "d", seq=2, amount=12.345)
    assert row2["amount"] == "12.35"          # 两位小数、四舍五入
    row3 = make_row("abc", "退款遗漏", "退款缺失", "refunds", "d", seq=3)
    assert row3["amount"] is None             # 不传金额也合法（None 落盘为空）
    with pytest.raises(ValueError):
        make_row("abc", "单边账", "删账单", "bills", "d", seq=4, amount=-1)


def test_diff_type_whitelist():
    with pytest.raises(ValueError):
        make_row("x", "不存在的类型", "v", "bills", "d", seq=1)


def test_write_read_roundtrip(tmp_path):
    rows = [
        make_row("o1", "单边账", "删账单", "bills", "d1", seq=1, amount=154.39),
        make_row("o2", "金额不符", "费率错误", "bills", "d2", seq=2, amount=10.0),
    ]
    path = tmp_path / "gt.csv"
    write(rows, path)
    got = read(path)
    # CSV 读回都是字符串：既有六列逐列相等，amount 以两位小数字符串往返
    assert [{k: r[k] for k in COLUMNS if k != "amount"} for r in got] == \
           [{k: r[k] for k in COLUMNS if k != "amount"} for r in rows]
    assert [r["amount"] for r in got] == ["154.39", "10.00"]
