# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""J-mirrors-and-dx-21: one free-port-and-retry helper, not four byte-identical
copies of a helper with no retry at all.

``hephaestus.testing.ports`` (``server/src/hephaestus/testing/ports.py``) is
that one helper: :func:`~hephaestus.testing.ports.free_port` for the sites
that need only a number, :func:`~hephaestus.testing.ports.with_free_port` for
the sites that start a server on it, with the retry that makes the bind race
recoverable rather than an unexplained failure in an unrelated suite.

``server/tests/test_agent_client_mode.py``, ``server/tests/test_mcp_unit_build.py``
and ``web/e2e/harness/serve_fixture.py`` already import from it.
``tests/stage3/_stock_client.py`` deliberately keeps its own copy (the module's
own docstring: the Gate G3 client toolkit must import no ``hephaestus`` code at
all, structurally enforced). What had no test at all was the module itself —
this covers both shapes, including the actual value of consolidating: the
retry recovering from a genuine bind collision.
"""

from __future__ import annotations

import socket

import pytest
from hephaestus.testing.ports import free_port, with_free_port


def test_free_port_returns_a_number_that_is_actually_bindable() -> None:
    port = free_port()
    assert isinstance(port, int)
    assert 0 < port < 65536
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_with_free_port_passes_the_port_to_the_caller_and_returns_its_result() -> None:
    seen: list[int] = []

    def start(port: int) -> str:
        seen.append(port)
        return f"started on {port}"

    result = with_free_port(start)
    assert seen and result == f"started on {seen[0]}"


def test_with_free_port_retries_past_a_deliberately_occupied_port() -> None:
    """The retry actually covers the window: occupy a real port, force the
    first attempt to land on it (a realistic ``EADDRINUSE``), and require a
    SECOND, different port to be tried and to succeed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied = blocker.getsockname()[1]

        attempts: list[int] = []

        def start(port: int) -> str:
            attempts.append(port)
            # First call: force a collision on the ALREADY-occupied port,
            # regardless of what with_free_port actually picked, so this test
            # does not depend on free_port() coincidentally returning the
            # occupied number. Subsequent calls bind for real.
            target = occupied if len(attempts) == 1 else port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", target))
            return f"started on {port}"

        result = with_free_port(start)
        assert len(attempts) >= 2, (
            "with_free_port did not retry after a bind collision — it must "
            "re-pick a port and call the start closure again"
        )
        assert result == f"started on {attempts[-1]}"


def test_with_free_port_does_not_retry_a_non_collision_failure() -> None:
    """Narrow on purpose (the module's own stated design): retrying a start
    that failed for an unrelated reason would turn one clear error into the
    same error several times over, rather than surfacing it once."""
    calls = 0

    def start(port: int) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("the server's own startup logic failed, unrelated to the port")

    with pytest.raises(RuntimeError, match="unrelated to the port"):
        with_free_port(start)
    assert calls == 1, "a non-bind-collision failure must not be retried"


def test_with_free_port_gives_up_after_its_bounded_attempts() -> None:
    calls = 0

    def always_collides(port: int) -> None:
        nonlocal calls
        calls += 1
        raise OSError("Address already in use")

    with pytest.raises(AssertionError, match="could not start on a free port"):
        with_free_port(always_collides)
    assert calls >= 2, "a bounded retry that only ever tries once is not a retry"


# --------------------------------------------------------------------------
# The Gate G4 harness's use of the helper (J-mirrors-and-dx-21 and -24)
#
# The retry only helps if the closure it wraps actually decides. `serve_fixture`
# waited a fixed 1.0 s and read "still alive" as "bound", which was wrong twice
# over: `heph serve` prints its entry URL BEFORE `uvicorn.run` binds, and a real
# collision takes ~3.7 s to exit — so every collision sailed past the grace, the
# doomed child was accepted, and the gate died three minutes later in
# `await_ready` with no retry. Meanwhile any early exit at all was reported as
# EADDRINUSE, so a genuine refusal was retried five times and then mislabelled.


def _harness():  # type: ignore[no-untyped-def] - a module, loaded by path
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "web" / "e2e" / "harness" / "serve_fixture.py"
    spec = importlib.util.spec_from_file_location("g4_serve_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_g4_harness_asks_whether_the_port_is_taken_rather_than_guessing() -> None:
    harness = _harness()
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        taken = int(held.getsockname()[1])
        assert harness._port_is_taken(taken) is True
    # Closed again: the same number now answers the other way, which is what
    # makes the probe a question rather than a constant.
    assert harness._port_is_taken(taken) is False


def test_the_g4_harness_does_not_call_a_real_refusal_a_bind_collision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A `heph serve` that refuses for its own reason must surface that reason.

    ``tmp_path`` is not a Hephaestus project, so the child exits 2 naming the
    missing ``hephaestus.toml``. The port is free, so this is not the race:
    `with_free_port` must decline to retry and the error must say so, instead of
    the five-attempt "could not start on a free port" that hid the cause.
    """
    harness = _harness()
    with pytest.raises(RuntimeError) as caught:
        harness.start_server(tmp_path)
    message = str(caught.value)
    assert "not the bind race" in message, message
    assert "could not start on a free port" not in message, message


def test_the_g4_harness_waits_on_a_positive_edge_not_on_a_clock() -> None:
    """Structural, because the behavioural half above cannot see a fixed sleep.

    A grace period that expires before the bind is even attempted is a test of
    nothing; the deadline here may only be an upper bound on a wait that ends on
    an observed edge.
    """
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "web" / "e2e" / "harness" / "serve_fixture.py"
    ).read_text(encoding="utf-8")
    assert "_BIND_GRACE_S" not in source, (
        "the fixed bind grace is back; the start must end on a listener or on the "
        "child's exit (J-mirrors-and-dx-24)"
    )
    assert "_port_is_taken(port)" in source
