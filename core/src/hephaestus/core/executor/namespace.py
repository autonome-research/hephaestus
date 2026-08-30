"""The §2 injected namespace: the entire API surface a part script sees.

Builds the execution globals for part scripts and ``globals.py``:
``build123d`` complete (``from build123d import *``), ``math``, ``Param`` /
``PARAMS`` / ``p`` (§3), ``hc`` (§4, read-tracking), ``part`` (§5), ``tag``
(§5.3), ``check`` / ``CHECKS`` / ``approx`` (§6), ``import_step`` (INGEST.md
§1) — and nothing else.
``open``, ``__import__``, ``exec``/``eval``/``compile``, filesystem and
network access are absent from the builtins; attempting a well-known denied
name raises ``sandbox_denied``, which the worker surfaces as a build error.
This whitelist is defense in depth, not the security boundary — the OS
sandbox is (architecture §3.1).
"""

from __future__ import annotations

import builtins as _builtins
import math as _math
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from hephaestus.core.errors import SandboxDeniedError, ValidationError
from hephaestus.core.params import Param, extract_params, merge_overrides

if TYPE_CHECKING:
    from hephaestus.core.executor.tags import TagRegistry
    from hephaestus.geom.mesh import MeshAsset
    from opstore.types import JSONValue

#: §5.2 manufacturing-metadata field names (schema'd for lint, free-text valued).
METADATA_FIELDS: tuple[str, ...] = (
    "description",
    "material_spec",
    "process",
    "stock_form",
    "blank_size",
    "general_tolerance",
    "finish",
    "assembly_method",
    "joint",
)

#: The §2 injected name for STEP ingest (``INGEST.md`` §1).
_IMPORT_STEP = "import_step"
#: The two §2 injected names for mesh ingest (``MESH_INGEST.md`` §1.1, §7.1).
#: Terms, not tools — the 8A precedent: ``import_step`` never became a tool
#: either, and at a tool surface pinned in two places the capability belongs in
#: the script.
_IMPORT_MESH = "import_mesh"
_IMPORT_POINT_CLOUD = "import_point_cloud"
#: The three ``MESH_INGEST.md`` 12B terms (§4.3, §5.2, §5.3). Each must be
#: injected because ``__import__`` is absent and the §2 namespace is closed: a
#: part script has no route to ``BRepBuilderAPI_Sewing`` or
#: ``GeomAPI_PointsToBSpline``, so a workflow naming one would name an
#: unreachable path. G12B.29 asserts the injected set is exactly these five
#: plus the pre-existing §2 list.
_MESH_TO_SOLID = "mesh_to_solid"
_SECTION_POLYLINES = "section_polylines"
_LOFT_SECTIONS = "loft_sections"

#: The five ``MESH_INGEST.md`` names this stage injects, in the order
#: ``script_contract.md`` §2 lists them. Declared as a value so the closure test
#: can compare against a constant rather than transcribe one.
MESH_INJECTED_NAMES: Final[tuple[str, ...]] = (
    _IMPORT_MESH,
    _IMPORT_POINT_CLOUD,
    _MESH_TO_SOLID,
    _SECTION_POLYLINES,
    _LOFT_SECTIONS,
)

#: Builtins deliberately absent; attempting them raises ``sandbox_denied``.
DENIED_BUILTINS: tuple[str, ...] = (
    "open",
    "__import__",
    "exec",
    "eval",
    "compile",
    "input",
    "breakpoint",
    "exit",
    "quit",
    "help",
    "memoryview",
    "globals",
    "locals",
    "vars",
)

#: Non-exception builtins allowed in part scripts.
_ALLOWED_BUILTINS: tuple[str, ...] = (
    "abs",
    "all",
    "any",
    "ascii",
    "bin",
    "bool",
    "bytearray",
    "bytes",
    "callable",
    "chr",
    "complex",
    "dict",
    "divmod",
    "enumerate",
    "filter",
    "float",
    "format",
    "frozenset",
    "getattr",
    "hasattr",
    "hash",
    "hex",
    "id",
    "int",
    "isinstance",
    "issubclass",
    "iter",
    "len",
    "list",
    "map",
    "max",
    "min",
    "next",
    "object",
    "oct",
    "ord",
    "pow",
    "print",
    "property",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "setattr",
    "slice",
    "sorted",
    "staticmethod",
    "classmethod",
    "str",
    "sum",
    "super",
    "tuple",
    "type",
    "zip",
    "True",
    "False",
    "None",
    "NotImplemented",
    "Ellipsis",
)


def _denier(name: str) -> Callable[..., object]:
    def denied(*_args: object, **_kwargs: object) -> object:
        raise SandboxDeniedError(
            f"{name!r} is not available in part scripts; the injected namespace "
            "is the entire API surface (script contract §2)"
        )

    denied.__name__ = f"denied_{name}"
    return denied


def safe_builtins() -> dict[str, object]:
    """The restricted ``__builtins__`` mapping for script execution."""
    out: dict[str, object] = {}
    for name in _ALLOWED_BUILTINS:
        if hasattr(_builtins, name):
            out[name] = getattr(_builtins, name)
    for name, value in vars(_builtins).items():
        if isinstance(value, type) and issubclass(value, BaseException):
            out[name] = value
    for name in DENIED_BUILTINS:
        out[name] = _denier(name)
    return out


