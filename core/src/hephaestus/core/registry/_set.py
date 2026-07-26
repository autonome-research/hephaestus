"""Resolving a project's registries into one verified, indexed set.

:class:`RegistrySet` is the single place pins, loading and the per-kind content
indexes meet: it reads the project's pins, falls back to the bundled trees, and
loads each registry through the verify-on-load path exactly once. A serving
runtime can additionally insist that every registry was explicitly pinned.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hephaestus.core.errors import ValidationError

from ._dfm import DfmIndex
from ._digest import merkle_digest
from ._errors import RegistryIntegrityError
from ._layout import Registry, load_registry
from ._materials import MaterialsIndex
from ._parts import PartsIndex
from ._pins import bundled_pins, read_pins
from ._skills import SkillsIndex

__all__ = ["RegistrySet"]


class RegistrySet:
    """Every registry a project resolves, loaded and integrity-verified once."""

    def __init__(self, registries: Mapping[str, Registry]) -> None:
        self._registries = dict(registries)
        by_kind: dict[str, Registry] = {}
        for registry in self._registries.values():
            by_kind.setdefault(registry.kind, registry)
        self._by_kind = by_kind
        self.skills = SkillsIndex(by_kind.get("skills"))
        self.parts = PartsIndex(by_kind.get("parts"))
        self.materials = MaterialsIndex(by_kind.get("materials"))
        self.dfm = DfmIndex(by_kind.get("dfm"))

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
        return self._by_kind.get(kind)
