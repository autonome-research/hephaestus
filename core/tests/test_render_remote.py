"""Host injection/publication regressions with explicitly synthetic geometry/pixels.

These are boundary tests, never CAD, raster, GLB execution or acceptance evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import struct
import subprocess
import sys
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import NotRequired, TypedDict

import pytest
from _execution_identity import identity
from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.executor.identity import ExecutionIdentity
from hephaestus.core.executor.runner import BuildRequest, assemble_build
from hephaestus.core.executor.sandbox.oci_ownership import OwnershipJournal
from hephaestus.core.project_store.layout import open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import StaleSelectionError, resolve_selection
from hephaestus.core.render.glb_gate import parse_glb, validate_linked_glb
from hephaestus.core.render.gltf_publish import publish_gltf_for_build, resolve_published_gltf
from hephaestus.core.render.inspect import Channel, MaskMode, RenderProject, inspect_part
from hephaestus.core.render.oci_backend import RenderResult
from hephaestus.core.render.oci_protocol import RenderRequest, Response, request_hash
from hephaestus.testing.render_fixture import require_fixture_faces
from test_execution_identity import ImageBackend, result_record, write_artifacts
from test_project_store_helpers import DEFAULT_SCRIPT, make_project
from test_render_oci import response


def pack(doc: object, binary: bytes) -> bytes:
    data = json.dumps(doc, separators=(",", ":")).encode()
    data += b" " * (-len(data) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(data) + len(binary))
        + struct.pack("<I4s", len(data), b"JSON")
        + data
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


def synthetic_glb(source: str, bundle: str, table: str) -> bytes:
    binary = struct.pack("<9f3I", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    doc = {
        "asset": {
            "version": "2.0",
            "extras": {
                "source_artifact_ref": source,
                "selection_bundle_ref": bundle,
                "selection_table_ref": table,
            },
        },
        "buffers": [{"byteLength": 48}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 12},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 3},
            {"bufferView": 1, "componentType": 5125, "type": "SCALAR", "count": 3},
        ],
        "meshes": [
            {
                "extras": {
                    "kind": "solid",
                    "solid_index": 0,
                    "selection_id": 1,
                    "label": "cube",
                    "explode_offset": [0, 0, 0],
                },
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "material": 0,
                        "mode": 4,
                        "extras": {
                            "kind": "face",
                            "solid_index": 0,
                            "selection_id": 2,
                            "face_index": 0,
                        },
                    }
                ],
            }
        ],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1]}}],
        "nodes": [{"mesh": 0}],
        "scene": 0,
        "scenes": [{"nodes": [0]}],
    }
    return pack(doc, binary)


class SyntheticRenderer:
    def __init__(self) -> None:
        self.value = identity(image_id="sha256:" + "f" * 64)
        self.operations: list[str] = []
        self.corrupt: Callable[[Response], None] | None = None

    def execution_identity(self) -> ExecutionIdentity:
        return self.value

    def render(self, request: RenderRequest, brep: bytes) -> RenderResult:
        import base64

        assert request["brep_sha256"] == hashlib.sha256(brep).hexdigest()
        self.operations.append(request["operation"])
        if request["operation"] == "gltf":
            selection: RenderRequest = {**request, "operation": "selection", "links": None}
            result = response(selection)
            result.update(operation="gltf", request_sha256=request_hash(request), images={})
            assert request["links"] is not None
            data = synthetic_glb(
                request["source_ref"],
                request["links"]["bundle_ref"],
                request["links"]["selection_table_ref"],
            )
            result["glb"] = {
                "data": base64.b64encode(data).decode(),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        else:
            result = response(request)
        if self.corrupt:
            self.corrupt(result)
        return RenderResult(json.dumps(result).encode(), self.value)


@dataclass(frozen=True)
class SyntheticProject(RenderProject):
    renderer: SyntheticRenderer = field(default_factory=SyntheticRenderer)
    backend: ImageBackend = field(default_factory=ImageBackend)


def current_source(project: RenderProject) -> str:
    result = project.publisher().current_result("widget")
    assert result is not None and result.artifact_ref is not None
    return result.artifact_ref


class InspectArgs(TypedDict):
    views: list[str]
    width: int
    height: int
    artifact_ref: NotRequired[str]
    focus: NotRequired[str]


@contextmanager
def render_project(tmp_path: Path) -> Generator[SyntheticProject, None, None]:
    layout = make_project(tmp_path)
    backend, renderer = ImageBackend(), SyntheticRenderer()
    out = tmp_path / "out"
    write_artifacts(out)
    record = result_record()
    record["geometries"] = [{"label": "cube", "solids": 1}]
    built = assemble_build(
        BuildRequest("widget", DEFAULT_SCRIPT),
        record,
        out_dir=out,
        execution_identity=backend.value,
    )
    with open_store(layout) as store:
        assert (
            Publisher(layout, store, backend=backend).publish_build(built, op_id="render-test").kind
            == "current"
        )
        yield SyntheticProject(layout, store, renderer=renderer, backend=backend)


@pytest.fixture
def project(tmp_path: Path) -> Iterator[SyntheticProject]:
    with render_project(tmp_path) as value:
        yield value


def run_native_free_case(tmp_path: Path, case: str, *args: str | None) -> None:
    """Execute the actual synthetic operation in a fresh import-guarded process.

    30 seconds is a hang detector, not a CAD performance threshold. These cases
    own only their temporary store; they launch no worker, daemon or provider.
    """
    root = Path(__file__).resolve().parents[2]
    program = """
