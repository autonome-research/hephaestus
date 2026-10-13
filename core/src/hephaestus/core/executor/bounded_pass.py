"""The one bounded-subprocess supervision loop the engine owns.

Several engine passes are *unbounded in the kernel*: one boolean on a
pathological B-rep has ground for ~19 h (``COMPARE.md``:152-176), a motion
sweep's grid is a boolean per sample, a scan distance is a kd-tree per
direction, and a solver's verification pass builds. Every one of them therefore
runs in a spawned child under a wall-clock ceiling, and every one of them needs
the *same* five-part supervision: spawn and close the parent's copy of the write
end, poll until a terminal message or the deadline, drain the pipe when the
child dies, drain it once more after the deadline, and kill/join/close whatever
is left.

That loop used to be written once per caller, and the copies drifted. The
newest carried two correctness fixes the others never received — the
post-deadline drain and the recomputation of the death flag — so a pass whose
child answered a millisecond before the ceiling was reported as a timeout with
its answer sitting unread in the pipe, and a pass that answered and then closed
the pipe could be reported as dead. This module is that loop, once, with the
fixes in it: *process supervision is machinery, and machinery is extracted
rather than duplicated* (``repo_conventions.md``). A caller supplies only its
message protocol (which messages are terminal) and its refusal vocabulary (what
a ceiling and a death are called in its own specification).

It is pure Python with **no geometry import**, which is what keeps the solver's
import-closure clause (``SOLVER.md`` §7: the verification pass must not drag
``hephaestus.geom.solve`` into the parent) trivially satisfiable at the
placement call site — and what lets a child that holds no geometry (a test's
scripted child, a future non-kernel pass) start without paying for the kernel.
The corollary is that quieting OCCT's messenger off the inherited fd 1 belongs
in each child beside its own geometry import (``J-cli-robustness-14``), which
``core/tests/test_bounded_pass.py`` enforces over every child reachable from a
call site here.

The loop is split in two on purpose. :func:`run_bounded_pass` is the spawn
wiring; :func:`supervise` is the poll/deadline/drain/kill body over an
already-started process and connection. The races this module exists to get
right — a terminal message that lands in the same instant the deadline fires,
and one that arrives between the poll that missed it and the liveness check
that follows — cannot be forced through real wall-clock timing, so the body is
reachable on its own against a scripted process/connection pair
(``core/tests/test_bounded_pass.py``). ``time`` is likewise a module-level name
so the clock those tests drive is the clock this loop reads.

Independent cleanup owners use that same poll/deadline/drain body through
:func:`run_independent_owner`, but with an explicit EOF-and-bounded-reap finish
policy. They must complete resource cleanup after reporting a terminal message;
killing them like a kernel pass would destroy that guarantee.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import selectors
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from multiprocessing.connection import Connection, Pipe
from typing import Any

# Child-side endpoint for both spawn passes and independent cleanup owners.
ChildConnection = Connection

__all__ = [
    "BoundedPassOutcome",
    "ChildConnection",
    "OwnerRefusal",
    "run_bounded_pass",
    "run_independent_owner",
    "supervise",
]

#: How long one poll blocks before the loop re-checks the deadline and the
#: child's liveness. Small enough that a ceiling is honoured promptly, large
#: enough that waiting costs no measurable CPU.
POLL_S: float = 0.05


@dataclass(frozen=True)
class BoundedPassOutcome:
    """What one bounded pass ended as — the three facts every caller needs.

    They are deliberately independent, because conflating them is the defect
    this module exists to remove. ``terminal`` is the child's own last word
    (``None`` when it never got one out). ``died`` says the child stopped
    *without* producing that word — never merely "the child is not alive now",
    which is equally true of a child that answered and exited. ``exit_code`` is
    read after the join, so it is the real status and not the ``None`` a
    pre-reap read returns, nor the ``-9`` a premature kill would forge. It is
    evidence *about* a stop, never the test for one: the caller asks ``died``.
    """

    #: The ``(kind, payload)`` message the caller's protocol called terminal,
    #: or ``None`` when the pass was cut short before one arrived.
    terminal: tuple[str, Any] | None
    #: True only when the child stopped without a terminal message. A run that
    #: answered is never dead, however it exited afterwards.
    died: bool
    #: ``Process.exitcode`` after the join. On the ceiling branch the child was
    #: killed first, so this is the kill's signal status (a negative number),
    #: never ``None``; ``died`` — not ``exit_code`` — is the honest
    #: discriminator between "the ceiling fired" and "the child crashed".
    exit_code: int | None

    @property
    def cut_short(self) -> bool:
        """Whether the pass produced no terminal message (ceiling **or** death)."""
        return self.terminal is None


def run_bounded_pass(
    child: Callable[..., None],
    args: tuple[Any, ...] = (),
    *,
    timeout_s: float,
    on_message: Callable[[str, Any], bool],
    poll_s: float = POLL_S,
) -> BoundedPassOutcome:
    """Run ``child(conn, *args)`` in a spawned process under ``timeout_s``.

    The helper owns the pipe, so a caller cannot forget to close the parent's
    copy of the write end — which is what makes an ``EOFError`` mean "the child
    is gone" rather than "nobody has written yet". ``args`` must be picklable:
    the context is ``spawn``, deliberately, because a forked kernel handle is
    not a kernel handle.

    ``on_message(kind, payload)`` is the caller's whole protocol: it consumes
    the message — accumulating streamed facts wherever it keeps them, which is
    what the partial evidence a refusal carries is built from — and returns
    True exactly when that message was the terminal one.

    A child that touches OCCT must quiet the kernel messenger as its first act
    (``J-cli-robustness-14``); that is done inside each child beside its own
    geometry import — the point at which OCP is first bound in that process —
    rather than here, because this wiring is shared with children that hold no
    geometry at all and must not pay the kernel's import to start.
    ``core/tests/test_bounded_pass.py`` checks every child reachable from a
    ``run_bounded_pass`` call site actually does it, so it cannot be forgotten.
    """
    ctx = multiprocessing.get_context("spawn")
    parent, write_end = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=child, args=(write_end, *args))
    proc.start()
    write_end.close()
    return supervise(proc, parent, timeout_s=timeout_s, on_message=on_message, poll_s=poll_s)


def supervise(
    proc: Any,
    parent: Any,
    *,
    timeout_s: float,
    on_message: Callable[[str, Any], bool],
    poll_s: float = POLL_S,
    finish: Callable[[], None] | None = None,
) -> BoundedPassOutcome:
    """The supervision body: poll ``parent`` until a terminal message or the ceiling.

    Shared by spawned passes and :func:`run_independent_owner`. ``finish`` is
    an explicit lifecycle policy: ordinary passes kill/join; independent cleanup
    owners close their duplex channel (parent EOF) and boundedly reap, NEVER
    kill on a terminal message. Poll/deadline/death drains stay identical.
    Scripted process/connection tests exercise their races without wall timing.

    The loop, and why each part is there:

    * **Poll, don't block.** A blocking ``recv`` cannot notice the deadline.
    * **Drain on death.** A child that sends its answer and exits can have both
      events fall either side of one poll window; reading the pipe before
      concluding "died" is what stops an answered run being reported as a
      crash. The death drain's window is deliberately wider than the loop's,
      because the message is known to be in flight.
    * **Drain after the deadline.** A message that landed during the final poll
      window is a measurement. Throwing it away because the clock ran out while
      it sat in a buffer would make the refusal poorer than the run actually
      was.
    * **Recompute ``died``.** An ``EOFError`` inside the death drain can be
      raised *after* an earlier receive in that same drain already produced the
      terminal message, so the flag is recomputed rather than left standing:
      "the subprocess died" can never be said about a run that answered.
    * **Join before reading the exit code.** ``exitcode`` is ``None`` until the
      child is reaped, so the join has to precede the read. The native policy
      kills before joining; an independent owner's finish bounds its reap and
      refuses reuse if the owner has not exited.
    """
    terminal: tuple[str, Any] | None = None
    died = False
    deadline = time.monotonic() + timeout_s

    def _receive() -> bool:
        """Consume one message; True when the caller called it terminal."""
        nonlocal terminal
        kind, payload = parent.recv()
        if on_message(str(kind), payload):
            terminal = (str(kind), payload)
            return True
        return False

    try:
        while terminal is None and time.monotonic() < deadline:
            try:
                if parent.poll(poll_s):
                    _receive()
                elif not proc.is_alive():
                    # Death, not a deadline — drain what it sent first, so a
                    # result that raced the exit is never misread as a crash.
                    while parent.poll(poll_s * 4) and not _receive():
                        pass
                    died = terminal is None
                    break
            except (EOFError, OSError):
                # The pipe closed before a terminal message (an ``OSError`` is
                # the same fact mid-message: "got end of file during message"
                # when the child died half-way through a payload larger than
                # the pipe buffer): the child is
                # crashing. Give it a moment to finish dying so the refusal
                # carries its real exit code; a child that hangs instead meets
                # the explicit finish policy in ``finally``.
                proc.join(5.0)
                died = True
                break
        # The deadline fell (or a death drain ended on EOF): take what is
        # already in the pipe before finalization.
        while terminal is None:
            try:
                if not parent.poll(0):
                    break
                _receive()
            except (EOFError, OSError):
                break
        # …and if that drain turned up the terminal message after all, the run
        # did not die.
        died = died and terminal is None
    finally:
        if finish is not None:
            finish()
        else:
            if proc.is_alive():
                proc.kill()
            proc.join()
            parent.close()
    return BoundedPassOutcome(terminal=terminal, died=died, exit_code=proc.exitcode)


class OwnerRefusal(RuntimeError):
    """An independent owner did not provide a clean terminal/reap acknowledgement."""


class _OwnerProcess:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def join(self, timeout: float) -> None:
        # The shared EOF path gives a dying process a chance to finish. A live
        # cleanup owner is never killed: its own ceiling remains authoritative.
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=timeout)

    @property
    def exitcode(self) -> int | None:
        return self.process.returncode


class _OwnerControlFailure(RuntimeError):
    def __init__(self, error: OSError | EOFError) -> None:
        super().__init__(str(error))
        self.error = error


class _OwnerEndpoint:
    def __init__(
        self,
        connection: Connection,
        selector: selectors.BaseSelector,
        maximum: int,
        cancel_fd: int | None,
        on_cancel: Callable[[], None],
    ) -> None:
        self.connection = connection
        self.selector = selector
        self.maximum = maximum
        self.cancel_fd = cancel_fd
        self.on_cancel = on_cancel

    def poll(self, timeout: float) -> bool:
        events = self.selector.select(timeout)
        if any(key.data == "cancel" for key, _ in events):
            try:
                self.on_cancel()
            except (OSError, EOFError) as exc:
                # A domain control/evidence failure is NOT a pipe disconnect;
                # do not let the shared receive loop consume that exception.
                raise _OwnerControlFailure(exc) from exc
            assert self.cancel_fd is not None
            self.selector.unregister(self.cancel_fd)
        return any(key.data == "result" for key, _ in events)

    def recv(self) -> tuple[str, bytes]:
        # Bound the frame before decoding any parent/owner protocol object.
        return "terminal", self.connection.recv_bytes(self.maximum)


def run_independent_owner(
    command: Callable[[int], Sequence[str]],
    *,
    env: Mapping[str, str],
    timeout_s: float,
    maximum: int,
    on_started: Callable[[int, ChildConnection], None],
    on_reaped: Callable[[int, int], None],
    on_unreaped: Callable[[], None],
    cancel_fd: int | None = None,
    on_cancel: Callable[[], None],
    reap_s: float = 10.0,
) -> bytes:
    """Run a self-bounded, independent Popen cleanup owner over duplex IPC.

    Unlike a kernel pass, this child must survive parent EOF long enough to
    clean up its resources. No spawn/resource tracker and no kill on terminal,
    cancellation, timeout or parent exception. The child must enforce its own
    lifetime ceiling. Closing the parent's endpoint precedes the final bounded reap.
    An unreaped owner invokes the caller's poison hook; only a terminal frame
    AND a zero exit after reaping permit the durable acknowledgement callback.
    Callers own domain evidence/protocol decoding, not a second polling loop.
    """
    parent, child = Pipe(duplex=True)
    process: subprocess.Popen[bytes] | None = None
    finished = False

    def finish() -> None:
        nonlocal finished
        finished = True
        parent.close()  # EOF wakes the independent owner's control reader
        if process is not None:
            try:
                process.wait(timeout=reap_s)
            except subprocess.TimeoutExpired:
                on_unreaped()
            except BaseException:
                on_unreaped()
                raise

    try:
        process = subprocess.Popen(
            command(child.fileno()),
            pass_fds=(child.fileno(),),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        child.close()  # never retain the peer and accidentally suppress EOF
        on_started(process.pid, parent)
        with selectors.DefaultSelector() as selector:
            selector.register(parent.fileno(), selectors.EVENT_READ, "result")
            if cancel_fd is not None:
                selector.register(cancel_fd, selectors.EVENT_READ, "cancel")
            endpoint = _OwnerEndpoint(parent, selector, maximum, cancel_fd, on_cancel)
            outcome = supervise(
                _OwnerProcess(process),
                endpoint,
                timeout_s=timeout_s,
                on_message=lambda _kind, _payload: True,
                finish=finish,
            )
        if outcome.terminal is None:
            raise OwnerRefusal(
                "owner disconnected; recover durable ownership"
                if outcome.died
                else "owner deadline exceeded; recover durable ownership"
            )
        if outcome.exit_code is None:
            raise OwnerRefusal("owner could not be reaped cleanly")
        if outcome.exit_code != 0:
            raise OwnerRefusal("owner did not exit cleanly")
        data = outcome.terminal[1]
        if not isinstance(data, bytes):
            raise OwnerRefusal("owner terminal frame is not bytes")
        try:
            on_reaped(process.pid, outcome.exit_code)
        except BaseException:
            # A successful wait without the caller's durable acknowledgement
            # must not authorize reuse either.
            on_unreaped()
            raise
        return data
    except _OwnerControlFailure as exc:
        raise exc.error from None
    finally:
        # Also covers spawn, on_started, selector and receive failures. Do not
        # retry an expired reap (or double the caller's cleanup budget).
        if not finished:
            finish()
        child.close()
