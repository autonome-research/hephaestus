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
import multiprocessing
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from hephaestus.core.checks.facade import KernelOps, default_kernel_ops
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from opstore.types import JSONValue

from opstore import OpStore

__all__ = [
    "ALIGN_MODES",
    "COMPARE_TIMEOUT_ENV",
    "COMPARE_TIMEOUT_S",
    "IMPORT_TARGET_PREFIX",
    "LOST_SURFACE",
    "LOST_TOPOLOGY",
    "LOST_VOLUME",
    "PART_TARGET_PREFIX",
    "SCAN_TARGET_PREFIX",
    "CompareOperand",
    "CompareRefusal",
    "CompareRefusalReason",
    "CompareTimeout",
    "ProjectComparer",
    "SolidComparison",
    "bounded_kernel_ops",
    "bounded_solid_diff",
    "compare_timeout_s",
]

#: ``COMPARE.md`` §1 alignment modes.
ALIGN_MODES: tuple[str, ...] = ("as_posed", "principal")

#: Target naming another part of this project.
PART_TARGET_PREFIX = "part:"

#: Target naming a file beneath ``imports/``.
IMPORT_TARGET_PREFIX = "import:"

#: Target naming a SCAN beneath ``imports/`` (``MESH_INGEST.md`` §6.5). Named
#: here only so this tool can refuse it by name: ``compare_solids`` does not
#: measure scans and this module does not learn how.
SCAN_TARGET_PREFIX = "scan:"

#: Wall-clock ceiling for ONE ``SolidDiff`` computation, process-killed with no
#: retry (``COMPARE.md`` §5). Comparison on pathological B-reps is unbounded in
#: the kernel — one CADGenBench editing sample held a core for ~19 h, and five
#: of six live-run infrastructure deaths in the 2026-07-29 sweep ended on an
#: unanswered ``compare_solids`` — so every engine surface computes the diff in
#: a killable spawned subprocess under this ceiling (the ``bench`` local-floor
#: pattern). Env-overridable via :data:`COMPARE_TIMEOUT_ENV`.
COMPARE_TIMEOUT_S: Final[float] = 300.0

#: Environment override for :data:`COMPARE_TIMEOUT_S` (seconds, float).
COMPARE_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_COMPARE_TIMEOUT_S"

#: The parts of a ``SolidDiff`` a ceiling kill can lose, by cost order: the
#: cheap first look (census + bboxes + volumes), the boolean half, and the
#: surface-sampling half. ``CompareTimeout.lost`` names exactly which were cut.
LOST_TOPOLOGY: Final[str] = "topology_census"
LOST_VOLUME: Final[str] = "volume_boolean"
LOST_SURFACE: Final[str] = "surface_sampling"


def compare_timeout_s() -> float:
    """The effective diff ceiling: :data:`COMPARE_TIMEOUT_ENV` else the default."""
    raw = os.environ.get(COMPARE_TIMEOUT_ENV)
    if raw is None:
        return COMPARE_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return COMPARE_TIMEOUT_S


CompareRefusalReason = Literal[
    "compare_timeout",
    "invalid_align",
    "invalid_target",
    "missing_artifact",
    "no_solid_geometry",
    "scan_target_unsupported",
    "unreadable_step",
]


#: The reasons in this vocabulary that belong to ``MESH_INGEST.md`` §10 rather
#: than to ``COMPARE.md``. Exactly one today, and it is listed rather than
#: hard-coded at its raise site so that a second §10 code arriving here has one
#: place to be added. Stage 8B's own six reasons are deliberately NOT in this
#: set: their message text is a pinned Stage 8B surface, and widening a later
#: stage's derivation over an earlier stage's contract is not this stage's to do
#: (the :class:`~hephaestus.core.executor.imports.ImportResolutionError`
#: precedent, which derives for the §1.7 reasons only).
MESH_INGEST_REFUSAL_REASONS: Final[frozenset[str]] = frozenset({"scan_target_unsupported"})


class CompareRefusal(ValidationError):
    """A comparison could not be set up or computed; ``reason`` is stable.

    Import-path refusals are NOT remapped into this type: they keep their
    :class:`~hephaestus.core.executor.imports.ImportResolutionError` identity and
    its own reason vocabulary, because "the file is missing" and "that path
    leaves the project" are different facts that INGEST.md §1 already names.

    For a :data:`MESH_INGEST_REFUSAL_REASONS` code the ``[code]`` suffix is
    derived here rather than written into the raise site's prose, on the
    ``MeshReadError`` rule: a message that names its own code can keep saying one
    thing while ``reason=`` says another, and every message-level assertion
    downstream stays green while the vocabulary drifts.
    """

    def __init__(self, message: str, *, reason: CompareRefusalReason) -> None:
        if reason in MESH_INGEST_REFUSAL_REASONS and f"[{reason}]" not in message:
            message = f"{message} [{reason}]"
        super().__init__(message, kind="contract")
        self.reason: CompareRefusalReason = reason


