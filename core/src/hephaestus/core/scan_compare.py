# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Project-level scan scoring: resolve a part and a scan, then measure the gap.

``MESH_INGEST.md`` §6/§7. :mod:`hephaestus.geom.compare`'s :func:`scan_distance`
measures two things a caller already holds and knows nothing about projects;
this module is the other half — *which* part, *which* scan, on what evidence,
and under whose ceiling. It sits beside :mod:`hephaestus.core.project_compare`
for the reason that one sits in core: the ``compare_to_scan`` tool, the
``m.scan_diff`` check facade and ``heph scan check`` must resolve the same two
operands and produce the same numbers, so a figure the operator sees and a
figure the model sees are the same figure.

Three things this module is deliberate about.

**The unit is a parameter, and it has to be.** ``compare_to_scan`` as
``MESH_INGEST.md`` §7.2 lists it takes ``(part, scan, align?,
declared_transform?)`` and no unit — but STL, PLY, OBJ, OFF and XYZ carry none
(§1.3), and a tool that read one of them without a declared unit would be
guessing a scale on the operator's behalf at exactly the size where the guess is
plausible and wrong. So ``units`` is a REQUIRED argument on every engine surface
here. This is the same defect §1.1's singular ``units`` had, one level up, and
it is resolved the same way: by carrying the declaration rather than inventing
a default.

**The ceiling carries partial facts.** ``COMPARE.md`` §5 reused, not reinvented:
the cheap facts (the §3 quality record, both bounding boxes, the counts) are
computed and streamed FIRST, then direction A, then direction B, so a kill at
the deadline still leaves the caller holding everything cheaper than the thing
that ran long — and :class:`ScanTimeout` names which directions were lost.

