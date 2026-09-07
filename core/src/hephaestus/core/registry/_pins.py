"""Project-side pinning: the ``[registries]`` table of ``hephaestus.toml``.

A pin says where a registry tree lives and what it must hash to.
``heph registry pin``/``update`` is the only path that writes one, and writing
rewrites *only* the registry sections — every other byte of the manifest is
preserved, and the result is re-parsed before the write commits.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.errors import ValidationError

from ._fields import req_str, table
from ._layout import BUNDLED_KINDS, MANIFEST_FILENAME

__all__ = [
    "BUNDLED_SCHEME",
    "REGISTRIES_TABLE",
    "RegistryPin",
    "bundled_pins",
    "bundled_registries_root",
    "read_pins",
    "write_pins",
]

#: The ``hephaestus.toml`` table holding registry pins.
REGISTRIES_TABLE: Final[str] = "registries"

#: Symbolic ``path`` prefix meaning "the registries bundled with whichever
#: installation reads this manifest", resolved per machine by
#: :meth:`RegistryPin.resolve`. ``bundled_registries_root()`` is a *runtime*
#: convenience — under an editable install it is the developer's clone — and
#: writing its answer into ``hephaestus.toml`` put an absolute path into a file
#: the documentation says to commit, making the project unusable on any other
#: machine (ledger J-cli-robustness-3). The digest beside the pin still pins the
#: bytes, so a machine whose installation ships different bytes fails
#: ``heph registry verify`` by design.
BUNDLED_SCHEME: Final[str] = "bundled:"

_SECTION_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\[")
_REGISTRIES_SECTION_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*\[" + REGISTRIES_TABLE + r"(?:\.[^\]]*)?\]\s*$"
)


@dataclass(frozen=True)
class RegistryPin:
    """One ``[registries.<name>]`` entry: where the tree is and what it hashes to."""

    name: str
    path: str
    digest: str | None = None

    @property
    def is_bundled(self) -> bool:
        """Whether ``path`` is the symbolic :data:`BUNDLED_SCHEME` form."""
        return self.path.startswith(BUNDLED_SCHEME)

    def resolve(self, project_root: Path) -> Path:
        """The directory this pin names on *this* machine.

        A ``bundled:<kind>`` path resolves through
        :func:`bundled_registries_root` at read time; an installation that ships
        none refuses by name rather than resolving to a path that is not there.
        Absolute and project-relative paths resolve exactly as before, so pins
        written before the symbolic form existed keep working with no migration.
        """
        if self.is_bundled:
            root = bundled_registries_root()
            if root is None:
                raise ValidationError(
                    f"registry {self.name!r} is pinned as {self.path!r}, but this "
                    "installation ships no bundled registries; pass --path DIR to pin "
                    "a tree this machine has",
                    kind="contract",
                )
            return root / self.path[len(BUNDLED_SCHEME) :]
        candidate = Path(self.path)
        return candidate if candidate.is_absolute() else (project_root / candidate)


def read_pins(project_root: Path) -> dict[str, RegistryPin]:
    """Parse the ``[registries]`` table of ``<project_root>/hephaestus.toml``."""
    manifest_path = project_root / "hephaestus.toml"
    if not manifest_path.is_file():
        raise ValidationError(f"{manifest_path} does not exist", kind="contract")
    source = str(manifest_path)
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"{source}: invalid TOML: {exc}", kind="contract") from exc
    entries = table(cast("Mapping[str, Any]", raw), REGISTRIES_TABLE, source=source)
    pins: dict[str, RegistryPin] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise ValidationError(f"{source}: [registries.{name}] must be a table", kind="contract")
        record = cast("Mapping[str, Any]", entry)
        digest = record.get("digest")
        pins[str(name)] = RegistryPin(
            name=str(name),
            path=req_str(record, "path", source=f"{source} [registries.{name}]"),
            digest=str(digest) if isinstance(digest, str) and digest else None,
        )
    return pins


def _render_pins(pins: Mapping[str, RegistryPin]) -> str:
    lines: list[str] = []
    for name in sorted(pins):
        pin = pins[name]
        lines.append(f"[{REGISTRIES_TABLE}.{name}]")
        lines.append(f"path = {json.dumps(pin.path)}")
        if pin.digest:
            lines.append(f"digest = {json.dumps(pin.digest)}")
        lines.append("")
    return "\n".join(lines)


def write_pins(project_root: Path, pins: Mapping[str, RegistryPin]) -> None:
    """Rewrite exactly the ``[registries...]`` sections of ``hephaestus.toml``.

    Every other line of the manifest is preserved byte for byte: the existing
    registry sections are removed and one freshly rendered, name-sorted block is
    appended. The result is re-parsed before the write commits, so a manifest is
    never left unparseable.
    """
    manifest_path = project_root / "hephaestus.toml"
    if not manifest_path.is_file():
        raise ValidationError(f"{manifest_path} does not exist", kind="contract")
    kept: list[str] = []
    dropping = False
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if _REGISTRIES_SECTION_RE.match(line):
            dropping = True
            continue
        if dropping:
            if _SECTION_RE.match(line):
                dropping = False
            else:
                continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    body = "\n".join(kept)
    rendered = _render_pins(pins)
    text = f"{body}\n\n{rendered}" if rendered else f"{body}\n"
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        raise ValidationError(
            f"{manifest_path}: refusing to write an unparseable manifest: {exc}", kind="contract"
        ) from exc
    manifest_path.write_text(text, encoding="utf-8")


def bundled_registries_root() -> Path | None:
    """The ``registries/`` directory shipped alongside this installation, if any."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "registries"
        if (candidate / "skills" / MANIFEST_FILENAME).is_file():
            return candidate
    return None


def bundled_pins() -> dict[str, RegistryPin]:
    """Unverified pins for the bundled registries (symbolic path, no digest).

    The path is :data:`BUNDLED_SCHEME` plus the kind, never the resolved
    directory: these pins are a *write* source for ``heph registry pin``, and an
    absolute host path in a committed manifest is a note to yourself, not the
    reviewable claim ``docs/registry-pinning.md`` requires.
    """
    root = bundled_registries_root()
    if root is None:
        return {}
    pins: dict[str, RegistryPin] = {}
    for kind in BUNDLED_KINDS:
        if (root / kind / MANIFEST_FILENAME).is_file():
            pins[kind] = RegistryPin(name=kind, path=f"{BUNDLED_SCHEME}{kind}", digest=None)
    return pins
