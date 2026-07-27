# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared helpers for the Gate G0B (Stage 0B) executor/contract test suite.

Pure build helpers over the public clean-room fixtures under
``corpus/public_fixtures/``. Two backends matter for the gate: the secure
bubblewrap sandbox (``secure_backend`` — required for the escape-denial
clauses, skipped when unprovable on the host) and the explicit
``--unsafe-local-executor`` plain-subprocess backend used for the
backend-agnostic logic clauses (failure shape, params, source map,
addressing, fingerprint, budgets). Both spawn the worker in a *separate*
process, so determinism assertions hold either way.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from hephaestus.core.addressing import GeometryIndex
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    ParamState,
    PartOutput,
    build_namespace,
)
from hephaestus.core.executor.runner import (
    BuildOrigin,
    BuildRequest,
    UnpublishedBuild,
    run_build,
)
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.probe import probe_bwrap
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.executor.splitter import (
    PART_FILENAME,
    compile_statement,
    parse_module,
    split_statements,
)
from hephaestus.core.executor.tags import TagRegistry
from hephaestus.geom import AnyShape, geometry_index

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"
FAILURE_FILLET = FIXTURES / "failure_fillet"
FINGERPRINT = FIXTURES / "fingerprint"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def secure_backend() -> ExecBackend | None:
    """A probed bubblewrap backend, or ``None`` when the sandbox is unprovable.

    Fail-closed: only a fully-passing containment probe returns a backend, so
    the escape-denial clauses run against a real sandbox and are skipped
    (never falsely green) where bwrap is absent.
    """
    from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

    report = probe_bwrap()
    if not report.available:
        return None
    return BwrapBackend()


def build(request: BuildRequest, backend: ExecBackend, out_dir: Path) -> UnpublishedBuild:
    return run_build(request, backend=backend, out_dir=out_dir)


def build_part(
    part: str,
    script_path: Path,
    out_dir: Path,
    backend: ExecBackend | None = None,
    *,
    globals_path: Path | None = None,
    part_overrides: dict[str, int | float | str] | None = None,
    project_overrides: dict[str, int | float | str] | None = None,
    origin: BuildOrigin = "local",
) -> UnpublishedBuild:
    """Build one part fixture through ``backend`` (unsafe by default)."""
    request = BuildRequest(
        part=part,
        script=read(script_path),
        globals_source=read(globals_path) if globals_path is not None else None,
        part_overrides=part_overrides or {},
        project_overrides=project_overrides or {},
        origin=origin,
    )
    return run_build(request, backend=backend or UnsafeLocalBackend(), out_dir=out_dir)


def build_source(
    part: str,
    script: str,
    out_dir: Path,
    backend: ExecBackend | None = None,
    *,
    globals_source: str | None = None,
) -> UnpublishedBuild:
    """Build a part from raw source text (for edited/synthetic scripts)."""
    request = BuildRequest(part=part, script=script, globals_source=globals_source)
    return run_build(request, backend=backend or UnsafeLocalBackend(), out_dir=out_dir)


class InProcessPart:
    """A part script executed in-process to recover real build123d solids.

    Only used by the measure-budget clause, which needs live geometry to time
    interference across every assembly pair; the sandbox/worker path returns
    JSON, not shapes.
    """

    def __init__(self, script: str, globals_source: str | None) -> None:
        from hephaestus.core.executor.globals_exec import execute_globals

        globals_result = execute_globals(globals_source)
        param_state = ParamState(scope="part", overrides={})
        self.part = PartOutput()
        self.tag_registry = TagRegistry()
        namespace = build_namespace(
            param_state=param_state,
            hc=globals_result.hc_namespace(),
            part=self.part,
            tag_registry=self.tag_registry,
            check_registry=CheckRegistry(),
        )
        module = parse_module(script, filename=PART_FILENAME)
        statements = split_statements(script, filename=PART_FILENAME)
        for statement, node in zip(statements, module.body, strict=True):
            self.tag_registry.set_statement(statement.index, statement.lineno)
            exec(compile_statement(node, filename=PART_FILENAME), namespace)
            if not param_state.published and "PARAMS" in namespace:
                param_state.publish(namespace)
        param_state.finalize()
        geometry = self.part.geometry_value
        assert geometry is not None
        self.shape = cast("AnyShape", geometry)

    def solids(self) -> list[AnyShape]:
        return list(self.shape.solids())

    def index(self) -> GeometryIndex:
        return geometry_index(self.shape, tags=self.tag_registry.names())
