# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# trimesh's loader is typed only as far as ``Geometry``, and its ``Scene``
# members are untyped; the relaxation is pinned per-file, exactly as
# ``geom.measure`` / ``geom.nesting`` pin the OCP one, so it stays scoped to the
# module that touches the third-party loader.
# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""External triangles -> facts: the tenth pure geom service (``MESH_INGEST.md`` §2.1).

A limb scan is not a CAD file. It has no exact surfaces, no parameters, no
units, and no stable topology — and the entire difficulty of this module is
refusing to let a mesh's vocabulary borrow a solid's field names. Every claim
this module makes is bounded by what a triangle soup can actually support, in a
CLOSED vocabulary (:data:`MESH_REFUSALS`), and every defect it finds is
**measured and named rather than silently repaired** (§3): a plausible-looking
wrong surface is worse than a named refusal.

The seam with :mod:`hephaestus.core.render.tessellate` is deliberate and is the
mission rule 6 answer (§2.1): ``render.tessellate`` owns *B-rep -> triangles for
rendering* — its deflection constants are golden provenance — and ``geom.mesh``
owns *external triangles -> facts*. They share a data shape and no code, and the
import boundary forbids this module from naming the render package at all.

What lives here, and nothing else:

1. **Admission** (:func:`sniff_format`) — the five formats of §1.2 by extension
   *and* sniffed magic, with a mismatch named rather than silently honoured.
2. **Ceilings before the parser** (:func:`count_ceiling_check`) — the
   triangle/point ceilings of §1.6, read from the format's own declared counts
   where the header carries them and otherwise by a counting pre-pass that
   aborts at the ceiling. The *byte* ceiling is not here: it fires inside the
   executor's confinement walk, off the already-open descriptor, because a
   ceiling checked after ``read()`` has already spent the resource it protects.
3. **Canonicalization** (:func:`canonicalize_mesh`, :func:`canonicalize_points`)
   — the §1.5 pipeline, whose every step is a decision and is therefore named:
   ``process=False`` parse, non-finite refusal, unit scale, weld, degenerate
   drop, canonical order, serialize. The canonical blob is the geometry AND the
   identity; the facts the canonicalizer destroyed ride a sidecar (§1.5.2).
4. **Quality** (:class:`MeshQuality`) — exact combinatorial facts about the
   welded mesh, plus the one honest exception: self-intersection is *sampled*,
   and ``None`` there means *not measured*, never *zero*.
5. **Sections** (:func:`section_polylines`, 12B) — the plane/triangle
   intersection of §5.3, whose contract is that a contour which does not close
   comes back OPEN and flagged, never joined end to end. Still numpy: a section
   of a triangle soup is arithmetic, not kernel work.

The kernel half of 12B — sewing, the ``BRepCheck_Analyzer`` gate, and the
section → B-spline → loft helper — lives next door in
:mod:`hephaestus.geom.mesh_solid`, on the same seam reasoning that separates
this module from ``render.tessellate``: facts computable from the triangles are
here, and everything that needs OCCT to answer is there.

This module holds no policy: it does not know where files live, does not
resolve or confine paths, does not hash a build input, and never touches a
project — exactly as :mod:`hephaestus.geom.step_io` does not. Path resolution,
content addressing and staging are executor-side
(:mod:`hephaestus.core.executor.imports`).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

import numpy as np
from hephaestus.core.errors import ValidationError

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from opstore.types import JSONValue

__all__ = [
    "MESH_BLOB_MAGIC",
    "MESH_BLOB_VERSION",
    "MESH_DEGENERATE_AREA_MM2",
    "MESH_EXTENSIONS",
    "MESH_MAX_BYTES",
    "MESH_MAX_BYTES_ENV",
    "MESH_MAX_POINTS",
    "MESH_MAX_POINTS_ENV",
    "MESH_MAX_TRIANGLES",
    "MESH_MAX_TRIANGLES_ENV",
    "MESH_OPERATION_REFUSALS",
    "MESH_REFUSALS",
    "MESH_SELFX_PAIR_MAX",
    "MESH_SELFX_PAIR_MAX_ENV",
    "MESH_TYPE_REFUSALS",
    "MESH_UNITS",
    "MESH_UNIT_FACTORS",
    "MESH_WELD_TOL_MM",
    "OPEN_SECTION_CONTOUR",
    "POINTS_BLOB_MAGIC",
    "SCAN_CANDIDATE_MAX",
    "SCAN_CANDIDATE_MAX_ENV",
    "SCAN_DISTANCE_METHODS",
    "SCAN_METHOD_BOUND",
    "SCAN_METHOD_EXACT",
    "CanonicalMesh",
    "CanonicalPoints",
    "MeshAsset",
    "MeshDistances",
    "MeshKind",
    "MeshOperationError",
    "MeshOperationReason",
    "MeshQuality",
    "MeshReadError",
    "MeshRefusalReason",
    "MeshTypeError",
    "MeshTypeReason",
    "MeshUnits",
    "PointCloudAsset",
    "SectionPolyline",
    "canonicalize_mesh",
    "canonicalize_points",
    "closest_point_on_triangle",
    "count_ceiling_check",
    "deserialize_mesh",
    "deserialize_points",
    "extension_kind",
    "facts_from_json",
    "facts_to_json",
    "mesh_asset_from_staged",
    "mesh_max_bytes",
    "mesh_max_points",
    "mesh_max_triangles",
    "mesh_quality",
    "mesh_selfx_pair_max",
    "point_cloud_asset_from_staged",
    "point_mesh_distances",
    "points_facts_to_json",
    "scan_candidate_max",
    "section_polylines",
    "sniff_format",
    "unit_factor",
]

# --------------------------------------------------------------------------
# §1.3 units — declared, never inferred

#: The closed unit set (§1.3). A file in these formats carries no unit, so the
#: declaration is the only honest source. "300 units across so probably mm" is
#: a guess dressed as a measurement, and a limb scan is exactly the size where
#: the guess is plausible and wrong.
MESH_UNITS: Final[tuple[str, ...]] = ("mm", "cm", "m", "in")
MeshUnits = Literal["mm", "cm", "m", "in"]

#: Exact scale factors to the engine's millimetres. Exact, not approximate:
#: 25.4 mm/in is the definition of the inch, not a measurement of it.
MESH_UNIT_FACTORS: Final[Mapping[str, float]] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
}

# --------------------------------------------------------------------------
# §1.2 admitted formats

MeshKind = Literal["mesh", "points"]

#: The 12A closed set: extension -> (kind, canonical format token). Admission
#: is by extension AND sniffed magic; a ``.stl`` whose bytes are a PLY header
#: is ``mesh_format_mismatch``, never a silently-honoured sniff (§1.2).
MESH_EXTENSIONS: Final[Mapping[str, tuple[MeshKind, str]]] = {
    ".stl": ("mesh", "stl"),
    ".ply": ("mesh", "ply"),
    ".obj": ("mesh", "obj"),
    ".off": ("mesh", "off"),
    ".xyz": ("points", "xyz"),
}

#: Extensions refused at admission with the amendment each would need (§1.2).
#: glTF/GLB is a *scene*: flattening one means choosing a node traversal order
#: and concatenating transformed meshes, which is a normalization with real
#: semantic content. 3MF costs an ``lxml`` dependency (mission rule 7) and is a
#: zip container besides. Neither is effort; both are substance.
_REFUSED_EXTENSIONS: Final[Mapping[str, str]] = {
    ".glb": "glTF/GLB is a scene, not a mesh: flattening one chooses a node "
    "traversal order and concatenates transformed meshes, which is a "
    "normalization with semantic content. It needs its own amendment "
    "(MESH_INGEST.md §1.2)",
    ".gltf": "glTF/GLB is a scene, not a mesh: flattening one chooses a node "
    "traversal order and concatenates transformed meshes, which is a "
    "normalization with semantic content. It needs its own amendment "
    "(MESH_INGEST.md §1.2)",
    ".3mf": "3MF needs trimesh's lxml-backed loader, and lxml is not a pinned "
    "dependency; admitting it is a mission rule 7 dependency amendment "
    "(MESH_INGEST.md §1.2)",
}

# --------------------------------------------------------------------------
# §1.5 canonicalization constants

#: Weld tolerance in mm (§1.5 step 4). Coordinates are quantized to
#: ``round(x / MESH_WELD_TOL_MM)`` and equal keys merged — the key function is
#: documented HERE rather than inherited from ``trimesh.merge_vertices``,
#: because a canonical form delegated to a library default is a canonical form
#: nobody can reproduce from the spec.
MESH_WELD_TOL_MM: Final[float] = 1e-6

#: A triangle at or below this area (mm²) is degenerate and is DROPPED — with
#: the count recorded on the quality record (§1.5 step 5), never silently
#: absorbed.
MESH_DEGENERATE_AREA_MM2: Final[float] = 1e-12

#: Canonical blob magic (§1.5 step 7). Two magics, because a point cloud is a
#: different kind and must not deserialize as a mesh with zero triangles.
MESH_BLOB_MAGIC: Final[bytes] = b"HEPHMESH"
POINTS_BLOB_MAGIC: Final[bytes] = b"HEPHPTS\x00"
#: Canonical blob format version. It is inside the hashed header on purpose: a
#: format change is a geometry-identity change, and pretending otherwise would
#: let a serializer edit silently keep an old hash.
MESH_BLOB_VERSION: Final[int] = 1
#: ``magic(8) + version(4) + vertices(4) + triangles(4) + unit factor(8) + 4
#: reserved`` = the fixed 32-byte header of §1.5 step 7.
_BLOB_HEADER = struct.Struct("<8sIIId4x")

# --------------------------------------------------------------------------
# §1.6 ceilings

#: Byte ceiling for an admitted mesh/point-cloud file. Enforced NOT here but
#: inside the executor's confinement walk, off ``os.fstat`` on the already-open
#: descriptor, before any ``read()`` — a refusal that runs after the file is in
#: memory and in CAS has already spent the resource it was protecting (§1.6).
#: The value is an engineering ceiling, not a measured budget: it bounds the
#: parent's memory, and mission rule 4's measured constants are the performance
#: budgets, not this.
MESH_MAX_BYTES: Final[int] = 512 * 1024 * 1024
MESH_MAX_BYTES_ENV: Final[str] = "HEPHAESTUS_MESH_MAX_BYTES"

#: Triangle / point ceilings, checked in the parent after the bytes are in hand
#: but BEFORE they reach trimesh. These two fire *after* the bytes are resident
#: and already in the opstore blob store, and this module says so rather than
#: implying otherwise: that is sound only because :data:`MESH_MAX_BYTES` has
#: already bounded both. They bound the PARSER's working set — a small file can
#: still declare 10⁸ triangles — where the byte ceiling bounds the harness's.
MESH_MAX_TRIANGLES: Final[int] = 20_000_000
MESH_MAX_TRIANGLES_ENV: Final[str] = "HEPHAESTUS_MESH_MAX_TRIANGLES"
MESH_MAX_POINTS: Final[int] = 50_000_000
MESH_MAX_POINTS_ENV: Final[str] = "HEPHAESTUS_MESH_MAX_POINTS"

