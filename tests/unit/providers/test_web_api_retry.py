import pytest

from market_helper.providers.web_api import with_retry


def test_with_retry_retries_then_succeeds() -> None:
    state = {"count": 0}

    def op() -> str:
        state["count"] += 1
        if state["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    sleeps: list[float] = []
    result = with_retry(op, attempts=3, delay_seconds=0.01, sleep=sleeps.append)

    assert result == "ok"
    assert state["count"] == 3
    assert sleeps == [0.01, 0.01]


def test_with_retry_raises_for_invalid_attempts() -> None:
    with pytest.raises(ValueError):
        with_retry(lambda: "ok", attempts=0)
