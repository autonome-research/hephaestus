"""Gate G0B — secure-sandbox escape denial and unsafe-mode refusal.

Two clauses:

- **Escape denial under the secure backend.** Part scripts that reach for host
  resources through Python *introspection* (walking ``object`` subclasses to
  recover the real ``open``/``__import__`` past the injected whitelist) are
  contained by the OS sandbox: filesystem reads outside the out dir, writes
  outside it, symlink escapes, subprocess/process escapes, and network
  connections all fail, and no host-side artifact is produced. These require a
  proven bwrap sandbox; the suite skips (never falsely passes) when the probe
  cannot prove containment.
- **Unsafe-mode refusal for registry content.** The ``--unsafe-local-executor``
  backend refuses registry-origin jobs (and unparseable payloads) outright,
  and its capability report flags every isolation feature false.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _gate import build_source, secure_backend
from hephaestus.core.errors import UnsafeRefusedError
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend, Rlimits, SandboxSpec
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

# Introspection preamble: recover a real builtins mapping from a class whose
# __init__ globals carry it, defeating the injected safe-builtins whitelist —
# so the test proves the OS sandbox (not the whitelist) is the boundary.
_RECOVER = (
    "for _c in (0).__class__.__mro__[-1].__subclasses__():\n"
    '    _g = getattr(getattr(_c, "__init__", None), "__globals__", {})\n'
    '    if "__builtins__" in _g:\n'
    '        _b = _g["__builtins__"]\n'
    '        _open = _b["open"] if isinstance(_b, dict) else _b.open\n'
    '        _imp = _b["__import__"] if isinstance(_b, dict) else _b.__import__\n'
    "        break\n"
)

# Filesystem-root target: read-only inside the sandbox (sealed by --remount-ro)
# and not user-writable on the host, so a contained escape both fails the write
# and leaves no host artifact. (/tmp is a sandbox tmpfs and would succeed
# harmlessly, so it is deliberately NOT used as the escape target.)
_HOST_MARKER = Path("/heph-g0b-escape-proof.txt")

ESCAPES: dict[str, str] = {
    "network": _RECOVER + '_sock = _imp("socket")\n'
    '_s = _sock.create_connection(("1.1.1.1", 443), timeout=3)\n'
    "_s.close()\n"
    "part.geometry = Box(1, 1, 1)\n",
    "read_shadow": _RECOVER + '_data = _open("/etc/shadow", "rb").read(1)\n'
    "part.geometry = Box(1, 1, 1)\n",
    "write_outside": _RECOVER + f'_f = _open({str(_HOST_MARKER)!r}, "w")\n'
    "_f.write('escaped')\n"
    "_f.close()\n"
    "part.geometry = Box(1, 1, 1)\n",
    "symlink": _RECOVER + '_os = _imp("os")\n'
    '_os.symlink("/etc/hostname", "escape-link")\n'
    '_data = _open("escape-link", "rb").read()\n'
    "part.geometry = Box(1, 1, 1)\n",
    "subprocess": _RECOVER + '_sp = _imp("subprocess")\n'
    f'_sp.run(["/usr/bin/touch", {str(_HOST_MARKER)!r}], check=True)\n'
    "part.geometry = Box(1, 1, 1)\n",
}


@pytest.fixture(scope="module")
def backend() -> ExecBackend:
    secure = secure_backend()
    if secure is None:
        pytest.skip("secure bwrap sandbox is not provable on this host")
    return secure


@pytest.fixture(autouse=True)
def _no_host_marker() -> None:
    # Guard: the root-targeted marker must not pre-exist, so a "does not exist"
    # assertion after the escape genuinely proves containment.
    assert not _HOST_MARKER.exists()


@pytest.mark.parametrize("name", sorted(ESCAPES))
def test_introspection_escape_denied(name: str, backend: ExecBackend, tmp_path: Path) -> None:
    built = build_source("escape", ESCAPES[name], tmp_path, backend=backend)
    # The escape attempt must be contained: the OS raises, so the statement
    # fails and the build reports failed — it never silently succeeds having
    # touched the host.
    assert built.result.status == "failed", f"{name} escape was not contained"
    assert built.result.error is not None
    # No host-side artifact was produced by any escape variant.
    assert not _HOST_MARKER.exists()


def test_write_escape_leaves_no_host_file(backend: ExecBackend, tmp_path: Path) -> None:
    build_source("escape", ESCAPES["write_outside"], tmp_path, backend=backend)
    assert not _HOST_MARKER.exists()


def test_out_dir_is_the_only_writable_surface(backend: ExecBackend, tmp_path: Path) -> None:
    # A benign write to the out dir succeeds (the ONE rw bind), proving the
    # denial above is containment, not a blanket build failure.
    script = (
        _RECOVER + '_f = _open("inside.txt", "w")\n_f.write("ok")\n_f.close()\n'
        "part.geometry = Box(1, 1, 1)\n"
    )
    built = build_source("inside", script, tmp_path, backend=backend)
    assert built.result.status == "ok"
    assert (tmp_path / "inside.txt").read_text() == "ok"


class TestUnsafeRefusal:
    """The unsafe backend refuses registry content and is honestly flagged."""

    def _spec(self, tmp_path: Path) -> SandboxSpec:
        return SandboxSpec(
            worker_cmd=("true",),
            ro_binds=(),
            rw_out_dir=tmp_path,
            rlimits=Rlimits(cpu_seconds=5, address_space_bytes=1 << 30, nproc=64),
            wall_clock_s=10.0,
        )

    def test_registry_origin_refused(self, tmp_path: Path) -> None:
        payload = json.dumps({"origin": "registry", "script": "x"}).encode("utf-8")
        with pytest.raises(UnsafeRefusedError):
            UnsafeLocalBackend().execute(self._spec(tmp_path), payload)

    def test_unparseable_payload_refused(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeRefusedError):
            UnsafeLocalBackend().execute(self._spec(tmp_path), b"\xff\x00not json")

    def test_non_object_payload_refused(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeRefusedError):
            UnsafeLocalBackend().execute(self._spec(tmp_path), b"[1, 2, 3]")

    def test_registry_build_refused_end_to_end(self, tmp_path: Path) -> None:
        # A registry-origin build through the unsafe backend never runs the
        # worker: the refusal surfaces before execution.
        request = BuildRequest(part="p", script="part.geometry = Box(1,1,1)", origin="registry")
        with pytest.raises(UnsafeRefusedError):
            run_build(request, backend=UnsafeLocalBackend(), out_dir=tmp_path)

    def test_capability_report_flags_no_isolation(self) -> None:
        report = UnsafeLocalBackend().probe()
        assert report.available is True
        assert report.features["filesystem_isolation"] is False
        assert report.features["network_isolation"] is False
        assert report.features["process_isolation"] is False
        assert report.features["unsafe"] is True
