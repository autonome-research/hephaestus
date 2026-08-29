"""Topology tagging (§5.3): recompute-per-build tag registry and placement.

``tag(topology, name)`` attaches a recomputed semantic name to a
face/edge/solid. Tags are re-derived by re-running the tagging statement's
selector on every build — never persisted by topological id. The registry
records (name, topology, tagging statement); :func:`resolve_placements` maps
each tag to (solid index, topology kind, topology index within the owning
solid) against the final compound for the source map.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue


@dataclass(frozen=True)
class TaggedTopology:
    """One recorded ``tag()`` call: the topology object and its statement."""

    name: str
    shape: object
    statement_index: int
    line: int


@dataclass(frozen=True)
class TagPlacement:
    """Source-map tag entry: name -> (solid, topology index, statement) (§5.3).

    ``solid_index`` / ``topo_index`` are ``None`` when the tagged topology is
    not part of the final ``part.geometry`` compound (the worker emits a
    warning in that case).
    """

    kind: str
    solid_index: int | None
    topo_index: int | None
    statement_index: int
    line: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind,
            "solid": self.solid_index,
            "topo_index": self.topo_index,
            "statement": self.statement_index,
            "line": self.line,
        }


#: ``PARTS_STORE.md`` §2.2: the infix an emitted store-interface tag carries.
#: A hand-authored tag never contains it — a declared interface name may not,
#: and the emitted form ``<instance>__<name>`` is the only producer — so scoping
#: the duplicate rule to it leaves every existing script's semantics untouched.
INTERFACE_TAG_INFIX = "__"


class TagRegistry:
    """Collects ``tag()`` calls during script execution.

    The worker calls :meth:`set_statement` before executing each top-level
    statement so every recorded tag carries its creating statement. Re-tagging
    an existing name overwrites (last tagging statement wins, deterministic) —
    **except** for a name carrying :data:`INTERFACE_TAG_INFIX`, which is a
    refusal (``PARTS_STORE.md`` §2.2).

    Why the exception. For a hand-authored script last-wins is reasonable and
    deterministic. For *pasted fragments* it is a silent correctness failure:
    two motors in one script both emitting ``tag(..., "shaft")`` would leave one
    ``shaft`` tag, and an 8C constraint anchored on it would be measured against
    whichever fragment was pasted lower in the file — a satisfied constraint
    about the wrong solid, which nothing today would report. Instance-scoping
    the emitted name makes the collision impossible between *different*
    instances; refusing the re-tag is what turns pasting the *same* instance
    twice into a build failure the operator sees.
    """

    def __init__(self) -> None:
        self._tags: dict[str, TaggedTopology] = {}
        self._statement_index = -1
        self._line = 0

    def set_statement(self, index: int, line: int) -> None:
        self._statement_index = index
        self._line = line

    def tag(self, topology: object, name: str) -> None:
        """The injected ``tag`` callable (§5.3)."""
        if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValidationError("tag(topology, name) requires a non-empty name", kind="contract")
        if not hasattr(topology, "wrapped"):
            raise ValidationError(
                f"tag({name!r}): topology must be a build123d shape "
                f"(got {type(topology).__name__})",
                kind="contract",
            )
        existing = self._tags.get(name)
        if existing is not None and INTERFACE_TAG_INFIX in name:
            raise ValidationError(
                f"duplicate_tag: the store-interface tag {name!r} is emitted twice "
                f"(statement {existing.statement_index} at line {existing.line}, and "
                f"statement {self._statement_index} at line {self._line}). Two pastes of "
                "one component instance are the same instance by construction; pass a "
                "distinct 'instance' to instance_store_part so each fragment carries its "
                "own tag names",
                kind="contract",
            )
        self._tags[name] = TaggedTopology(
            name=name,
            shape=topology,
            statement_index=self._statement_index,
            line=self._line,
        )

    def records(self) -> Mapping[str, TaggedTopology]:
        return dict(self._tags)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tags)


def _is_same(a: object, b: object) -> bool:
    wrapped_a = getattr(a, "wrapped", None)
    wrapped_b = getattr(b, "wrapped", None)
    if wrapped_a is None or wrapped_b is None:
        return False
    return bool(wrapped_a.IsSame(wrapped_b))


def _classify(shape: object) -> str:
    from build123d import Edge, Face, Solid, Vertex, Wire

    if isinstance(shape, Face):
        return "face"
    if isinstance(shape, Edge):
        return "edge"
    if isinstance(shape, Solid):
        return "solid"
    if isinstance(shape, Wire):
        return "wire"
    if isinstance(shape, Vertex):
        return "vertex"
    return "other"


def resolve_placements(registry: TagRegistry, compound: Any) -> dict[str, TagPlacement]:
    """Locate each tagged topology inside the final compound.

    Deterministic: solids enumerate in compound order; topology indices are
    positions within the owning solid's ``faces()`` / ``edges()`` list. A tag
    whose topology is not found gets ``solid_index=None`` (caller warns).
    """
    solids = list(compound.solids()) if hasattr(compound, "solids") else []
    out: dict[str, TagPlacement] = {}
    for name, record in registry.records().items():
        kind = _classify(record.shape)
        solid_index: int | None = None
        topo_index: int | None = None
        if kind == "solid":
            for i, solid in enumerate(solids):
                if _is_same(record.shape, solid):
                    solid_index = i
                    topo_index = i
                    break
        elif kind in ("face", "edge"):
            accessor = "faces" if kind == "face" else "edges"
            for i, solid in enumerate(solids):
                for j, topo in enumerate(getattr(solid, accessor)()):
                    if _is_same(record.shape, topo):
                        solid_index = i
                        topo_index = j
                        break
                if solid_index is not None:
                    break
        out[name] = TagPlacement(
            kind=kind,
            solid_index=solid_index,
            topo_index=topo_index,
            statement_index=record.statement_index,
            line=record.line,
        )
    return out