**Facts, never verdicts.** No threshold is applied here. "the wall clears the
scan by 1.5 mm at every sampled vertex" is a claim, and claims belong to a
``CHECKS`` predicate that names its tolerance (§11.3: a distance figure is not a
fit, and nothing here is a clinical claim).
"""

from __future__ import annotations

import multiprocessing
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from hephaestus.core.errors import AddressingError, ValidationError
from opstore.types import JSONValue

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore

__all__ = [
    "LOST_PART_TO_SCAN",
    "LOST_SCAN_FACTS",
    "LOST_SCAN_TO_PART",
    "PARTIAL_COMPLETED",
    "SCAN_OPERAND_REASONS",
    "SCAN_TARGET_PREFIX",
    "SCAN_TIMEOUT_ENV",
    "SCAN_TIMEOUT_S",
    "ProjectScanComparer",
    "ScanComparison",
    "ScanOperand",
    "ScanRefusal",
    "ScanRefusalReason",
    "ScanTimeout",
    "bounded_scan_distance",
    "scan_arrays",
    "scan_cheap_facts",
    "scan_timeout_s",
    "split_scan_target",
]

#: Prefix marking a comparison target as a scan under ``imports/`` (§6.5). It is
#: a THIRD prefix beside ``part:`` and ``import:`` rather than a widening of
#: ``import:``, because the record it produces is a different type: an
#: ``import:`` target promises a ``SolidDiff`` with an ``iou`` and a topology
#: census, and neither is available against a triangle soup.
SCAN_TARGET_PREFIX: Final[str] = "scan:"

#: Wall-clock ceiling for ONE scan comparison, process-killed with no retry
#: (§7.3, the ``COMPARE.md`` §5 pattern). Direction A is 0.05 ms/pt against a
#: smooth target — 200k scan points is ~10 s — and direction B's kd-tree half is
#: 0.45 µs/pt, so a comparison that runs past this is one whose part is
#: pathological rather than one that merely has a lot of points. Env-overridable
#: via :data:`SCAN_TIMEOUT_ENV` under the local-floor rule.
SCAN_TIMEOUT_S: Final[float] = 300.0
SCAN_TIMEOUT_ENV: Final[str] = "HEPHAESTUS_SCAN_TIMEOUT_S"

#: What a ceiling kill can lose, in cost order. The cheap facts first, then each
#: direction, so ``ScanTimeout.lost`` names exactly what never arrived.
LOST_SCAN_FACTS: Final[str] = "scan_facts"
LOST_SCAN_TO_PART: Final[str] = "scan_to_part"
LOST_PART_TO_SCAN: Final[str] = "part_to_scan"

#: Key under which a killed comparison's completed directions ride on
#: :attr:`ScanTimeout.partial`, each under its own direction name. It sits
#: BESIDE the cheap facts rather than merged into them because the two have
#: different provenance: the cheap facts are what the canonicalizer already
#: knew, and this is what the comparison actually measured before the kill.
PARTIAL_COMPLETED: Final[str] = "completed"


def scan_timeout_s() -> float:
    """The effective scan ceiling: :data:`SCAN_TIMEOUT_ENV` else the default."""
    raw = os.environ.get(SCAN_TIMEOUT_ENV)
    if raw is None:
        return SCAN_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        return SCAN_TIMEOUT_S


ScanRefusalReason = Literal[
    "scan_timeout",
    "scan_target_unsupported",
    "scan_principal_unavailable",
    "scan_iou_unavailable",
    "scan_neighborhood_overflow",
    "scan_unmeasurable",
    "declared_transform_not_rigid",
    "invalid_align",
    "invalid_target",
    "missing_artifact",
    "unreadable_scan",
]

#: This layer's OWN operand vocabulary — the reasons that are not
#: ``MESH_INGEST.md`` §10 codes. Declared as the complement rather than
#: re-listing §10 here, so the seven §10 codes exist in exactly one place (
#: ``geom.compare.SCAN_REFUSALS``) and this module cannot drift from it; a
#: stage-12 test asserts the two partition :data:`ScanRefusalReason` exactly.
#: The four are the
#: :class:`~hephaestus.core.project_compare.CompareRefusal` precedent — "you
#: named no part" is a fact about the request, not about a scan.
SCAN_OPERAND_REASONS: Final[frozenset[str]] = frozenset(
    {"invalid_align", "invalid_target", "missing_artifact", "unreadable_scan"}
)


class ScanRefusal(ValidationError):
    """A scan comparison could not be set up or computed; ``reason`` is stable.

    The §10 comparison reasons are carried through unchanged from
    :mod:`hephaestus.geom.compare` rather than re-decided here; the four in
    :data:`SCAN_OPERAND_REASONS` are this layer's own.

    For a §10 code the ``[code]`` suffix is **derived** here, on the
    :class:`~hephaestus.geom.mesh.MeshReadError` rule, so a raise site cannot
    hand-write a code that disagrees with its own ``reason=``. The derivation is
    idempotent: a refusal that crossed the subprocess boundary already carries
    the suffix ``geom`` gave it, and a refusal identity that survived a process
    boundary must not stutter its own name on arrival.
    """

    def __init__(self, message: str, *, reason: ScanRefusalReason) -> None:
        if reason not in SCAN_OPERAND_REASONS and f"[{reason}]" not in message:
            message = f"{message} [{reason}]"
        super().__init__(message, kind="contract")
        self.reason: ScanRefusalReason = reason


class ScanTimeout(ScanRefusal):
    """The distance subprocess hit the ceiling or died (§7.3).

    Never empty-handed: ``partial`` carries whatever the child streamed before
    the kill — the §3 quality record, both bounding boxes and the counts, and
    then whichever direction completed — and ``lost`` names the rest. Inside a
    ``CHECKS`` predicate this lands as ``unverifiable``: not a pass, not a
    crash, and never a silently coarse number.
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_s: float,
        partial: dict[str, JSONValue] | None,
        lost: tuple[str, ...],
    ) -> None:
        super().__init__(message, reason="scan_timeout")
        self.timeout_s = timeout_s
        self.partial: dict[str, JSONValue] | None = partial
        self.lost: tuple[str, ...] = lost

    def to_json(self) -> dict[str, JSONValue]:
        """The refusal shape every surface carries (tool error data, CLI --json)."""
        return {
            "status": "scan_timeout",
            "reason": "scan_timeout",
            "message": self.message,
            "timeout_s": self.timeout_s,
            "partial": cast("JSONValue", self.partial),
            "lost": cast("JSONValue", list(self.lost)),
        }