class CompareTimeout(CompareRefusal):
    """The diff subprocess hit the wall-clock ceiling or died (``COMPARE.md`` §5).

    Not an empty-handed refusal: ``partial`` CARRIES whatever facts the child
    streamed before the kill (topology census, both bboxes, both volumes — the
    cheap first look), and ``lost`` names exactly which halves of the record
    (:data:`LOST_VOLUME`, :data:`LOST_SURFACE`, and :data:`LOST_TOPOLOGY` when
    nothing arrived at all) were cut short. The caller gets signal it can act
    on — never a dead session, never a silently coarse number.
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_s: float,
        partial: dict[str, JSONValue] | None,
        lost: tuple[str, ...],
    ) -> None:
        super().__init__(message, reason="compare_timeout")
        self.timeout_s = timeout_s
        self.partial: dict[str, JSONValue] | None = partial
        self.lost: tuple[str, ...] = lost

    def to_json(self) -> dict[str, JSONValue]:
        """The refusal shape every surface carries (tool error data, CLI --json)."""
        return {
            "status": "compare_timeout",
            "reason": "compare_timeout",
            "message": self.message,
            "timeout_s": self.timeout_s,
            "partial": cast("JSONValue", self.partial),
            "lost": cast("JSONValue", list(self.lost)),
        }


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
            # COMPARE.md §5: the measurement runs in a killable subprocess under
            # the wall-clock ceiling; a completed diff is the same numbers the
            # direct geom call produces (the BRep hand-off is lossless).
            diff=bounded_solid_diff(a_shape, b_shape, align=align, scratch=scratch),
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
        if target.startswith(SCAN_TARGET_PREFIX):
            # MESH_INGEST.md §6.5: compare_solids is UNCHANGED, and this is what
            # "unchanged" costs — a scan target is refused here by name rather
            # than widening SolidDiff to carry fields it cannot fill. A SolidDiff
            # promises an ``iou`` and a topology census; against a triangle soup
            # the first needs a solid nobody should trust (§6.4) and the second
            # is 100% planar faces by construction (§2.2), so a record returning
            # them as zeros or as discretization noise is worse than a refusal.
            raise CompareRefusal(
                f"{target!r} is a scan, and compare_solids "
                "measures solids. A SolidDiff promises an iou and a topology census, "
                "and neither exists against a mesh. Use compare_to_scan (tool) or "
                "m.scan_diff (CHECKS), which return a ScanDistance that reports the "
                "two directions separately with their methods named "
                "(MESH_INGEST.md §6.4, §6.5)",
                reason="scan_target_unsupported",
            )
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


# --------------------------------------------------------------------------
# bounded execution (COMPARE.md §5)


def _diff_child(conn: Any, a_path: str, b_path: str, align: str) -> None:  # pragma: no cover
    """One ``SolidDiff``, computed where a kill cannot take the session down.

    Runs in a spawned subprocess. The cheap facts (topology census, bboxes,
    volumes) are computed and streamed FIRST — the boolean and surface halves
    below can be orders of magnitude more expensive, so a ceiling kill after
    the first send still leaves the caller holding the first look. Message
    protocol, in order: ``("cheap", facts)``, then exactly one of
    ``("full", asdict(SolidDiff))`` or ``("refusal", message)``.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.geom.compare import AlignMode, solid_diff, topology_diff
    from hephaestus.geom.metrics import bbox_mm, shape_volume

    a = cast("Any", load_brep_shape(Path(a_path).read_bytes()))
    b = cast("Any", load_brep_shape(Path(b_path).read_bytes()))
    cheap: dict[str, JSONValue] = {
        "topology": cast("JSONValue", dataclasses.asdict(topology_diff(a, b))),
        "a_bbox_mm": cast("JSONValue", bbox_mm(a)),
        "b_bbox_mm": cast("JSONValue", bbox_mm(b)),
        "a_volume_mm3": shape_volume(a),
        "b_volume_mm3": shape_volume(b),
    }
    conn.send(("cheap", cheap))
    try:
        record = solid_diff(a, b, align=cast("AlignMode", align))
    except ValueError as exc:
        conn.send(("refusal", str(exc)))
    else:
        conn.send(("full", dataclasses.asdict(record)))
    conn.close()


