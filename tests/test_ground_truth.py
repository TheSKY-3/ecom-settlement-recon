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


def test_diff_type_whitelist():
    with pytest.raises(ValueError):
        make_row("x", "不存在的类型", "v", "bills", "d", seq=1)


def test_write_read_roundtrip(tmp_path):
    rows = [
        make_row("o1", "单边账", "删账单", "bills", "d1", seq=1),
        make_row("o2", "金额不符", "费率错误", "bills", "d2", seq=2),
    ]
    path = tmp_path / "gt.csv"
    write(rows, path)
    assert read(path) == rows