#: Candidate-pair ceiling for the sampled self-intersection test (§3). Above
#: it the count is ``None`` with method ``not_evaluated_ceiling`` — *not
#: measured*, never *zero*.
MESH_SELFX_PAIR_MAX: Final[int] = 2_000_000
MESH_SELFX_PAIR_MAX_ENV: Final[str] = "HEPHAESTUS_MESH_SELFX_PAIR_MAX"


def _env_ceiling(name: str, default: int) -> int:
    """The effective ceiling: the env override when it RAISES the floor.

    The ``COMPARE.md`` §5 local-floor pattern (``COMPARE.md:113-118``): an
    operator may grant a bigger budget on their own machine, and may not
    quietly lower one below the shipped floor, because a lowered ceiling would
    turn a passing gate into a refusal nobody declared.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(default, value)


def mesh_max_bytes() -> int:
    """Effective :data:`MESH_MAX_BYTES` (:data:`MESH_MAX_BYTES_ENV` may raise it)."""
    return _env_ceiling(MESH_MAX_BYTES_ENV, MESH_MAX_BYTES)


def mesh_max_triangles() -> int:
    """Effective :data:`MESH_MAX_TRIANGLES`."""
    return _env_ceiling(MESH_MAX_TRIANGLES_ENV, MESH_MAX_TRIANGLES)


def mesh_max_points() -> int:
    """Effective :data:`MESH_MAX_POINTS`."""
    return _env_ceiling(MESH_MAX_POINTS_ENV, MESH_MAX_POINTS)


def mesh_selfx_pair_max() -> int:
    """Effective :data:`MESH_SELFX_PAIR_MAX` — overridable in BOTH directions.

    The local-floor rule the three ceilings above follow exists because lowering
    a *safety* ceiling turns a passing build into a refusal nobody declared.
    This one is not a safety ceiling, it is a measurement-effort ceiling, and
    the asymmetry is worth stating: lowering it can only move the record from a
    measured count to ``None`` with method ``not_evaluated_ceiling`` — from a
    claim to an honest *not measured*. It can never produce a false zero, which
    is the only direction that would matter.
    """
    raw = os.environ.get(MESH_SELFX_PAIR_MAX_ENV)
    if raw is None:
        return MESH_SELFX_PAIR_MAX
    try:
        return max(0, int(raw))
    except ValueError:
        return MESH_SELFX_PAIR_MAX


# --------------------------------------------------------------------------
# §1.7 the closed refusal set

MeshRefusalReason = Literal[
    "mesh_format_unsupported",
    "mesh_format_mismatch",
    "mesh_unreadable",
    "mesh_empty",
    "mesh_multi_object",
    "mesh_not_finite",
    "mesh_degenerate_only",
    "mesh_units_undeclared",
    "mesh_units_unsupported",
    "mesh_units_conflict",
    "mesh_import_too_large",
]

#: The complete §1.7 vocabulary, as a value a test can enumerate. It is CLOSED:
#: a mesh defect with no code here is a defect in ``MESH_INGEST.md``, to be
#: fixed by adding a code, never by widening an existing one.
#:
#: ``mesh_units_conflict`` is declared and, in 12A, UNREACHABLE — every
#: unit-carrying format (3MF, glTF) refuses at admission and the five admitted
#: extensions carry no unit at all. It is kept because the amendment that
#: admits a unit-carrying format must not be free to invent a silent preference
#: at that moment, and a code already in the vocabulary is a harder thing to
#: route around than one that must first be argued for (§1.3).
MESH_REFUSALS: Final[tuple[str, ...]] = (
    "mesh_format_unsupported",
    "mesh_format_mismatch",
    "mesh_unreadable",
    "mesh_empty",
    "mesh_multi_object",
    "mesh_not_finite",
    "mesh_degenerate_only",
    "mesh_units_undeclared",
    "mesh_units_unsupported",
    "mesh_units_conflict",
    "mesh_import_too_large",
)


class MeshReadError(ValidationError):
    """A mesh payload was refused, by name, at admission or canonicalization.

    ``reason`` is the stable §1.7 code. The executor turns it into the §8 build
    error at the offending ``import_mesh`` statement, exactly as it turns
    :class:`~hephaestus.geom.step_io.StepReadError` into one at ``import_step``.

    **The code is appended to the message here, not written into it at the raise
    site**, and that is the whole point of doing it in the constructor. The §8
    build error record carries a message and a source frame; the ``reason``
    object itself does not survive the crossing into the worker's error record.
    A raise site that hand-wrote its own code into its own prose could keep that
    prose and change ``reason=`` underneath it, and every message-level
    assertion downstream would still pass while the vocabulary silently drifted
    (G12A.2 is written to catch exactly that). Deriving the suffix from
    ``reason`` makes the two impossible to disagree: change the code and the
    message changes with it, at the build layer and at ``heph scan`` alike.
    """

    def __init__(self, message: str, *, reason: MeshRefusalReason) -> None:
        super().__init__(f"{message} [{reason}]", kind="contract")
        self.reason: MeshRefusalReason = reason


# --------------------------------------------------------------------------
# §10 the conversion-and-operations vocabulary (12B), closed the same way

MeshOperationReason = Literal[
    "mesh_sew_timeout",
    "mesh_solid_invalid",
    "mesh_derived_operation_refused",
    "open_section_contour",
    "empty_section",
]

#: The §10 "conversion and operations" codes, as a value a test can enumerate.
#: Disjoint from :data:`MESH_REFUSALS` by construction: an admission refusal is
#: about a FILE the harness will not read, and one of these is about an
#: OPERATION on a mesh it already read and admitted. Collapsing the two would
#: send a reader after the wrong fix — "your scan is unreadable" where the truth
#: is "your scan is fine and OCCT will not sew it into a valid solid".
MESH_OPERATION_REFUSALS: Final[tuple[str, ...]] = (
    "mesh_sew_timeout",
    "mesh_solid_invalid",
    "mesh_derived_operation_refused",
    "open_section_contour",
    "empty_section",
)

#: The flag a contour that does not close carries (§5.3). It is a *flag on a
#: returned record*, not only a raised refusal, because the honest answer to
#: "the plane crossed a hole" is the open polyline plus the name of what is
#: wrong with it — a caller that wants surface there must decide to invent it,
#: in the open, rather than receive it silently closed.
OPEN_SECTION_CONTOUR: Final[str] = "open_section_contour"


class MeshOperationError(ValidationError):
    """A mesh operation was refused, by name (``MESH_INGEST.md`` §10, 12B).

    Deliberately a different type from :class:`MeshReadError` with a different
    closed vocabulary: admission answers "may this file be read", and this
    answers "may this already-admitted mesh become that". A single type would
    let a widening of one vocabulary quietly widen the other.
    """

    def __init__(self, message: str, *, reason: MeshOperationReason) -> None:
        # The ``[code]`` suffix is derived here for the reason
        # :class:`MeshReadError` derives its own, and the second repair pass's
        # verifier is why it is derived HERE and not only there: this class had
        # the ``reason`` attribute but not the derivation, so all five of its
        # codes were hand-written into their own raise sites' prose and could
        # drift from ``reason=`` exactly as §1.7's could before. A vocabulary
        # closed for one third of §10 is not closed.
        super().__init__(f"{message} [{reason}]", kind="contract")
        self.reason: MeshOperationReason = reason


# --------------------------------------------------------------------------
# §10 the type-and-topology vocabulary, closed and carried the same way

MeshTypeReason = Literal[
    "point_cloud_not_a_shape",
    "mesh_topology_not_taggable",
]

#: The §10 "type and topology" codes. Two, and they are a third group rather
#: than members of either vocabulary above: an admission refusal is about a file
#: that will not be read, an operation refusal is about a mesh that will not
#: become something, and these two are about a KIND reaching a place its type
#: cannot go — a point cloud handed to a shape parameter, a triangle handed to
#: ``tag()``. They lived only as hand-written prose until the third repair pass,
#: which is why they are a vocabulary now: a code with no ``reason=`` behind it
#: is a code that exists in a message and nowhere a caller can branch on.
MESH_TYPE_REFUSALS: Final[tuple[str, ...]] = (
    "point_cloud_not_a_shape",
    "mesh_topology_not_taggable",
)


class MeshTypeError(ValidationError):
    """A mesh or point cloud reached a place its kind cannot go (§2.3, §2.4).

    Raised executor-side (``executor/namespace.py``, ``executor/tags.py``) and
    declared here beside the other two §10 vocabularies for the reason the
    vocabularies themselves live in ``geom``: the closed set of names is a fact
    about mesh geometry, not about the executor that happens to notice the
    violation, and a set declared where it is raised would be a set each caller
    could widen privately.

    ``kind="contract"`` and a :class:`ValidationError` base, so every existing
    catcher of the bare ``ValidationError`` these sites used to raise still
    catches it — the change adds a ``reason`` a caller can branch on and a
    derived ``[code]`` suffix that cannot disagree with it, and removes nothing.
    """

    def __init__(self, message: str, *, reason: MeshTypeReason) -> None:
        super().__init__(f"{message} [{reason}]", kind="contract")
        self.reason: MeshTypeReason = reason


@dataclass(frozen=True)
class SectionPolyline:
    """One ordered contour where a plane crossed the mesh (``MESH_INGEST.md`` §5.3).

    ``closed`` is measured, never arranged: the walk either returned to its
    start or it did not. When it did not, ``flag`` is
    :data:`OPEN_SECTION_CONTOUR` and the two ends stay apart — the plane crossed
    a hole in the scan, and closing it would fabricate limb surface the scanner
    never saw at exactly the place a socket presses.

    ``point_spacing_mm`` is the DECLARED spacing this contour was resampled at,
    or ``None`` for the mesh's own crossing points. It rides the record rather
    than a docstring because "how far apart are these points" is a fact about
    the measurement, and a consumer that fits a curve through them is entitled
    to know whether it is fitting the data or a resampling of it.
    """

    points: tuple[tuple[float, float, float], ...]
    closed: bool
    flag: str | None
    point_spacing_mm: float | None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "points": cast("JSONValue", [list(point) for point in self.points]),
            "closed": self.closed,
            "flag": self.flag,
            "point_spacing_mm": self.point_spacing_mm,
        }


def unit_factor(units: object) -> float:
    """The §1.3 scale factor for a declared unit, or a named refusal.

    ``None`` is ``mesh_units_undeclared`` and anything outside the closed set is
    ``mesh_units_unsupported``. There is no default and there is no inference:
    the two failures are different mistakes and are told apart by name.
    """
    if units is None:
        raise MeshReadError(
            "units= is required on a mesh import: STL, PLY, OBJ, OFF and XYZ carry no "
            "unit, and the engine is millimetres throughout. Declare one of "
            f"{', '.join(MESH_UNITS)} (MESH_INGEST.md §1.3)",
            reason="mesh_units_undeclared",
        )
    if not isinstance(units, str) or units not in MESH_UNIT_FACTORS:
        raise MeshReadError(
            f"units={units!r} is not a supported unit; the closed set is "
            f"{', '.join(MESH_UNITS)} (MESH_INGEST.md §1.3)",
            reason="mesh_units_unsupported",
        )
    return MESH_UNIT_FACTORS[units]


def extension_kind(path: str) -> MeshKind | None:
    """``"mesh"`` / ``"points"`` for an admitted extension, else ``None``.

    Used by the executor's staleness path to resolve a byte ceiling for a file
    **no script declares** (§1.6): there is no declaration to read a kind from
    there, so the extension is the only thing available, and an unknown
    extension keeps STEP's ``None`` ceiling so no existing behaviour moves.
    """
    _, _, suffix = path.rpartition(".")
    entry = MESH_EXTENSIONS.get("." + suffix.lower())
    return None if entry is None else entry[0]


# --------------------------------------------------------------------------
# §1.2 admission: extension + sniffed magic


def _looks_binary_stl(data: bytes) -> bool:
    if len(data) < 84:
        return False
    (count,) = struct.unpack_from("<I", data, 80)
    return len(data) == 84 + 50 * int(count)


def _sniff(data: bytes) -> str | None:
    """The format the BYTES claim to be, or ``None`` when they claim nothing.

    Only signatures a file format actually defines count as a claim. OBJ and
    XYZ have no magic — they are plain text — so they sniff as ``None`` and are
    admitted on their extension. That is not a hole: a claim of PLY/OFF/STL
    under an ``.obj`` name is still caught, because those three DO claim.
    """
    if data[:3] == b"ply" and data[3:4] in (b"\n", b"\r"):
        return "ply"
    head = data[:4].lstrip()
    if head[:3] == b"OFF" or head[:4] in (b"COFF", b"NOFF", b"STOF"):
        return "off"
    if _looks_binary_stl(data):
        return "stl"
    if _ascii_stl(data):
        return "stl"
    return None


def sniff_format(path: str, data: bytes) -> tuple[MeshKind, str]:
    """Admit ``data`` under ``path``'s extension, or refuse by name (§1.2).

    Returns ``(kind, format token)``. Three refusals, and the split between
    them is the point: an extension outside the table is
    ``mesh_format_unsupported`` **naming the amendment it would need**, empty
    bytes are ``mesh_empty``, and bytes whose own magic contradicts the
    extension are ``mesh_format_mismatch`` — never a silently-honoured sniff,
    because honouring it would mean the build's declared format and its actual
    format disagree with nothing recording it.
    """
    _, _, suffix = path.rpartition(".")
    extension = "." + suffix.lower()
    refusal = _REFUSED_EXTENSIONS.get(extension)
    if refusal is not None:
        raise MeshReadError(
            f"{path}: {extension} is not admitted in Stage 12A. {refusal}",
            reason="mesh_format_unsupported",
        )
    entry = MESH_EXTENSIONS.get(extension)
    if entry is None:
        raise MeshReadError(
            f"{path}: {extension or '(no extension)'} is not an admitted mesh format; "
            f"the closed 12A set is {', '.join(sorted(MESH_EXTENSIONS))} "
            "(MESH_INGEST.md §1.2)",
            reason="mesh_format_unsupported",
        )
    if not data:
        raise MeshReadError(f"{path}: payload is empty", reason="mesh_empty")
    kind, fmt = entry
    sniffed = _sniff(data)
    if sniffed is not None and sniffed != fmt:
        raise MeshReadError(
            f"{path}: extension says {fmt} but the bytes are {sniffed}; the sniff is "
            "never silently honoured (MESH_INGEST.md §1.2)",
            reason="mesh_format_mismatch",
        )
    return kind, fmt


# --------------------------------------------------------------------------
# §1.6 count ceilings, before trimesh sees the bytes


def _ascii_stl(data: bytes) -> bool:
    """True when the bytes are an ASCII STL, whose offset 80 is text not a count."""
    return data[:512].lstrip()[:5].lower() == b"solid" and b"facet" in data[:4096].lower()


def _binary_stl_count(data: bytes) -> int | None:
    """The triangle count a binary STL's header CLAIMS, believed or not.

    Deliberately looser than :func:`_looks_binary_stl`, which requires the
    file's length to match the claim. The ceiling has to read the count from a
    header whose claim the file does *not* honour — a 84-byte file declaring
    10⁸ triangles is exactly the case the ceiling exists for, and requiring the
    length to match would let it through to the parser precisely when the claim
    is a lie.
    """
    if len(data) < 84 or _ascii_stl(data):
        return None
    (count,) = struct.unpack_from("<I", data, 80)
    return int(count)


def _declared_counts(data: bytes, fmt: str) -> tuple[int | None, int | None]:
    """``(vertices, triangles)`` the FORMAT ITSELF declares, where it does."""
    if fmt == "stl":
        count = _binary_stl_count(data)
        if count is not None:
            return None, count
    if fmt == "ply":
        vertices: int | None = None
        faces: int | None = None
        for raw in data[:65536].split(b"\n"):
            line = raw.strip()
            if line == b"end_header":
                break
            parts = line.split()
            if len(parts) == 3 and parts[0] == b"element":
                try:
                    value = int(parts[2])
                except ValueError:
                    continue
                if parts[1] == b"vertex":
                    vertices = value
                elif parts[1] == b"face":
                    faces = value
        return vertices, faces
    if fmt == "off":
        for raw in data[:65536].split(b"\n"):
            line = raw.strip()
            if not line or line.startswith(b"#"):
                continue
            if line[:3] in (b"OFF", b"COF", b"NOF") or line[:4] == b"STOF":
                rest = line.split()
                if len(rest) >= 4:
                    try:
                        return int(rest[1]), int(rest[2])
                    except ValueError:
                        return None, None
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    return int(parts[0]), int(parts[1])
                except ValueError:
                    return None, None
            return None, None
    return None, None


def _counting_prepass(data: bytes, fmt: str, ceiling: int) -> int:
    """Count elements the format does not declare, ABORTING at ``ceiling``.

    Aborting matters: a counting pass that runs to completion on a 10⁸-element
    file has done the work the ceiling exists to refuse. The return value is
    therefore "the count, or ``ceiling + 1``" — enough to refuse, never more.
    """
    seen = 0
    if fmt == "stl":
        needle = b"facet normal"
    elif fmt == "obj":
        needle = b"\nf "
        data = b"\n" + data
    else:  # xyz: one point per non-empty, non-comment line
        for raw in data.split(b"\n"):
            line = raw.strip()
            if not line or line.startswith((b"#", b"//")):
                continue
            seen += 1
            if seen > ceiling:
                return seen
        return seen
    start = 0
    while True:
        found = data.find(needle, start)
        if found < 0:
            return seen
        seen += 1
        if seen > ceiling:
            return seen
        start = found + 1


def count_ceiling_check(path: str, data: bytes, kind: MeshKind, fmt: str) -> None:
    """Refuse ``mesh_import_too_large`` on a declared or counted element count.

    §1.6: the format's own declared counts where the header carries them (binary
    STL, PLY, OFF), and otherwise a counting pre-pass that aborts at the
    ceiling. Nothing here parses geometry — the point is to refuse *before*
    trimesh allocates for a count the file merely claims.
    """
    if kind == "points":
        ceiling = mesh_max_points()
        declared, _ = _declared_counts(data, fmt)
        count = declared if declared is not None else _counting_prepass(data, fmt, ceiling)
        what, env = "points", MESH_MAX_POINTS_ENV
    else:
        ceiling = mesh_max_triangles()
        _, declared = _declared_counts(data, fmt)
        count = declared if declared is not None else _counting_prepass(data, fmt, ceiling)
        what, env = "triangles", MESH_MAX_TRIANGLES_ENV
    if count > ceiling:
        raise MeshReadError(
            f"{path}: {count} {what} exceeds the ceiling of {ceiling}; raise {env} to "
            "allow more (MESH_INGEST.md §1.6)",
            reason="mesh_import_too_large",
        )


def _refuse_multi_object(path: str, data: bytes, fmt: str) -> None:
    """Refuse a file carrying several objects rather than choosing one (§1.7).

    Measured, and the reason this check is not delegated: trimesh 4.12.2 loads a
    two-``o`` OBJ as ONE concatenated ``Trimesh`` — a silent normalization the
    file never authorized. The refusal is therefore taken from the bytes, before
    the loader gets a chance to merge them.
    """
    if fmt == "obj":
        groups = sum(1 for raw in data.split(b"\n") if raw[:2] in (b"o ", b"g "))
        if groups > 1:
            raise MeshReadError(
                f"{path}: OBJ declares {groups} objects; the harness refuses rather than "
                "choosing one or concatenating them — either choice is a normalization "
                "the file did not authorize (MESH_INGEST.md §1.7)",
                reason="mesh_multi_object",
            )
    elif fmt == "ply":
        extra: list[str] = []
        for raw in data[:65536].split(b"\n"):
            line = raw.strip()
            if line == b"end_header":
                break
            parts = line.split()
            if len(parts) == 3 and parts[0] == b"element" and parts[1] not in (b"vertex", b"face"):
                try:
                    count = int(parts[2])
                except ValueError:
                    continue
                if count > 0:
                    extra.append(parts[1].decode("ascii", "replace"))
        if extra:
            raise MeshReadError(
                f"{path}: PLY declares non-geometry elements {', '.join(extra)}; the "
                "harness refuses rather than choosing which to read "
                "(MESH_INGEST.md §1.7)",
                reason="mesh_multi_object",
            )


# --------------------------------------------------------------------------
# §1.5 the canonical pipeline


@dataclass(frozen=True)
class MeshQuality:
    """Every defect this stage can see, measured and named (``MESH_INGEST.md`` §3).

    The single most dangerous thing mesh ingest could do is quietly clean a
    scan. Nothing here repairs anything: a scan that arrives with holes,
    non-manifold edges and inverted normals is ADMITTED with all of it
    recorded, because every real limb scan is imperfect and a harness that
    refuses them all has not opened the door.

    ``self_intersecting_pairs`` is the honest exception. An exact all-pairs
    test is O(n²) and unbounded on a 10⁵-triangle scan, so the count is a
    *sampled* fact: ``None`` means **not measured** — ``self_intersection_method``
    says which — and never *zero*. That is ``holds_at_samples`` discipline
    (``KINEMATICS.md:201-211``) applied to a defect count: the absence of a found
    intersection is evidence, not proof.
    """

    weld_tol_mm: float
    welded_vertex_pairs: int
    degenerate_triangles_dropped: int
    boundary_edge_count: int
    boundary_loop_count: int
    largest_hole_perimeter_mm: float
    nonmanifold_edge_count: int
    nonmanifold_vertex_count: int
    connected_component_count: int
    inverted_normal_triangles: int
    self_intersecting_pairs: int | None
    self_intersection_method: str

    def to_json(self) -> dict[str, JSONValue]:
        """The record as JSON, key-sorted so the sidecar is byte-reproducible."""
        return {
            "weld_tol_mm": self.weld_tol_mm,
            "welded_vertex_pairs": self.welded_vertex_pairs,
            "degenerate_triangles_dropped": self.degenerate_triangles_dropped,
            "boundary_edge_count": self.boundary_edge_count,
            "boundary_loop_count": self.boundary_loop_count,
            "largest_hole_perimeter_mm": self.largest_hole_perimeter_mm,
            "nonmanifold_edge_count": self.nonmanifold_edge_count,
            "nonmanifold_vertex_count": self.nonmanifold_vertex_count,
            "connected_component_count": self.connected_component_count,
            "inverted_normal_triangles": self.inverted_normal_triangles,
            "self_intersecting_pairs": self.self_intersecting_pairs,
            "self_intersection_method": self.self_intersection_method,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JSONValue]) -> MeshQuality:
        """Rebuild the record the parent computed (never a second computation)."""
        pairs = data.get("self_intersecting_pairs")
        return cls(
            weld_tol_mm=float(cast("float", data["weld_tol_mm"])),
            welded_vertex_pairs=int(cast("int", data["welded_vertex_pairs"])),
            degenerate_triangles_dropped=int(cast("int", data["degenerate_triangles_dropped"])),
            boundary_edge_count=int(cast("int", data["boundary_edge_count"])),
            boundary_loop_count=int(cast("int", data["boundary_loop_count"])),
            largest_hole_perimeter_mm=float(cast("float", data["largest_hole_perimeter_mm"])),
            nonmanifold_edge_count=int(cast("int", data["nonmanifold_edge_count"])),
            nonmanifold_vertex_count=int(cast("int", data["nonmanifold_vertex_count"])),
            connected_component_count=int(cast("int", data["connected_component_count"])),
            inverted_normal_triangles=int(cast("int", data["inverted_normal_triangles"])),
            self_intersecting_pairs=None if pairs is None else int(cast("int", pairs)),
            self_intersection_method=str(cast("str", data["self_intersection_method"])),
        )


@dataclass(frozen=True)
class CanonicalMesh:
    """The §1.5 output: the blob, plus the facts canonicalization destroyed.

    ``blob`` is the geometry AND the identity — ``sha256(blob)`` is
    ``mesh_canonical_hash`` and nothing else contributes to it. ``quality`` and
    ``vertex_count_as_read`` are facts about the mesh *before* the weld, so they
    are unrecoverable from a post-weld blob by construction (§1.5.2) and travel
    in a sidecar the hash deliberately excludes.
    """

    blob: bytes
    vertex_count_as_read: int
    quality: MeshQuality
    bbox_mm: tuple[float, float, float]


@dataclass(frozen=True)
class CanonicalPoints:
    """The §1.5 point-cloud output: steps 1-3 and 6-7, no weld, no triangles."""

    blob: bytes
    point_count: int
    bbox_mm: tuple[float, float, float]


def _parse_arrays(
    path: str, data: bytes, kind: MeshKind, fmt: str
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """§1.5 step 1: parse with ``process=False``, refusing what cannot be read.

    ``process=True`` — trimesh's default — merges and REORDERS vertices; the
    render path pins ``process=False`` for exactly this reason
    (``tessellate.py:210``). Measured on a 320-triangle STL: ``process=False``
    gives 960 vertices, ``process=True`` gives 162. Both were stable in-process;
    neither is a *documented* function of the input, which is why the weld below
    is the harness's own and not a library default.
    """
    import trimesh  # local: importing the loader stack is not free

    stream = io.BytesIO(data)
    load_type = fmt
    try:
        loaded = trimesh.load(stream, file_type=load_type, process=False)
    except Exception as exc:  # trimesh raises a wide family on malformed input
        raise MeshReadError(
            f"{path}: not a readable {fmt.upper()} payload ({exc})", reason="mesh_unreadable"
        ) from exc
    if isinstance(loaded, trimesh.Scene):
        # A scene of one (or none) is not a multi-object file — it is a payload
        # the loader could not resolve into a mesh, and giving it the
        # multi-object code would name the wrong defect. The two are told apart
        # here because a reader acts differently on each.
        count = len(loaded.geometry)
        if count < 2:
            raise MeshReadError(
                f"{path}: not a readable {fmt.upper()} payload (the loader produced no "
                "single mesh)",
                reason="mesh_unreadable",
            )
        raise MeshReadError(
            f"{path}: file loads as a scene of {count} geometries; the harness refuses "
            "rather than flattening it (MESH_INGEST.md §1.7)",
            reason="mesh_multi_object",
        )
    vertices = np.asarray(getattr(loaded, "vertices", np.zeros((0, 3))), dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise MeshReadError(
            f"{path}: payload carries no (n, 3) vertex array", reason="mesh_unreadable"
        )
    if kind == "points":
        faces = np.zeros((0, 3), dtype=np.int64)
    else:
        raw_faces = np.asarray(getattr(loaded, "faces", np.zeros((0, 3))), dtype=np.int64)
        if raw_faces.ndim != 2 or raw_faces.shape[1] != 3:
            raise MeshReadError(
                f"{path}: payload carries no (n, 3) triangle array", reason="mesh_unreadable"
            )
        faces = raw_faces
        if faces.shape[0] == 0:
            raise MeshReadError(f"{path}: mesh carries no triangles", reason="mesh_empty")
    if vertices.shape[0] == 0:
        raise MeshReadError(f"{path}: payload carries no vertices", reason="mesh_empty")
    return vertices, faces


def _refuse_non_finite(path: str, vertices: NDArray[np.float64]) -> None:
    """§1.5 step 2. NaN in a scan is common and silently poisons every mean."""
    finite = np.isfinite(vertices).all(axis=1)
    if not bool(finite.all()):
        first = int(np.flatnonzero(~finite)[0])
        raise MeshReadError(
            f"{path}: vertex {first} is not finite; a NaN or Inf coordinate silently "
            "poisons every downstream mean, so it is refused rather than dropped "
            "(MESH_INGEST.md §1.5)",
            reason="mesh_not_finite",
        )


def _weld(
    vertices: NDArray[np.float64], faces: NDArray[np.int64]
) -> tuple[NDArray[np.float64], NDArray[np.int64], NDArray[np.int64], int]:
    """§1.5 steps 4 and 6: quantize-merge, then canonically order.

    The key is ``round(x / MESH_WELD_TOL_MM)`` per coordinate — stated here so a
    reader can reproduce the canonical form from the spec rather than from
    trimesh's source. Vertices then sort by that integer key lexicographically,
    which makes canonical order a documented function of the geometry and
    destroys the file's own vertex order on purpose (§2.4: mesh topology carries
    no identity).
    """
    keys = np.rint(vertices / MESH_WELD_TOL_MM).astype(np.int64)
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    sorted_keys = keys[order]
    if sorted_keys.shape[0] == 0:
        first = np.zeros((0,), dtype=np.bool_)
    else:
        same = np.all(sorted_keys[1:] == sorted_keys[:-1], axis=1)
        first = np.concatenate(([True], ~same))
    group = np.cumsum(first) - 1
    remap = np.empty(vertices.shape[0], dtype=np.int64)
    remap[order] = group
    unique_count = int(first.sum())
    # The surviving coordinate is the FIRST in canonical order, not a mean:
    # averaging welded vertices would move geometry the file never moved.
    welded = vertices[order][first]
    merged_pairs = int(vertices.shape[0] - unique_count)
    return welded, remap[faces] if faces.size else faces, remap, merged_pairs


def _triangle_areas(vertices: NDArray[np.float64], faces: NDArray[np.int64]) -> NDArray[np.float64]:
    if faces.shape[0] == 0:
        return np.zeros((0,), dtype=np.float64)
    a = vertices[faces[:, 0]]
    b = vertices[faces[:, 1]]
    c = vertices[faces[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def _order_triangles(faces: NDArray[np.int64]) -> NDArray[np.int64]:
    """§1.5 step 6: rotate each triangle onto its smallest index, then sort.

    Rotation preserves winding — orientation is a fact about the file and is
    never "fixed" here, only *reported* (``inverted_normal_triangles``).
    """
    if faces.shape[0] == 0:
        return faces
    smallest = np.argmin(faces, axis=1)
    index = (smallest[:, None] + np.arange(3)[None, :]) % 3
    rotated = np.take_along_axis(faces, index, axis=1)
    order = np.lexsort((rotated[:, 2], rotated[:, 1], rotated[:, 0]))
    return rotated[order]


def _serialize(
    magic: bytes, vertices: NDArray[np.float64], faces: NDArray[np.int64], factor: float
) -> bytes:
    """§1.5 step 7: the fixed 32-byte header, then float64 verts, int32 tris."""
    header = _BLOB_HEADER.pack(magic, MESH_BLOB_VERSION, vertices.shape[0], faces.shape[0], factor)
    body = np.ascontiguousarray(vertices, dtype="<f8").tobytes()
    tail = np.ascontiguousarray(faces, dtype="<i4").tobytes() if faces.size else b""
    return header + body + tail


def _deserialize(
    blob: bytes, magic: bytes, source: str
) -> tuple[NDArray[np.float64], NDArray[np.int64], float]:
    if len(blob) < _BLOB_HEADER.size:
        raise MeshReadError(f"{source}: canonical blob is truncated", reason="mesh_unreadable")
    found, version, n_vertices, n_faces, factor = cast(
        "tuple[bytes, int, int, int, float]", _BLOB_HEADER.unpack_from(blob, 0)
    )
    if found != magic or version != MESH_BLOB_VERSION:
        raise MeshReadError(
            f"{source}: canonical blob header is {found!r} v{version}, expected "
            f"{magic!r} v{MESH_BLOB_VERSION}",
            reason="mesh_unreadable",
        )
    offset = _BLOB_HEADER.size
    vertex_bytes = n_vertices * 24
    face_bytes = n_faces * 12
    if len(blob) != offset + vertex_bytes + face_bytes:
        raise MeshReadError(
            f"{source}: canonical blob length disagrees with its header",
            reason="mesh_unreadable",
        )
    vertices = np.frombuffer(blob, dtype="<f8", count=n_vertices * 3, offset=offset).reshape(
        n_vertices, 3
    )
    faces = np.frombuffer(
        blob, dtype="<i4", count=n_faces * 3, offset=offset + vertex_bytes
    ).reshape(n_faces, 3)
    # A corrupted blob must refuse BY NAME. Without this an out-of-range index
    # reaches numpy as an ``IndexError`` from inside the fact computation — an
    # opaque crash where the whole point of this layer is that a payload it
    # cannot trust is refused, never half-read. The blob is staged read-only,
    # so this fires on real corruption rather than on ordinary use, which is
    # exactly when an unnamed failure is least useful.
    if n_faces and (faces.min() < 0 or faces.max() >= n_vertices):
        raise MeshReadError(
            f"{source}: canonical blob has a triangle index outside its {n_vertices} "
            "vertices; the payload is corrupt",
            reason="mesh_unreadable",
        )
    return (
        np.array(vertices, dtype=np.float64),
        np.array(faces, dtype=np.int64),
        float(factor),
    )


def deserialize_mesh(
    blob: bytes, *, source: str = "<hmesh>"
) -> tuple[NDArray[np.float64], NDArray[np.int64], float]:
    """``(vertices, triangles, unit factor)`` of a canonical mesh blob."""
    return _deserialize(blob, MESH_BLOB_MAGIC, source)


def deserialize_points(blob: bytes, *, source: str = "<hpts>") -> tuple[NDArray[np.float64], float]:
    """``(points, unit factor)`` of a canonical point-cloud blob."""
    vertices, _, factor = _deserialize(blob, POINTS_BLOB_MAGIC, source)
    return vertices, factor


def _bbox(vertices: NDArray[np.float64]) -> tuple[float, float, float]:
    if vertices.shape[0] == 0:
        return (0.0, 0.0, 0.0)
    extent = vertices.max(axis=0) - vertices.min(axis=0)
    return (float(extent[0]), float(extent[1]), float(extent[2]))


def canonicalize_mesh(path: str, data: bytes, units: object) -> CanonicalMesh:
    """The whole §1.5 pipeline for a mesh, in the parent, outside the sandbox.

    Steps 1-7 in order, every one of them named because every one is a
    decision: parse ``process=False``, refuse non-finite, scale by the declared
    unit, weld, drop degenerates, canonically order, serialize. The dropped and
    merged counts are RECORDED on the quality record — never silently absorbed —
    and an all-degenerate file is ``mesh_degenerate_only`` rather than an empty
    success.
    """
    factor = unit_factor(units)
    kind, fmt = sniff_format(path, data)
    if kind != "mesh":
        raise MeshReadError(
            f"{path}: {fmt} is a point-cloud format; use import_point_cloud (MESH_INGEST.md §2.3)",
            reason="mesh_format_mismatch",
        )
    _refuse_multi_object(path, data, fmt)
    count_ceiling_check(path, data, kind, fmt)
    vertices, faces = _parse_arrays(path, data, kind, fmt)
    _refuse_non_finite(path, vertices)
    vertex_count_as_read = int(vertices.shape[0])
    scaled = vertices * factor
    welded, remapped, _, merged_pairs = _weld(scaled, faces)
    areas = _triangle_areas(welded, remapped)
    distinct = (
        (remapped[:, 0] != remapped[:, 1])
        & (remapped[:, 1] != remapped[:, 2])
        & (remapped[:, 0] != remapped[:, 2])
    )
    keep = distinct & (areas > MESH_DEGENERATE_AREA_MM2)
    dropped = int(remapped.shape[0] - int(keep.sum()))
    kept = remapped[keep]
    if kept.shape[0] == 0:
        raise MeshReadError(
            f"{path}: every one of the {remapped.shape[0]} triangles is degenerate at "
            f"weld tolerance {MESH_WELD_TOL_MM} mm; there is no surface here "
            "(MESH_INGEST.md §1.7)",
            reason="mesh_degenerate_only",
        )
    ordered = _order_triangles(kept)
    quality = mesh_quality(
        welded,
        ordered,
        welded_vertex_pairs=merged_pairs,
        degenerate_triangles_dropped=dropped,
    )
    return CanonicalMesh(
        blob=_serialize(MESH_BLOB_MAGIC, welded, ordered, factor),
        vertex_count_as_read=vertex_count_as_read,
        quality=quality,
        bbox_mm=_bbox(welded),
    )


def canonicalize_points(path: str, data: bytes, units: object) -> CanonicalPoints:
    """§1.5 for a point cloud: steps 1-3 and 6-7, no welding, no triangles.

    A point cloud is not a shape (§2.3) and this pipeline deliberately does not
    pretend it could become one: nothing is welded (two coincident samples are
    two samples), nothing is triangulated, and no topology is claimed.
    """
    factor = unit_factor(units)
    kind, fmt = sniff_format(path, data)
    if kind != "points":
        raise MeshReadError(
            f"{path}: {fmt} is a mesh format; use import_mesh (MESH_INGEST.md §2.3)",
            reason="mesh_format_mismatch",
        )
    count_ceiling_check(path, data, kind, fmt)
    vertices, _ = _parse_arrays(path, data, kind, fmt)
    _refuse_non_finite(path, vertices)
    scaled = vertices * factor
    keys = np.rint(scaled / MESH_WELD_TOL_MM).astype(np.int64)
    order = np.lexsort((keys[:, 2], keys[:, 1], keys[:, 0]))
    ordered = scaled[order]
    return CanonicalPoints(
        blob=_serialize(POINTS_BLOB_MAGIC, ordered, np.zeros((0, 3), dtype=np.int64), factor),
        point_count=int(ordered.shape[0]),
        bbox_mm=_bbox(ordered),
    )


# --------------------------------------------------------------------------
# §5.3 sections: a plane through a triangle soup, and the hole it must not close


def section_polylines(
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
    *,
    origin: Sequence[float],
    normal: Sequence[float],
    spacing: float | None = None,
    source: str = "<hmesh>",
) -> tuple[SectionPolyline, ...]:
    """Ordered contours where a plane crosses the canonical mesh (§5.3).

    ``geom.measure.section`` takes an ``AnyShape`` and returns faces; it cannot
    take a mesh, and this is the plane/triangle intersection that can — the
    first half of the §5.2 socket path, whose whole point is that the scan is
    *measured* and the socket is *authored*.

    Two properties carry the honesty of this stage, and both are structural
    rather than documented:

    * **An open contour stays open.** Where the plane crosses a hole in the
      scan the walk runs out of segments, and the contour comes back
      ``closed=False`` flagged :data:`OPEN_SECTION_CONTOUR`. Joining its two
      ends would fabricate limb surface the scanner never saw, at exactly the
      place a socket would press. Nothing here closes a contour.
    * **A plane that misses is a refusal, not an empty success.** No crossing
      triangle raises ``empty_section``; an empty tuple would read as "the
      section is empty", which is a claim about the geometry rather than about
      the plane.

    Determinism (§8 Tier 1): every crossing point is identified by the mesh
    *edge* it crosses, with the edge's endpoints in ascending index order, so
    the two triangles sharing an edge compute bit-identical coordinates and the
    walk is a pure function of canonical triangle order. ``spacing`` resamples
    each contour by arc length and is RECORDED on the record
    (:attr:`SectionPolyline.point_spacing_mm`); ``None`` — the default — means
    the mesh's own crossings, unresampled, which is what makes a hand-computable
    fixture hand-computable.
    """
    axis = np.asarray(normal, dtype=np.float64).reshape(3)
    length = float(np.linalg.norm(axis))
    if not np.isfinite(length) or length == 0.0:
        raise MeshOperationError(
            f"{source}: a section plane needs a non-zero finite normal, got {tuple(axis)!r}",
            reason="empty_section",
        )
    axis = axis / length
    base = np.asarray(origin, dtype=np.float64).reshape(3)
    signed = (vertices - base) @ axis

    #: ``key -> point``. A key is ``(-1, i)`` for the mesh vertex ``i`` lying on
    #: the plane and ``(lo, hi)`` for a crossing of the edge ``lo < hi``.
    points: dict[tuple[int, int], tuple[float, float, float]] = {}
    segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
    coplanar = 0

    for tri in faces:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        keys: list[tuple[int, int]] = []
        for a, b in ((i0, i1), (i1, i2), (i2, i0)):
            da, db = float(signed[a]), float(signed[b])
            if da == 0.0:
                _offer(keys, points, (-1, a), vertices[a])
            if db == 0.0:
                _offer(keys, points, (-1, b), vertices[b])
            if da == 0.0 or db == 0.0 or (da > 0.0) == (db > 0.0):
                continue
            lo, hi = (a, b) if a < b else (b, a)
            dlo, dhi = float(signed[lo]), float(signed[hi])
            t = dlo / (dlo - dhi)
            crossing = vertices[lo] + t * (vertices[hi] - vertices[lo])
            _offer(keys, points, (lo, hi), crossing)
        if len(keys) == 2:
            segments.append((keys[0], keys[1]))
        elif len(keys) > 2:
            # Every vertex of this triangle is on the plane: the "section" of a
            # coplanar facet is the facet, not a curve. Counted, never emitted
            # as a degenerate contour — a zero-length polyline in the middle of
            # a walk is the kind of thing that silently closes a hole later.
            coplanar += 1
    if not segments:
        raise MeshOperationError(
            f"{source}: the plane through {tuple(float(v) for v in base)} with normal "
            f"{tuple(float(v) for v in axis)} crosses no triangle of this mesh "
            f"({faces.shape[0]} triangles, {coplanar} coplanar); a section that "
            "misses is a refusal, not an empty success (MESH_INGEST.md §5.3)",
            reason="empty_section",
        )
    return tuple(_resample(contour, spacing) for contour in _assemble_contours(segments, points))


def _offer(
    keys: list[tuple[int, int]],
    points: dict[tuple[int, int], tuple[float, float, float]],
    key: tuple[int, int],
    value: NDArray[np.float64],
) -> None:
    """Record one crossing point, deduplicated by its key within a triangle."""
    points.setdefault(key, (float(value[0]), float(value[1]), float(value[2])))
    if key not in keys:
        keys.append(key)


def _assemble_contours(
    segments: Sequence[tuple[tuple[int, int], tuple[int, int]]],
    points: Mapping[tuple[int, int], tuple[float, float, float]],
) -> list[tuple[tuple[tuple[float, float, float], ...], bool]]:
    """Chain crossing segments into ordered contours, opening where they open.

    Open contours are walked FIRST, from their degree-1 ends, so a hole's two
    loose ends can never be swept into a neighbouring closed loop by walk
    order. What remains after that is closed by construction; a walk that comes
    back to its start says so, and one that does not is reported open.
    """
    # ``adjacency[key]`` is the list of (other endpoint, segment id) leaving
    # ``key``, in first-seen order; a segment id is consumed once and is
    # therefore visible as spent from BOTH of its ends.
    adjacency: dict[tuple[int, int], list[tuple[tuple[int, int], int]]] = {}
    order: list[tuple[int, int]] = []
    for segment_id, (a, b) in enumerate(segments):
        if a == b:
            continue
        for key in (a, b):
            if key not in adjacency:
                adjacency[key] = []
                order.append(key)
        adjacency[a].append((b, segment_id))
        adjacency[b].append((a, segment_id))

    used: set[int] = set()
    contours: list[tuple[tuple[tuple[float, float, float], ...], bool]] = []
    # Loose ends first: a hole's two degree-1 ends must start their own walk, or
    # a walk that happened to arrive there first would sweep them into a
    # neighbouring loop and report a closed contour where the scan has a hole.
    starts = [key for key in order if len(adjacency[key]) == 1] + order
    for start in starts:
        if _degree_left(adjacency, start, used) == 0:
            continue
        walk = _walk(adjacency, points, start, used)
        if walk is not None:
            contours.append(walk)
    return contours


def _degree_left(
    adjacency: Mapping[tuple[int, int], list[tuple[tuple[int, int], int]]],
    key: tuple[int, int],
    used: set[int],
) -> int:
    """How many segments still leave ``key``."""
    return sum(1 for _, segment_id in adjacency[key] if segment_id not in used)


def _walk(
    adjacency: Mapping[tuple[int, int], list[tuple[tuple[int, int], int]]],
    points: Mapping[tuple[int, int], tuple[float, float, float]],
    start: tuple[int, int],
    used: set[int],
) -> tuple[tuple[tuple[float, float, float], ...], bool] | None:
    """One contour from ``start``, consuming each segment exactly once."""
    chain: list[tuple[int, int]] = [start]
    current = start
    while True:
        step = _next_step(adjacency, current, used)
        if step is None:
            break
        chain.append(step)
        current = step
        if step == start:
            break
    if len(chain) < 2:
        return None
    closed = chain[-1] == start and len(chain) > 2
    keys = chain[:-1] if closed else chain
    return (tuple(points[key] for key in keys), closed)


def _next_step(
    adjacency: Mapping[tuple[int, int], list[tuple[tuple[int, int], int]]],
    current: tuple[int, int],
    used: set[int],
) -> tuple[int, int] | None:
    """The first unconsumed segment leaving ``current``, marking it consumed."""
    for neighbour, segment_id in adjacency[current]:
        if segment_id in used:
            continue
        used.add(segment_id)
        return neighbour
    return None


def _resample(
    contour: tuple[tuple[tuple[float, float, float], ...], bool], spacing: float | None
) -> SectionPolyline:
    """Wrap one walked contour, resampling by arc length when a spacing is declared."""
    raw, closed = contour
    if spacing is None or spacing <= 0.0:
        return SectionPolyline(
            points=raw,
            closed=closed,
            flag=None if closed else OPEN_SECTION_CONTOUR,
            point_spacing_mm=None,
        )
    # A closed contour's record does not repeat its first point; the arc-length
    # walk must see the wrap-around segment or the resampling loses it.
    walked = (*raw, raw[0]) if closed else raw
    loop = np.asarray(walked, dtype=np.float64)
    steps = np.linalg.norm(np.diff(loop, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(steps)])
    total = float(arc[-1])
    if total <= 0.0:
        return SectionPolyline(
            points=raw,
            closed=closed,
            flag=None if closed else OPEN_SECTION_CONTOUR,
            point_spacing_mm=spacing,
        )
    count = max(2, int(np.ceil(total / spacing)) + (0 if closed else 1))
    targets = np.linspace(0.0, total, count, endpoint=not closed)
    resampled = np.stack([np.interp(targets, arc, loop[:, axis]) for axis in range(3)], axis=1)
    return SectionPolyline(
        points=tuple((float(p[0]), float(p[1]), float(p[2])) for p in resampled),
        closed=closed,
        flag=None if closed else OPEN_SECTION_CONTOUR,
        point_spacing_mm=spacing,
    )


# --------------------------------------------------------------------------
# §3 quality: exact combinatorial facts in numpy


class _UnionFind:
    """Plain union-find; the component counts below are the only consumers."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _undirected_edges(faces: NDArray[np.int64]) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """``(unique undirected edges, use count)`` over the triangle set."""
    pairs = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=0)
    ordered = np.sort(pairs, axis=1)
    unique, counts = np.unique(ordered, axis=0, return_counts=True)
    return unique, counts


def _boundary_loops(vertices: NDArray[np.float64], edges: NDArray[np.int64]) -> tuple[int, float]:
    """Loop count and the largest loop perimeter, over boundary edges alone.

    "Loop" is the connected component of the boundary-edge graph, not a walk: a
    hole whose boundary pinches at a vertex is still one hole, and calling it
    two would over-report a defect the file does not have.
    """
    if edges.shape[0] == 0:
        return 0, 0.0
    labels = {int(v): i for i, v in enumerate(np.unique(edges))}
    union = _UnionFind(len(labels))
    for a, b in edges:
        union.union(labels[int(a)], labels[int(b)])
    lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    perimeters: dict[int, float] = {}
    for index, (a, _b) in enumerate(edges):
        root = union.find(labels[int(a)])
        perimeters[root] = perimeters.get(root, 0.0) + float(lengths[index])
    return len(perimeters), max(perimeters.values())


def _nonmanifold_vertices(faces: NDArray[np.int64], vertex_count: int) -> int:
    """Vertices whose triangle fan is not a disc (open path or closed cycle).

    The link of a manifold vertex is a single path (a boundary vertex) or a
    single cycle (an interior one). Anything else — two fans meeting at a point,
    a bowtie — is non-manifold, and is reported rather than repaired.
    """
    link: dict[int, list[tuple[int, int]]] = {}
    for tri in faces:
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        link.setdefault(a, []).append((b, c))
        link.setdefault(b, []).append((c, a))
        link.setdefault(c, []).append((a, b))
    bad = 0
    for _vertex, opposite in link.items():
        degree: dict[int, int] = {}
        nodes: dict[int, int] = {}
        for u, v in opposite:
            for node in (u, v):
                if node not in nodes:
                    nodes[node] = len(nodes)
            degree[u] = degree.get(u, 0) + 1
            degree[v] = degree.get(v, 0) + 1
        union = _UnionFind(len(nodes))
        for u, v in opposite:
            union.union(nodes[u], nodes[v])
        components = len({union.find(index) for index in nodes.values()})
        if components != 1 or any(count > 2 for count in degree.values()):
            bad += 1
    del vertex_count
    return bad


def _inverted_normals(faces: NDArray[np.int64]) -> int:
    """Triangles wound against their component's majority (§3), never flipped.

    Two triangles sharing an edge agree when they traverse it in OPPOSITE
    directions. Propagating that relation over the face-adjacency graph gives
    each face a parity; the minority parity in each component is the count.
    Which majority is "right" is not a fact about the file, so the harness
    reports the disagreement and never resolves it.
    """
    if faces.shape[0] == 0:
        return 0
    directed: dict[tuple[int, int], list[int]] = {}
    for index, tri in enumerate(faces):
        a, b, c = int(tri[0]), int(tri[1]), int(tri[2])
        for u, v in ((a, b), (b, c), (c, a)):
            directed.setdefault((min(u, v), max(u, v)), []).append(
                index if u < v else ~index  # ~index encodes "traversed high->low"
            )
    adjacency: dict[int, list[tuple[int, int]]] = {}
    for entries in directed.values():
        if len(entries) != 2:
            continue
        first, second = entries
        i, j = (first if first >= 0 else ~first), (second if second >= 0 else ~second)
        same_direction = (first >= 0) == (second >= 0)
        parity = 1 if same_direction else 0  # same direction ⇒ flipped relative
        adjacency.setdefault(i, []).append((j, parity))
        adjacency.setdefault(j, []).append((i, parity))
    seen: dict[int, int] = {}
    inverted = 0
    for start in range(faces.shape[0]):
        if start in seen:
            continue
        seen[start] = 0
        stack = [start]
        component = [start]
        while stack:
            node = stack.pop()
            for neighbour, parity in adjacency.get(node, ()):
                flag = seen[node] ^ parity
                if neighbour not in seen:
                    seen[neighbour] = flag
                    stack.append(neighbour)
                    component.append(neighbour)
        ones = sum(seen[member] for member in component)
        inverted += min(ones, len(component) - ones)
    return inverted


def _self_intersections(
    vertices: NDArray[np.float64], faces: NDArray[np.int64]
) -> tuple[int | None, str]:
    """Sampled self-intersection: a uniform grid, then EXACT pairs inside it.

    The grid is a candidate filter, not an approximation — every pair it yields
    is tested exactly — but the *ceiling* on candidate pairs is what makes this
    a sampled fact. Above :func:`mesh_selfx_pair_max` the answer is ``None``
    with method ``not_evaluated_ceiling``: not measured, and never reported as
    zero.
    """
    count = faces.shape[0]
    budget = mesh_selfx_pair_max()
    if count < 2:
        return 0, "uniform_grid_exact_pairs"
    corners = vertices[faces]
    lows = corners.min(axis=1)
    highs = corners.max(axis=1)
    spans = highs - lows
    # Cell size from the MEDIAN triangle, not the largest: one enormous
    # triangle sizing the grid would collapse every other triangle into one
    # cell and turn the filter back into all-pairs. The cost of that choice is
    # that the big triangle spans many cells, which the insertion budget below
    # is what bounds.
    typical = float(np.median(spans)) if spans.size else 0.0
    cell = max(typical * 2.0, MESH_WELD_TOL_MM)
    low_cells = np.floor(lows / cell).astype(np.int64)
    high_cells = np.floor(highs / cell).astype(np.int64)
    insertions = int(np.prod(high_cells - low_cells + 1, axis=1).sum())
    if insertions > budget:
        return None, "not_evaluated_ceiling"
    cells: dict[tuple[int, int, int], list[int]] = {}
    for index in range(count):
        for x in range(int(low_cells[index, 0]), int(high_cells[index, 0]) + 1):
            for y in range(int(low_cells[index, 1]), int(high_cells[index, 1]) + 1):
                for z in range(int(low_cells[index, 2]), int(high_cells[index, 2]) + 1):
                    cells.setdefault((x, y, z), []).append(index)
    candidates: set[tuple[int, int]] = set()
    for members in cells.values():
        size = len(members)
        if len(candidates) + size * (size - 1) // 2 > budget:
            return None, "not_evaluated_ceiling"
        for i in range(size):
            for j in range(i + 1, size):
                a, b = members[i], members[j]
                candidates.add((a, b) if a < b else (b, a))
    found = 0
    for a, b in candidates:
        if set(faces[a].tolist()) & set(faces[b].tolist()):
            continue  # shares a vertex: adjacency is not an intersection
        if _triangles_intersect(corners[a], corners[b]):
            found += 1
    return found, "uniform_grid_exact_pairs"


def _triangles_intersect(a: NDArray[np.float64], b: NDArray[np.float64]) -> bool:
    """Exact triangle/triangle overlap by segment-vs-triangle crossing.

    Each of the six edges is tested against the other triangle's plane; a
    crossing point inside the triangle is an intersection. Coplanar overlap is
    NOT detected, and that omission is stated rather than hidden — it makes the
    count a lower bound, which is the direction a defect count may honestly err
    when the method field says the measurement was sampled.
    """
    return _edges_cross(a, b) or _edges_cross(b, a)


def _edges_cross(edges_of: NDArray[np.float64], target: NDArray[np.float64]) -> bool:
    normal = np.cross(target[1] - target[0], target[2] - target[0])
    norm = float(np.linalg.norm(normal))
    if norm <= 0.0:
        return False
    normal = normal / norm
    offsets = (edges_of - target[0]) @ normal
    for i, j in ((0, 1), (1, 2), (2, 0)):
        d0, d1 = float(offsets[i]), float(offsets[j])
        if (d0 > 0.0 and d1 > 0.0) or (d0 < 0.0 and d1 < 0.0) or (d0 == 0.0 and d1 == 0.0):
            continue
        t = d0 / (d0 - d1)
        point = edges_of[i] + t * (edges_of[j] - edges_of[i])
        if _point_in_triangle(point, target, normal):
            return True
    return False


def _point_in_triangle(
    point: NDArray[np.float64], tri: NDArray[np.float64], normal: NDArray[np.float64]
) -> bool:
    for i, j in ((0, 1), (1, 2), (2, 0)):
        edge = tri[j] - tri[i]
        if float(np.dot(np.cross(edge, point - tri[i]), normal)) < -1e-12:
            return False
    return True


def mesh_quality(
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64],
    *,
    welded_vertex_pairs: int,
    degenerate_triangles_dropped: int,
) -> MeshQuality:
    """The §3 record over a welded, canonically ordered mesh.

    Computed ONCE, in the parent, so the worker reports the numbers the
    canonicalizer actually observed rather than a second computation that might
    disagree. The first two fields are passed in because they are *differences*
    between the as-read mesh and this one and cannot be recovered from it.
    """
    edges, counts = _undirected_edges(faces)
    boundary = edges[counts == 1]
    loops, perimeter = _boundary_loops(vertices, boundary)
    union = _UnionFind(int(vertices.shape[0]))
    for tri in faces:
        union.union(int(tri[0]), int(tri[1]))
        union.union(int(tri[1]), int(tri[2]))
    used = np.unique(faces) if faces.size else np.zeros((0,), dtype=np.int64)
    components = len({union.find(int(index)) for index in used})
    pairs, method = _self_intersections(vertices, faces)
    return MeshQuality(
        weld_tol_mm=MESH_WELD_TOL_MM,
        welded_vertex_pairs=welded_vertex_pairs,
        degenerate_triangles_dropped=degenerate_triangles_dropped,
        boundary_edge_count=int(boundary.shape[0]),
        boundary_loop_count=loops,
        largest_hole_perimeter_mm=perimeter,
        nonmanifold_edge_count=int((counts >= 3).sum()),
        nonmanifold_vertex_count=_nonmanifold_vertices(faces, int(vertices.shape[0])),
        connected_component_count=components,
        inverted_normal_triangles=_inverted_normals(faces),
        self_intersecting_pairs=pairs,
        self_intersection_method=method,
    )


# --------------------------------------------------------------------------
# §2.2 / §2.3 the records, and the field-naming rule that does the work


@dataclass(frozen=True)
class MeshAsset:
    """What a mesh IS in the type system (``MESH_INGEST.md`` §2.2).

    The record deliberately has **no field named** ``volume``, ``sealed`` or
    ``genus``, and that is the whole mechanism — ``KINEMATICS.md:201-211`` is the
    precedent, where a sweep emits ``holds_at_samples`` and never ``holds``
    because "the verdict name says so" is stronger than a note asking the reader
    to remember. Applied to measurement:

    * ``tessellated_volume_mm3`` — the POLYHEDRON's volume, systematically low
      because facets are inscribed (measured: -0.36% at 0.05 mm deflection). It
      measures the sample, not the object, and is ``None`` — not zero, not a
      number — when the mesh is not watertight, because a volume computed from
      an open surface is not a small error, it is not a volume.
    * ``watertight_at_weld_tol`` — a combinatorial fact about edge-manifoldness
      **at a stated tolerance**, which the name carries. ``geom.metrics.is_sealed``
      is a B-rep predicate about shells and measured True on a shape whose
      ``BRepCheck_Analyzer.IsValid()`` is False; the two words must not be
      interchangeable.
    * ``euler_characteristic`` — the raw ``V - E + F`` of the welded mesh,
      reported as a fact about the FILE. On a scan, genus counts the scanner's
      bridged folds and artifacts: the genus of a scan is a property of the
      scanner, not of the limb.

    ``V`` is :attr:`vertex_count`, every welded vertex including any left
    unreferenced by the degenerate drop — stated because χ is only checkable if
    the reader knows which V was used.
    """

    source_path: str
    units_declared: str
    canonical_hash: str
    weld_tol_mm: float
    vertex_count_as_read: int
    vertex_count: int
    triangle_count: int
    bbox_mm: tuple[float, float, float]
    tessellated_volume_mm3: float | None
    tessellated_area_mm2: float
    watertight_at_weld_tol: bool
    euler_characteristic: int
    quality: MeshQuality

    def to_json(self) -> dict[str, JSONValue]:
        """The asset as JSON (``heph scan --json``, build output, reviewer context)."""
        return {
            "source_path": self.source_path,
            "units_declared": self.units_declared,
            "canonical_hash": self.canonical_hash,
            "weld_tol_mm": self.weld_tol_mm,
            "vertex_count_as_read": self.vertex_count_as_read,
            "vertex_count": self.vertex_count,
            "triangle_count": self.triangle_count,
            "bbox_mm": list(self.bbox_mm),
            "tessellated_volume_mm3": self.tessellated_volume_mm3,
            "tessellated_area_mm2": self.tessellated_area_mm2,
            "watertight_at_weld_tol": self.watertight_at_weld_tol,
            "euler_characteristic": self.euler_characteristic,
            "quality": self.quality.to_json(),
        }


@dataclass(frozen=True)
class PointCloudAsset:
    """A distinct kind, because a point cloud is not a shape (§2.3).

    It has no volume, no area, no watertightness and no topology, and the record
    carries none of those names. It is also the sharpest silent-failure risk in
    the stage: ``geom.compare.surface_distance`` on a shape with no faces
    returns zeros with zero sample counts (``compare.py:599-608``) rather than
    refusing — honest only because the counts are in the record, and not honest
    enough for something that will be handed a point cloud by mistake. Passing
    one where a shape is expected is refused ``point_cloud_not_a_shape`` at the
    boundary, never silently sampled to zeros.
    """

    source_path: str
    units_declared: str
    canonical_hash: str
    point_count: int
    bbox_mm: tuple[float, float, float]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "source_path": self.source_path,
            "units_declared": self.units_declared,
            "canonical_hash": self.canonical_hash,
            "point_count": self.point_count,
            "bbox_mm": list(self.bbox_mm),
        }


# --------------------------------------------------------------------------
# §1.5.2 the sidecar, and the asset constructors that read it


def facts_to_json(canonical: CanonicalMesh) -> str:
    """The ``.hmesh.facts`` sidecar text: sorted keys, round-trippable floats.

    It exists because ``welded_vertex_pairs``, ``degenerate_triangles_dropped``
    and ``vertex_count_as_read`` are facts about the mesh BEFORE the weld, and
    the canonical blob is post-weld: a deserializer inside the sandbox cannot
    recover them from it, by construction. Specifying a record whose fields
    cannot be computed where they are built is an unimplementable clause, so the
    parent writes them down beside the blob.

    It is **explicitly not part of** ``mesh_canonical_hash``. The hash names
    geometry; the sidecar reports history.
    """
    payload: dict[str, JSONValue] = {
        "vertex_count_as_read": canonical.vertex_count_as_read,
        "bbox_mm": list(canonical.bbox_mm),
        "quality": canonical.quality.to_json(),
    }
    return json.dumps(payload, sort_keys=True)


def points_facts_to_json(canonical: CanonicalPoints) -> str:
    """The ``.hpts.facts`` sidecar: a point cloud stages two files on the same rule.

    Every field here IS recoverable from the blob — a point cloud has no
    pre-canonical facts to lose, because nothing is welded and nothing is
    dropped. It is written anyway so the two kinds stage identically and the
    §1.5.2 separation (mutate the sidecar, the hash does not move) is one rule
    rather than two.
    """
    payload: dict[str, JSONValue] = {
        "point_count": canonical.point_count,
        "bbox_mm": list(canonical.bbox_mm),
    }
    return json.dumps(payload, sort_keys=True)


def facts_from_json(text: str) -> tuple[int, tuple[float, float, float], MeshQuality]:
    """``(vertex_count_as_read, bbox, quality)`` from a sidecar's text."""
    try:
        raw = cast("dict[str, JSONValue]", json.loads(text))
        bbox = cast("Sequence[float]", raw["bbox_mm"])
        return (
            int(cast("int", raw["vertex_count_as_read"])),
            (float(bbox[0]), float(bbox[1]), float(bbox[2])),
            MeshQuality.from_json(cast("Mapping[str, JSONValue]", raw["quality"])),
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MeshReadError(
            f"staged mesh facts sidecar is unreadable: {exc}", reason="mesh_unreadable"
        ) from exc


def mesh_asset_from_staged(blob: bytes, facts: str, *, source_path: str, units: str) -> MeshAsset:
    """Assemble a :class:`MeshAsset` from the two staged files (§1.5.2, §7.1).

    Provenance, stated because the record is assembled from two sources:
    ``canonical_hash``, the counts, the tessellated figures,
    ``watertight_at_weld_tol`` and ``euler_characteristic`` are RECOMPUTED from
    the blob and are therefore checkable against it; ``vertex_count_as_read``
    and ``quality`` are READ from the sidecar, because they are facts about the
    pre-canonical mesh the blob no longer contains. No field is guessed, and
    none is recomputed from a different mesh than the one the hash names.
    """
    vertices, faces, _factor = _deserialize(blob, MESH_BLOB_MAGIC, source_path)
    vertex_count_as_read, _bbox_from_facts, quality = facts_from_json(facts)
    _edges, counts = _undirected_edges(faces)
    watertight = bool(faces.shape[0] > 0 and bool((counts == 2).all()))
    areas = _triangle_areas(vertices, faces)
    volume: float | None = None
    if watertight:
        a = vertices[faces[:, 0]]
        b = vertices[faces[:, 1]]
        c = vertices[faces[:, 2]]
        volume = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
    return MeshAsset(
        source_path=source_path,
        units_declared=units,
        canonical_hash="sha256:" + hashlib.sha256(blob).hexdigest(),
        weld_tol_mm=MESH_WELD_TOL_MM,
        vertex_count_as_read=vertex_count_as_read,
        vertex_count=int(vertices.shape[0]),
        triangle_count=int(faces.shape[0]),
        bbox_mm=_bbox(vertices),
        tessellated_volume_mm3=volume,
        tessellated_area_mm2=float(areas.sum()),
        watertight_at_weld_tol=watertight,
        euler_characteristic=int(vertices.shape[0]) - int(counts.shape[0]) + int(faces.shape[0]),
        quality=quality,
    )


def point_cloud_asset_from_staged(blob: bytes, *, source_path: str, units: str) -> PointCloudAsset:
    """Assemble a :class:`PointCloudAsset` from its staged canonical blob."""
    points, _factor = deserialize_points(blob, source=source_path)
    return PointCloudAsset(
        source_path=source_path,
        units_declared=units,
        canonical_hash="sha256:" + hashlib.sha256(blob).hexdigest(),
        point_count=int(points.shape[0]),
        bbox_mm=_bbox(points),
    )


# --------------------------------------------------------------------------
# §6.3 direction B — the mesh-side nearest-point structure
#
# The existing B-rep path cannot be used and the numbers say why: every triangle
# is a face, ``_face_samples`` has a floor of four samples per face, and
# ``BRepExtrema_DistShapeShape`` against a 4002-face target measures 54.6 ms/pt
# against 0.05 ms/pt on a smooth one — ~515 s for ONE direction of ONE small
# mesh, growing as O(n_tri²). So this direction is built mesh-side, in numpy,
# and it is **exact**: the kd-tree only chooses candidates.

#: Per-query ceiling on candidate triangles (§6.3 step 5). A pathological mesh
#: with one enormous triangle inflates ``L_max`` and therefore the query radius;
#: above this the exact refinement is abandoned BY NAME rather than ground
#: through. Like :data:`MESH_SELFX_PAIR_MAX` this is a measurement-effort
#: ceiling, not a safety one: lowering it can only move the record from an exact
#: number to a declared upper bound, never to a false zero.
SCAN_CANDIDATE_MAX: Final[int] = 4096
SCAN_CANDIDATE_MAX_ENV: Final[str] = "HEPHAESTUS_SCAN_CANDIDATE_MAX"

#: The exact method: kd-tree candidates, point-to-triangle refinement (§6.3).
SCAN_METHOD_EXACT: Final[str] = "kdtree_bound_exact_triangle"

#: The declared fallback: the vertex nearest-neighbour distance, which is a
#: SOUND UPPER BOUND on the true point-to-surface distance because the nearest
#: vertex lies on some triangle. Measured bias for reference: vertex-NN mean
#: 0.409, centroid-NN 0.372, true point-to-surface 0.300 — always an
#: over-estimate, bounded by the mesh's own edge length.
SCAN_METHOD_BOUND: Final[str] = "vertex_nn_upper_bound"

#: The two method strings, closed. A third would be a different measurement and
#: the Tier 2 determinism clause treats a differing method string as a failure,
#: not as a rounding difference.
SCAN_DISTANCE_METHODS: Final[tuple[str, ...]] = (SCAN_METHOD_EXACT, SCAN_METHOD_BOUND)


def scan_candidate_max() -> int:
    """Effective :data:`SCAN_CANDIDATE_MAX` — overridable in both directions.

    Same asymmetry :func:`mesh_selfx_pair_max` states: this is effort, not
    safety. Lowering it can only trade an exact number for a named bound.
    """
    raw = os.environ.get(SCAN_CANDIDATE_MAX_ENV)
    if raw is None:
        return SCAN_CANDIDATE_MAX
    try:
        return max(1, int(raw))
    except ValueError:
        return SCAN_CANDIDATE_MAX


@dataclass(frozen=True)
class MeshDistances:
    """Distances from a set of query points to a mesh, with the method named.

    ``exact`` is the whole record's property and not a per-point one: a mean
    formed from some exact distances and some bounds is a number with no defined
    meaning, which is the same reason ``ScanDistance`` has no ``chamfer_mm``. So
    one query point over the candidate ceiling abandons the refinement for the
    whole direction, and :attr:`method` says which measurement this is.
    """

    distances: NDArray[np.float64]
    exact: bool
    method: str
    candidate_max: int
    max_candidates: int

    @property
    def refusal(self) -> str | None:
        """``scan_neighborhood_overflow`` when the exact refinement was dropped."""
        return None if self.exact else "scan_neighborhood_overflow"


def closest_point_on_triangle(
    points: NDArray[np.float64],
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    c: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Closest point of triangle ``(a, b, c)`` to ``points``, elementwise.

    The standard barycentric region test (Ericson, *Real-Time Collision
    Detection* §5.1.5), vectorised: the interior projection first, then the
    three edge regions, then the three vertex regions, so the most specific
    verdict wins. Exported because the gate's brute-force reference needs the
    same primitive — what G12C.35 tests is the *candidate set*, and a reference
    that reimplemented the point-to-triangle arithmetic would be testing two
    implementations of it instead.
    """
    ab = b - a
    ac = c - a
    ap = points - a
    d1 = np.einsum("ij,ij->i", ab, ap)
    d2 = np.einsum("ij,ij->i", ac, ap)
    bp = points - b
    d3 = np.einsum("ij,ij->i", ab, bp)
    d4 = np.einsum("ij,ij->i", ac, bp)
    cp = points - c
    d5 = np.einsum("ij,ij->i", ab, cp)
    d6 = np.einsum("ij,ij->i", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    # Interior: the barycentric projection onto the triangle's plane. The
    # denominator is positive for any triangle with area, and canonicalization
    # has already dropped the degenerate ones (§1.5 step 5); the guard is here
    # so a caller passing raw arrays gets vertex A rather than a NaN.
    total = va + vb + vc
    safe = np.where(np.abs(total) > 0.0, total, 1.0)
    v = (vb / safe)[:, None]
    w = (vc / safe)[:, None]
    out = a + ab * v + ac * w

    def _place(mask: NDArray[np.bool_], value: NDArray[np.float64]) -> None:
        if mask.any():
            out[mask] = value[mask]

    def _on_edge(
        start: NDArray[np.float64],
        span: NDArray[np.float64],
        numerator: NDArray[np.float64],
        denominator: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        good = np.where(np.abs(denominator) > 0.0, denominator, 1.0)
        t = np.clip(numerator / good, 0.0, 1.0)
        return start + span * t[:, None]

    _place((vc <= 0.0) & (d1 >= 0.0) & (d3 <= 0.0), _on_edge(a, ab, d1, d1 - d3))
    _place((vb <= 0.0) & (d2 >= 0.0) & (d6 <= 0.0), _on_edge(a, ac, d2, d2 - d6))
    _place(
        (va <= 0.0) & ((d4 - d3) >= 0.0) & ((d5 - d6) >= 0.0),
        _on_edge(b, c - b, d4 - d3, (d4 - d3) + (d5 - d6)),
    )
    _place((d1 <= 0.0) & (d2 <= 0.0), a)
    _place((d3 >= 0.0) & (d4 <= d3), b)
    _place((d6 >= 0.0) & (d5 <= d6), c)
    return out


def _vertex_triangles(
    faces: NDArray[np.int64], vertex_count: int
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """CSR-style vertex -> incident-triangle map ``(offsets, triangle ids)``."""
    triangles = np.repeat(np.arange(faces.shape[0], dtype=np.int64), 3)
    vertices = faces.reshape(-1)
    order = np.argsort(vertices, kind="stable")
    sorted_vertices = vertices[order]
    counts = np.bincount(sorted_vertices, minlength=vertex_count)
    offsets = np.zeros(vertex_count + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    return offsets, triangles[order]


def point_mesh_distances(
    vertices: NDArray[np.float64],
    faces: NDArray[np.int64] | None,
    queries: NDArray[np.float64],
    *,
    candidate_max: int | None = None,
) -> MeshDistances:
    """Distance from each query point to the mesh — exact, or a named bound.

    The §6.3 construction, and every step of it is a soundness argument rather
    than a heuristic:

    1. a ``scipy.spatial.cKDTree`` over the welded vertices gives ``d_v``, the
       distance to the nearest vertex — measured at 0.45 µs/pt against
       ``BRepExtrema``'s 54.6 ms/pt on a comparable target;
    2. ``d_v`` is a **sound upper bound** on the true point-to-surface distance,
       because the nearest vertex lies on some triangle — which is true only of
       vertices the tree is allowed to contain. Canonicalization keeps every
       welded vertex INCLUDING any left unreferenced by the degenerate-triangle
       drop (see :class:`MeshAsset`), so a tree over all of them can return an
       orphan that lies on no triangle, and ``d_v`` is then a distance to a
       point of the surface that is not part of the surface — an UNDER-estimate
       published under a field that promises the opposite. Measured on a
       canonical fixture 2026-08-30: true 19.8 mm, reported 1.208 mm, a 16x
       under-estimate that makes a clearance predicate pass on a part that is
       nowhere near. The tree is therefore built over INCIDENT vertices only
       (below). Dropping orphans at canonicalization instead would move
       ``vertex_count`` and ``euler_characteristic``, which G12A pins;
    3. every triangle whose closest point lies within ``d_v`` must have a vertex
       within ``d_v + L_max`` (``L_max`` = the mesh's longest edge), so the
       radius query is a **sound superset** of the candidates;
    4. the exact point-to-triangle distance over that superset is therefore the
       true distance — *exact*, not approximate, and :data:`SCAN_METHOD_EXACT`
       says so;
    5. above :func:`scan_candidate_max` candidates for any one query the exact
       refinement is abandoned by name (``scan_neighborhood_overflow``) and the
       record reports the step-2 bound with :data:`SCAN_METHOD_BOUND`.

    A ``faces`` of ``None`` (or an empty triangle array) is the point-cloud
    case: there is no surface between the points, so step 2's bound is all a
    point set can honestly support and it is reported as the bound it is.
    """
    # ``KDTree`` IS ``cKDTree`` (a subclass of it, same C implementation and
    # the same 0.45 µs/pt the §6.3 measurement was taken at); the compiled name
    # is not re-exported from ``scipy.spatial``'s typed surface, and reaching
    # into ``scipy.spatial._ckdtree`` for a private module would be a worse
    # trade than naming the public alias here.
    from scipy.spatial import KDTree

    ceiling = scan_candidate_max() if candidate_max is None else candidate_max
    # Step 2's soundness needs the nearest vertex to lie on a triangle, so the
    # tree holds only vertices some triangle references; `referenced` maps tree
    # indices back to mesh indices for the incidence lookup below. In the
    # point-cloud case every vertex IS the surface, so the identity map is the
    # correct restriction and the same code path serves both.
    referenced: NDArray[np.int64] = (
        np.arange(int(vertices.shape[0]), dtype=np.int64)
        if faces is None or faces.shape[0] == 0
        else np.asarray(np.unique(faces.reshape(-1)), dtype=np.int64)
    )
    tree = KDTree(vertices[referenced])
    nearest = cast("NDArray[np.float64]", np.asarray(tree.query(queries, k=1)[0], dtype=np.float64))
    if faces is None or faces.shape[0] == 0:
        return MeshDistances(
            distances=nearest,
            exact=False,
            method=SCAN_METHOD_BOUND,
            candidate_max=ceiling,
            max_candidates=0,
        )

    corners = vertices[faces]
    edges = np.concatenate(
        [
            corners[:, 1] - corners[:, 0],
            corners[:, 2] - corners[:, 1],
            corners[:, 0] - corners[:, 2],
        ]
    )
    longest = float(np.sqrt(np.einsum("ij,ij->i", edges, edges)).max())
    offsets, incident = _vertex_triangles(faces, int(vertices.shape[0]))

    out = np.empty(queries.shape[0], dtype=np.float64)
    seen = 0
    neighbourhoods = cast(
        "list[list[int]]", tree.query_ball_point(queries, nearest + longest, return_sorted=False)
    )
    for index, neighbours in enumerate(neighbourhoods):
        # Tree indices are positions in `referenced`, not mesh vertex ids.
        picked: NDArray[np.int64] = referenced[np.asarray(neighbours, dtype=np.int64)]
        spans = [incident[offsets[int(v)] : offsets[int(v) + 1]] for v in picked]
        candidates = np.unique(np.concatenate(spans)) if spans else np.zeros(0, dtype=np.int64)
        seen = max(seen, int(candidates.shape[0]))
        if candidates.shape[0] == 0 or candidates.shape[0] > ceiling:
            # One over-ceiling neighbourhood abandons the refinement for the
            # whole direction: a mean mixing exact distances with bounds is a
            # number with no defined meaning (§6.4). The empty case shares this
            # exit but is NOT an overflow — with the tree restricted to
            # incident vertices it is unreachable for a non-empty surface, and
            # it stays here as a fail-closed floor rather than a silent one.
            return MeshDistances(
                distances=nearest,
                exact=False,
                method=SCAN_METHOD_BOUND,
                candidate_max=ceiling,
                max_candidates=seen,
            )
        tri = corners[candidates]
        point = np.repeat(queries[index][None, :], candidates.shape[0], axis=0)
        closest = closest_point_on_triangle(point, tri[:, 0], tri[:, 1], tri[:, 2])
        offset = point - closest
        out[index] = float(np.sqrt(np.einsum("ij,ij->i", offset, offset)).min())
    return MeshDistances(
        distances=out,
        exact=True,
        method=SCAN_METHOD_EXACT,
        candidate_max=ceiling,
        max_candidates=seen,
    )
