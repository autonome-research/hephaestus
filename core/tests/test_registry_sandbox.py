# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Executable registry content has sandbox parity with part scripts.

Store generators are untrusted executable content (architecture §7.2). This file
asserts the boundary from both sides:

* the *happy* path — a shipped generator instances under the probed bwrap sandbox,
  and the fragment it returns rebuilds the same geometry when pasted into a part;
* the *denial* paths — a generator reaching for the filesystem, for ``__import__``
  or for the project's own ``hc`` namespace is refused, the unsafe local backend
  refuses registry-origin jobs outright, and no configured backend at all is a
  typed ``capability_not_available`` rather than a quiet unsandboxed run.

The bwrap cases skip where bubblewrap is unavailable; the refusal cases do not
need a sandbox and always run.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.bwrap import BwrapBackend, find_bwrap
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.registry import (
    MANIFEST_FILENAME,
    RegistryError,
    RegistryOps,
    RegistrySet,
    load_registry,
    parse_generator,
)

from opstore import OpStore

REPO = Path(__file__).resolve().parents[2]
REGISTRIES = REPO / "registries"

requires_bwrap = pytest.mark.skipif(
    sys.platform != "linux" or find_bwrap() is None,
    reason="registry generators execute only under a probed secure sandbox (bubblewrap)",
)

HOSTILE_MANIFEST = """\
[registry]
name = "hostile-parts"
kind = "parts"
version = "0.0.1"
license = "Apache-2.0"

[[parts]]
id = "reads_a_file"
dir = "reads_a_file"

[[parts]]
id = "imports_os"
dir = "imports_os"
"""

#: Body statements that reach the sandbox and must fail there.
HOSTILE_BODIES: dict[str, str] = {
    # Straight filesystem read: `open` is not in the injected namespace at all,
    # and the sandbox has no bind to read from even if it were.
    "reads_a_file": '_leak = open("/etc/passwd").read()\n_solid = Box(_size, _size, _size)\n',
    # The classic namespace escape.
    "imports_os": '_os = __import__("os")\n_solid = Box(_size, _size, _size)\n',
}


def _hostile_generator(body: str) -> str:
    return (
        "# --- hephaestus-store: params ---\n"
        'PARAMS = {\n    "size": Param(10.0, min=1.0, max=50.0),\n}\n'
        "# --- hephaestus-store: bind ---\n"
        "_size = p.size\n"
        "# --- hephaestus-store: body ---\n"
        f"{body}"
        "part.geometry = _solid\n"
    )


@pytest.fixture
def hostile_registry(tmp_path: Path) -> Path:
    root = tmp_path / "hostile"
    root.mkdir()
    (root / MANIFEST_FILENAME).write_text(HOSTILE_MANIFEST, encoding="utf-8")
    for part_id, body in HOSTILE_BODIES.items():
        directory = root / part_id
        directory.mkdir()
        (directory / "generator.py").write_text(_hostile_generator(body), encoding="utf-8")
        (directory / "part.json").write_text(
            json.dumps({"id": part_id, "name": part_id, "params": {"size": {"default": 10.0}}}),
            encoding="utf-8",
        )
    return root


@pytest.fixture
def store(tmp_path: Path) -> Iterator[OpStore]:
    opened = OpStore.create(tmp_path / "store")
    yield opened
    opened.close()


def _ops(root: Path, store: OpStore, backend: object | None) -> RegistryOps:
    registries = RegistrySet({root.name: load_registry(root)})
    return RegistryOps(registries, store, backend=backend)  # type: ignore[arg-type]


def _shipped_ops(store: OpStore, backend: object | None, tmp_path: Path) -> RegistryOps:
    registries = RegistrySet({"parts": load_registry(REGISTRIES / "parts")})
    return RegistryOps(
        registries,
        store,
        backend=backend,  # type: ignore[arg-type]
        scratch_root=tmp_path / "scratch",
    )


# -- the boundary: no backend, unsafe backend --------------------------------


def test_no_backend_is_capability_not_available(store: OpStore, tmp_path: Path) -> None:
    ops = _shipped_ops(store, None, tmp_path)
    with pytest.raises(RegistryError) as ei:
        ops.instance_store_part("screw_socket_head_m5", {"length": 16.0})
    assert ei.value.reason == "capability_not_available"
    # The code rides in data so the sidecar proxy can discriminate the result.
    assert ei.value.data["code"] == "capability_not_available"
    assert "unsandboxed" in ei.value.message


def test_unsafe_backend_refuses_registry_origin(store: OpStore, tmp_path: Path) -> None:
    """Sandbox parity, hard edge: registry code never runs on the unsafe backend."""
    ops = _shipped_ops(store, UnsafeLocalBackend(), tmp_path)
    with pytest.raises(RegistryError) as ei:
        ops.instance_store_part("screw_socket_head_m5", {"length": 16.0})
    assert ei.value.reason == "unsafe_refused"


def test_read_only_registry_tools_need_no_backend(store: OpStore, tmp_path: Path) -> None:
    """Search is metadata; only instancing executes anything."""
    ops = _shipped_ops(store, None, tmp_path)
    assert ops.search_parts_store("m3 screw", 3)[0]["id"] == "screw_socket_head_m3"


