import pytest

from market_helper.safety import (
    ReadOnlyViolationError,
    assert_operation_allowed,
    assert_read_only_mode,
)


def test_assert_read_only_mode_accepts_read_only() -> None:
    assert_read_only_mode("read_only")


def test_assert_read_only_mode_rejects_other_modes() -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_read_only_mode("paper")


def test_assert_operation_allowed_blocks_trading_operation() -> None:
    with pytest.raises(ReadOnlyViolationError):
        assert_operation_allowed("place_order")
