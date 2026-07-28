"""Geometry addressing: the §7 selector grammar over an abstract geometry tree.

Pure module — no build123d import. Resolution operates on a
:class:`GeometryIndex` (tree-order labels, binding names with element counts,
tag names) that the kernel/executor construct after a build; the returned
:class:`Resolution` names the rule that matched and the concrete occurrence
indices so callers can map back to real shapes.

Precedence (§7), within a part:

1. ``"part"`` — the full ``part.geometry`` compound.
2. A tag name (§5.3).
3. A geometry label; duplicate labels dedup deterministically in tree order
   with ``#2``, ``#3`` … suffixes: the bare name addresses the first
   occurrence, ``name#k`` the k-th (1-based), ``name#*`` the fused compound
   of all occurrences.
4. A binding name from the source map; a list binding bare name is the fused
   compound of its members and ``name#k`` selects the k-th element in append
   order (1-based).

A selector matching more than one interpretation at the same level, or
matching nothing, raises ``addressing_error`` listing candidates/near-misses
— never a silent guess. Cross-part selectors are ``"<part>/<selector>"``.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from hephaestus.core.errors import AddressingError

ResolutionKind = Literal["part", "tag", "label", "binding"]

PART_SELECTOR = "part"

_SUFFIX_RE = re.compile(r"\A(?P<base>.+)#(?P<sel>[1-9][0-9]*|\*)\Z", re.DOTALL)


@dataclass(frozen=True)
class GeometryIndex:
    """Abstract per-part geometry namespace for addressing.

    ``labels``: the ``.label`` string of every labeled node of the (flattened)
    geometry tree, in deterministic tree order; duplicates allowed and
    meaningful. ``bindings``: source-map binding name -> element count
    (1 for a scalar binding; N >= 0 for a list binding accumulated in append
    order). ``tags``: tag names attached via ``tag()``.
    """

    labels: tuple[str, ...] = ()
    bindings: Mapping[str, int] = field(default_factory=dict[str, int])
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        for label in self.labels:
            if not label:
                raise ValueError("empty geometry label")
        for name, count in self.bindings.items():
            if not name:
                raise ValueError("empty binding name")
            if count < 0:
                raise ValueError(f"negative element count for binding {name!r}")

    def label_occurrences(self, label: str) -> tuple[int, ...]:
        """Tree-order indices (into ``labels``) of every node labeled ``label``."""
        return tuple(i for i, x in enumerate(self.labels) if x == label)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GeometryIndex):
            return NotImplemented
        return (
            self.labels == other.labels
            and dict(self.bindings) == dict(other.bindings)
            and self.tags == other.tags
        )

    def __hash__(self) -> int:
        return hash((self.labels, tuple(sorted(self.bindings.items())), self.tags))


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving one selector inside one part.

    ``kind`` is the grammar rule that matched. ``name`` is the base name
    (tag/label/binding name, or ``"part"``). For labels, ``occurrences``
    holds tree-order indices into ``GeometryIndex.labels``; for bindings,
    element indices in append order. ``fused`` is True when the selection is
    the fused compound of several members (``#*`` or a bare list binding).
    """

    kind: ResolutionKind
    name: str
    occurrences: tuple[int, ...] = ()
    fused: bool = False


