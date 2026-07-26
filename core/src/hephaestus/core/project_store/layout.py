"""Project layout: ``hephaestus.toml`` manifest, root discovery, ``.heph/`` store.

A Hephaestus project is a directory containing ``hephaestus.toml`` (name,
units, ``[params]`` project-parameter overrides), ``globals.py``, ``parts/``,
``checks/``, and the gitignored ``.heph/`` store root (architecture §3.5).
The store root is an :class:`opstore.OpStore` — created on first open, opened
fail-closed afterwards; the accepted-overwrite preimage journal lives under
``.heph/journal/``.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from hephaestus.core.errors import ValidationError
from opstore.gc import ProtectedRoots
from opstore.types import Clock, CrashHook, Liveness
from opstore.wal import LockProvider

from opstore import OpStore

__all__ = [
    "CHECKS_DIRNAME",
    "GLOBALS_FILENAME",
    "MANIFEST_FILENAME",
    "PARTS_DIRNAME",
    "STORE_DIRNAME",
    "ProjectLayout",
    "ProjectManifest",
    "find_project_root",
    "load_project",
    "open_store",
    "parse_manifest",
]

MANIFEST_FILENAME = "hephaestus.toml"
GLOBALS_FILENAME = "globals.py"
PARTS_DIRNAME = "parts"
CHECKS_DIRNAME = "checks"
STORE_DIRNAME = ".heph"
JOURNAL_DIRNAME = "journal"
EXPORTS_DIRNAME = "exports"
STATE_DB_NAME = "state.db"

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ProjectManifest:
    """Parsed ``hephaestus.toml``: name, units, ``[params]``, ``[dfm]``.

    ``dfm_auto_run`` is the project's DFM *mode* (mission Stage 6): with it on,
    every successful build carries the process pack's findings in its post-build
    critique block, unrequested, exactly as the other ``VALIDATION.md`` §4 rungs
    do. It is a project setting rather than a tool argument precisely so no model
    choice decides whether manufacturability gets checked.
    """

    name: str
    units: str = "mm"
    params: Mapping[str, int | float] = field(default_factory=dict[str, "int | float"])
    dfm_auto_run: bool = False


def parse_manifest(text: str, *, source: str = MANIFEST_FILENAME) -> ProjectManifest:
    """Parse manifest TOML; malformed input raises ``validation_error`` (contract).

    ``name`` is required and non-empty; ``units`` defaults to ``"mm"``; the
    optional ``[params]`` table holds project-parameter overrides whose values
    must be plain numbers (§3 — bools are not numbers); the optional ``[dfm]``
    table carries ``auto_run`` (default off), the project's DFM mode.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"{source}: invalid TOML: {exc}", kind="contract") from exc
    # ``name``/``units`` may live at top level or under a [project] table
    # (both manifest spellings appear in the wild; the corpus fixtures use
    # the [project] form). Top-level keys win when both are present.
    project_raw = data.get("project")
    if isinstance(project_raw, dict):
        project_table = cast("Mapping[str, object]", project_raw)
        for key in ("name", "units"):
            if key not in data and key in project_table:
                data[key] = project_table[key]
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError(
            f"{source}: 'name' is required and must be a non-empty string", kind="contract"
        )
    units = data.get("units", "mm")
    if not isinstance(units, str) or not units:
        raise ValidationError(f"{source}: 'units' must be a non-empty string", kind="contract")
    raw_params = data.get("params", {})
    if not isinstance(raw_params, dict):
        raise ValidationError(f"{source}: [params] must be a table", kind="contract")
    params: dict[str, int | float] = {}
    for key, value in cast("Mapping[object, object]", raw_params).items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValidationError(
                f"{source}: [params] {key!r} must be a number, got {type(value).__name__}",
                kind="contract",
            )
        params[str(key)] = value
    raw_dfm = data.get("dfm", {})
    if not isinstance(raw_dfm, dict):
        raise ValidationError(f"{source}: [dfm] must be a table", kind="contract")
    auto_run = cast("Mapping[str, object]", raw_dfm).get("auto_run", False)
    if not isinstance(auto_run, bool):
        raise ValidationError(f"{source}: [dfm] 'auto_run' must be a boolean", kind="contract")
    return ProjectManifest(name=name, units=units, params=params, dfm_auto_run=auto_run)


