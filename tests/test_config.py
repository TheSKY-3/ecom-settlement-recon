import pytest

from src.synth import config


def test_config_frozen_numbers():
    assert config.SEED == 20260926
    assert config.COMMISSION_RATE == 0.20
    assert config.WRONG_RATE == 0.10
    assert config.OLD_RATE == 0.15
    assert config.TOLERANCE == 0.005
    assert config.SINGLE_DROP_BILL == 400
    assert config.SINGLE_ORPHAN_BILL == 100
    assert config.SINGLE_DROP_PAYMENT == 200
    assert config.AMOUNT_WRONG_RATE == 250
    assert config.AMOUNT_MISSING_FREIGHT == 250
    assert config.STATUS_REBILL == 150
    assert config.REFUND_MISSING == 200
    assert config.DUPLICATE_BILL == 100
    assert config.VERSION_DIFF == 100
