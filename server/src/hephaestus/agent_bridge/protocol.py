"""JSON-RPC method registry, frozen wire vocabulary, and ``hv`` negotiation.

The frozen method names and frame shape are fixed by ``agent/DESIGN.md`` §"Wire
protocol"; the mirror TypeScript constants live in ``agent/src/rpc.ts``. Every
frame carries ``{"hv": 1, "jsonrpc": "2.0", ...}``; an unknown ``hv`` fails
closed. This module supplies the reusable pieces the supervisor composes with
:mod:`framing`:

* the frozen sets of request methods / notifications each side may originate,
* JSON-RPC + Hephaestus error codes shared with the sidecar,
* :func:`validate_frame` (version + envelope shape),
* :class:`MethodRegistry` for dispatching ``py.*`` requests the sidecar sends.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final, cast

from .limits import FRAME_VERSION

__all__ = [
    "FRAME_VERSION",
    "JSONRPC_VERSION",
    "PY_NOTIFICATIONS",
    "PY_REQUEST_METHODS",
    "SIDECAR_NOTIFICATIONS",
    "SIDECAR_REQUEST_METHODS",
    "ErrorCode",
    "MethodRegistry",
    "ProtocolError",
    "make_error",
    "make_notification",
    "make_request",
    "make_response",
    "validate_frame",
]

JSONRPC_VERSION: Final[str] = "2.0"


class ErrorCode:
    """Stable JSON-RPC + Hephaestus error codes (mirrored in ``rpc.ts``)."""

    PARSE_ERROR: Final[int] = -32700
    INVALID_REQUEST: Final[int] = -32600
    METHOD_NOT_FOUND: Final[int] = -32601
    INVALID_PARAMS: Final[int] = -32602
    INTERNAL_ERROR: Final[int] = -32603
    # Hephaestus application range.
    BUSY: Final[int] = -32000
    FRAME_TOO_LARGE: Final[int] = -32001
    UNSUPPORTED_VERSION: Final[int] = -32002
    TIMEOUT: Final[int] = -32003
    PROCESS_DOWN: Final[int] = -32004
    CANCELLED: Final[int] = -32800


# Python (supervisor) -> sidecar requests.
SIDECAR_REQUEST_METHODS: Final[frozenset[str]] = frozenset(
    {
        "session.create",
        "session.prompt",
        "session.cancel",
        "session.compact",
        "history.page",
        "query.snapshot",
        "runtime.configure",
        "shutdown",
    }
)

# Sidecar -> Python (supervisor) requests.
PY_REQUEST_METHODS: Final[frozenset[str]] = frozenset(
    {
        "py.tool_dispatch",
        "py.jobstore_get",
        "py.jobstore_put",
        "py.jobstore_list",
        "py.jobstore_delete",
        "py.jobstore_checkpoint",
        "py.admission_capacity",
        "py.delegate",
        "py.ask_user",
    }
)

# Sidecar -> Python notifications.
SIDECAR_NOTIFICATIONS: Final[frozenset[str]] = frozenset({"event", "terminal"})

# Python -> sidecar notifications.
PY_NOTIFICATIONS: Final[frozenset[str]] = frozenset({"cancel", "terminal.ack", "session.answer"})


class ProtocolError(Exception):
    """A frame violated the envelope contract. ``code`` is a JSON-RPC code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_frame(frame: object) -> dict[str, Any]:
    """Validate the shared envelope; fail closed on a bad ``hv``.

    Returns the frame as a ``dict`` on success. Raises :class:`ProtocolError`
    with :data:`ErrorCode.UNSUPPORTED_VERSION` for a missing/unknown ``hv`` and
    :data:`ErrorCode.INVALID_REQUEST` for a malformed envelope.
    """
    if not isinstance(frame, dict):
        raise ProtocolError(ErrorCode.INVALID_REQUEST, "frame is not a JSON object")
    d = cast("dict[str, Any]", frame)
    hv = d.get("hv")
    if hv != FRAME_VERSION:
        raise ProtocolError(
            ErrorCode.UNSUPPORTED_VERSION,
            f"unsupported hv {hv!r}; this bridge speaks hv={FRAME_VERSION}",
        )
    if d.get("jsonrpc") != JSONRPC_VERSION:
        raise ProtocolError(
            ErrorCode.INVALID_REQUEST,
            f"jsonrpc must be {JSONRPC_VERSION!r}",
        )
    return d


def make_request(request_id: int | str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "hv": FRAME_VERSION,
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
        "params": params,
    }


def make_notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "hv": FRAME_VERSION,
        "jsonrpc": JSONRPC_VERSION,
        "method": method,
        "params": params,
    }


def make_response(request_id: int | str, result: Any) -> dict[str, Any]:
    return {
        "hv": FRAME_VERSION,
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def make_error(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "hv": FRAME_VERSION,
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error,
    }


Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class MethodRegistry:
    """Dispatch table for the ``py.*`` requests the sidecar sends to Python.

    Only method names in :data:`PY_REQUEST_METHODS` may be registered; a call to
    an unregistered (or unknown) method raises :class:`ProtocolError` with
    :data:`ErrorCode.METHOD_NOT_FOUND` so the supervisor can reply fail-closed.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, method: str, handler: Handler) -> None:
        if method not in PY_REQUEST_METHODS:
            raise ValueError(f"{method!r} is not a frozen py.* request method")
        if method in self._handlers:
            raise ValueError(f"{method!r} already registered")
        self._handlers[method] = handler

    def has(self, method: str) -> bool:
        return method in self._handlers

    async def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handler = self._handlers.get(method)
        if handler is None:
            raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"method not found: {method}")
        return await handler(params)
