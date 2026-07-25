"""Secure bubblewrap execution backend (Linux).

Adapts the proven argv from ``spikes/sandbox`` (Stage S, spike F — see its
RESULTS.md) to the :class:`~hephaestus.core.executor.sandbox.base.ExecBackend`
protocol. Sandbox profile:

- every ``ro_bind`` of the spec (project dir, venv prefix, pinned interpreter
  install root) is bound read-only at its own host path (identity bind), so
  ``worker_cmd`` host paths work unchanged inside the sandbox;
- ONE writable bind: the fresh per-build ``rw_out_dir`` (also the chdir);
- tmpfs ``/tmp`` and ``/run``; private ``/proc`` and ``/dev``; base OS from a
  read-only ``/usr`` bind; ``--remount-ro /`` seals everything else;
- ``--unshare-net/pid/user/ipc/uts`` plus ``--die-with-parent``;
- ``--clearenv`` with a minimal fixed environment (PATH, HOME=/tmp, TMPDIR,
  LANG, PYTHONDONTWRITEBYTECODE) — no PYTHONHASHSEED override: determinism
  relies on the default hash randomization being irrelevant to geometry;
- rlimits (cpu, address-space, nproc, no core dumps) applied in a pre-exec
  hook and inherited across bwrap's exec into the worker;
- parent-side wall-clock kill of the whole process group.

Fail-closed: :meth:`BwrapBackend.execute` raises ``sandbox_denied`` when
bwrap is absent; capability probing lives in
:mod:`hephaestus.core.executor.sandbox.probe`.
"""

from __future__ import annotations

import contextlib
import os
import resource
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from hephaestus.core.errors import SandboxDeniedError
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecOutcome,
    Rlimits,
    SandboxSpec,
)

__all__ = [
    "BwrapBackend",
    "build_bwrap_argv",
    "find_bwrap",
    "interpreter_ro_binds",
]

BWRAP_BINARY = "bwrap"

#: Minimal fixed environment inside the sandbox (after --clearenv).
SANDBOX_ENV: tuple[tuple[str, str], ...] = (
    ("PATH", "/usr/bin:/bin"),
    ("HOME", "/tmp"),
    ("TMPDIR", "/tmp"),
    ("LANG", "C.UTF-8"),
    ("PYTHONDONTWRITEBYTECODE", "1"),
)


def find_bwrap() -> str | None:
    """Locate the bwrap binary on PATH (None when absent — fail closed upstream)."""
    return shutil.which(BWRAP_BINARY)


def interpreter_ro_binds() -> tuple[Path, ...]:
    """Read-only binds required to run the *current* interpreter in the sandbox.

    Returns the venv prefix (``sys.prefix``) and the underlying interpreter
    install root (``sys.base_prefix`` — e.g. the uv-managed CPython directory
    the venv symlinks into), each in BOTH its stated and fully resolved form,
    plus the resolved real interpreter root. The sandbox root is an empty
    tmpfs, so every path a symlink chain traverses must itself be bound: a
    venv ``bin/python`` pointing through an unresolved uv path dangles if only
    the resolved terminal directory is mounted (observed on GitHub runners).
    """
    candidates = [Path(sys.prefix), Path(sys.base_prefix)]
    real_exe_root = Path(sys.executable).resolve().parent.parent
    candidates.append(real_exe_root)
    binds: list[Path] = []
    for prefix in candidates:
        for form in (prefix, prefix.resolve()):
            if form not in binds:
                binds.append(form)
    return tuple(binds)


def build_bwrap_argv(bwrap: str | Path, spec: SandboxSpec) -> tuple[str, ...]:
    """Build the exact bwrap argv for one worker invocation (pure, testable).

    Raises ``ValueError`` when the spec's paths do not exist on the host —
    bwrap would fail anyway, but with a far less useful diagnostic.
    """
    out_dir = Path(spec.rw_out_dir).resolve()
    if not out_dir.is_dir():
        raise ValueError(f"rw_out_dir does not exist or is not a directory: {out_dir}")
    ro_binds: list[Path] = []
    for bind in spec.ro_binds:
        resolved = Path(bind).resolve()
        if not resolved.exists():
            raise ValueError(f"ro_bind path does not exist: {resolved}")
        if resolved not in ro_binds:
            ro_binds.append(resolved)

    argv: list[str] = [
        str(bwrap),
        "--die-with-parent",
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-net",
        "--unshare-pid",
        "--clearenv",
    ]
    for key, value in SANDBOX_ENV:
        argv += ["--setenv", key, value]
    argv += [
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        "/run",
        # Base OS, read-only; merged-usr symlinks for the dynamic loader.
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib",
        "/lib64",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/bin",
        "/sbin",
    ]
    for bind in ro_binds:
        argv += ["--ro-bind", str(bind), str(bind)]
    argv += [
        # The ONE writable mount: the fresh per-build out dir.
        "--bind",
        str(out_dir),
        str(out_dir),
        "--chdir",
        str(out_dir),
        # Seal the base tmpfs root last; explicit mounts keep their own flags.
        "--remount-ro",
        "/",
    ]
    argv += list(spec.worker_cmd)
    return tuple(argv)


def _preexec_factory(rlimits: Rlimits) -> Callable[[], None]:
    """Pre-exec hook: own process group + POSIX rlimits (inherited by the worker)."""

    def _preexec() -> None:
        os.setsid()  # own process group so the parent can kill the whole tree
        mem = rlimits.address_space_bytes
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_DATA, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (rlimits.cpu_seconds, rlimits.cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_NPROC, (rlimits.nproc, rlimits.nproc))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    return _preexec


class BwrapBackend:
    """The secure Linux backend: one worker per :meth:`execute`, fully sandboxed.

    ``bwrap_path=None`` (the default) resolves bwrap from PATH at call time,
    which keeps :meth:`probe` honest under PATH manipulation.
    """

    def __init__(self, *, bwrap_path: str | Path | None = None) -> None:
        self._explicit_bwrap: str | None = str(bwrap_path) if bwrap_path is not None else None

    @property
    def name(self) -> str:
        return "bwrap"

    def bwrap_path(self) -> str | None:
        """The bwrap binary this backend would use right now (None => unavailable)."""
        if self._explicit_bwrap is not None:
            return self._explicit_bwrap
        return find_bwrap()

    def probe(self) -> CapabilityReport:
        """Full fail-closed capability probe (delegates to ``probe.probe_bwrap``)."""
        from hephaestus.core.executor.sandbox import probe as probe_mod

        return probe_mod.probe_bwrap(self)

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        """Run one worker under bwrap; enforce rlimits and the wall clock."""
        bwrap = self.bwrap_path()
        if bwrap is None:
            raise SandboxDeniedError(
                "sandbox_unavailable: bwrap not on PATH; secure execution fails closed"
            )
        argv = build_bwrap_argv(bwrap, spec)
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_preexec_factory(spec.rlimits),
            close_fds=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(stdin_payload, timeout=spec.wall_clock_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
        return ExecOutcome(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
