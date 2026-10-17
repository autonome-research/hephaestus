"""Synthetic stored build and RGB worker output, never CAD/render acceptance.

The server Plan test needs real host publication without a host CAD dependency.
The executor refuses every execution; only preconstructed test bytes are stored.
"""

import base64
import hashlib
import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Never

from hephaestus.core.executor.identity import ExecutionIdentity
from hephaestus.core.executor.runner import BuildRequest, assemble_build
from hephaestus.core.executor.sandbox.base import CapabilityReport, SandboxSpec
from hephaestus.core.project_store.layout import load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.render.inspect import RenderProject
from hephaestus.core.render.oci_backend import RenderResult
from hephaestus.core.render.oci_protocol import RenderRequest, Response, request_hash


def identity() -> ExecutionIdentity:
    return ExecutionIdentity.for_oci(
        image_ref="registry.example/synthetic@sha256:" + "a" * 64,
        image_id="sha256:" + "b" * 64,
        platform="linux/arm64",
        runtime={
            "version": 1,
            "python": "3.13.7",
            "packages": {
                name: {"version": version, "metadata_sha256": "sha256:" + "d" * 64}
                for name, version in (
                    ("hephaestus-executor-runtime", "0.1.0"),
                    ("opstore", "0.1.0"),
                    ("build123d", "0.11.1"),
                    ("cadquery-ocp-novtk", "7.9.3.1.1"),
                )
            },
            "source_trees": {
                "hephaestus-executor-runtime": "sha256:" + "a" * 64,
                "opstore": "sha256:" + "b" * 64,
            },
        },
    )


class RefusingExecutor:
    name = "synthetic-no-execution"

    def execution_identity(self) -> ExecutionIdentity:
        return identity()

    def probe(self) -> CapabilityReport:
        return CapabilityReport(self.name, False)

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> Never:
        raise AssertionError("Plan must not execute modeling work")


class SyntheticRenderer:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def execution_identity(self) -> ExecutionIdentity:
        return identity()

    def render(self, request: RenderRequest, brep: bytes) -> RenderResult:
        assert request["operation"] == "rgb"
        assert hashlib.sha256(brep).hexdigest() == request["brep_sha256"]
        self.operations.append(request["operation"])
        pixels = bytes([0, 0, 1, 255]) * request["width"] * request["height"]
        result: Response = {
            "version": 2,
            "operation": "rgb",
            "request_sha256": request_hash(request),
            "source_ref": request["source_ref"],
            "gl_renderer": "llvmpipe (synthetic schema fixture, not evidence)",
            "topology": [{"faces": 1, "edges": 1}],
            "entries": {},
            "glb": None,
            "section": None,
            "images": {
                "rgb": {
                    "channels": 4,
                    "pixels": base64.b64encode(pixels).decode(),
                    "sha256": hashlib.sha256(pixels).hexdigest(),
                }
            },
        }
        return RenderResult(json.dumps(result).encode(), identity())


@contextmanager
def render_project(
    root: Path,
) -> Generator[tuple[RenderProject, RefusingExecutor, SyntheticRenderer], None, None]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir()
    script = "part.geometry = None  # synthetic stored fixture\n"
    (root / "parts/widget.py").write_text(script)
    (root / "globals.py").write_text("PARAMS = {}\n")
    (root / "hephaestus.toml").write_text('name = "plan-fixture"\nunits = "mm"\n')
    layout = load_project(root)
    out = root / "out"
    out.mkdir()
    (out / "final.brep").write_bytes(b"synthetic geometry, not kernel evidence")
    (out / "source_map.json").write_text("{}")
    built = assemble_build(
        BuildRequest("widget", script),
        {
            "status": "ok",
            "artifacts": {"build": "final.brep", "source_map": "source_map.json"},
            "source_map": {},
            "params_declaration": {},
            "error": None,
            "metadata": {},
            "geometries": [{"label": "cube", "solids": 1}],
        },
        out_dir=out,
        execution_identity=identity(),
    )
    backend, renderer = RefusingExecutor(), SyntheticRenderer()
    with open_store(layout) as store:
        assert (
            Publisher(layout, store, backend=backend).publish_build(built, op_id="fixture").kind
            == "current"
        )
        yield RenderProject(layout, store, backend=backend, renderer=renderer), backend, renderer


def current_source(project: RenderProject) -> str:
    result = project.publisher().current_result("widget")
    assert result is not None and result.artifact_ref is not None
    return result.artifact_ref
