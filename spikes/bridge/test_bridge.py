"""Spike E tests: supervised Python<->Node JSON-RPC-over-stdio bridge fixture.

Run from spikes/bridge:  uv run pytest -v test_bridge.py
Every scenario's teardown verifies (via ps/pgrep) that no sidecar survived it.
"""

from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from supervisor import (
    MAX_FRAME_BYTES,
    BridgeSupervisor,
    pid_alive,
    sidecar_orphans,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make(max_pending: int = 64) -> BridgeSupervisor:
    sup = BridgeSupervisor(max_pending=max_pending)
    ready = sup.wait_for_event(lambda e: e.get("type") == "ready", timeout=10)
    assert ready is not None, "sidecar never sent its spontaneous 'ready' event"
    return sup


def _teardown_and_assert_no_orphan(sup: BridgeSupervisor) -> None:
    pid = sup.child_pid
    sup.shutdown()
    assert not pid_alive(pid), f"sidecar pid {pid} still alive after shutdown"
    assert sidecar_orphans() == [], "orphaned sidecar processes found via pgrep"


@pytest.fixture
def sup():
    s = _make()
    yield s
    _teardown_and_assert_no_orphan(s)


def test_round_trip_and_spontaneous_events(sup: BridgeSupervisor):
    r = sup.call("echo", {"hello": "world", "n": [1, 2, 3]})
    assert r["ok"] and r["result"] == {"hello": "world", "n": [1, 2, 3]}
    # 'ready' was consumed by the fixture; 'tick' is a second spontaneous event.
    tick = sup.wait_for_event(lambda e: e.get("type") == "tick", timeout=5)
    assert tick is not None


def test_oversized_frame_rejected_by_sidecar(sup: BridgeSupervisor):
    """Supervisor -> sidecar direction: sidecar rejects >1 MiB with -32001."""
    blob = "x" * (MAX_FRAME_BYTES + 200_000)
    r = sup.call("echo", {"blob": blob}, timeout=10, bypass_size_guard=True)
    assert not r["ok"]
    assert r["error"]["code"] == -32001
    assert str(MAX_FRAME_BYTES) in r["error"]["message"]
    assert len(sup.protocol_errors) >= 1
    # Sidecar did not crash or desynchronize: a normal call still round-trips.
    r2 = sup.call("echo", {"after": "oversize"})
    assert r2["ok"] and r2["result"] == {"after": "oversize"}


def test_oversized_frame_rejected_by_supervisor_outbound_guard(sup: BridgeSupervisor):
    """Local guard: without bypass, the frame is never written to the pipe."""
    blob = "x" * (MAX_FRAME_BYTES + 1)
    r = sup.call("echo", {"blob": blob})
    assert not r["ok"] and r["error"]["code"] == "frame_too_large"
    assert r["error"]["frame_bytes"] > MAX_FRAME_BYTES


def test_oversized_frame_rejected_inbound(sup: BridgeSupervisor):
    """Sidecar -> supervisor direction: Python framer discards >1 MiB frames."""
    r = sup.call("big", {"bytes": MAX_FRAME_BYTES + 500_000}, timeout=10)
    assert not r["ok"]
    assert r["error"]["code"] == "frame_too_large_inbound"
    # Framer resynchronized on the newline: bridge still works.
    r2 = sup.call("echo", {"still": "alive"})
    assert r2["ok"] and r2["result"] == {"still": "alive"}


def test_per_call_timeout(sup: BridgeSupervisor):
    t0 = time.monotonic()
    r = sup.call("slow", {"ms": 5000}, timeout=0.4)
    elapsed = time.monotonic() - t0
    assert not r["ok"] and r["error"]["code"] == "timeout"
    assert elapsed < 2.0, f"timeout took {elapsed:.2f}s"
    # Sidecar healthy; the timed-out request was cancelled server-side too.
    r2 = sup.call("echo", {"post": "timeout"})
    assert r2["ok"]


def test_pending_queue_overflow_returns_busy():
    sup = _make(max_pending=3)
    try:
        calls = [sup.submit("slow", {"ms": 1200}) for _ in range(3)]
        assert all(not c.done() for c in calls)
        r = sup.call("echo", {"overflow": True}, timeout=5)
        assert not r["ok"]
        assert r["error"]["code"] == "busy"
        assert r["error"]["max_pending"] == 3
        # The three admitted calls still complete normally.
        results = [c.wait(10) for c in calls]
        assert all(res is not None and res["ok"] for res in results)
        # Capacity is released: a new call succeeds.
        assert sup.call("echo", {"after": "drain"})["ok"]
    finally:
        _teardown_and_assert_no_orphan(sup)


def test_cancellation_observed_by_sidecar(sup: BridgeSupervisor):
    call = sup.submit("slow", {"ms": 8000})
    time.sleep(0.2)  # let the request reach the sidecar
    sup.cancel(call)
    r = call.wait(5)
    assert r is not None and not r["ok"]
    assert r["error"]["code"] == -32800  # JSON-RPC RequestCancelled
    ev = sup.wait_for_event(
        lambda e: e.get("type") == "cancelled" and e.get("id") == call.id, timeout=5
    )
    assert ev is not None, "sidecar never emitted the 'cancelled' event"


def test_ask_user_suspension_and_resume(sup: BridgeSupervisor):
    r1 = sup.call("ask_user", {"question": "Approve fillet radius 3mm?"})
    assert r1["ok"] and r1["result"]["status"] == "suspended"
    qid = r1["result"]["question_id"]
    assert qid
    r2 = sup.call("answer", {"question_id": qid, "answer": "yes, 3mm"})
    assert r2["ok"]
    assert r2["result"] == {
        "status": "completed",
        "question_id": qid,
        "question": "Approve fillet radius 3mm?",
        "answer": "yes, 3mm",
    }
    ev = sup.wait_for_event(
        lambda e: e.get("type") == "ask_user_completed" and e.get("question_id") == qid,
        timeout=5,
    )
    assert ev is not None
    # Answering twice fails structurally (question consumed).
    r3 = sup.call("answer", {"question_id": qid, "answer": "again"})
    assert not r3["ok"] and r3["error"]["code"] == -32602


def test_image_payload_round_trip(sup: BridgeSupervisor):
    r = sup.call("image")
    assert r["ok"]
    payload = r["result"]
    assert payload["mime"] == "image/png"
    raw = base64.b64decode(payload["data"], validate=True)
    assert raw[: len(PNG_MAGIC)] == PNG_MAGIC, "decoded payload is not a PNG"
    assert len(raw) > len(PNG_MAGIC)


def test_crash_reporting_and_restart_recovery(sup: BridgeSupervisor):
    call = sup.submit("slow", {"ms": 30000})
    time.sleep(0.2)  # ensure the request is in flight
    old_pid = sup.kill_child()
    r = call.wait(10)
    assert r is not None and not r["ok"]
    assert r["error"]["code"] == "process_crash"
    assert r["error"]["returncode"] == -9  # SIGKILL surfaced structurally
    # New submissions fail fast while down.
    down = sup.call("echo", {"while": "down"}, timeout=2)
    assert not down["ok"] and down["error"]["code"] == "process_down"
    # Crashed child is reaped (no zombie/orphan) before restart.
    assert not pid_alive(old_pid)
    sup.restart()
    ready = sup.wait_for_event(
        lambda e: e.get("type") == "ready" and e.get("pid") != old_pid, timeout=10
    )
    assert ready is not None
    assert sup.child_pid != old_pid
    r2 = sup.call("echo", {"recovered": True})
    assert r2["ok"] and r2["result"] == {"recovered": True}


def test_concurrent_calls_correlate_correctly(sup: BridgeSupervisor):
    """20 interleaved calls with distinct payloads all come back to their callers."""
    def one(i: int):
        method = "slow" if i % 3 == 0 else "echo"
        params = {"ms": 100, "tag": i} if method == "slow" else {"tag": i}
        return i, sup.call(method, params, timeout=10)

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, r in ex.map(one, range(20)):
            assert r["ok"], f"call {i} failed: {r}"
            if "tag" in (r["result"] or {}):
                assert r["result"]["tag"] == i


def test_clean_shutdown_leaves_no_orphan():
    sup = _make()
    pid = sup.child_pid
    assert pid_alive(pid)
    rc = sup.shutdown()
    assert rc == 0, f"sidecar exit code {rc} on clean shutdown"
    assert not pid_alive(pid)
    assert sidecar_orphans() == []
