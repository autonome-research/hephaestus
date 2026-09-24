"""Fail-closed sandbox capability detection, per-store caching, backend factory.

``probe_bwrap`` proves the sandbox works by *running* it: a trivial Python
job executes inside bwrap and performs live escape probes (network connect
must fail, writes outside the out dir must fail, ``/etc/shadow`` must be
unreadable, the out dir must be writable and visible to the host). A version
string is never trusted as evidence. Any failure — bwrap missing, launch
error, a probe not blocking — yields ``available=False`` with a reason.

``cached_probe`` persistently caches only *passing* bwrap reports per store
root; OCI reports remain instance-local. Failures are always re-probed.

``secure_backend`` is the only factory secure builds may use. Linux is
bwrap-only. Darwin is OCI-only but currently refuses before discovery because
no production image is published. Unsupported platforms refuse. It NEVER
falls back to the unsafe backend. ``refuse_unsafe`` is the policy gate the unsafe
backend must call before running anything: registry content and ``serve``
are always refused (``unsafe_refused``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from hephaestus.core.errors import SandboxDeniedError, UnsafeRefusedError
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecBackend,
    Rlimits,
    SandboxSpec,
)
from hephaestus.core.executor.sandbox.oci import OciBackend

if TYPE_CHECKING:
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

__all__ = [
    "PROBE_CACHE_FILENAME",
    "cached_probe",
    "probe_bwrap",
    "refuse_unsafe",
    "secure_backend",
]

PROBE_CACHE_FILENAME = "sandbox_probe.json"

# Production OCI activation is intentionally unavailable until the executor
# package/image/release-lane contract is complete. This setting is package-owned:
# environment variables, project files, and CLI flags may not override it.
PRODUCTION_OCI_IMAGE: str | None = None

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
    from hephaestus.core.executor.sandbox.bwrap import (
        BwrapBackend,
        build_bwrap_argv,
        describe_argv,
    )

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
            worker_args=("-c", _PROBE_SOURCE),
            ro_binds=(),
            rw_out_dir=out_dir,
            rlimits=_PROBE_RLIMITS,
            wall_clock_s=_PROBE_WALL_CLOCK_S,
        )
        # The mount plan the probe actually attempted. A launch/exec failure is
        # almost always a MISSING MOUNT, and the bwrap message names the binary
        # it could not exec rather than the file that was really absent (a
        # missing dynamic loader reports as ENOENT on the interpreter). Carrying
        # the argv into the structured error makes the next failure diagnosable
        # from the CI log alone.
        try:
            plan = describe_argv(build_bwrap_argv(bwrap, spec))
        except (ValueError, OSError) as exc:  # pragma: no cover - defensive
            plan = f"argv unavailable: {exc}"

        try:
            outcome = backend.execute(spec, b"")
        except (SandboxDeniedError, OSError, ValueError) as exc:
            return _unavailable(f"sandboxed probe launch failed: {exc}; {plan}")
        if outcome.timed_out:
            return _unavailable(f"sandboxed probe timed out; {plan}")
        if outcome.exit_code != 0:
            tail = outcome.stderr.decode("utf-8", errors="replace")[-300:]
            return _unavailable(
                f"sandboxed probe exited {outcome.exit_code}; stderr tail: {tail!r}; {plan}"
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
    if any(feature_map.get(name) is not True for name in REQUIRED_FEATURES):
        return None
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
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{cache_path.name}.",
        suffix=".tmp",
        dir=cache_path.parent,
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(cache_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def cached_probe(
    store_root: Path,
    backend: ExecBackend | None = None,
    *,
    scratch_dir: Path | None = None,
) -> CapabilityReport:
    """Probe a backend, persistently caching passing bwrap evidence only.

    OCI evidence is cached only inside its backend instance and never written
    into a project-controlled store. Failing reports are never cached.
    """
    if backend is not None and backend.name != "bwrap":
        return backend.probe()
    if sys.platform != "linux":
        return _unavailable("bwrap is supported only on Linux")

    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    selected = backend or BwrapBackend()
    if not isinstance(selected, BwrapBackend):
        return selected.probe()

    store_root.mkdir(parents=True, exist_ok=True)
    cache_path = store_root / PROBE_CACHE_FILENAME
    entry = _read_cache(cache_path)
    if entry is not None:
        current_path = selected.bwrap_path()
        cached_report = _report_from_cache(entry)
        if (
            cached_report is not None
            and current_path is not None
            and entry.get("bwrap_path") == current_path
            and entry.get("bwrap_version") == _bwrap_version(current_path)
        ):
            return cached_report

    report = probe_bwrap(selected, scratch_dir=scratch_dir)
    if report.available:
        bwrap = selected.bwrap_path()
        version = _bwrap_version(bwrap) if bwrap is not None else None
        if bwrap is not None and version is not None:
            _write_cache(cache_path, bwrap, version, report)
    return report


def _discover_darwin_oci_backends(image_ref: str) -> tuple[OciBackend, ...]:
    """Return validated local-runtime candidates once production activation lands.

    Runtime discovery deliberately remains absent while ``PRODUCTION_OCI_IMAGE``
    is unavailable. Tests inject candidates at this boundary; production must
    later replace this empty implementation together with a published digest
    and real macOS release-lane evidence.
    """
    del image_ref
    return ()


def secure_backend(store_root: Path, *, scratch_dir: Path | None = None) -> ExecBackend:
    """Select the sole secure backend allowed by the current host platform.

    Linux is bwrap-only. Darwin is OCI-only, but currently fails closed before
    discovery because no package-owned production image has been published.
    Other platforms are unsupported. No branch falls back to unsafe execution.
    """
    if sys.platform == "linux":
        from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

        backend = BwrapBackend()
        report = cached_probe(store_root, backend, scratch_dir=scratch_dir)
        if report.available:
            return backend
        raise SandboxDeniedError(f"sandbox_unavailable: secure bwrap probe failed: {report.reason}")

    if sys.platform == "darwin":
        image_ref = PRODUCTION_OCI_IMAGE
        if image_ref is None:
            raise SandboxDeniedError(
                "sandbox_unavailable: the macOS OCI executor image is not published"
            )
        candidates = _discover_darwin_oci_backends(image_ref)
        reasons: list[str] = []
        for backend in candidates:
            report = cached_probe(store_root, backend, scratch_dir=scratch_dir)
            if report.available:
                return backend
            reasons.append(report.reason or f"{backend.name} probe failed")
        detail = "; ".join(reasons) if reasons else "no validated local OCI runtime"
        raise SandboxDeniedError(f"sandbox_unavailable: secure OCI probe failed: {detail}")

    raise SandboxDeniedError(
        f"sandbox_unavailable: no secure sandbox backend supports {sys.platform!r}"
    )


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
