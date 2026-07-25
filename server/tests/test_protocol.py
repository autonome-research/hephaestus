"""Protocol registry + hv negotiation tests."""

from __future__ import annotations

import pytest
from hephaestus.agent_bridge.protocol import (
    PY_REQUEST_METHODS,
    SIDECAR_REQUEST_METHODS,
    ErrorCode,
    MethodRegistry,
    ProtocolError,
    make_error,
    make_request,
    validate_frame,
)


def test_validate_frame_accepts_current_version() -> None:
    frame = make_request(1, "session.create", {})
    assert validate_frame(frame) is frame


def test_validate_frame_rejects_unknown_hv() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_frame({"hv": 99, "jsonrpc": "2.0", "id": 1, "method": "x"})
    assert exc.value.code == ErrorCode.UNSUPPORTED_VERSION


def test_validate_frame_rejects_bad_jsonrpc() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_frame({"hv": 1, "jsonrpc": "1.0", "id": 1})
    assert exc.value.code == ErrorCode.INVALID_REQUEST


def test_validate_frame_rejects_non_object() -> None:
    with pytest.raises(ProtocolError):
        validate_frame([1, 2, 3])


def test_frozen_method_sets_are_disjoint() -> None:
    assert SIDECAR_REQUEST_METHODS.isdisjoint(PY_REQUEST_METHODS)
    assert "session.create" in SIDECAR_REQUEST_METHODS
    assert "py.tool_dispatch" in PY_REQUEST_METHODS


def test_make_error_shape() -> None:
    err = make_error(7, ErrorCode.BUSY, "busy", data={"x": 1})
    assert err["id"] == 7
    assert err["error"] == {"code": ErrorCode.BUSY, "message": "busy", "data": {"x": 1}}
    assert err["hv"] == 1


def test_registry_registration_rules() -> None:
    reg = MethodRegistry()

    async def handler(_params: dict[str, object]) -> dict[str, object]:
        return {"ok": True}

    reg.register("py.admission_capacity", handler)
    assert reg.has("py.admission_capacity")

    with pytest.raises(ValueError):
        reg.register("session.create", handler)  # not a py.* method

    with pytest.raises(ValueError):
        reg.register("py.admission_capacity", handler)  # duplicate


def test_registry_dispatch_and_missing() -> None:
    import asyncio

    reg = MethodRegistry()

    async def handler(params: dict[str, object]) -> dict[str, object]:
        return {"echo": params}

    reg.register("py.ask_user", handler)

    async def run() -> None:
        result = await reg.dispatch("py.ask_user", {"q": 1})
        assert result == {"echo": {"q": 1}}
        with pytest.raises(ProtocolError) as exc:
            await reg.dispatch("py.delegate", {})
        assert exc.value.code == ErrorCode.METHOD_NOT_FOUND

    asyncio.run(run())
