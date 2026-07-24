"""Fail-closed sandbox capability detection, per-store caching, backend factory.

``probe_bwrap`` proves the sandbox works by *running* it: a trivial Python
job executes inside bwrap and performs live escape probes (network connect
must fail, writes outside the out dir must fail, ``/etc/shadow`` must be
unreadable, the out dir must be writable and visible to the host). A version
string is never trusted as evidence. Any failure — bwrap missing, launch
error, a probe not blocking — yields ``available=False`` with a reason.

``cached_probe`` caches only *passing* reports per store root (failures are
re-probed every time so installing bwrap later is picked up); the cache is
invalidated when the bwrap path or version changes.

``secure_backend`` is the only factory secure builds may use: it returns a
probed :class:`BwrapBackend` or raises ``sandbox_denied`` — it NEVER falls
back to the unsafe backend. ``refuse_unsafe`` is the policy gate the unsafe
backend must call before running anything: registry content and ``serve``
are always refused (``unsafe_refused``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from hephaestus.core.errors import SandboxDeniedError, UnsafeRefusedError
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    Rlimits,
    SandboxSpec,
)
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, interpreter_ro_binds

__all__ = [
    "PROBE_CACHE_FILENAME",
    "cached_probe",
    "probe_bwrap",
    "refuse_unsafe",
    "secure_backend",
]

PROBE_CACHE_FILENAME = "sandbox_probe.json"

#: Every feature the probe must observe as True for ``available=True``.
REQUIRED_FEATURES: tuple[str, ...] = (
    "trivial_run",
    "network_blocked",
    "shadow_unreadable",
    "outside_write_blocked",
    "ro_bind_write_blocked",
    "out_dir_writable",
)

# nproc must exceed the invoking user's current kernel task ucount, or bwrap's
# userns clone fails EAGAIN (tasks of the same kuid are charged to the ucounts
# hierarchy the sandbox inherits). 4096 is a safe fork-bomb cap.
_PROBE_RLIMITS = Rlimits(cpu_seconds=30, address_space_bytes=1 << 30, nproc=4096)
_PROBE_WALL_CLOCK_S = 60.0

# Child-side probe program (stdlib only). Runs INSIDE the sandbox; prints one
# JSON object mapping feature name -> bool. Every containment feature is True
# only when the escape attempt actually failed.
_PROBE_SOURCE = """\
import json, os, socket, sys

checks = {}

def attempt(name, fn, expect_blocked):
    try:
        fn()
        blocked = False
    except Exception:
        blocked = True
    checks[name] = blocked is expect_blocked

def _net():
    s = socket.create_connection(("1.1.1.1", 443), timeout=3)
    s.close()

def _out_write():
    with open("probe-ok.txt", "w") as f:
        f.write("ok")

attempt("network_blocked", _net, True)
attempt("shadow_unreadable", lambda: open("/etc/shadow", "rb").read(1), True)
attempt("outside_write_blocked", lambda: open("/probe-escape.txt", "w"), True)
attempt(
    "ro_bind_write_blocked",
    lambda: open(os.path.join(sys.prefix, "probe-escape.txt"), "w"),
    True,
)
attempt("out_dir_writable", _out_write, False)
checks["trivial_run"] = True
print(json.dumps(checks))
"""


def _unavailable(reason: str, features: dict[str, bool] | None = None) -> CapabilityReport:
    return CapabilityReport(
        backend="bwrap",
        available=False,
        reason=reason,
        probed_at=time.time(),
        features=features or {},
    )


def _bwrap_version(bwrap: str) -> str | None:
    """The bwrap version string, or None when it cannot be obtained."""
    try:
        proc = subprocess.run(
            [bwrap, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _parse_probe_stdout(stdout: bytes) -> dict[str, bool] | None:
    """Extract the single JSON feature object from the child's stdout."""
    for raw_line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and all(
            isinstance(k, str) and isinstance(v, bool)
            for k, v in parsed.items()  # pyright: ignore[reportUnknownVariableType]
        ):
            return {str(k): bool(v) for k, v in parsed.items()}
    return None