@dataclass(frozen=True)
class ProjectLayout:
    """One project directory plus its parsed manifest."""

    root: Path
    manifest: ProjectManifest

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILENAME

    @property
    def globals_path(self) -> Path:
        return self.root / GLOBALS_FILENAME

    @property
    def parts_dir(self) -> Path:
        return self.root / PARTS_DIRNAME

    @property
    def checks_dir(self) -> Path:
        return self.root / CHECKS_DIRNAME

    @property
    def store_root(self) -> Path:
        return self.root / STORE_DIRNAME

    @property
    def journal_dir(self) -> Path:
        return self.store_root / JOURNAL_DIRNAME

    @property
    def exports_dir(self) -> Path:
        return self.store_root / EXPORTS_DIRNAME

    def part_path(self, part: str) -> Path:
        """``parts/<part>.py`` for a validated part name."""
        if not _PART_NAME_RE.match(part):
            raise ValidationError(
                f"invalid part name {part!r} (expected a python identifier)", kind="contract"
            )
        return self.parts_dir / f"{part}.py"

    def part_names(self) -> tuple[str, ...]:
        """Lexically sorted names of every ``parts/*.py`` script."""
        if not self.parts_dir.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem for path in self.parts_dir.glob("*.py") if _PART_NAME_RE.match(path.stem)
            )
        )


def find_project_root(start: Path) -> Path:
    """Nearest ancestor (including ``start``) containing ``hephaestus.toml``."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / MANIFEST_FILENAME).is_file():
            return candidate
    raise ValidationError(f"no {MANIFEST_FILENAME} found at or above {start}", kind="contract")


def load_project(root: Path) -> ProjectLayout:
    """Load the project at ``root`` (which must contain ``hephaestus.toml``)."""
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValidationError(f"{manifest_path} does not exist", kind="contract")
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"), source=str(manifest_path))
    return ProjectLayout(root=root.resolve(), manifest=manifest)


def open_store(
    layout: ProjectLayout,
    *,
    clock: Clock | None = None,
    liveness: Liveness | None = None,
    crash_hook: CrashHook | None = None,
    lock_provider: LockProvider | None = None,
    protected_roots: ProtectedRoots | None = None,
) -> OpStore:
    """Open (or initialize) the project's ``.heph/`` opstore root.

    First open creates the store (keyring + ``state.db``); later opens are
    fail-closed on keyring loss per the opstore contract. The preimage
    journal directory is ensured alongside. When the caller supplies no
    ``protected_roots``, the §3.5 default policy applies: the current
    successful bundle and most-recent-failure record per part plus the live
    projection/check-set pointers are protected from GC
    (:mod:`hephaestus.core.project_store.retention`).
    """
    # Imported lazily to avoid a cycle (retention resolves pointer names
    # defined across project_store/checks modules that import layout).
    from hephaestus.core.project_store.retention import DefaultProtectedRoots

    layout.store_root.mkdir(parents=True, exist_ok=True)
    layout.journal_dir.mkdir(parents=True, exist_ok=True)
    opener = OpStore.open if (layout.store_root / STATE_DB_NAME).exists() else OpStore.create
    default_roots: DefaultProtectedRoots | None = None
    if protected_roots is None:
        default_roots = DefaultProtectedRoots(layout)
        protected_roots = default_roots
    store = opener(
        layout.store_root,
        clock=clock,
        liveness=liveness,
        crash_hook=crash_hook,
        lock_provider=lock_provider,
        protected_roots=protected_roots,
    )
    if default_roots is not None:
        default_roots.bind(store)
    return store
