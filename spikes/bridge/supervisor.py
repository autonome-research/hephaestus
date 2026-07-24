"""Spike E supervisor: spawns the Node sidecar and speaks LF-delimited JSON-RPC.

Proves, at spike scale, the architecture.md S5 bridge concepts:
  - request/response correlation with per-call timeouts
  - bounded pending-request queue (overflow -> structured ``busy``)
  - bounded framing in both directions (1 MiB spike cap; oversized frames are
    rejected with structured errors, never crashes)
  - cancellation ($/cancel notification observed by the sidecar)
  - crash reporting (child death fails pending calls with ``process_crash``)
    followed by restart and recovery
  - clean shutdown with no orphaned sidecar (verifiable via ps/pgrep)

All results are structured envelopes:
  ok:    {"ok": True,  "result": {...}}
  error: {"ok": False, "error": {"code": ..., "message": ..., ...}}
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

MAX_FRAME_BYTES = 1024 * 1024  # 1 MiB spike-level cap
SIDECAR_PATH = Path(__file__).with_name("node_sidecar.mjs")


def _ok(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": result}


def _err(code: Any, message: str, **extra: Any) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return {"ok": False, "error": error}


class Call:
    """Handle for one in-flight request."""

    def __init__(self, call_id: int, bypass_size_guard: bool = False) -> None:
        self.id = call_id
        self.bypass_size_guard = bypass_size_guard
        self._done = threading.Event()
        self.result: dict[str, Any] | None = None

    def _complete(self, envelope: dict[str, Any]) -> None:
        if not self._done.is_set():
            self.result = envelope
            self._done.set()

    def done(self) -> bool:
        return self._done.is_set()

    def wait(self, timeout: float | None = None) -> dict[str, Any] | None:
        self._done.wait(timeout)
        return self.result


class BridgeSupervisor:
    def __init__(self, max_pending: int = 64, node: str = "node") -> None:
        self.max_pending = max_pending
        self.node = node
        self.proc: subprocess.Popen[bytes] | None = None
        self._next_id = 0
        self._pending: dict[int, Call] = {}
        self._plock = threading.RLock()
        self._wlock = threading.Lock()
        self._cond = threading.Condition()
        self.events: list[dict[str, Any]] = []
        self.protocol_errors: list[dict[str, Any]] = []
        self.stderr_lines: list[str] = []
        self.last_exit: int | None = None
        self._reader: threading.Thread | None = None
        self.start()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        assert self.proc is None or self.proc.poll() is not None, "sidecar already running"
        self.proc = subprocess.Popen(
            [self.node, str(SIDECAR_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc = self.proc
        self._reader = threading.Thread(target=self._read_loop, args=(proc,), daemon=True)
        self._reader.start()
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()

    def restart(self) -> None:
        """Restart after a crash (or force-restart a live child)."""
        proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        if self._reader is not None:
            self._reader.join(timeout=5)
        with self._plock:
            self._pending.clear()
        # start() asserts the old proc is dead; the old Popen stays reapable.
        self.start()

    def shutdown(self, timeout: float = 5.0) -> int | None:
        """Close stdin (sidecar exits on stdin end), escalate if needed, reap."""
        proc = self.proc
        if proc is None:
            return None
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            rc = proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                rc = proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
                rc = proc.wait()
        if self._reader is not None:
            self._reader.join(timeout=5)
        self.last_exit = rc
        return rc

    def kill_child(self) -> int:
        """SIGKILL the sidecar (crash-injection for tests). Returns the pid killed."""
        assert self.proc is not None
        pid = self.proc.pid
        os.kill(pid, signal.SIGKILL)
        return pid

    @property
    def child_pid(self) -> int:
        assert self.proc is not None
        return self.proc.pid

    # -- request path ------------------------------------------------------

    def submit(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        bypass_size_guard: bool = False,
    ) -> Call:
        with self._plock:
            self._next_id += 1
            call = Call(self._next_id, bypass_size_guard=bypass_size_guard)
            proc = self.proc
            if proc is None or proc.poll() is not None:
                call._complete(_err("process_down", "sidecar process is not running"))
                return call
            if len(self._pending) >= self.max_pending:
                call._complete(
                    _err("busy", "pending request queue full", max_pending=self.max_pending)
                )
                return call
            self._pending[call.id] = call
        frame = (
            json.dumps(
                {"jsonrpc": "2.0", "id": call.id, "method": method, "params": params or {}}
            )
            + "\n"
        ).encode("utf-8")
        if not bypass_size_guard and len(frame) > MAX_FRAME_BYTES:
            with self._plock:
                self._pending.pop(call.id, None)
            call._complete(
                _err(
                    "frame_too_large",
                    f"outbound frame is {len(frame)} bytes (max {MAX_FRAME_BYTES})",
                    frame_bytes=len(frame),
                    max_frame_bytes=MAX_FRAME_BYTES,
                )
            )
            return call
        try:
            with self._wlock:
                assert proc.stdin is not None
                proc.stdin.write(frame)
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            with self._plock:
                self._pending.pop(call.id, None)
            call._complete(_err("process_crash", "sidecar stdin closed while writing"))
        return call

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 10.0,
        bypass_size_guard: bool = False,
    ) -> dict[str, Any]:
        call = self.submit(method, params, bypass_size_guard=bypass_size_guard)
        if call.wait(timeout) is None:
            with self._plock:
                self._pending.pop(call.id, None)
            self.cancel(call)  # tell the sidecar to stop working on it
            call._complete(_err("timeout", f"no response within {timeout}s", timeout_s=timeout))
        assert call.result is not None
        return call.result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        frame = (json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        try:
            with self._wlock:
                assert proc.stdin is not None
                proc.stdin.write(frame.encode("utf-8"))
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def cancel(self, call: Call) -> None:
        self.notify("$/cancel", {"id": call.id})

    # -- events ------------------------------------------------------------

    def wait_for_event(self, predicate: Any, timeout: float = 5.0) -> dict[str, Any] | None:
        with self._cond:
            end = _monotonic() + timeout
            while True:
                for ev in self.events:
                    if predicate(ev):
                        return ev
                remaining = end - _monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)

    # -- reader ------------------------------------------------------------

    def _read_loop(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stdout is not None
        buf = bytearray()
        discarding = False
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            data = chunk
            while data:
                nl = data.find(b"\n")
                if nl == -1:
                    if not discarding:
                        buf += data
                        if len(buf) > MAX_FRAME_BYTES:
                            discarding = True
                            buf.clear()
                            self._on_inbound_oversize()
                    data = b""
                else:
                    part, data = data[:nl], data[nl + 1 :]
                    if discarding:
                        discarding = False
                        buf.clear()
                    else:
                        buf += part
                        if len(buf) > MAX_FRAME_BYTES:
                            self._on_inbound_oversize()
                        else:
                            self._on_frame(bytes(buf))
                        buf.clear()
        self._on_child_exit(proc)

    def _drain_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            self.stderr_lines.append(line.decode("utf-8", "replace").rstrip())

    def _on_inbound_oversize(self) -> None:
        """Sidecar sent a frame over the cap: reject it, fail the oldest pending call."""
        entry = _err(
            "frame_too_large_inbound",
            f"sidecar frame exceeded {MAX_FRAME_BYTES} bytes and was discarded",
            max_frame_bytes=MAX_FRAME_BYTES,
        )
        with self._plock:
            oldest = next(iter(self._pending), None)
            call = self._pending.pop(oldest, None) if oldest is not None else None
        with self._cond:
            self.protocol_errors.append(entry)
            self._cond.notify_all()
        if call is not None:
            call._complete(entry)

    def _on_frame(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            with self._cond:
                self.protocol_errors.append(_err("bad_json", raw[:200].decode("utf-8", "replace")))
                self._cond.notify_all()
            return
        if not isinstance(msg, dict):
            return
        msg_id = msg.get("id")
        if msg_id is None and "method" in msg:
            # Notification from the sidecar.
            with self._cond:
                self.events.append(msg.get("params", {}))
                self._cond.notify_all()
            return
        if msg_id is None and "error" in msg:
            # Sidecar-level protocol error (e.g. it rejected an oversized or
            # unparseable frame). Route to the oldest pending call that opted
            # out of the local size guard, since only those can trigger it.
            err = msg["error"]
            entry = _err(err.get("code"), err.get("message", ""), **{"data": err.get("data")})
            with self._plock:
                target = next(
                    (c for c in self._pending.values() if c.bypass_size_guard), None
                )
                if target is not None:
                    self._pending.pop(target.id, None)
            with self._cond:
                self.protocol_errors.append(entry)
                self._cond.notify_all()
            if target is not None:
                target._complete(entry)
            return
        with self._plock:
            call = self._pending.pop(msg_id, None)
        if call is None:
            return  # late response after timeout/cancel: ignore
        if "error" in msg:
            err = msg["error"]
            call._complete(_err(err.get("code"), err.get("message", "")))
        else:
            call._complete(_ok(msg.get("result")))

    def _on_child_exit(self, proc: subprocess.Popen[bytes]) -> None:
        rc = proc.wait()  # reap; no zombie
        self.last_exit = rc
        with self._plock:
            pending = list(self._pending.values())
            self._pending.clear()
        for call in pending:
            call._complete(
                _err(
                    "process_crash",
                    f"sidecar exited (returncode={rc}) with the call in flight",
                    returncode=rc,
                )
            )
        with self._cond:
            self._cond.notify_all()


def _monotonic() -> float:
    import time

    return time.monotonic()


# -- orphan verification helpers (used by tests) ---------------------------


def pid_alive(pid: int) -> bool:
    """True if pid exists in the process table (per ps) and is not a zombie."""
    r = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    )
    if r.returncode != 0 or not r.stdout.strip():
        return False
    return "Z" not in r.stdout.strip()


def sidecar_orphans() -> list[int]:
    """Pids of any process whose command line references our sidecar script."""
    r = subprocess.run(["pgrep", "-f", str(SIDECAR_PATH)], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]
