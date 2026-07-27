"""Secure bubblewrap execution backend (Linux).

Adapts the proven argv from ``spikes/sandbox`` (Stage S, spike F — see its
RESULTS.md) to the :class:`~hephaestus.core.executor.sandbox.base.ExecBackend`
protocol. Sandbox profile:

- every ``ro_bind`` of the spec (project dir, venv prefix, pinned interpreter
  install root) is bound read-only at its own host path (identity bind), so
  ``worker_cmd`` host paths work unchanged inside the sandbox;
- ONE writable bind: the fresh per-build ``rw_out_dir`` (also the chdir);
- tmpfs ``/tmp`` and ``/run``; private ``/proc`` and ``/dev``; base OS from a
  read-only ``/usr`` bind plus the host's OWN top-level merged-usr entries
  (see :func:`base_os_argv`); ``--remount-ro /`` seals everything else;
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
import sysconfig
from collections.abc import Callable, Iterable, Sequence
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
    "base_os_argv",
    "build_bwrap_argv",
    "describe_argv",
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


#: Top-level compatibility entries a merged-usr distro keeps outside ``/usr``.
#: Their SHAPE differs per distro and must never be hardcoded — see
#: :func:`base_os_argv`.
_BASE_OS_TOPLEVEL: tuple[str, ...] = ("/lib", "/lib64", "/bin", "/sbin")

#: Guard against a pathological (or looping) symlink chain.
_MAX_SYMLINK_HOPS = 64


def base_os_argv() -> tuple[str, ...]:
    """bwrap args reproducing the HOST's top-level merged-usr layout.

    The sandbox root is a fresh tmpfs holding only what we mount, so the
    ``/lib``, ``/lib64``, ``/bin`` and ``/sbin`` compatibility entries every
    dynamically linked ELF reaches through must be recreated. Their shape is
    distro-specific and MUST be read from the host rather than assumed:

    - Arch: ``/lib64 -> usr/lib``, ``/sbin -> usr/bin``
    - Debian/Ubuntu: ``/lib64 -> usr/lib64`` (a REAL directory holding only
      ``ld-linux-x86-64.so.2``), ``/sbin -> usr/sbin``

    CPython's ``PT_INTERP`` is the absolute path ``/lib64/ld-linux-x86-64.so.2``.
    Hardcoding the Arch shape pointed ``/lib64`` at ``/usr/lib`` on Ubuntu
    runners, so the dynamic loader was absent, ``execve`` returned ENOENT, and
    bwrap reported ``execvp <python>: No such file or directory`` — blaming the
    interpreter for a missing loader. Reading each entry from the host fixes
    both distro shapes by construction.
    """
    argv: list[str] = ["--ro-bind", "/usr", "/usr"]
    for entry in _BASE_OS_TOPLEVEL:
        if os.path.islink(entry):
            # Reproduce the host's link verbatim (usually relative: "usr/lib").
            argv += ["--symlink", os.readlink(entry), entry]
        elif os.path.isdir(entry):
            # A real directory outside /usr (non-merged-usr host): bind it.
            argv += ["--ro-bind", entry, entry]
    return tuple(argv)


def _symlink_chain(start: Path) -> list[Path]:
    """Every path traversed following ``start``'s symlink chain, hop by hop.

    Each relative hop is resolved against the directory of the link that
    named it, exactly as the kernel does. Stops at the first non-symlink, on
    a cycle, or at ``_MAX_SYMLINK_HOPS``.
    """
    chain: list[Path] = []
    seen: set[Path] = set()
    current = start
    for _ in range(_MAX_SYMLINK_HOPS):
        chain.append(current)
        if current in seen:
            break
        seen.add(current)
        if not os.path.islink(current):
            break
        target = os.readlink(current)
        current = Path(os.path.normpath(os.path.join(current.parent, target)))
    return chain


def prune_binds(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Deduplicate, drop paths nested inside a kept ancestor, sort deterministically.

    A bind of a parent already exposes every child, and in bwrap argv order a
    parent bound AFTER a child SHADOWS that child — so keeping only maximal
    roots is both minimal and order-safe. Sorting by path parts keeps the
    result stable and places ancestors before descendants.
    """
    unique = sorted({Path(p) for p in paths}, key=lambda p: p.parts)
    kept: list[Path] = []
    for candidate in unique:
        if any(candidate == k or k in candidate.parents for k in kept):
            continue  # already exposed by a kept ancestor
        kept.append(candidate)
    return tuple(kept)