def _dedup_names(labels: tuple[str, ...]) -> list[str]:
    """Display dedup of tree-order labels: first bare, then ``name#2``… (§7.3)."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for label in labels:
        count = seen.get(label, 0) + 1
        seen[label] = count
        out.append(label if count == 1 else f"{label}#{count}")
    return out


def label_rows(index: GeometryIndex) -> tuple[str, ...]:
    """Deduplicated display names of the label tree, in tree order.

    Exactly the row names of the Results geometry tree and the §8
    ``geometries`` array (bare first occurrence, ``name#2``… thereafter).
    """
    return tuple(_dedup_names(index.labels))


def namespace(index: GeometryIndex) -> tuple[str, ...]:
    """Every resolvable selector advertised by this index (deterministic order).

    ``"part"``, tags (sorted), deduplicated labels in tree order plus
    ``name#1`` aliases and ``name#*`` for duplicated labels, then binding
    names (sorted) with ``name#k`` element selectors for list bindings.
    Resolution is total over this set: every member resolves without error.
    """
    names: list[str] = [PART_SELECTOR]
    names.extend(sorted(index.tags))
    label_counts: dict[str, int] = {}
    for label in index.labels:
        label_counts[label] = label_counts.get(label, 0) + 1
    names.extend(_dedup_names(index.labels))
    for label in sorted(label_counts):
        if label_counts[label] > 1:
            names.append(f"{label}#1")
            names.append(f"{label}#*")
    for binding in sorted(index.bindings):
        names.append(binding)
        count = index.bindings[binding]
        if count > 1:
            names.extend(f"{binding}#{k}" for k in range(1, count + 1))
            names.append(f"{binding}#*")
    # Deterministic de-duplication preserving first appearance.
    unique: dict[str, None] = dict.fromkeys(names)
    return tuple(unique)


def _near_misses(selector: str, index: GeometryIndex) -> tuple[str, ...]:
    pool = list(namespace(index))
    return tuple(difflib.get_close_matches(selector, pool, n=5, cutoff=0.5))


def _resolve_label(selector: str, index: GeometryIndex) -> tuple[Resolution, ...]:
    """All label-level interpretations of ``selector`` (ambiguity preserved)."""
    matches: list[Resolution] = []
    literal = index.label_occurrences(selector)
    if literal:
        matches.append(Resolution(kind="label", name=selector, occurrences=(literal[0],)))
    suffix = _SUFFIX_RE.match(selector)
    if suffix is not None:
        base = suffix.group("base")
        sel = suffix.group("sel")
        occurrences = index.label_occurrences(base)
        if occurrences:
            if sel == "*":
                matches.append(
                    Resolution(kind="label", name=base, occurrences=occurrences, fused=True)
                )
            else:
                k = int(sel, 10)
                if k <= len(occurrences):
                    matches.append(
                        Resolution(kind="label", name=base, occurrences=(occurrences[k - 1],))
                    )
    return tuple(matches)


def _resolve_binding(selector: str, index: GeometryIndex) -> tuple[Resolution, ...]:
    """All binding-level interpretations of ``selector`` (ambiguity preserved)."""
    matches: list[Resolution] = []
    count = index.bindings.get(selector)
    if count is not None:
        occurrences = tuple(range(count))
        matches.append(
            Resolution(kind="binding", name=selector, occurrences=occurrences, fused=count != 1)
        )
    suffix = _SUFFIX_RE.match(selector)
    if suffix is not None:
        base = suffix.group("base")
        sel = suffix.group("sel")
        base_count = index.bindings.get(base)
        if base_count is not None:
            if sel == "*":
                matches.append(
                    Resolution(
                        kind="binding",
                        name=base,
                        occurrences=tuple(range(base_count)),
                        fused=True,
                    )
                )
            else:
                k = int(sel, 10)
                if k <= base_count:
                    matches.append(Resolution(kind="binding", name=base, occurrences=(k - 1,)))
    return tuple(matches)


def _describe(res: Resolution) -> str:
    if res.kind == "label":
        if res.fused:
            return f"label {res.name!r}#* (all {len(res.occurrences)} occurrences)"
        return f"label {res.name!r} (tree position {res.occurrences[0]})"
    if res.fused:
        return f"binding {res.name!r} (fused {len(res.occurrences)} elements)"
    return f"binding {res.name!r} (element {res.occurrences[0] + 1})"


def resolve(selector: str, index: GeometryIndex) -> Resolution:
    """Resolve ``selector`` inside one part per the §7 precedence order.

    Raises :class:`AddressingError` (code ``addressing_error``) listing
    candidates on same-level ambiguity, or near-misses when nothing matches.
    """
    if not selector:
        raise AddressingError("empty selector", selector=selector, candidates=namespace(index)[:5])
    if selector == PART_SELECTOR:
        return Resolution(kind="part", name=PART_SELECTOR)
    if selector in index.tags:
        return Resolution(kind="tag", name=selector)
    label_matches = _resolve_label(selector, index)
    if len(label_matches) > 1:
        raise AddressingError(
            f"selector {selector!r} is ambiguous among labels: "
            + "; ".join(_describe(m) for m in label_matches),
            selector=selector,
            candidates=tuple(_describe(m) for m in label_matches),
            reason="ambiguous",
        )
    if label_matches:
        return label_matches[0]
    binding_matches = _resolve_binding(selector, index)
    if len(binding_matches) > 1:
        raise AddressingError(
            f"selector {selector!r} is ambiguous among bindings: "
            + "; ".join(_describe(m) for m in binding_matches),
            selector=selector,
            candidates=tuple(_describe(m) for m in binding_matches),
            reason="ambiguous",
        )
    if binding_matches:
        return binding_matches[0]
    near = _near_misses(selector, index)
    detail = f"; near misses: {', '.join(near)}" if near else ""
    raise AddressingError(
        f"selector {selector!r} resolves to nothing{detail}",
        selector=selector,
        candidates=near,
    )


def resolve_in_project(
    selector: str,
    indexes: Mapping[str, GeometryIndex],
    *,
    current_part: str | None = None,
) -> tuple[str, Resolution]:
    """Resolve a possibly part-prefixed selector (``"<part>/<selector>"``).

    Without a ``/`` prefix the selector resolves in ``current_part`` (which
    must then be given). Returns ``(part_name, resolution)``. An unknown part
    prefix raises ``addressing_error`` listing the known parts.
    """
    part_name, sep, rest = selector.partition("/")
    if sep and part_name in indexes:
        return part_name, resolve(rest, indexes[part_name])
    if sep:
        known = tuple(sorted(indexes))
        near = tuple(difflib.get_close_matches(part_name, known, n=5, cutoff=0.5)) or known
        raise AddressingError(
            f"unknown part {part_name!r} in selector {selector!r}; "
            f"known parts: {', '.join(known) or '(none)'}",
            selector=selector,
            candidates=near,
        )
    if current_part is None:
        raise AddressingError(
            f"selector {selector!r} has no part prefix and no current part is set",
            selector=selector,
            candidates=tuple(sorted(indexes)),
        )
    if current_part not in indexes:
        raise AddressingError(
            f"current part {current_part!r} not in project",
            selector=selector,
            candidates=tuple(sorted(indexes)),
        )
    return current_part, resolve(selector, indexes[current_part])
