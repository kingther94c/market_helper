from __future__ import annotations


class ReadOnlyViolationError(RuntimeError):
    """Raised when a write/trading operation is attempted in read-only mode."""


def assert_read_only_mode(mode: str) -> None:
    if mode != "read_only":
        raise ReadOnlyViolationError(
            f"Invalid mode '{mode}'. Only 'read_only' is allowed in V1."
        )


def assert_operation_allowed(operation: str) -> None:
    allowed_prefixes = (
        "read_",
        "get_",
        "fetch_",
        "stream_",
    )
    if not operation.startswith(allowed_prefixes):
        raise ReadOnlyViolationError(
            f"Operation '{operation}' is blocked by read-only policy."
        )