def bounded_solid_diff(
    a: object,
    b: object,
    *,
    align: str,
    timeout_s: float | None = None,
    scratch: Path | None = None,
) -> dict[str, JSONValue]:
    """``ProjectComparer.solid_diff`` under the wall-clock ceiling (COMPARE.md §5).

    Both shapes cross to a spawned child as BRep files (lossless, so a
    completed diff is bit-for-bit the direct geom call's record); the child
    streams the cheap facts first and the full record second, and the parent
    kills it at the deadline. A ceiling kill or a child death raises
    :class:`CompareTimeout` carrying whatever arrived; the one geom refusal
    (``no_solid_geometry``) keeps its identity across the process boundary.
    ``timeout_s`` defaults to :func:`compare_timeout_s`, resolved per call so
    the env override applies to long-lived engines too.
    """
    from hephaestus.core.executor.artifact_geometry import write_brep_shape

    if timeout_s is None:
        timeout_s = compare_timeout_s()
    with tempfile.TemporaryDirectory(prefix="heph-diff-", dir=scratch) as tmp:
        a_path = Path(tmp) / "a.brep"
        b_path = Path(tmp) / "b.brep"
        write_brep_shape(a, a_path)
        write_brep_shape(b, b_path)

        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_diff_child, args=(child, str(a_path), str(b_path), align))
        proc.start()
        child.close()

        cheap: dict[str, JSONValue] | None = None
        outcome: tuple[str, Any] | None = None
        died = False
        cut_short = f"did not finish within {timeout_s:g}s and was killed"
        deadline = time.monotonic() + timeout_s

        def _receive() -> bool:
            """Consume one message; True when it was terminal (full/refusal)."""
            nonlocal cheap, outcome
            kind, payload = parent.recv()
            if kind == "cheap":
                cheap = cast("dict[str, JSONValue]", payload)
                return False
            outcome = (str(kind), payload)
            return True

        try:
            while outcome is None and time.monotonic() < deadline:
                try:
                    if parent.poll(0.05):
                        _receive()
                    elif not proc.is_alive():
                        # Death, not a deadline — drain what it sent first, so a
                        # result that raced the exit is never misread as a crash.
                        while parent.poll(0.2) and not _receive():
                            pass
                        died = outcome is None
                        break
                except EOFError:
                    # The pipe closed before a terminal message: the child is
                    # crashing.  Give it a moment to finish dying so the
                    # refusal carries its real exit code (reading it before
                    # the reap yields None; killing it here would forge -9);
                    # a child that hangs instead meets the kill in `finally`.
                    proc.join(5.0)
                    died = True
                    break
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join()
            parent.close()
        if died:
            cut_short = f"subprocess died (exit code {proc.exitcode})"

    if outcome is not None:
        kind, payload = outcome
        if kind == "full":
            return cast("dict[str, JSONValue]", payload)
        raise CompareRefusal(
            f"align={align!r} needs both shapes to enclose volume: {payload}",
            reason="no_solid_geometry",
        )
    lost = ((LOST_TOPOLOGY,) if cheap is None else ()) + (LOST_VOLUME, LOST_SURFACE)
    raise CompareTimeout(
        f"solid diff {cut_short} (COMPARE.md §5, ceiling {timeout_s:g}s via "
        f"{COMPARE_TIMEOUT_ENV}); lost: {', '.join(lost)}",
        timeout_s=timeout_s,
        partial=cheap,
        lost=lost,
    )


class _BoundedKernelOps:
    """The production :class:`KernelOps` with ``diff`` under the §5 ceiling.

    Every other measurement delegates to :func:`default_kernel_ops` unchanged —
    only the diff can grind for hours on a pathological B-rep, so only the diff
    pays the subprocess round-trip. Engine-side check runs use this backend by
    default; the sandboxed build worker deliberately does NOT (its whole
    process already runs under RLIMIT_CPU and a parent wall-clock kill).
    """

    def __init__(self, timeout_s: float | None = None) -> None:
        self._inner = default_kernel_ops()
        self._timeout_s = timeout_s

    def interference(self, a: object, b: object) -> float:
        return self._inner.interference(a, b)

    def clearance(self, a: object, b: object) -> float:
        return self._inner.clearance(a, b)

    def distance(self, a: object, b: object) -> float:
        return self._inner.distance(a, b)

    def mass(self, shape: object, density: float) -> float:
        return self._inner.mass(shape, density)

    def bbox(self, shape: object) -> tuple[float, float, float]:
        return self._inner.bbox(shape)

    def volume(self, shape: object) -> float:
        return self._inner.volume(shape)

    def sealed(self, shape: object) -> bool:
        return self._inner.sealed(shape)

    def genus(self, shape: object) -> int:
        return self._inner.genus(shape)

    def diff(self, a: object, b: object, align: str) -> dict[str, JSONValue]:
        return bounded_solid_diff(a, b, align=align, timeout_s=self._timeout_s)


def bounded_kernel_ops(timeout_s: float | None = None) -> KernelOps:
    """:func:`default_kernel_ops` with ``diff`` bounded per ``COMPARE.md`` §5."""
    return _BoundedKernelOps(timeout_s)
