"""Resolving a project's registries into one verified, indexed set.

:class:`RegistrySet` is the single place pins, loading and the per-kind content
indexes meet: it reads the project's pins, falls back to the bundled trees, and
loads each registry through the verify-on-load path exactly once. A serving
runtime can additionally insist that every registry was explicitly pinned.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from hephaestus.core.errors import ValidationError

from ._dfm import DfmIndex
from ._digest import merkle_digest
from ._errors import RegistryIntegrityError, RegistryRefusal
from ._layout import Registry, load_registry
from ._materials import MaterialsIndex
from ._parts import PartsIndex
from ._pins import bundled_pins, read_pins
from ._skills import SkillsIndex

__all__ = ["RegistrySet"]


class RegistrySet:
    """Every registry a project resolves, loaded and integrity-verified once."""

    #: Kinds whose registries index **together** (``PARTS_STORE.md`` §8, G11C
    #: item 25). Every other kind still indexes exactly one registry, so a second
    #: one would be the silent drop §8 opens with — and stays
    #: ``duplicate_registry_kind`` until the merge for that kind is built and
    #: gated. The set is the *whole* difference between the two behaviours, so a
    #: later stage federating another kind adds it here and nowhere else.
    FEDERATED_KINDS: Final[frozenset[str]] = frozenset({"parts"})

    def __init__(self, registries: Mapping[str, Registry]) -> None:
        self._registries = dict(registries)
        by_kind: dict[str, list[Registry]] = {}
        for name in sorted(self._registries):
            registry = self._registries[name]
            resolved = by_kind.setdefault(registry.kind, [])
            if resolved and registry.kind not in self.FEDERATED_KINDS:
                # PARTS_STORE.md §8. This was `by_kind.setdefault(...)` alone: a
                # second registry of a kind was *silently discarded*, and which
                # one survived depended on `hephaestus.toml` table order plus the
                # bundled fallback. Fail closed instead — a silent wrong answer
                # becomes something the operator can fix.
                #
                # G11C federates `parts` (`FEDERATED_KINDS`), so two parts trees
                # now index together and a colliding id is refused per *id* as
                # `ambiguous_component_id`. This refusal keeps its job for every
                # kind whose index still reads one tree, where a second really
                # would be dropped.
                existing = resolved[0]
                raise RegistryRefusal(
                    "duplicate_registry_kind",
                    f"two registries of kind {registry.kind!r} are resolved "
                    f"({existing.name!r} at {existing.root} and {registry.name!r} at "
                    f"{registry.root}); one registry per kind is indexed for this kind, so "
                    "opening the set would silently drop one — remove or re-point a pin",
                    detail={
                        "kind": registry.kind,
                        "registries": [existing.name, registry.name],
                        "roots": [str(existing.root), str(registry.root)],
                    },
                )
            resolved.append(registry)
        self._by_kind = {kind: tuple(found) for kind, found in by_kind.items()}
        self.skills = SkillsIndex(self._one("skills"))
        self.parts = PartsIndex(self._by_kind.get("parts", ()))
        self.materials = MaterialsIndex(self._one("materials"))
        self.dfm = DfmIndex(self._one("dfm"))

    def _one(self, kind: str) -> Registry | None:
        """The single registry of an unfederated kind (refused above if two)."""
        found = self._by_kind.get(kind, ())
        return found[0] if found else None

    @classmethod
    def open(
        cls,
        project_root: Path,
        *,
        fallback_to_bundled: bool = True,
        require_pinned: bool = False,
    ) -> RegistrySet:
        """Load the project's pinned registries (falling back to the bundled trees).

        A pinned tree that no longer hashes to its pin raises
        :class:`RegistryIntegrityError`. With ``require_pinned=True`` an unpinned
        registry is refused the same way, so a serving runtime can insist that
        every byte of registry content was explicitly accepted.
        """
        pins = dict(read_pins(project_root))
        if fallback_to_bundled:
            for name, pin in bundled_pins().items():
                pins.setdefault(name, pin)
        loaded: dict[str, Registry] = {}
        for name, pin in pins.items():
            root = pin.resolve(project_root)
            if pin.digest is None and require_pinned:
                raise RegistryIntegrityError(
                    f"registry {name!r} at {root} is not pinned in hephaestus.toml; "
                    "run 'heph registry pin' before serving",
                    expected="",
                    actual=merkle_digest(root) if root.is_dir() else "",
                    root=root,
                )
            loaded[name] = load_registry(root, expected_digest=pin.digest)
        return cls(loaded)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registries))

    def get(self, name: str) -> Registry:
        registry = self._registries.get(name)
        if registry is None:
            raise ValidationError(f"no registry named {name!r}", kind="contract")
        return registry

    def by_kind(self, kind: str) -> Registry | None:
        """The first resolved registry of ``kind`` in registry-key order.

        Exact for every unfederated kind, where a second one is refused outright.
        A **federated** kind (``FEDERATED_KINDS``) may resolve several and this
        returns only the first — use :meth:`by_kind_all`, or the merged index
        itself, rather than reading a federated pack's tree through this.
        """
        found = self._by_kind.get(kind, ())
        return found[0] if found else None

    def by_kind_all(self, kind: str) -> tuple[Registry, ...]:
        """Every resolved registry of ``kind``, in registry-key order (§8)."""
        return self._by_kind.get(kind, ())