def split_scan_target(target: str) -> str:
    """The ``imports/``-relative path a ``scan:`` target names, or a refusal."""
    if not target.startswith(SCAN_TARGET_PREFIX):
        raise ScanRefusal(
            f"scan target {target!r} must be {SCAN_TARGET_PREFIX!r}<path under imports/> "
            "(MESH_INGEST.md §6.5)",
            reason="invalid_target",
        )
    path = target[len(SCAN_TARGET_PREFIX) :]
    if not path:
        raise ScanRefusal(f"scan target {target!r} names no imports/ file", reason="invalid_target")
    return path


# --------------------------------------------------------------------------
# the cheap facts, and the bounded measurement


def scan_arrays(blob: bytes, *, source: str) -> tuple[Any, Any | None]:
    """``(points, triangles)`` from a staged canonical blob of EITHER kind.

    The blob's own magic decides (§1.5): a point cloud stages ``HEPHPTS`` and has
    no triangles, so it comes back with ``None`` for them — which is exactly what
    ``scan_distance`` needs to fall to the declared upper-bound method rather
    than inventing a surface between the points (§2.3, §6.3).
    """
    from hephaestus.geom.mesh import MESH_BLOB_MAGIC, deserialize_mesh, deserialize_points

    if blob[: len(MESH_BLOB_MAGIC)] == MESH_BLOB_MAGIC:
        vertices, triangles, _factor = deserialize_mesh(blob, source=source)
        return vertices, triangles
    points, _factor = deserialize_points(blob, source=source)
    return points, None


def scan_cheap_facts(blob: bytes, facts: str, *, source: str) -> dict[str, JSONValue]:
    """Everything about the scan that costs no distance computation at all.

    Streamed before either direction runs, so a ceiling kill still answers "what
    is this scan?" — which is the question an operator whose comparison timed
    out asks first. The quality record travels verbatim from the sidecar the
    canonicalizer wrote (§1.5.2): the worker reports the numbers the
    canonicalizer observed, never a second computation that might disagree.

    A point cloud has no quality record and this reports an empty one rather
    than a zero-filled one: §2.3's rule is that a point cloud does not carry a
    mesh's fields at all, and a record of zeros would read as a clean mesh.
    """
    import json as _json

    from hephaestus.geom.mesh import facts_from_json

    points, triangles = scan_arrays(blob, source=source)
    if triangles is None:
        raw = cast("dict[str, JSONValue]", _json.loads(facts))
        bbox_raw = cast("list[float]", raw.get("bbox_mm", [0.0, 0.0, 0.0]))
        return {
            "source_path": source,
            "kind": "points",
            "point_count": int(points.shape[0]),
            "scan_bbox_mm": cast("JSONValue", [float(value) for value in bbox_raw]),
            "quality": cast("JSONValue", {}),
        }
    _as_read, bbox, quality = facts_from_json(facts)
    return {
        "source_path": source,
        "kind": "mesh",
        "vertex_count": int(points.shape[0]),
        "triangle_count": int(triangles.shape[0]),
        "scan_bbox_mm": cast("JSONValue", [float(value) for value in bbox]),
        "quality": cast("JSONValue", quality.to_json()),
    }


