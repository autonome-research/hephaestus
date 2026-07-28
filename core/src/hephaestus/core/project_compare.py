"""Project-level solid comparison: resolve two operands, then measure them.

``COMPARE.md`` §2. :mod:`hephaestus.geom.compare` compares two shapes a caller
already holds and knows nothing about projects; this module is the other half —
*which* two shapes, and on what evidence. It is deliberately in core rather than
in the agent bridge because both consumers need it and neither may depend on the
other: the ``compare_solids`` tool (server) and ``heph diff`` (CLI) resolve
operands identically, so a number the operator sees and a number the model sees
are the same number.

Resolution rules, both borrowed rather than invented:

* a part is its **current successful build artifact** — the same "never a live
  build" rule ``measure`` follows, so what is compared is exactly what a ref
  names;
* an ``import:<relpath>`` target rides the Stage 8A machinery (``INGEST.md`` §1)
  unchanged: the same ``openat2``-class confinement walk, the same content hash,
  which the result carries so the comparison is re-runnable against provably the
  same bytes.

Facts only, exactly as in geom: no threshold is applied here and no verdict is
returned. Reading "iou 0.994" as a failure is a claim, and claims belong to a
``CHECKS`` predicate or a bench task policy that names its tolerance.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "ALIGN_MODES",
    "IMPORT_TARGET_PREFIX",
    "PART_TARGET_PREFIX",
    "CompareOperand",
    "CompareRefusal",
    "CompareRefusalReason",
    "ProjectComparer",
    "SolidComparison",
]

#: ``COMPARE.md`` §1 alignment modes.
ALIGN_MODES: tuple[str, ...] = ("as_posed", "principal")

#: Target naming another part of this project.
PART_TARGET_PREFIX = "part:"

#: Target naming a file beneath ``imports/``.
IMPORT_TARGET_PREFIX = "import:"

CompareRefusalReason = Literal[
    "invalid_align",
    "invalid_target",
    "missing_artifact",
    "no_solid_geometry",
    "unreadable_step",
]


class CompareRefusal(ValidationError):
    """A comparison could not be set up or computed; ``reason`` is stable.

    Import-path refusals are NOT remapped into this type: they keep their
    :class:`~hephaestus.core.executor.imports.ImportResolutionError` identity and
    its own reason vocabulary, because "the file is missing" and "that path
    leaves the project" are different facts that INGEST.md §1 already names.
    """

    def __init__(self, message: str, *, reason: CompareRefusalReason) -> None:
        super().__init__(message, kind="contract")
        self.reason: CompareRefusalReason = reason


@dataclass(frozen=True)
class CompareOperand:
    """What one side of a comparison was, and how it is attributed.

    A part side carries the artifact ref it was read from; an import side
    carries the content hash of the bytes it was parsed from. Either way the
    comparison names its evidence, which is the whole difference between a
    measurement and an assertion.
    """

    kind: Literal["part", "import"]
    name: str | None = None
    path: str | None = None
    artifact_ref: str | None = None
    sha256: str | None = None
    snapshot_ref: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {"kind": self.kind}
        for key, value in (
            ("name", self.name),
            ("path", self.path),
            ("artifact_ref", self.artifact_ref),
            ("sha256", self.sha256),
            ("snapshot_ref", self.snapshot_ref),
        ):
            if value is not None:
                out[key] = value
        return out

    @property
    def ref(self) -> str | None:
        """The immutable ref this operand was read from, if it has one."""
        return self.artifact_ref if self.kind == "part" else self.snapshot_ref


@dataclass(frozen=True)
class SolidComparison:
    """One ``solid_diff`` plus the provenance of both operands."""

    align: str
    a: CompareOperand
    b: CompareOperand
    #: ``dataclasses.asdict(SolidDiff)`` — the geom record's own shape, never a
    #: re-derived one, so the wire form cannot drift from ``COMPARE.md`` §1.
    diff: dict[str, JSONValue]

    @property
    def resolved_refs(self) -> list[str]:
        return [ref for ref in (self.a.ref, self.b.ref) if ref is not None]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": "ok",
            "align": self.align,
            "a": self.a.to_json(),
            "b": self.b.to_json(),
            "diff": dict(self.diff),
            "resolved_artifact_refs": cast("JSONValue", list(self.resolved_refs)),
        }


class ProjectComparer:
    """Compares one project's parts against parts and ``imports/`` files."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        self._layout = layout
        self._store = store
        self._publisher = Publisher(layout, store)

    def compare(
        self, part: str, target: str, *, align: str = "as_posed", scratch: Path | None = None
    ) -> SolidComparison:
        """Compare ``part``'s current build against ``target`` (COMPARE.md §2)."""
        if align not in ALIGN_MODES:
            raise CompareRefusal(
                f"align must be one of {', '.join(ALIGN_MODES)}, got {align!r}",
                reason="invalid_align",
            )
        a_shape, a_operand = self.part_operand(part, scratch)
        b_shape, b_operand = self.target_operand(target, scratch)
        return SolidComparison(
            align=align,
            a=a_operand,
            b=b_operand,
            diff=self.solid_diff(a_shape, b_shape, align=align),
        )

    # -- operands -----------------------------------------------------------

    def part_operand(self, name: str, scratch: Path | None) -> tuple[object, CompareOperand]:
        """One part's current successful build artifact, as a shape plus its ref."""
        from hephaestus.core.executor.artifact_geometry import load_brep_shape

        result = self._publisher.current_result(name)
        if result is None or result.artifact_ref is None:
            raise AddressingError(
                f"part {name!r} has no current successful build to compare",
                selector=name,
                candidates=self._layout.part_names(),
            )
        blob = blob_hash_of_ref(result.artifact_ref)
        if not self._store.blobs.has(blob):
            raise CompareRefusal(
                f"artifact {result.artifact_ref} is not durably stored",
                reason="missing_artifact",
            )
        shape = load_brep_shape(self._store.blobs.get(blob), scratch_dir=scratch)
        return shape, CompareOperand(kind="part", name=name, artifact_ref=result.artifact_ref)

    def target_operand(self, target: str, scratch: Path | None) -> tuple[object, CompareOperand]:
        """Resolve a ``part:``/``import:`` target to a shape and its attribution."""
        if target.startswith(PART_TARGET_PREFIX):
            name = target[len(PART_TARGET_PREFIX) :]
            if not name:
                raise CompareRefusal(f"target {target!r} names no part", reason="invalid_target")
            return self.part_operand(name, scratch)
        if target.startswith(IMPORT_TARGET_PREFIX):
            path = target[len(IMPORT_TARGET_PREFIX) :]
            if not path:
                raise CompareRefusal(
                    f"target {target!r} names no imports/ file", reason="invalid_target"
                )
            return self.import_operand(path)
        raise CompareRefusal(
            f"target {target!r} must be {PART_TARGET_PREFIX!r}<part> or "
            f"{IMPORT_TARGET_PREFIX!r}<path under imports/> (COMPARE.md §2)",
            reason="invalid_target",
        )

    def import_operand(self, path: str) -> tuple[object, CompareOperand]:
        """One ``imports/`` file as a shape, attributed to its content hash."""
        from hephaestus.geom.step_io import StepReadError, read_step_bytes

        # Raises ImportResolutionError with its own reason for a missing file,
        # a traversal, or a symlink escape — the Stage 8A walk, unchanged.
        snapshot = self._publisher.parts.read_import(path)
        try:
            shape = read_step_bytes(snapshot.data, source=path)
        except StepReadError as exc:
            raise CompareRefusal(
                f"import {path!r} is not a readable STEP part: {exc.message}",
                reason="unreadable_step",
            ) from exc
        return shape, CompareOperand(
            kind="import",
            path=path,
            sha256=snapshot.content_hash,
            snapshot_ref=snapshot.snapshot_ref,
        )

    # -- the measurement ----------------------------------------------------

    @staticmethod
    def solid_diff(a: object, b: object, *, align: str) -> dict[str, JSONValue]:
        """``geom.solid_diff`` as JSON, with its one documented refusal named.

        ``align="principal"`` needs an inertia frame, which a shape enclosing no
        volume does not have — geom raises rather than inventing one
        (``COMPARE.md`` §1). Letting that escape as a bare ``ValueError`` would
        reach a caller as an internal error instead of a fact about the geometry
        it asked about.
        """
        from hephaestus.geom.compare import AlignMode, solid_diff

        try:
            record = solid_diff(cast("Any", a), cast("Any", b), align=cast("AlignMode", align))
        except ValueError as exc:
            raise CompareRefusal(
                f"align={align!r} needs both shapes to enclose volume: {exc}",
                reason="no_solid_geometry",
            ) from exc
        return cast("dict[str, JSONValue]", dataclasses.asdict(record))