# -- parameter validation happens before anything executes -------------------


def test_unknown_and_non_numeric_params_are_refused(store: OpStore, tmp_path: Path) -> None:
    ops = _shipped_ops(store, None, tmp_path)
    for params in ({"lenght": 16.0}, {"length": "16"}, {"length": float("inf")}):
        with pytest.raises(RegistryError) as ei:
            ops.instance_store_part("screw_socket_head_m5", params)
        assert ei.value.reason == "invalid_params"


def test_unknown_store_part_names_the_candidates(store: OpStore, tmp_path: Path) -> None:
    ops = _shipped_ops(store, None, tmp_path)
    with pytest.raises(RegistryError) as ei:
        ops.instance_store_part("screw_socket_head_m8", {})
    assert ei.value.reason == "unknown_store_part"
    assert "screw_socket_head_m5" in str(ei.value.data["candidates"])


# -- the fragment contract rejects generators that cannot be instanced -------


def test_generator_contract_rejects_unbounded_and_leaky_sources() -> None:
    for body in (
        "_solid = Box(p.size, 10.0, 10.0)\npart.geometry = _solid\n",  # reads p in the body
        "solid = Box(_size, 10.0, 10.0)\npart.geometry = solid\n",  # module name not private
        "_solid = Box(_size, 10.0, 10.0)\npart.description = 'x'\n",  # no geometry publication
        "_solid = Box(_size, 10.0, 10.0)\nCHECKS = {}\npart.geometry = _solid\n",  # touches CHECKS
        # Project state: a store generator is pure geometry and never sees `hc`.
        # This one is refused at parse time, before anything is executed at all.
        "_solid = Box(_size, _size, hc.sheet_t)\npart.geometry = _solid\n",
    ):
        with pytest.raises(ValidationError):
            parse_generator(_hostile_generator(body))


# -- denial under the real sandbox -------------------------------------------


@requires_bwrap
@pytest.mark.parametrize("part_id", sorted(HOSTILE_BODIES))
def test_hostile_generator_is_denied_under_the_sandbox(
    part_id: str, hostile_registry: Path, store: OpStore
) -> None:
    ops = _ops(hostile_registry, store, BwrapBackend())
    with pytest.raises(RegistryError) as ei:
        ops.instance_store_part(part_id, {"size": 10.0})
    assert ei.value.reason in {"generator_failed", "sandbox_denied"}
    # Nothing leaked into the refusal: it names the generator, not file contents.
    assert part_id in ei.value.message
    assert "root:" not in ei.value.message


# -- the happy path under the real sandbox -----------------------------------


@requires_bwrap
def test_shipped_generator_instances_under_the_sandbox(store: OpStore, tmp_path: Path) -> None:
    ops = _shipped_ops(store, BwrapBackend(), tmp_path)
    result = ops.instance_store_part(
        "screw_socket_head_m5", {"length": 20.0}, {"x": 25.0, "y": 0.0, "z": 6.0}
    )
    assert result["id"] == "screw_socket_head_m5"
    assert result["params"] == {"length": 20.0}
    fragment = str(result["script_fragment"])
    assert "hephaestus-parts" in fragment
    assert str(result["registry_digest"]) in fragment
    assert "Pos(25.0, 0.0, 6.0)" in fragment
    assert "_length = 20.0" in fragment


@requires_bwrap
def test_the_returned_fragment_rebuilds_as_part_of_a_script(store: OpStore, tmp_path: Path) -> None:
    """A pasted fragment is source that builds — that is the whole contract."""
    ops = _shipped_ops(store, BwrapBackend(), tmp_path)
    result = ops.instance_store_part("heatset_insert_m3", {"clearance": 0.1}, {"z": 4.0})
    fragment = str(result["script_fragment"])
    root = next(
        line.split("=", 1)[0].strip()
        for line in reversed(fragment.splitlines())
        if line.startswith("_") and ".label" not in line
    )
    script = (
        "_plate = Box(20.0, 20.0, 4.0, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
        '_plate.label = "plate"\n'
        f"{fragment}\n"
        f'{root}.label = "insert"\n'
        f"part.geometry = Compound(children=[_plate, {root}])\n"
        'part.description = "Pasted store instance."\n'
        'CHECKS = {"instance_present": lambda m: m.volume("insert") > 20.0}\n'
    )
    with tempfile.TemporaryDirectory() as scratch:
        build = run_build(
            BuildRequest(part="pasted", script=script),
            backend=UnsafeLocalBackend(),
            out_dir=Path(scratch) / "out",
        )
    assert build.result.status == "ok", build.result.error
    assert all(check.passed for check in build.result.checks.values())


@requires_bwrap
def test_instancing_is_deterministic_across_two_sandboxed_builds(
    store: OpStore, tmp_path: Path
) -> None:
    ops = _shipped_ops(store, BwrapBackend(), tmp_path)
    args = ("screw_socket_head_m4", {"length": 12.0}, {"x": 1.0})
    first = ops.instance_store_part(*args)
    second = ops.instance_store_part(*args)
    assert first["script_fragment"] == second["script_fragment"]
    assert first["metrics"] == second["metrics"]