def jsonify(value: object) -> JSONValue:
    """Best-effort JSON projection of a namespace value (hashing/consumption)."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        items = list(value)  # pyright: ignore[reportUnknownArgumentType]
        return [jsonify(item) for item in items]
    if isinstance(value, dict):
        raw: dict[object, object] = dict(value)  # pyright: ignore[reportUnknownArgumentType]
        return {str(k): jsonify(v) for k, v in raw.items()}
    return repr(value)


class ParamState:
    """PARAMS publication state for one scope (part or project).

    ``PARAMS`` MUST appear before first use of ``p`` (§3): the proxy raises a
    contract error until :meth:`publish` runs. Publication extracts and
    validates the declaration, then merges overrides all-or-nothing
    (``param_out_of_bounds`` naming every offender).
    """

    def __init__(self, *, scope: str, overrides: Mapping[str, int | float | str]) -> None:
        self.scope = scope
        self.overrides: dict[str, int | float | str] = dict(overrides)
        self.declared: dict[str, Param] | None = None
        self.effective: dict[str, int | float] | None = None

    @property
    def published(self) -> bool:
        return self.effective is not None

    def publish(self, namespace: Mapping[str, object]) -> None:
        """Extract PARAMS from ``namespace`` and merge overrides (all-or-nothing)."""
        self.declared = extract_params(namespace)
        self.effective = merge_overrides(self.declared, self.overrides)

    def finalize(self) -> None:
        """Called after the last statement: overrides without PARAMS are a contract error."""
        if self.effective is None:
            if self.overrides:
                names = ", ".join(sorted(self.overrides))
                raise ValidationError(
                    f"{self.scope} parameter overrides given ({names}) but the script "
                    "declares no PARAMS",
                    kind="contract",
                )
            self.declared = {}
            self.effective = {}


class ParamProxy:
    """The ``p`` object: attribute reads of effective parameter values."""

    def __init__(self, state: ParamState) -> None:
        object.__setattr__(self, "_state", state)

    def __getattr__(self, name: str) -> int | float:
        state: ParamState = object.__getattribute__(self, "_state")
        if name.startswith("__"):
            raise AttributeError(name)
        if state.effective is None:
            raise ValidationError(
                f"p.{name} read before PARAMS was declared; PARAMS must appear "
                "before first use of p (script contract §3)",
                kind="contract",
            )
        if name not in state.effective:
            declared = ", ".join(sorted(state.effective)) or "(none)"
            raise ValidationError(
                f"unknown parameter p.{name}; declared parameters: {declared}",
                kind="contract",
            )
        return state.effective[name]

    def __setattr__(self, name: str, value: object) -> None:
        raise ValidationError(
            f"p.{name} is read-only; parameters are set via PARAMS defaults and "
            "build-request overrides",
            kind="contract",
        )


class HcNamespace:
    """The ``hc`` object: read-only project-shared names with read tracking (§4)."""

    def __init__(self, values: Mapping[str, object]) -> None:
        object.__setattr__(self, "_values", dict(values))
        object.__setattr__(self, "_consumed", set())

    def __getattr__(self, name: str) -> object:
        values: dict[str, object] = object.__getattribute__(self, "_values")
        if name.startswith("__"):
            raise AttributeError(name)
        if name not in values:
            available = ", ".join(sorted(values)) or "(none)"
            raise AttributeError(
                f"hc.{name} is not defined in globals.py; available names: {available}"
            )
        consumed: set[str] = object.__getattribute__(self, "_consumed")
        consumed.add(name)
        return values[name]

    def __setattr__(self, name: str, value: object) -> None:
        raise ValidationError(
            f"hc.{name} is read-only from part scripts; edit globals.py instead",
            kind="contract",
        )

    def consumed_names(self) -> tuple[str, ...]:
        consumed: set[str] = object.__getattribute__(self, "_consumed")
        return tuple(sorted(consumed))

    def consumed_projection(self) -> dict[str, JSONValue]:
        """Exactly the consumed name -> value mapping (JSON-projected, name-sorted)."""
        values: dict[str, object] = object.__getattribute__(self, "_values")
        return {name: jsonify(values[name]) for name in self.consumed_names()}

    def names(self) -> tuple[str, ...]:
        values: dict[str, object] = object.__getattribute__(self, "_values")
        return tuple(sorted(values))


class FeatureMetadata:
    """Per-feature metadata bag: ``part.feature(name).<field> = "..."`` (§5.3)."""

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_fields", {})

    def __setattr__(self, name: str, value: object) -> None:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        fields[name] = value

    def __getattr__(self, name: str) -> object:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        if name in fields:
            return fields[name]
        raise AttributeError(name)

    def to_json(self) -> dict[str, JSONValue]:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return {name: jsonify(value) for name, value in fields.items()}


#: Every assignable ``part.*`` name: the geometry plus the §5.2 metadata set.
PART_FIELDS: frozenset[str] = frozenset(METADATA_FIELDS) | {"geometry"}


class PartOutput:
    """The ``part`` output object (§5): geometry, metadata fields, features."""

    def __init__(self) -> None:
        object.__setattr__(self, "_fields", {})
        object.__setattr__(self, "_features", {})

    def __setattr__(self, name: str, value: object) -> None:
        # An unknown assignment is a build error AT THE STATEMENT, never a
        # silent no-op. The 2026-07-29 corpus sweep showed why: models wrote
        # `part.metadata = {...}` — a perfectly reasonable reading of "give
        # the part its manufacturing metadata" — the namespace swallowed it,
        # and the grade later said the metadata was "missing" with no signal
        # the model could have acted on. Naming the real fields here lets the
        # author self-correct inside the same run (mission rule 1: a silently
        # ignored contract is a defect resolved by tightening).
        if name not in PART_FIELDS:
            raise ValidationError(
                f"part.{name} is not a part attribute. Assignable fields are "
                f"part.geometry and the manufacturing metadata fields: "
                f"{', '.join(METADATA_FIELDS)}. Per-feature metadata goes "
                f"through part.feature(name).<field>.",
                kind="contract",
            )
        # §5.2 metadata fields are STRING-valued — enforced here for the same
        # reason unknown names are refused: the 2026-08-03 re-run showed a
        # model writing part.blank_size = (hc.blank_len, hc.blank_width,
        # hc.sheet_t) — semantically right, silently stored, and failed later
        # as "missing" when the grader's blank parser saw a list. The loud
        # error names the expected form so the author converts in-run.
        if name == "geometry":
            # MESH_INGEST.md §2.3: a point cloud is not a shape. It has no
            # faces, and ``geom.compare.surface_distance`` on a shape with no
            # faces returns ZEROS with zero sample counts rather than refusing
            # — honest only because the counts are in the record, and not
            # honest enough for something that will be handed a point cloud by
            # mistake. The refusal is at the boundary, by name, so it can never
            # be silently sampled to zeros downstream.
            from hephaestus.geom.mesh import MeshAsset, MeshTypeError, PointCloudAsset

            if isinstance(value, PointCloudAsset):
                # ``MeshTypeError`` rather than a bare ``ValidationError``: this
                # site used to hand-write ``point_cloud_not_a_shape:`` into its
                # own prose with no ``reason=`` behind it, so the §10 code
                # existed as text and nowhere a caller could branch on — and
                # G12A.14 binds it by message substring, which such prose can
                # keep saying after the vocabulary has moved. The code now
                # derives from ``reason``.
                raise MeshTypeError(
                    "a PointCloudAsset has no faces, no "
                    "volume and no topology, so it cannot be part.geometry. In 12A a "
                    "point cloud can be measured (bbox, count) and nothing else; "
                    "reconstruction to a mesh is out of scope (MESH_INGEST.md §2.3)",
                    reason="point_cloud_not_a_shape",
                )
            if isinstance(value, MeshAsset):
                raise ValidationError(
                    "a MeshAsset is a measurement target, not geometry: a mesh has no "
                    "exact topology, so it is not a Shape and part.geometry will not "
                    "take one. Author the socket against the scan and measure the gap "
                    "(MESH_INGEST.md §5.2); mesh_to_solid lands in 12B behind a "
                    "mandatory validity gate (§4.3)",
                    kind="contract",
                )
        if name != "geometry" and not isinstance(value, str):
            raise ValidationError(
                f"part.{name} is a string-valued §5.2 metadata field "
                f"(got {type(value).__name__}). Write it as prose, e.g. "
                f'part.blank_size = "210 x 125 x 6 mm" — f-strings over hc '
                f"values are fine.",
                kind="contract",
            )
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        fields[name] = value

    def __getattr__(self, name: str) -> object:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        if name in fields:
            return fields[name]
        raise AttributeError(name)

    def feature(self, name: str) -> FeatureMetadata:
        """Per-feature metadata joined on the tag name (§5.3)."""
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError("part.feature(name) requires a non-empty name", kind="contract")
        features: dict[str, FeatureMetadata] = object.__getattribute__(self, "_features")
        if name not in features:
            features[name] = FeatureMetadata(name)
        return features[name]

    @property
    def geometry_value(self) -> object | None:
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return fields.get("geometry")

    def metadata(self) -> dict[str, JSONValue]:
        """The §5.2 string-valued metadata fields that were assigned."""
        fields: dict[str, object] = object.__getattribute__(self, "_fields")
        return {name: jsonify(fields[name]) for name in METADATA_FIELDS if name in fields}

    def feature_metadata(self) -> dict[str, dict[str, JSONValue]]:
        features: dict[str, FeatureMetadata] = object.__getattribute__(self, "_features")
        return {name: feature.to_json() for name, feature in features.items()}


class ImportRegistry:
    """The ``import_step`` implementation inside the worker (``INGEST.md`` §1).

    Harness-resolved, never script I/O: the executor read, hashed and converted
    each declared file OUTSIDE the sandbox and staged the BRep in this build's
    input area. ``import_step(name)`` is therefore a lookup plus a
    deserialization — it opens exactly one staged path and never a project
    path, so the §2 rule that the namespace has no filesystem access still
    holds exactly as written.

    ``failures`` carries the resolver's verdict for a declared name that could
    not be staged (missing file, unreadable STEP, refused path). Raising it
    HERE, when the statement runs, is what makes an unresolvable import a §8
    build error at the ``import_step`` statement rather than an opaque
    pre-build exception.
    """

    def __init__(
        self,
        staged: Mapping[str, Path],
        *,
        failures: Mapping[str, str] | None = None,
    ) -> None:
        self._staged = dict(staged)
        self._failures = dict(failures or {})
        self.used: list[str] = []
        #: ``{declared path: mesh_canonical_hash}`` for every mesh asset this
        #: script resolved (``MESH_INGEST.md`` §1.4, §12 item 15). A second hash
        #: the build record has never carried: two builds whose
        #: ``input_hashes`` differ but whose canonical hashes agree can say
        #: "the file changed, the geometry did not". It is an explanatory fact
        #: and never an invalidation key — reversing that would let a
        #: normalizer decide what counts as a changed build.
        self.mesh_hashes: dict[str, str] = {}
        #: ``{mesh_canonical_hash: canonical blob}`` for every mesh this script
        #: resolved. A :class:`~hephaestus.geom.mesh.MeshAsset` is a FACTS
        #: record — §2.2's whole mechanism is that it has no field a solid's
        #: vocabulary would recognise — so the geometry cannot ride on it, and
        #: ``mesh_to_solid`` / ``section_polylines`` look it up here by the hash
        #: that names it. The blob is keyed by its own hash rather than by path,
        #: so two declarations of one file at one unit share one entry and two
        #: units never do.
        self._mesh_blobs: dict[str, bytes] = {}
        #: Whether this build ever converted a mesh into geometry (§4.3). It is
        #: what ``geometry_source`` reads: importing a mesh and MEASURING
        #: against it leaves a build ``"authored"`` — the scan was measurement
        #: data — and §5.2 exists precisely so that distinction stays true.
        self.mesh_derived = False

    def import_step(self, name: str) -> object:
        """Deserialize the staged shape for ``name`` (script contract §2)."""
        shape = self.resolve(name)
        self._record(name)
        return shape

    def import_mesh(self, name: str, units: str | None = None) -> object:
        """The ``MESH_INGEST.md`` §1.1 mesh term, inside the worker (§7.1).

        Three steps, not the two ``import_step`` does, and this does not claim
        parity with it: a dictionary lookup, a deserialize of the ``.hmesh``
        blob, and a read of its ``.hmesh.facts`` sidecar. The third exists
        because ``welded_vertex_pairs``, ``degenerate_triangles_dropped`` and
        ``vertex_count_as_read`` are facts about the mesh *before*
        canonicalization and are unrecoverable from a post-weld blob; the
        sidecar is the only honest channel for them (§1.5.2).

        What IS unchanged from ``import_step`` is the property that matters: the
        worker never sees a project path, both files are staged read-only in the
        worker's own input area, and ``open`` stays absent from the script
        namespace — the registry reads them, not the script.
        """
        from hephaestus.core.executor.imports import staged_key
        from hephaestus.geom.mesh import mesh_asset_from_staged

        blob, facts, resolved = self._staged_mesh(name, units, "import_mesh")
        asset = mesh_asset_from_staged(blob, facts, source_path=name, units=resolved)
        self._record(name)
        # Keyed by (path, unit), not by path: two units over one file are two
        # canonical geometries, and a path-keyed record would report one of
        # them as if it were both (§1.5.1).
        self.mesh_hashes[staged_key(name, resolved)] = asset.canonical_hash
        self._mesh_blobs[asset.canonical_hash] = blob
        return asset

    def import_point_cloud(self, name: str, units: str | None = None) -> object:
        """The §1.1 point-cloud term: a :class:`PointCloudAsset`, never a shape.

        A point cloud has no faces and cannot ride ``shape_from_brep``. It is
        also the sharpest silent-failure risk in the stage — ``surface_distance``
        on a shape with no faces returns zeros with zero sample counts rather
        than refusing — so it is a *distinct kind*, and passing one where a shape
        is expected is refused ``point_cloud_not_a_shape`` at the boundary (§2.3).
        """
        from hephaestus.core.executor.imports import staged_key
        from hephaestus.geom.mesh import point_cloud_asset_from_staged

        blob, _facts, resolved = self._staged_mesh(name, units, "import_point_cloud")
        asset = point_cloud_asset_from_staged(blob, source_path=name, units=resolved)
        self._record(name)
        # Keyed by (path, unit), not by path: two units over one file are two
        # canonical geometries, and a path-keyed record would report one of
        # them as if it were both (§1.5.1).
        self.mesh_hashes[staged_key(name, resolved)] = asset.canonical_hash
        return asset

    # ------------------------------------------------------------------
    # MESH_INGEST.md 12B: the three terms that turn a scan into something a
    # script can build with — behind the refusals that keep each of them from
    # producing a surface the geometry does not support.

    def mesh_to_solid(self, asset: object, intent: str | None = None) -> object:
        """§4.3: sew a mesh into a B-rep solid, behind a MANDATORY validity gate.

        ``intent`` is the closed set ``{"measurement_target", "boolean_operand"}``
        and is required. There is no ``"offset_operand"`` value and there will
        not be one: §4.2 measured ``BRepOffsetAPI_MakeOffsetShape`` at +2 mm over
        a faceted solid returning ``IsDone``, non-null, sealed, genus 0 — and a
        volume 0.003 mm³ where the answer is 44602 mm³. Naming the intent is
        what makes the absent third value visible at the call site.

        The sew runs under the §4.1 subprocess ceiling and
        ``BRepCheck_Analyzer.IsValid()`` is then checked, with a False verdict
        refusing ``mesh_solid_invalid``. On the pinned kernel that verdict is
        False even for a clean tessellated sphere, so this term is expected to
        refuse most real scans, and §5.2 is the workflow that does not need it.
        """
        from hephaestus.core.mesh_solid import bounded_sew_to_solid
        from hephaestus.geom.mesh_solid import MESH_SOLID_INTENTS, gate_sewn_solid

        mesh = self._mesh_operand(asset, "mesh_to_solid")
        if not isinstance(intent, str) or intent not in MESH_SOLID_INTENTS:
            raise ValidationError(
                f"mesh_to_solid(asset, intent=…): intent is required and comes from the "
                f"closed set {sorted(MESH_SOLID_INTENTS)}, got {intent!r}. There is no "
                "'offset_operand': offsetting a mesh-derived solid was measured "
                "returning a sealed, genus-0, plausible solid whose volume is five "
                "million times too small (MESH_INGEST.md §4.2, §4.3)",
                kind="contract",
            )
        blob = self._mesh_blobs.get(mesh.canonical_hash)
        if blob is None:  # pragma: no cover - only reachable via a forged asset
            raise ValidationError(
                f"mesh_to_solid({mesh.source_path!r}): that MeshAsset was not produced by "
                "import_mesh in this build, so its canonical geometry is not staged here",
                kind="contract",
            )
        solid, report = bounded_sew_to_solid(
            blob,
            source=mesh.source_path,
            quality=mesh.quality,
            bbox_mm=mesh.bbox_mm,
        )
        gated = gate_sewn_solid(solid, report, source=mesh.source_path, quality=mesh.quality)
        # Only a SUCCESSFUL conversion makes the build mesh-derived. A refused
        # one leaves no mesh geometry in the part, and recording it as derived
        # would tell a reviewer the part contains scan surface it does not.
        self.mesh_derived = True
        return gated

    def section_polylines(
        self,
        asset: object,
        plane: object = None,
        *,
        spacing: float | None = None,
    ) -> object:
        """§5.3: ordered contours where ``plane`` crosses the scan.

        ``plane`` is a build123d ``Plane`` (or any object exposing ``origin``
        and ``z_dir``); ``(origin, normal)`` as a pair of triples is accepted
        too, because a script that computed a cut height arithmetically should
        not have to construct a ``Plane`` to say so.

        A contour that does not close comes back OPEN and flagged
        ``open_section_contour`` — never joined end to end, because that would
        fabricate limb surface at exactly the place a socket presses. A plane
        that misses is ``empty_section``.
        """
        from hephaestus.geom.mesh import deserialize_mesh
        from hephaestus.geom.mesh import section_polylines as _sections

        mesh = self._mesh_operand(asset, "section_polylines")
        origin, normal = _plane_terms(plane)
        blob = self._mesh_blobs.get(mesh.canonical_hash)
        if blob is None:  # pragma: no cover - only reachable via a forged asset
            raise ValidationError(
                f"section_polylines({mesh.source_path!r}): that MeshAsset was not produced "
                "by import_mesh in this build",
                kind="contract",
            )
        vertices, faces, _factor = deserialize_mesh(blob, source=mesh.source_path)
        return _sections(
            vertices,
            faces,
            origin=origin,
            normal=normal,
            spacing=spacing,
            source=mesh.source_path,
        )

    def loft_sections(
        self,
        polylines: object,
        *,
        closed: bool = True,
        ruled: bool = False,
    ) -> object:
        """§5.2: section contours -> one B-spline each -> an ANALYTIC solid.

        The result is an ordinary build123d ``Solid``, not a mesh-derived one,
        and that is the point: it was authored through the scan's measurements
        rather than sewn from its triangles, so ``offset`` / ``thicken`` /
        ``fillet`` on it are the operations §5.1 measured as working. The scan
        stays measurement data; the socket is authored geometry.

        ``closed`` is accepted and must be ``True``: this helper lofts through
        closed contours, and an open one is refused ``open_section_contour``
        rather than closed on the caller's behalf. It is a keyword rather than
        an absence so a script reads as §5.2 writes it.
        """
        from hephaestus.geom.mesh import SectionPolyline
        from hephaestus.geom.mesh_solid import loft_sections as _loft

        if closed is not True:
            raise ValidationError(
                "loft_sections(polylines, closed=True): closed=False would ask this "
                "helper to loft through contours it must not close, which is the "
                "fabrication MESH_INGEST.md §5.3 refuses",
                kind="contract",
            )
        if isinstance(polylines, SectionPolyline):
            sections = [polylines]
        elif isinstance(polylines, Sequence) and not isinstance(polylines, str | bytes):
            sections = list(cast("Sequence[object]", polylines))
        else:
            raise ValidationError(
                "loft_sections(polylines, …) takes the section_polylines results to "
                f"loft through, got {type(polylines).__name__}",
                kind="contract",
            )
        flat: list[SectionPolyline] = []
        for entry in sections:
            if isinstance(entry, SectionPolyline):
                flat.append(entry)
            elif isinstance(entry, Sequence) and not isinstance(entry, str | bytes):
                for inner in cast("Sequence[object]", entry):
                    if not isinstance(inner, SectionPolyline):
                        raise ValidationError(
                            "loft_sections(polylines, …): every entry must be a "
                            f"SectionPolyline, got {type(inner).__name__}",
                            kind="contract",
                        )
                    flat.append(inner)
            else:
                raise ValidationError(
                    "loft_sections(polylines, …): every entry must be a SectionPolyline, "
                    f"got {type(entry).__name__}",
                    kind="contract",
                )
        return _loft(flat, ruled=ruled, source="section_polylines")

    def _mesh_operand(self, asset: object, term: str) -> MeshAsset:
        """The one place a mesh term checks what it was handed (§2.3).

        A ``PointCloudAsset`` here is ``point_cloud_not_a_shape`` by name, never
        a silent zero: ``geom.compare.surface_distance`` on a shape with no
        faces returns zeros with zero sample counts, and a point cloud reaching
        a sew would be the same silent-failure shape one level up.
        """
        from hephaestus.geom.mesh import MeshAsset as _MeshAsset
        from hephaestus.geom.mesh import MeshTypeError, PointCloudAsset

        if isinstance(asset, PointCloudAsset):
            raise MeshTypeError(
                f"{term}({asset.source_path!r}) was handed a "
                "PointCloudAsset. A point cloud has no faces, no volume, no area and "
                "no topology; there is nothing to sew or section. Surface "
                "reconstruction is not available and is not approximated "
                "(MESH_INGEST.md §2.3, §4.4)",
                reason="point_cloud_not_a_shape",
            )
        if not isinstance(asset, _MeshAsset):
            raise ValidationError(
                f"{term}(asset, …) takes the MeshAsset that import_mesh returned, got "
                f"{type(asset).__name__}",
                kind="contract",
            )
        return asset

    def _staged_mesh(self, name: str, units: object, term: str) -> tuple[bytes, str, str]:
        """``(blob, sidecar text, declared unit)`` for one staged mesh import.

        The lookup key carries the declared unit, because the staged geometry
        does (§1.5.1): one script may name one file at two units and the two
        staged blobs are different geometry, so a name-only lookup would hand
        the second declaration the first's mesh.
        """
        from hephaestus.core.executor.imports import ImportResolutionError, staged_key

        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError(
                f"{term}(name, units=…) requires a non-empty path relative to imports/",
                kind="contract",
            )
        if not isinstance(units, str) or not units:
            # Raised as an ``ImportResolutionError`` rather than a bare
            # ``ValidationError`` so the §1.7 code lands in the message by
            # derivation instead of by hand (G12A.2): this is the site that
            # actually fires for a positional-only ``import_mesh("x.stl")``, and
            # a hand-written code here could drift away from the vocabulary
            # while every message-level assertion downstream stayed green.
            raise ImportResolutionError(
                f"{term}({name!r}): units= is required — STL, PLY, OBJ, OFF and XYZ "
                "carry no unit and the engine is millimetres throughout, so the unit "
                "is declared or the import is refused (MESH_INGEST.md §1.3)",
                reason="mesh_units_undeclared",
                path=name,
            )
        key = staged_key(name, units)
        failure = self._failures.get(key) or self._failures.get(name)
        if failure is not None:
            raise ValidationError(failure, kind="contract")
        staged = self._staged.get(key)
        if staged is None:
            available = ", ".join(sorted(self._staged)) or "(none)"
            raise ValidationError(
                f"{term}({name!r}, units={units!r}): no such import was staged for this "
                f"build; imports are resolved from the declared string literals in this "
                f"script (staged: {available!r})",
                kind="contract",
            )
        facts = staged.with_name(staged.name + ".facts")
        return staged.read_bytes(), facts.read_text(encoding="utf-8"), units

    def resolve_scan(
        self,
        shape: object,
        path: str,
        align: str = "as_posed",
        declared_transform: tuple[float, ...] | None = None,
    ) -> dict[str, JSONValue]:
        """The ``m.scan_diff`` resolver inside the worker (``MESH_INGEST.md`` §7.3).

        The scan was frozen and staged with the script's own imports, so this is
        the same staged-blob lookup ``import_mesh`` does and the sandbox still
        opens no project path. Two refusals live here and both are named:

        * the target's path was never declared at a unit — a ``scan:`` string
          carries none and §1.3 forbids inferring one — so the check refuses
          ``mesh_units_undeclared`` and names the ``import_mesh`` that would fix
          it, rather than measuring against a scale nobody declared;
        * the script declared the SAME path at two different units, which makes
          "the scan" ambiguous: two staged geometries differing by a factor of
          25.4 are not one target, and picking either would be the §1.5.1
          failure at check time.

        ``part_artifact_ref`` is deliberately empty on this path. Inside a build
        the artifact does not exist yet — checks run before publication — and
        minting a ref for bytes that are not in the store would attribute a
        measurement to evidence nobody can fetch. The tool and CLI surfaces fill
        it, because there the build is already published.
        """
        import hashlib

        from hephaestus.core.scan_compare import bounded_scan_distance

        staged = self._staged_scan(path)
        blob = staged.read_bytes()
        facts = staged.with_name(staged.name + ".facts").read_text(encoding="utf-8")
        record = bounded_scan_distance(
            shape,
            blob,
            facts,
            source=path,
            align=align,
            declared_transform=None if declared_transform is None else list(declared_transform),
            scan_canonical_hash="sha256:" + hashlib.sha256(blob).hexdigest(),
            part_artifact_ref="",
        )
        # The §3 quality record is lifted beside the distance rather than left
        # nested under the cheap-facts section: a predicate reading
        # ``m.scan_diff(...).quality`` is reading the defects the canonicalizer
        # measured in the scan it was just compared against, and a check that
        # had to walk a partial-facts envelope to find them would not be read.
        cheap = record.pop("scan_facts", None)
        if isinstance(cheap, dict):
            quality = cast("dict[str, JSONValue]", cheap).get("quality")
            record["quality"] = quality if isinstance(quality, dict) else {}
        return record

    def _staged_scan(self, path: str) -> Path:
        """The one staged mesh a ``scan:`` target names, or a named refusal."""
        from hephaestus.core.executor.imports import ImportResolutionError, staged_key

        # ``staged_key(path, unit)`` is ``f"{path}\x00{unit}"`` for a mesh, so
        # every staged unit of one path shares this prefix. Derived from the
        # function rather than spelled out, so a change to the key format cannot
        # silently make this lookup find nothing.
        prefix = staged_key(path, "")
        matches = sorted(key for key in self._staged if key.startswith(prefix))
        if len(matches) == 1:
            return self._staged[matches[0]]
        if not matches:
            failure = self._failures.get(path)
            detail = f" ({failure})" if failure else ""
            # The code is DERIVED from ``reason`` by
            # ``ImportResolutionError.__init__``, never written into this prose.
            # This site used to hand-write ``mesh_units_undeclared:`` into a bare
            # ``ValidationError`` — the last such copy in the repository after
            # the G12A.2 repair routed the others through the constructor, and
            # the same drift that repair exists to stop: prose and ``reason=``
            # that can disagree, plus a ``code: `` prefix that a search for the
            # derived ``[code]`` form does not find. Raised in the same class as
            # the ``import_mesh`` site above (line ~741) because it is the same
            # refusal seen from the other end — a declared import that never
            # happened — and ``ImportResolutionError`` is a ``ValidationError``
            # with ``kind="contract"``, so every caller that catches one still
            # does.
            raise ImportResolutionError(
                f"the scan target {path!r} was frozen as a build "
                "input, but no unit was ever declared for it. A scan: target is a string "
                "and STL/PLY/OBJ/OFF/XYZ carry no unit, so the unit comes from this "
                f"script's own import_mesh({path!r}, units=…) — declare one of mm, cm, "
                f"m, in (MESH_INGEST.md §1.3, §7.3){detail}",
                reason="mesh_units_undeclared",
                path=path,
            )
        units = ", ".join(key[len(prefix) :] for key in matches)
        # Named, for the reason every other refusal in this stage is: an
        # unnamed refusal is one a caller can only match by prose, and until
        # the third repair pass this was the one branch here that had no code
        # behind it. ``scan_target_ambiguous_units`` is its own term rather
        # than a reuse of ``mesh_units_conflict`` (§1.3's in-file-versus-
        # declaration conflict, asserted unreachable in 12A): the same code
        # spent on two different facts is exactly what §10's disjointness
        # paragraph forbids.
        raise ImportResolutionError(
            f"the scan target {path!r} is ambiguous: this script declared it at "
            f"{units}. Two staged geometries at different units are not one target — "
            "they differ by the whole factor the declaration exists to fix — so the "
            "check names which one it means or it is refused (MESH_INGEST.md §1.5.1)",
            reason="scan_target_ambiguous_units",
            path=path,
        )

    def resolve(self, name: str) -> object:
        """The staged shape for ``name``, without recording it as script-used.

        The comparison targets of ``m.diff`` (``COMPARE.md`` §2) are staged by
        the same machinery and read through here: a check comparing against
        ``imports/target.step`` did not put that solid in the part, so it does
        not belong in ``imports_used``, which reports what the *script* built
        with.
        """
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError(
                "import_step(name) requires a non-empty path relative to imports/",
                kind="contract",
            )
        failure = self._failures.get(name)
        if failure is not None:
            raise ValidationError(failure, kind="contract")
        staged = self._staged.get(name)
        if staged is None:
            available = ", ".join(sorted(self._staged)) or "(none)"
            raise ValidationError(
                f"import_step({name!r}): no such import was staged for this build; "
                f"imports are resolved from the declared string literals in this script "
                f"(staged: {available})",
                kind="contract",
            )
        from hephaestus.geom.step_io import shape_from_brep

        # Deserialized afresh per call: two ``import_step`` calls on one file
        # must yield two independent shapes, never one aliased object a later
        # placement could move under both names.
        return shape_from_brep(staged.read_bytes(), source=name)

    def _record(self, name: str) -> None:
        if name not in self.used:
            self.used.append(name)


def _plane_terms(plane: object) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """``(origin, normal)`` from a build123d ``Plane`` or an explicit pair.

    Kept here rather than in ``geom.mesh`` for the reason the whole geom seam
    exists: the pure section function takes numbers, and translating a script's
    vocabulary into numbers is the executor's job. A ``Plane`` is read through
    its public ``origin`` / ``z_dir``, so anything build123d calls a plane works
    without this module naming a build123d type.
    """
    origin_obj = getattr(plane, "origin", None)
    normal_obj = getattr(plane, "z_dir", None)
    if origin_obj is not None and normal_obj is not None:
        return _triple(origin_obj, "plane.origin"), _triple(normal_obj, "plane.z_dir")
    if isinstance(plane, Sequence) and not isinstance(plane, str | bytes) and len(plane) == 2:
        pair = cast("Sequence[object]", plane)
        return _triple(pair[0], "origin"), _triple(pair[1], "normal")
    raise ValidationError(
        "section_polylines(asset, plane, …): plane must be a build123d Plane, or an "
        f"(origin, normal) pair of three numbers each; got {type(plane).__name__}",
        kind="contract",
    )


def _triple(value: object, label: str) -> tuple[float, float, float]:
    """Three floats out of a ``Vector``, a tuple, or anything indexable by x/y/z."""
    if all(hasattr(value, axis) for axis in ("X", "Y", "Z")):
        return (
            float(cast("float", getattr(value, "X"))),  # noqa: B009 - OCP-style attrs
            float(cast("float", getattr(value, "Y"))),  # noqa: B009
            float(cast("float", getattr(value, "Z"))),  # noqa: B009
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes) and len(value) == 3:
        numbers = cast("Sequence[float]", value)
        return (float(numbers[0]), float(numbers[1]), float(numbers[2]))
    raise ValidationError(
        f"section_polylines: {label} must be three numbers, got {value!r}",
        kind="contract",
    )


class Approx:
    """§6 ``approx(value, abs=tol)``: deterministic tolerant numeric comparison."""

    def __init__(self, value: float, *, abs: float = 1e-9) -> None:
        if abs < 0:
            raise ValidationError("approx tolerance must be non-negative", kind="contract")
        self.value = float(value)
        self.abs = float(abs)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, bool) or not isinstance(other, int | float):
            return NotImplemented
        return _math.fabs(float(other) - self.value) <= self.abs

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        if eq is NotImplemented:
            return NotImplemented
        return not eq

    def __hash__(self) -> int:
        return hash((self.value, self.abs))

    def __repr__(self) -> str:
        return f"approx({self.value!r}, abs={self.abs!r})"


def approx(value: float, *, abs: float = 1e-9) -> Approx:
    """§6 comparator: ``m.interference(...) == approx(0, abs=1e-6)``."""
    return Approx(value, abs=abs)


class CheckRegistry:
    """Collects checks registered imperatively via ``check(name, predicate)``."""

    def __init__(self) -> None:
        self._checks: dict[str, object] = {}

    def register(self, name: str, predicate: object) -> None:
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError(
                "check(name, predicate) requires a non-empty name", kind="contract"
            )
        if not callable(predicate):
            raise ValidationError(f"check {name!r}: predicate must be callable", kind="contract")
        self._checks[name] = predicate

    def collected(self) -> dict[str, object]:
        return dict(self._checks)


def _build123d_exports() -> dict[str, object]:
    import build123d

    return {name: getattr(build123d, name) for name in build123d.__all__}


def build_namespace(
    *,
    param_state: ParamState,
    hc: HcNamespace | None = None,
    part: PartOutput | None = None,
    tag_registry: TagRegistry | None = None,
    check_registry: CheckRegistry | None = None,
    imports: ImportRegistry | None = None,
) -> dict[str, object]:
    """Assemble the §2 injected namespace as execution globals.

    Part mode passes ``part`` + ``tag_registry`` (+ ``imports``, INGEST.md §1);
    globals mode omits them (globals.py declares values, not geometry — §4).
    ``__builtins__`` is the restricted mapping from :func:`safe_builtins`.
    """
    namespace: dict[str, object] = {}
    namespace.update(_build123d_exports())
    namespace["math"] = _math
    namespace["Param"] = Param
    namespace["p"] = ParamProxy(param_state)
    if hc is not None:
        namespace["hc"] = hc
    if part is not None:
        namespace["part"] = part
    if tag_registry is not None:
        namespace["tag"] = tag_registry.tag
    if check_registry is not None:
        namespace["check"] = check_registry.register
    if imports is not None:
        namespace[_IMPORT_STEP] = imports.import_step
        namespace[_IMPORT_MESH] = imports.import_mesh
        namespace[_IMPORT_POINT_CLOUD] = imports.import_point_cloud
        namespace[_MESH_TO_SOLID] = imports.mesh_to_solid
        namespace[_SECTION_POLYLINES] = imports.section_polylines
        namespace[_LOFT_SECTIONS] = imports.loft_sections
    namespace["approx"] = approx
    namespace["__builtins__"] = safe_builtins()
    namespace["__name__"] = "__hephaestus_script__"
    return namespace


def injected_names(namespace: Mapping[str, object]) -> frozenset[str]:
    """The injected key set — used to identify script-bound names afterwards."""
    return frozenset(namespace)


# --------------------------------------------------------------------------
# PARTS_STORE.md §2.1: the interface-region selector whitelist


#: Not script vocabulary at all — the two keys :func:`build_namespace` sets for
#: Python's own benefit.
_DUNDERS: Final[frozenset[str]] = frozenset({"__builtins__", "__name__"})

#: The harness handles, which a store generator's ``interface`` region has no
#: business reading (``PARTS_STORE.md`` §2.1). ``p`` is the bind region's alone —
#: a parameter read inside a selector is a coordinate in the *unplaced* frame,
#: the same hazard as a body local; ``part`` would root the chain somewhere
#: other than the generator's root name; ``tag`` is the statement's own callee;
#: ``hc`` / ``check`` / ``CHECKS`` are already in ``_generator.py``'s
#: ``_FORBIDDEN_NAMES`` and stay forbidden everywhere; ``import_step`` would put
#: an ingest inside a selector; ``approx`` is a check helper. None of this is new
#: policy — it is the existing contract, written down where a parser can cite it.
#: The two ``MESH_INGEST.md`` §1.1 terms join for exactly the ``import_step``
#: reason, and one stronger: a selector addresses topology, and mesh topology
#: carries no identity at all (§2.4). The three 12B terms join with them: a
#: selector names a region of an already-built solid, and every one of these
#: three *makes* geometry — ``mesh_to_solid`` sews it, ``loft_sections`` lofts
#: it, and ``section_polylines`` measures the thing they build from.
_HANDLES: Final[frozenset[str]] = frozenset(
    {
        "p",
        "part",
        "tag",
        "hc",
        "check",
        "CHECKS",
        "import_step",
        "import_mesh",
        "import_point_cloud",
        "mesh_to_solid",
        "section_polylines",
        "loft_sections",
        "approx",
    }
)

if TYPE_CHECKING:
    #: Every name an interface selector may load, besides the generator's own
    #: root name (``PARTS_STORE.md`` §2.1). Exactly
    #: ``injected_names(build_namespace(...)) - _DUNDERS - _HANDLES``: the pure
    #: geometry vocabulary, which is what a selector is for.
    SELECTOR_NAMES: frozenset[str]


@cache
def _selector_names() -> frozenset[str]:
    """Assemble :data:`SELECTOR_NAMES` once, on first use.

    A parse-time rule cannot cite a runtime dict, so ``PARTS_STORE.md`` §2.1
    requires a *declared constant*; deriving it from :func:`build_namespace`
    rather than transcribing 200 names is what keeps one definition of the
    namespace instead of two that could disagree (mission rule 6).

    Computed lazily and cached because the derivation imports ``build123d``
    (~2.3 s), and ``_parts.py`` — which reaches this through
    ``parse_generator`` — indexes registries on the CLI and server startup
    paths. A registry with no ``interface`` region pays nothing at all.
    """
    namespace = build_namespace(
        param_state=ParamState(scope="part", overrides={}),
        hc=HcNamespace({}),
        part=PartOutput(),
        tag_registry=_selector_tag_registry(),
        check_registry=CheckRegistry(),
        imports=ImportRegistry({}),
    )
    return injected_names(namespace) - _DUNDERS - _HANDLES


def _selector_tag_registry() -> TagRegistry:
    from hephaestus.core.executor.tags import TagRegistry as _TagRegistry

    return _TagRegistry()


def __getattr__(name: str) -> frozenset[str]:
    """PEP 562 lazy export of :data:`SELECTOR_NAMES` (see :func:`_selector_names`)."""
    if name == "SELECTOR_NAMES":
        return _selector_names()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
