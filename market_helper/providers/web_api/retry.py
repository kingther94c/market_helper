from __future__ import annotations

from collections.abc import Callable
import time
from typing import TypeVar

T = TypeVar("T")


def with_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_seconds: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_error: Exception | None = None
    for index in range(attempts):
        try:
            return operation()
        except Exception as error:  # noqa: BLE001
            last_error = error
            if index < attempts - 1:
                sleep(delay_seconds)

    assert last_error is not None
    raise last_error