def probe_bwrap(
    backend: BwrapBackend | None = None, *, scratch_dir: Path | None = None
) -> CapabilityReport:
    """Live fail-closed probe of the bwrap sandbox. Never raises for unavailability."""
    backend = backend or BwrapBackend()
    bwrap = backend.bwrap_path()
    if bwrap is None:
        return _unavailable("bwrap not on PATH")
    version = _bwrap_version(bwrap)
    if version is None:
        return _unavailable(f"bwrap at {bwrap!r} did not report a version")

    with tempfile.TemporaryDirectory(prefix="heph-sandbox-probe-", dir=scratch_dir) as tmp:
        out_dir = Path(tmp) / "out"
        out_dir.mkdir()
        spec = SandboxSpec(
            worker_cmd=(sys.executable, "-c", _PROBE_SOURCE),
            ro_binds=interpreter_ro_binds(),
            rw_out_dir=out_dir,
            rlimits=_PROBE_RLIMITS,
            wall_clock_s=_PROBE_WALL_CLOCK_S,
        )
        try:
            outcome = backend.execute(spec, b"")
        except (SandboxDeniedError, OSError, ValueError) as exc:
            return _unavailable(f"sandboxed probe launch failed: {exc}")
        if outcome.timed_out:
            return _unavailable("sandboxed probe timed out")
        if outcome.exit_code != 0:
            tail = outcome.stderr.decode("utf-8", errors="replace")[-300:]
            return _unavailable(
                f"sandboxed probe exited {outcome.exit_code}; stderr tail: {tail!r}"
            )
        features = _parse_probe_stdout(outcome.stdout)
        if features is None:
            return _unavailable("sandboxed probe produced no structured output")
        # Host-side confirmation that the rw out-dir bind maps through.
        proof = out_dir / "probe-ok.txt"
        features["out_dir_writable"] = (
            features.get("out_dir_writable", False)
            and proof.is_file()
            and proof.read_text() == "ok"
        )

    missing = [f for f in REQUIRED_FEATURES if not features.get(f, False)]
    if missing:
        return _unavailable(
            "sandbox ran but containment was not proven; failed feature(s): "
            + ", ".join(sorted(missing)),
            features,
        )
    return CapabilityReport(
        backend="bwrap",
        available=True,
        reason=None,
        probed_at=time.time(),
        features=features,
    )


def _read_cache(cache_path: Path) -> dict[str, object] | None:
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return {str(k): v for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType]


def _report_from_cache(entry: dict[str, object]) -> CapabilityReport | None:
    report = entry.get("report")
    if not isinstance(report, dict):
        return None
    backend = report.get("backend")  # pyright: ignore[reportUnknownMemberType]
    available = report.get("available")  # pyright: ignore[reportUnknownMemberType]
    probed_at = report.get("probed_at")  # pyright: ignore[reportUnknownMemberType]
    features = report.get("features")  # pyright: ignore[reportUnknownMemberType]
    if backend != "bwrap" or available is not True:
        return None
    if not isinstance(probed_at, int | float) or not isinstance(features, dict):
        return None
    feature_map: dict[str, bool] = {}
    for key, value in features.items():  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(key, str) or not isinstance(value, bool):
            return None
        feature_map[key] = value
    try:
        return CapabilityReport(
            backend="bwrap",
            available=True,
            reason=None,
            probed_at=float(probed_at),
            features=feature_map,
        )
    except ValueError:
        return None


def _write_cache(cache_path: Path, bwrap_path: str, version: str, report: CapabilityReport) -> None:
    payload = {
        "bwrap_path": bwrap_path,
        "bwrap_version": version,
        "report": {
            "backend": report.backend,
            "available": report.available,
            "reason": report.reason,
            "probed_at": report.probed_at,
            "features": dict(report.features),
        },
    }
    tmp = cache_path.with_name(cache_path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(cache_path)


def cached_probe(
    store_root: Path,
    backend: BwrapBackend | None = None,
    *,
    scratch_dir: Path | None = None,
) -> CapabilityReport:
    """Per-store-root cached probe (cache file: ``<store_root>/sandbox_probe.json``).

    A cached PASSING report is returned only when the current bwrap path and
    version still match the ones that passed. Failing reports are never
    cached — unavailability is always re-checked (fail closed, cheap).
    """
    backend = backend or BwrapBackend()
    store_root.mkdir(parents=True, exist_ok=True)
    cache_path = store_root / PROBE_CACHE_FILENAME

    entry = _read_cache(cache_path)
    if entry is not None:
        current_path = backend.bwrap_path()
        cached_report = _report_from_cache(entry)
        if (
            cached_report is not None
            and current_path is not None
            and entry.get("bwrap_path") == current_path
            and entry.get("bwrap_version") == _bwrap_version(current_path)
        ):
            return cached_report

    report = probe_bwrap(backend, scratch_dir=scratch_dir)
    if report.available:
        bwrap = backend.bwrap_path()
        version = _bwrap_version(bwrap) if bwrap is not None else None
        if bwrap is not None and version is not None:
            _write_cache(cache_path, bwrap, version, report)
    return report


def secure_backend(store_root: Path, *, scratch_dir: Path | None = None) -> BwrapBackend:
    """The ONLY factory secure builds may use. Probed bwrap or ``sandbox_denied``.

    Never falls back to the unsafe backend — silently or otherwise. The
    unsafe backend exists solely behind its explicit CLI flag and its own
    module.
    """
    backend = BwrapBackend()
    report = cached_probe(store_root, backend, scratch_dir=scratch_dir)
    if not report.available:
        raise SandboxDeniedError(
            f"sandbox_unavailable: secure sandbox probe failed: {report.reason}"
        )
    return backend


def refuse_unsafe(*, registry_content: bool, serve: bool = False) -> None:
    """Policy gate for the unsafe local backend; raises ``unsafe_refused``.

    Registry content and ``heph serve`` may never run under the unsafe
    backend, flag or no flag. The unsafe backend must call this before
    executing anything.
    """
    if registry_content:
        raise UnsafeRefusedError(
            "unsafe local executor refused: registry content requires the secure sandbox"
        )
    if serve:
        raise UnsafeRefusedError(
            "unsafe local executor refused: serve never runs the unsafe backend"
        )