def interpreter_ro_binds() -> tuple[Path, ...]:
    """Read-only binds required to run the *current* interpreter in the sandbox.

    Built by construction rather than by enumerating guessed prefixes:

    1. every directory along ``sys.executable``'s FULL symlink chain (each hop
       in both stated and resolved form) — a venv ``bin/python`` may point
       through several intermediate paths, and any unbound hop dangles — plus
       the *install root* (``<dir>/..``) of any hop that sits in a ``bin``
       directory. CPython derives its prefix from the path it was EXEC'd
       through, so the stdlib must be reachable under that path: uv publishes
       a version-less ``cpython-3.13-linux-x86_64-gnu`` symlink to the
       versioned install, and binding only the ``bin`` hop left
       ``<versionless>/lib/python3.13`` absent — the sandboxed interpreter
       then died with ``No module named 'encodings'``;
    2. ``sys.prefix`` and ``sys.base_prefix`` (stated + resolved) — ``pyvenv.cfg``
       and the stdlib live there;
    3. every existing directory on ``sys.path`` — site-packages can sit outside
       both prefixes (editable installs, ``--target`` installs);
    4. the ``sysconfig`` paths ``stdlib``/``platstdlib``/``purelib``/``platlib``/``data``.

    The union is then pruned to maximal roots by :func:`prune_binds`, so the
    exposed surface stays as small as the layout allows (typically just the
    venv prefix and the base install root).

    Fail-closed: raises ``sandbox_denied`` when the interpreter cannot be
    located at all, rather than emitting an argv that would fail obscurely.
    """
    if not sys.executable or not os.path.exists(sys.executable):
        raise SandboxDeniedError(
            "sandbox_unavailable: cannot locate the running interpreter "
            f"(sys.executable={sys.executable!r}); refusing to build a sandbox argv"
        )

    candidates: list[Path] = []

    def offer(path: Path) -> None:
        """Add a directory in both its stated and fully resolved form."""
        for form in (path, path.resolve()):
            if form.is_dir():
                candidates.append(form)

    # 1. the interpreter's full symlink chain: bind the directory of each hop,
    #    and the install root above a ``bin`` dir so the stdlib is reachable
    #    under whichever path the interpreter is actually exec'd through.
    for hop in _symlink_chain(Path(sys.executable)):
        offer(hop.parent)
        if hop.parent.name == "bin":
            offer(hop.parent.parent)

    # 2. the stated prefixes.
    for prefix in (sys.prefix, sys.base_prefix):
        if prefix:
            offer(Path(prefix))

    # 3. import roots that may live outside every prefix.
    for entry in sys.path:
        if entry:
            offer(Path(entry))

    # 4. the installation's declared layout.
    for name in ("stdlib", "platstdlib", "purelib", "platlib", "data"):
        location = sysconfig.get_path(name)
        if location:
            offer(Path(location))

    binds = prune_binds(candidates)
    if not binds:  # pragma: no cover - unreachable once sys.executable exists
        raise SandboxDeniedError(
            "sandbox_unavailable: no interpreter directories could be resolved for binding"
        )
    return binds


def describe_argv(argv: Sequence[str], *, limit: int = 40) -> str:
    """One-line, truncated rendering of a bwrap argv for error messages.

    Keeps the mount plan (the part that goes wrong) legible in a CI log while
    bounding the length of the ``--ro-bind`` list on large specs.
    """
    binds = [argv[i + 1] for i, a in enumerate(argv) if a in ("--ro-bind", "--bind")]
    shown = binds[:limit]
    elided = len(binds) - len(shown)
    bind_note = ", ".join(shown) + (f", ... (+{elided} more)" if elided > 0 else "")
    flat = " ".join(argv)
    if len(flat) > 4000:
        flat = flat[:4000] + " ...(truncated)"
    return f"argv={flat}; binds=[{bind_note}]"


def build_bwrap_argv(bwrap: str | Path, spec: SandboxSpec) -> tuple[str, ...]:
    """Build the exact bwrap argv for one worker invocation (pure, testable).

    Raises ``ValueError`` when the spec's paths do not exist on the host —
    bwrap would fail anyway, but with a far less useful diagnostic.
    """
    out_dir = Path(spec.rw_out_dir).resolve()
    if not out_dir.is_dir():
        raise ValueError(f"rw_out_dir does not exist or is not a directory: {out_dir}")
    # Keep BOTH the stated and the resolved form of every ro_bind: worker_cmd
    # and sys.path entries name STATED paths, which dangle inside the sandbox
    # if only the symlink's resolved target was mounted.
    stated_and_resolved: list[Path] = []
    for bind in spec.ro_binds:
        stated = Path(bind)
        resolved = stated.resolve()
        if not resolved.exists():
            raise ValueError(f"ro_bind path does not exist: {resolved}")
        stated_and_resolved += [stated, resolved]
    ro_binds = prune_binds(stated_and_resolved)

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
    ]
    # Base OS, read-only, plus the host's own top-level merged-usr entries so
    # the dynamic loader named by PT_INTERP resolves on ANY distro.
    argv += list(base_os_argv())
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