def _distance_child(  # pragma: no cover - runs in the spawned child
    conn: Connection,
    brep_path: str,
    blob_path: str,
    facts_path: str,
    source: str,
    align: str,
    declared_transform: list[float] | None,
    scan_canonical_hash: str,
    part_artifact_ref: str,
) -> None:
    """One :class:`ScanDistance`, computed where a kill cannot take the caller down.

    Protocol, in order: ``("cheap", facts)`` — always first — then zero or more
    ``("direction", (name, fields))`` as each direction finishes, then exactly
    one of ``("full", ScanDistance.to_json())`` or
    ``("refusal", {reason, message})``.

    The per-direction message is what makes "whichever direction completed"
    (§7.3) a fact rather than a hope. Direction A is exact and cheap and
    direction B is the expensive one, so the deadline usually falls inside B —
    and a protocol that only spoke at the end would throw away a measurement
    that had already been taken, on the run where the operator most needs it.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.geom.compare import ScanAlignMode, ScanCompareError, scan_distance
    from hephaestus.geom.metrics import bbox_mm

    blob = Path(blob_path).read_bytes()
    facts = Path(facts_path).read_text(encoding="utf-8")

    def _direction(name: str, fields: Mapping[str, float | int | str]) -> None:
        conn.send(("direction", (name, dict(fields))))

    try:
        cheap = scan_cheap_facts(blob, facts, source=source)
        part = cast("Any", load_brep_shape(Path(brep_path).read_bytes()))
        cheap["part_bbox_mm"] = cast("JSONValue", [float(v) for v in bbox_mm(part)])
        conn.send(("cheap", cheap))
        vertices, triangles = scan_arrays(blob, source=source)
        record = scan_distance(
            part,
            vertices,
            triangles,
            align=cast("ScanAlignMode", align),
            declared_transform=declared_transform,
            scan_canonical_hash=scan_canonical_hash,
            part_artifact_ref=part_artifact_ref,
            progress=_direction,
        )
    except ScanCompareError as exc:
        conn.send(("refusal", {"reason": exc.reason, "message": exc.message}))
    except BaseException as exc:
        conn.send(
            ("refusal", {"reason": "unreadable_scan", "message": f"{type(exc).__name__}: {exc}"})
        )
    else:
        conn.send(("full", record.to_json()))
    conn.close()


def bounded_scan_distance(
    part: object,
    blob: bytes,
    facts: str,
    *,
    source: str,
    align: str = "as_posed",
    declared_transform: list[float] | None = None,
    scan_canonical_hash: str = "",
    part_artifact_ref: str = "",
    timeout_s: float | None = None,
    scratch: Path | None = None,
) -> dict[str, JSONValue]:
    """:func:`~hephaestus.geom.compare.scan_distance` under the §7.3 ceiling.

    The part crosses to a spawned child as BRep (lossless, so a completed
    comparison is the direct geom call's record) and the scan as its own
    canonical blob plus sidecar. The child streams the cheap facts first and the
    record second; the parent kills it at the deadline. A ceiling kill or a
    child death raises :class:`ScanTimeout` carrying whatever arrived, and every
    named geom refusal keeps its identity across the process boundary.
    """
    from hephaestus.core.executor.artifact_geometry import write_brep_shape

    if timeout_s is None:
        timeout_s = scan_timeout_s()
    with tempfile.TemporaryDirectory(prefix="heph-scan-", dir=scratch) as tmp:
        brep_path = Path(tmp) / "part.brep"
        blob_path = Path(tmp) / "scan.hmesh"
        facts_path = Path(tmp) / "scan.hmesh.facts"
        write_brep_shape(part, brep_path)
        blob_path.write_bytes(blob)
        facts_path.write_text(facts, encoding="utf-8")

        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe(duplex=False)
        proc = ctx.Process(
            target=_distance_child,
            args=(
                child,
                str(brep_path),
                str(blob_path),
                str(facts_path),
                source,
                align,
                declared_transform,
                scan_canonical_hash,
                part_artifact_ref,
            ),
        )
        proc.start()
        child.close()

        cheap: dict[str, JSONValue] | None = None
        completed: dict[str, JSONValue] = {}
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
            if kind == "direction":
                name, fields = cast("tuple[str, dict[str, JSONValue]]", payload)
                completed[name] = cast("JSONValue", fields)
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
                    proc.join(5.0)
                    died = True
                    break
            # The deadline fell: take what is already in the pipe before the
            # kill. A direction that finished one millisecond before the ceiling
            # is a measurement, and throwing it away because the clock ran out
            # while it sat in a buffer would make the refusal poorer than the
            # run actually was.
            while outcome is None and parent.poll(0):
                try:
                    _receive()
                except EOFError:
                    break
            # …and if that drain turned up the terminal message after all, the
            # run did not die: recomputed rather than left standing, so "the
            # subprocess died" can never be said about a run that answered.
            died = died and outcome is None
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
            record = cast("dict[str, JSONValue]", payload)
            if cheap is not None:
                record["scan_facts"] = cast("JSONValue", cheap)
            return record
        detail = cast("dict[str, Any]", payload)
        raise ScanRefusal(
            str(detail.get("message", "the scan comparison was refused")),
            reason=cast("ScanRefusalReason", detail.get("reason", "unreadable_scan")),
        )
    # ``lost`` and ``completed`` partition the same vocabulary: a direction that
    # reported is named in one and absent from the other, never in both and
    # never in neither. That is what lets an operator read the refusal without
    # having to guess which half of it is missing.
    lost = ((LOST_SCAN_FACTS,) if cheap is None else ()) + tuple(
        name for name in (LOST_SCAN_TO_PART, LOST_PART_TO_SCAN) if name not in completed
    )
    partial: dict[str, JSONValue] | None = None
    if cheap is not None or completed:
        partial = dict(cheap or {})
        if completed:
            partial[PARTIAL_COMPLETED] = cast("JSONValue", completed)
    raise ScanTimeout(
        f"the comparison against {source!r} {cut_short} "
        f"(MESH_INGEST.md §7.3, COMPARE.md §5; ceiling {timeout_s:g}s via "
        f"{SCAN_TIMEOUT_ENV}); lost: {', '.join(lost) or '(nothing)'}; "
        f"completed: {', '.join(sorted(completed)) or '(nothing)'}",
        timeout_s=timeout_s,
        partial=partial,
        lost=lost,
    )


# --------------------------------------------------------------------------
# operands


@dataclass(frozen=True)
class ScanOperand:
    """What the scan side of a comparison was, and how it is attributed.

    Two hashes, and the record carries both because they answer different
    questions (§1.4): ``sha256`` is the raw file's identity — what a build
    freezes and what staleness keys on — and ``canonical_hash`` is the
    *geometry's* identity. Two comparisons whose ``sha256`` differ but whose
    ``canonical_hash`` agree can say "the file changed, the geometry did not".
    """

    path: str
    units: str
    sha256: str
    canonical_hash: str
    snapshot_ref: str | None = None
    kind: Literal["scan"] = "scan"

    def to_json(self) -> dict[str, JSONValue]:
        out: dict[str, JSONValue] = {
            "kind": self.kind,
            "path": self.path,
            "units": self.units,
            "sha256": self.sha256,
            "canonical_hash": self.canonical_hash,
        }
        if self.snapshot_ref is not None:
            out["snapshot_ref"] = self.snapshot_ref
        return out


@dataclass(frozen=True)
class ScanComparison:
    """One ``ScanDistance`` plus the provenance of both operands (§7.2)."""

    align: str
    part: str
    part_artifact_ref: str | None
    scan: ScanOperand
    #: ``ScanDistance.to_json()`` — the geom record's own shape, never a
    #: re-derived one, so the wire form cannot drift from §6.4.
    distance: dict[str, JSONValue]
    quality: dict[str, JSONValue]

    @property
    def resolved_refs(self) -> list[str]:
        return [ref for ref in (self.part_artifact_ref, self.scan.snapshot_ref) if ref is not None]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "status": "ok",
            "align": self.align,
            "part": {
                "kind": "part",
                "name": self.part,
                "artifact_ref": self.part_artifact_ref,
            },
            "scan": self.scan.to_json(),
            "distance": dict(self.distance),
            "quality": dict(self.quality),
            "resolved_artifact_refs": cast("JSONValue", list(self.resolved_refs)),
        }


class ProjectScanComparer:
    """Compares one project's parts against scans under its ``imports/``."""

    def __init__(self, layout: ProjectLayout, store: OpStore) -> None:
        from hephaestus.core.project_store.publication import Publisher

        self._layout = layout
        self._store = store
        self._publisher = Publisher(layout, store)

    def compare(
        self,
        part: str,
        target: str,
        *,
        units: str,
        align: str = "as_posed",
        declared_transform: list[float] | None = None,
        scratch: Path | None = None,
        timeout_s: float | None = None,
    ) -> ScanComparison:
        """Compare ``part``'s current build against a ``scan:`` target (§6, §7.2)."""
        from hephaestus.geom.compare import SCAN_ALIGN_MODES, refuse_scan_principal

        path = split_scan_target(target)
        if align == "principal":
            refuse_scan_principal(target)
        if align not in SCAN_ALIGN_MODES:
            raise ScanRefusal(
                f"align must be one of {', '.join(SCAN_ALIGN_MODES)}, got {align!r} — "
                "'principal' is refused by name against a scan (MESH_INGEST.md §6.5)",
                reason="invalid_align",
            )
        shape, artifact_ref = self.part_operand(part, scratch)
        operand, blob, facts = self.scan_operand(path, units)
        record = bounded_scan_distance(
            shape,
            blob,
            facts,
            source=path,
            align=align,
            declared_transform=declared_transform,
            scan_canonical_hash=operand.canonical_hash,
            part_artifact_ref=artifact_ref or "",
            scratch=scratch,
            timeout_s=timeout_s,
        )
        cheap = record.pop("scan_facts", None)
        quality = {}
        if isinstance(cheap, dict):
            raw = cheap.get("quality")
            quality = cast("dict[str, JSONValue]", raw) if isinstance(raw, dict) else {}
        return ScanComparison(
            align=align,
            part=part,
            part_artifact_ref=artifact_ref,
            scan=operand,
            distance=record,
            quality=quality,
        )

    def part_operand(self, name: str, scratch: Path | None) -> tuple[object, str | None]:
        """One part's current successful build artifact, as a shape plus its ref."""
        from hephaestus.core.executor.artifact_geometry import load_brep_shape
        from hephaestus.core.project_store.store import blob_hash_of_ref

        result = self._publisher.current_result(name)
        if result is None or result.artifact_ref is None:
            raise AddressingError(
                f"part {name!r} has no current successful build to compare against a scan",
                selector=name,
                candidates=self._layout.part_names(),
            )
        blob = blob_hash_of_ref(result.artifact_ref)
        if not self._store.blobs.has(blob):
            raise ScanRefusal(
                f"artifact {result.artifact_ref} is not durably stored",
                reason="missing_artifact",
            )
        shape = load_brep_shape(self._store.blobs.get(blob), scratch_dir=scratch)
        return shape, result.artifact_ref

    def scan_operand(self, path: str, units: str) -> tuple[ScanOperand, bytes, str]:
        """One ``imports/`` mesh as its canonical blob, sidecar and attribution.

        The read is the Stage 8A confinement walk under the §1.6 byte ceiling
        for a mesh, and the canonicalization is the §1.5 pipeline — the same one
        a build's staging runs — so what a tool measures is exactly what a build
        would have admitted, refusals included.
        """
        import hashlib

        from hephaestus.geom.mesh import (
            MeshReadError,
            canonicalize_mesh,
            canonicalize_points,
            extension_kind,
            facts_to_json,
            points_facts_to_json,
            sniff_format,
        )

        kind = extension_kind(path) or "mesh"
        snapshot = self._publisher.parts.read_import(path, kind=kind)
        try:
            # Admission decides the kind from the BYTES, not from the extension
            # guess above: a point cloud is a point cloud whatever it is named,
            # and a mismatch is ``mesh_format_mismatch`` rather than a silently
            # honoured sniff (§1.2).
            admitted, _fmt = sniff_format(path, snapshot.data)
            if admitted == "points":
                cloud = canonicalize_points(path, snapshot.data, units)
                blob, facts = cloud.blob, points_facts_to_json(cloud)
            else:
                canonical = canonicalize_mesh(path, snapshot.data, units)
                blob, facts = canonical.blob, facts_to_json(canonical)
        except MeshReadError as exc:
            raise ScanRefusal(
                f"scan {path!r} could not be admitted: {exc.message}",
                reason="unreadable_scan",
            ) from exc

        operand = ScanOperand(
            path=path,
            units=units,
            sha256=snapshot.content_hash,
            canonical_hash="sha256:" + hashlib.sha256(blob).hexdigest(),
            snapshot_ref=snapshot.snapshot_ref,
        )
        return operand, blob, facts