import importlib.abc
import json
import sys
from pathlib import Path

forbidden = {'build123d', 'OCP', 'numpy', 'pyrender', 'OpenGL'}
def require_clean():
    assert not forbidden.intersection(n.partition('.')[0] for n in sys.modules)
require_clean()
attempts = []
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition('.')[0] in forbidden:
            attempts.append(fullname)
            raise AssertionError('forbidden host import: ' + fullname)
sys.meta_path.insert(0, Guard())
import test_render_remote as cases
with cases.render_project(Path.cwd()) as project:
    getattr(cases, sys.argv[1])(project, *json.loads(sys.argv[2]))
require_clean()
assert not attempts, attempts
"""
    paths = [
        root / p for p in ("core/tests", "core/src", "opstore/src", "server/src", "contract/src")
    ]
    completed = subprocess.run(
        [sys.executable, "-c", program, case, json.dumps(args)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(map(str, paths)),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "channel,mode,section",
    [
        ("rgb", "solid", None),
        ("mask", "solid", None),
        ("mask", "selection", None),
        ("section", "solid", "+Z@0"),
    ],
)
def test_inspection_routes_without_host_cad(
    tmp_path: Path, channel: Channel, mode: MaskMode, section: str | None
) -> None:
    run_native_free_case(tmp_path, "inspection_routes_without_host_cad", channel, mode, section)


def inspection_routes_without_host_cad(
    project: SyntheticProject, channel: Channel, mode: MaskMode, section: str | None
) -> None:
    result = inspect_part(
        project,
        "widget",
        views=["iso"],
        channel=channel,
        mask_mode=mode,
        section_plane=section,
        width=16,
        height=16,
    )
    assert result.images and result.images[0].png.startswith(b"\x89PNG")
    assert project.renderer.operations == ["selection" if mode == "selection" else channel]
    if mode == "selection":
        assert result.selection_bundles is not None
        resolved = resolve_selection(
            project.store,
            result.selection_bundles[0].bundle_ref,
            expected_source_artifact_ref=result.source_artifact_ref,
        )
        assert len(resolved.entries) == 3
    assert not {"build123d", "OCP", "numpy", "pyrender", "OpenGL"}.intersection(sys.modules)


def test_fresh_glb_uses_mint_bundle_and_rechecks_all_links(project: SyntheticProject) -> None:
    source = current_source(project)
    glb = publish_gltf_for_build(project, source, width=16, height=16)
    assert glb.minted and glb.mesh_count == 1
    assert project.renderer.operations == ["selection", "gltf"]
    assert publish_gltf_for_build(project, source, width=16, height=16).minted is False
    bundle = json.loads(project.store.blobs.get(blob_hash_of_ref(glb.bundle_ref)))
    assert bundle["provenance"]["renderer_identity"] != bundle["provenance"]["executor_identity"]
    with pytest.raises(StaleSelectionError):
        resolve_selection(
            project.store,
            glb.bundle_ref,
            expected_source_artifact_ref="artifact:build:sha256:" + "0" * 64,
        )
    project.store.gc.unlink(glb.blob_hash, blob_hash_of_ref(glb.bundle_ref))
    assert resolve_published_gltf(project.store, source) is None


@pytest.mark.parametrize(
    "fault", ["source", "executor", "dimensions", "unsupported", "bad_response"]
)
def test_integration_refuses_before_publication(project: SyntheticProject, fault: str) -> None:
    kwargs: InspectArgs = {"views": ["iso"], "width": 16, "height": 16}
    if fault == "source":
        kwargs["artifact_ref"] = "artifact:build:sha256:" + "0" * 64
    elif fault == "executor":
        project.backend.value = identity(image_id="sha256:" + "b" * 64)
    elif fault == "dimensions":
        kwargs["width"] = 513
    elif fault == "unsupported":
        kwargs["focus"] = "cube"
    else:

        def corrupt(r: Response) -> None:
            r["source_ref"] = "wrong"

        project.renderer.corrupt = corrupt
    before = set(project.store.gc.links())
    with pytest.raises((ValueError, ValidationError)):
        inspect_part(project, "widget", **kwargs)
    assert set(project.store.gc.links()) == before


@pytest.mark.parametrize(
    "fault",
    [
        "mesh_count",
        "face_id",
        "solid_id",
        "table",
        "source",
        "bundle",
        "uri",
        "texture",
        "accessor",
        "index",
        "transform",
        "nan",
        "trailing",
        "bool_node",
        "bool_face",
        "float_component",
        "label",
    ],
)
def test_strict_glb_gate(fault: str) -> None:
    from test_render_oci import request

    entries = response(request())["entries"]
    data = synthetic_glb("source", "bundle", "table")

    def validate(data: bytes) -> Mapping[str, object]:
        return validate_linked_glb(
            data,
            source_ref="source",
            bundle_ref="bundle",
            selection_table_ref="table",
            entries=entries,
        )

    assert validate(data)["mesh_count"] == 1
    doc, binary = parse_glb(data)
    if fault == "mesh_count":
        doc["meshes"] *= 2
    elif fault in ("face_id", "solid_id"):
        extra = (
            doc["meshes"][0]["primitives"][0]["extras"]
            if fault == "face_id"
            else doc["meshes"][0]["extras"]
        )
        extra["selection_id"] = 3
    elif fault in ("table", "source", "bundle"):
        key = {
            "table": "selection_table_ref",
            "source": "source_artifact_ref",
            "bundle": "selection_bundle_ref",
        }[fault]
        doc["asset"]["extras"][key] = "wrong"
    elif fault == "uri":
        doc["buffers"][0]["uri"] = "https://invalid.example/not-fetched"
    elif fault == "texture":
        doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    elif fault == "accessor":
        doc["accessors"][0]["count"] = -1
    elif fault == "index":
        binary = binary[:-4] + struct.pack("<I", 100)
    elif fault == "nan":
        binary = struct.pack("<f", float("nan")) + binary[4:]
    elif fault == "transform":
        doc["nodes"][0]["translation"] = [1, 0, 0]
    elif fault == "bool_node":
        doc["nodes"][0]["mesh"] = False
    elif fault == "bool_face":
        doc["meshes"][0]["primitives"][0]["extras"]["face_index"] = False
    elif fault == "float_component":
        doc["accessors"][0]["componentType"] = 5126.0
    elif fault == "label":
        doc["meshes"][0]["extras"]["label"] = "wrong"
    data = pack(doc, binary) + (b"extra" if fault == "trailing" else b"")
    with pytest.raises(ValueError):
        validate(data)


def test_native_free_imports() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from hephaestus.core.render.inspect import inspect_part; "
            "from hephaestus.core.render.gltf_publish import publish_gltf_for_build; "
            "assert not {'numpy','build123d','OCP','pyrender','OpenGL'}.intersection(sys.modules)",
        ],
        check=True,
        timeout=15,
    )


def test_capacity_admission_retains_cleanup_reserve(tmp_path: Path) -> None:
    with OwnershipJournal(tmp_path / "journal", {}) as journal:
        # Synthetic reaped client evidence, no process was launched by this test.
        for i in range(193):
            journal.client(10000 + i, reaped=True)
        before = copy.deepcopy(journal.state)
        with pytest.raises(SandboxDeniedError, match="capacity"):
            journal.admit_operation()
        assert journal.state == before and not journal.pending
        assert len(journal.state["clients"]) == 193


def test_corrupt_glb_not_installed(project: SyntheticProject) -> None:
    import base64

    def corrupt(result: Response) -> None:
        if result["glb"] is not None:
            doc, binary = parse_glb(base64.b64decode(result["glb"]["data"]))
            doc["asset"]["extras"]["selection_table_ref"] = "wrong"
            raw = pack(doc, binary)
            result["glb"] = {
                "data": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }

    project.renderer.corrupt = corrupt
    source = current_source(project)
    with pytest.raises(ValueError, match="references"):
        publish_gltf_for_build(project, source, width=16, height=16)
    assert resolve_published_gltf(project.store, source) is None
    assert (
        project.store.db.conn.execute(
            "SELECT COUNT(*) FROM tp_artifact_kinds WHERE kind='gltf'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("fault", ["result", "live-drift"])
def test_render_service_identity_mismatch_refuses_before_publication(
    project: SyntheticProject, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    original = SyntheticRenderer.render
    other = identity(image_id="sha256:" + "b" * 64)

    def render(self: SyntheticRenderer, request: RenderRequest, brep: bytes) -> RenderResult:
        result = original(self, request, brep)
        if fault == "live-drift":
            self.value = other
            return result
        return RenderResult(result.data, other)

    monkeypatch.setattr(SyntheticRenderer, "render", render)
    before = set(project.store.gc.links())
    with pytest.raises(ValidationError, match="renderer identity"):
        inspect_part(project, "widget", views=["iso"], width=16, height=16)
    assert set(project.store.gc.links()) == before


def test_glb_export_refuses_a_bundle_from_another_renderer(project: SyntheticProject) -> None:
    from hephaestus.core.render.inspect import resolve_render_source
    from hephaestus.core.render.remote_service import export_remote, selection_bundle

    source = resolve_render_source(project, "widget", last_good=False, artifact_ref=None)
    bundle, _, _ = selection_bundle(project, source, "iso", 16, 16)
    project.renderer.value = identity(image_id="sha256:" + "b" * 64)
    before = set(project.store.gc.links())
    with pytest.raises(ValidationError, match="bundle provenance"):
        export_remote(project, source, bundle, "iso", 16, 16)
    assert set(project.store.gc.links()) == before
    assert resolve_published_gltf(project.store, source.source_artifact_ref) is None


def test_render_identity_change_cannot_reuse_old_bundle(project: SyntheticProject) -> None:
    source = current_source(project)
    first = publish_gltf_for_build(project, source, width=16, height=16)
    project.renderer.value = identity(image_id="sha256:" + "b" * 64)
    second = publish_gltf_for_build(project, source, width=16, height=16)
    assert second.minted and second.bundle_ref != first.bundle_ref and second.ref != first.ref
    from hephaestus.agent_bridge.cad_ops._geometry import GeometryOps

    cad = GeometryOps(
        project.layout, project.store, backend=project.backend, renderer=project.renderer
    )
    for published in (first, second):
        assert cad.linked_gltf(published.ref).data == published.data
    operations = list(project.renderer.operations)
    for _ in range(3):
        cached = publish_gltf_for_build(project, source, width=16, height=16)
        assert not cached.minted and cached.ref == second.ref
    assert project.renderer.operations == operations


def test_renderer_busy_and_operation_bound_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    from pathlib import Path

    from hephaestus.core.executor.sandbox.oci import OciIdentity, OciRuntime
    from hephaestus.core.executor.sandbox.oci_supervisor import SupervisorConfig
    from hephaestus.core.render.oci_backend import OciRenderer
    from test_render_oci import request

    config = SupervisorConfig(
        OciRuntime(
            "docker",
            Path("/nonexistent/never-executed"),
            ("--context", "desktop-linux"),
            "unix:///synthetic.sock",
            "Docker Desktop",
        ),
        "example.invalid/render@sha256:" + "a" * 64,
        "linux/arm64",
        tmp_path / "renderer",
        OciIdentity(os.getuid(), os.getgid()),
        runtime_profile="renderer",
    )
    renderer = OciRenderer(config)
    import threading

    busy = threading.Lock()
    monkeypatch.setattr(renderer, "_ready", True)  # admission test only; no launch allowed
    monkeypatch.setattr(renderer, "_busy", busy)
    busy.acquire()
    try:
        with pytest.raises(SandboxDeniedError, match="already active"):
            renderer.render(request(), b"fixture")
        with pytest.raises(SandboxDeniedError, match="already active"):
            renderer.probe()
    finally:
        busy.release()
    monkeypatch.setattr(renderer, "_operations", 16)
    req = request()
    req["brep_sha256"] = hashlib.sha256(b"fixture").hexdigest()
    req["source_ref"] = "artifact:build:sha256:" + req["brep_sha256"]
    with pytest.raises(SandboxDeniedError, match="operation limit"):
        renderer.render(req, b"fixture")
    renderer.close()
    assert not list(config.directory.glob("operation-*"))


def test_cadops_factory_and_linked_glb_reader_use_native_free_service(tmp_path: Path) -> None:
    run_native_free_case(tmp_path, "cadops_factory_and_linked_glb_reader_use_native_free_service")


def cadops_factory_and_linked_glb_reader_use_native_free_service(project: SyntheticProject) -> None:
    from hephaestus.agent_bridge.cad_ops._geometry import GeometryOps

    class RenderOps(GeometryOps):
        def render_project(self) -> RenderProject:
            return self._render_project()

    cad = RenderOps(
        project.layout, project.store, backend=project.backend, renderer=project.renderer
    )
    assert cad.render_project().renderer is project.renderer
    assert cad.render_project().backend is project.backend
    source = current_source(project)
    glb = publish_gltf_for_build(cad.render_project(), source, width=16, height=16)
    assert cad.linked_gltf(glb.ref).data == glb.data
    assert not {"numpy", "build123d", "OCP", "pyrender", "OpenGL"}.intersection(sys.modules)


def test_runtime_open_and_reload_retain_renderer_injection() -> None:
    # Structural regression only: full HTTP runtime requires the later native-
    # free workspace import slice; this does not claim server/browser acceptance.
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "server/src/hephaestus/http/runtime.py"
    tree = ast.parse(path.read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "CadOps"
    ]
    assert len(calls) == 2
    assert all({"backend", "renderer"} <= {k.arg for k in call.keywords} for call in calls)


@pytest.mark.parametrize("fault", [None, "create", "removal", "client", "launch", "owner", "reap"])
def test_renderer_rollover_requires_affirmative_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    import os
    from pathlib import Path

    from hephaestus.core.executor.sandbox.base import CapabilityReport, ExecOutcome, SandboxSpec
    from hephaestus.core.executor.sandbox.oci import OciIdentity, OciRuntime
    from hephaestus.core.executor.sandbox.oci_supervisor import (
        SupervisedOciBackend,
        SupervisorConfig,
    )
    from hephaestus.core.render import oci_backend
    from hephaestus.core.render.oci_backend import OciRenderer
    from test_render_oci import request

    calls: list[str] = []
    value = identity()

    class SyntheticSupervisor(SupervisedOciBackend):
        def probe(self) -> CapabilityReport:
            calls.append("probe")
            self._identity = value
            self._report = CapabilityReport("synthetic", True)
            return self._report

        def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
            calls.append("execute")
            return ExecOutcome(
                0,
                json.dumps(response(json.loads(stdin_payload))).encode(),
                b"",
                False,
                execution_identity=value,
            )

    monkeypatch.setattr(oci_backend, "SupervisedOciBackend", SyntheticSupervisor)
    config = SupervisorConfig(
        OciRuntime("docker", Path("/nonexistent/never-executed")),
        "example.invalid/render@sha256:" + "a" * 64,
        "linux/arm64",
        tmp_path / "renderer",
        OciIdentity(os.getuid(), os.getgid()),
        runtime_profile="renderer",
    )
    renderer = OciRenderer(config)
    renderer.probe()  # synthetic passing probe; real durable settlement code below
    if fault in {"create", "removal", "client", "launch"}:
        with OwnershipJournal(config.directory / "ownership", config.binding()) as journal:
            if fault in {"create", "removal"}:
                name = "heph-exec-" + "a" * 64
                journal.submitted(name)
                if fault == "removal":
                    journal.settled(name, "b" * 64)
            elif fault == "client":
                journal.client(12345, reaped=False)
            else:
                journal.launching_client()
    elif fault in {"owner", "reap"}:
        operation = config.directory / "operation-00"
        operation.mkdir()
        (operation / "owner.json").write_text(json.dumps({"pid": 12345}))
        if fault == "reap":
            (operation / "owner-final.json").write_text(
                json.dumps({"pid": 12345, "commands_finished": True})
            )
    before = {p: p.read_bytes() for p in config.directory.rglob("*.json")}
    req = request()
    req["brep_sha256"] = hashlib.sha256(b"fixture").hexdigest()
    req["source_ref"] = "artifact:build:sha256:" + req["brep_sha256"]
    try:
        if fault:
            with pytest.raises(SandboxDeniedError):
                renderer.render(req, b"fixture")
            with pytest.raises(SandboxDeniedError, match="poisoned"):
                renderer.probe()
            assert calls == ["probe", "execute"]
            assert not (config.directory / "render-01").exists()
            assert before == {p: p.read_bytes() for p in config.directory.rglob("*.json")}
        else:
            renderer.render(req, b"fixture")
            assert calls == ["probe", "execute", "probe", "execute"]
            assert renderer.supervisor.config.directory == config.directory / "render-01"
    finally:
        renderer.close()


@pytest.mark.parametrize("large", ["bytes", "id"])
def test_native_glb_publication_readback_above_experimental_limits(
    project: SyntheticProject, monkeypatch: pytest.MonkeyPatch, large: str
) -> None:
    import hephaestus.core.render.gltf_publish as publication
    from hephaestus.agent_bridge.cad_ops._geometry import GeometryOps
    from hephaestus.core.render.bundle import RenderStore, SelectionBundle
    from hephaestus.core.render.palette import SelectionEntry
    from test_render_oci import request

    source = current_source(project)
    entries = copy.deepcopy(response(request())["entries"])
    if large == "id":
        entries["2049"] = entries.pop("2")
    table = {int(k): SelectionEntry(**v) for k, v in entries.items()}
    # Native v1 publication uses native bundle linkage, not OCI provenance.
    from hephaestus.core.render.remote_service import png

    image = png(
        {"channels": 3, "pixels": "AAAC", "sha256": hashlib.sha256(b"\x00\x00\x02").hexdigest()},
        1,
        1,
    )
    bundle = RenderStore(project.store).publish_selection_bundle(
        view="iso",
        source_artifact_ref=source,
        solid_png=image,
        face_png=image,
        edge_png=image,
        entries=table,
    )
    doc, binary = parse_glb(synthetic_glb(source, bundle.bundle_ref, bundle.selection_table_ref))
    if large == "bytes":
        binary += b"\0" * (4 * 1024**2)
        doc["buffers"][0]["byteLength"] = len(binary)
    else:
        doc["meshes"][0]["primitives"][0]["extras"]["selection_id"] = 2049
    data = pack(doc, binary)
    with pytest.raises(ValueError):
        validate_linked_glb(
            data,
            source_ref=source,
            bundle_ref=bundle.bundle_ref,
            selection_table_ref=bundle.selection_table_ref,
            entries=entries,
            experimental=True,
        )

    # Stub only native CAD/raster production for this host-only linkage regression.
    # Publication, artifact kinds, links and readback below are the actual service.
    def shape(_: object) -> object:
        return object()

    def tessellation(_: object) -> SimpleNamespace:
        return SimpleNamespace(solids=[0])

    def mint(*a: object, **kw: object) -> SelectionBundle:
        return bundle

    def unused(*a: object, **kw: object) -> None:
        return None

    def export(*a: object, **kw: object) -> bytes:
        return data

    monkeypatch.setattr(publication, "load_brep_shape", shape)
    monkeypatch.setattr(publication, "scene_tessellation", tessellation)
    monkeypatch.setattr(publication, "_mint_bundle", mint)
    monkeypatch.setitem(
        sys.modules,
        "hephaestus.core.render.channels",
        SimpleNamespace(scene_from_shape=unused),
    )
    monkeypatch.setitem(
        sys.modules,
        "hephaestus.core.render.selection",
        SimpleNamespace(build_selection_catalog=unused),
    )
    monkeypatch.setitem(
        sys.modules,
        "hephaestus.core.render.gltf",
        SimpleNamespace(export_gltf=export, validate_gltf=unused),
    )
    native = RenderProject(project.layout, project.store, backend=project.backend)
    published = publish_gltf_for_build(native, source)
    assert published.minted and published.data == data
    cad = GeometryOps(project.layout, project.store, backend=project.backend)
    assert cad.linked_gltf(published.ref).data == data
    assert not publish_gltf_for_build(native, source).minted


def test_fixture_glb_missing_one_valid_primitive_refuses() -> None:
    from hephaestus.core.render.palette import SelectionEntry

    doc, binary = parse_glb(synthetic_glb("source", "bundle", "table"))
    doc["meshes"].append(copy.deepcopy(doc["meshes"][0]))
    entries: dict[int, SelectionEntry] = {}
    for solid, mesh in enumerate(doc["meshes"]):
        sid = solid * 7 + 1
        mesh["extras"].update(selection_id=sid, solid_index=solid)
        entries[sid] = SelectionEntry(
            kind="solid", solid_index=solid, topology_index=solid, label="cube"
        )
        primitive = mesh["primitives"][0]
        mesh["primitives"] = []
        for face in range(6):
            fid = sid + face + 1
            p = copy.deepcopy(primitive)
            p["extras"].update(selection_id=fid, solid_index=solid, face_index=face)
            mesh["primitives"].append(p)
            entries[fid] = SelectionEntry(kind="face", solid_index=solid, topology_index=face)
    doc["nodes"] = [{"mesh": 0}, {"mesh": 1}]
    doc["scenes"] = [{"nodes": [0, 1]}]

    def validate(data: bytes):
        return validate_linked_glb(
            data,
            source_ref="source",
            bundle_ref="bundle",
            selection_table_ref="table",
            entries={str(k): v.to_json() for k, v in entries.items()},
        )

    require_fixture_faces(validate(pack(doc, binary)), entries)
    doc["meshes"][1]["primitives"].pop()
    validation = validate(pack(doc, binary))
    assert validation["mesh_count"] == 2 and validation["primitive_count"] == 11
    with pytest.raises(RuntimeError, match="12 primitives"):
        require_fixture_faces(validation, entries)
