# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The one place that answers "which sidecar do we spawn, and is it intact?".

`repo_conventions.md` §Naming and packaging binds three properties that this
module owns end to end:

* `heph agent` and agent-enabled serving **execute the wheel's integrity-checked
  sidecar — never a global `pi` or `thread-phase` binary**;
* they require **Node ≥22.19** and perform *an explicit startup compatibility
  check* rather than discovering the incompatibility as a syntax error;
* the shipped sidecar is a **bounded artifact** with no required native addon.

Before Stage 7H the first property was unenforceable and the second absent.
Three modules each re-derived ``Path(__file__).resolve().parents[4]`` and
appended ``agent/dist/…``; that arithmetic is only true inside a source
checkout, so an installed wheel resolved its sidecar to a path above
``site-packages`` that has never existed. Nothing computed or checked a digest.

The policy here is ordered and **fail-closed at every step** — a resolution that
cannot be completed raises a named error, and no branch ever degrades into
"spawn whatever ``pi`` is on PATH":

1. **override** — ``$HEPHAESTUS_SIDECAR`` (or an explicit constructor argument)
   names a sidecar root. Used by CI lanes that pin a specific artifact. A named
   override that does not resolve is an error, never a fallback.
2. **packaged** — the sidecar shipped inside this distribution, located with
   :mod:`importlib.resources` anchored on this *regular* package (never
   ``__file__`` arithmetic, never the ``hephaestus`` namespace package, whose
   ``files()`` is not usable on 3.11). This is the branch an installed wheel
   takes, and G7H requires a test proving it.
3. **development** — ``<repo>/agent/build/sidecar`` in a source checkout, and
   only when step 2 found *nothing at all*. A packaged sidecar that exists but
   fails verification refuses; it must never be "repaired" by silently reaching
   for the developer's tree, because that is exactly how a tampered release
   would go unnoticed on the one machine that could detect it.

Integrity is verified against ``MANIFEST.json``, generated at build time
(``scripts/stage_sidecar.py``). Verification is **bidirectional**: every
manifest entry must be present with a matching SHA-256, *and* the tree must
contain no file the manifest does not list. A one-directional check would let an
attacker add a module that the bundle's chunk graph then imports.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final, cast

__all__ = [
    "MANIFEST_NAME",
    "MINIMUM_NODE",
    "SIDECAR_PACKAGE",
    "NodeMissingError",
    "NodeTooOldError",
    "NodeVersionError",
    "SidecarError",
    "SidecarIntegrityError",
    "SidecarManifest",
    "SidecarMissingError",
    "SidecarResolution",
    "development_sidecar_root",
    "node_executable",
    "packaged_sidecar_root",
    "resolve_sidecar",
    "verify_sidecar",
    "write_manifest",
]

#: Name of the integrity manifest at the root of a sidecar tree.
MANIFEST_NAME: Final[str] = "MANIFEST.json"

#: The regular package the packaged sidecar is anchored to. Deliberately *not*
#: ``hephaestus`` — that is an implicit namespace package split across four
#: distributions, and ``importlib.resources.files()`` on a namespace package is
#: not usable on the 3.11 floor this project supports.
SIDECAR_PACKAGE: Final[str] = "hephaestus.agent_bridge"

#: Directory name of the packaged sidecar inside :data:`SIDECAR_PACKAGE`.
SIDECAR_DIRNAME: Final[str] = "_sidecar"

#: ``agent/package.json`` declares ``engines.node >=22.19``; the supervisor
#: refuses to spawn under anything older instead of letting the child die on a
#: syntax error whose message names no version at all.
MINIMUM_NODE: Final[tuple[int, int]] = (22, 19)

#: Environment variable naming an explicit sidecar root (branch 1).
SIDECAR_ENV: Final[str] = "HEPHAESTUS_SIDECAR"

#: Environment variable naming the Node binary to spawn.
NODE_ENV: Final[str] = "HEPHAESTUS_NODE"

#: Logical entry-point names every sidecar manifest must declare, mapped to the
#: supervisor that spawns each one.
ENTRYPOINTS: Final[tuple[str, ...]] = ("main", "runner")


class SidecarError(RuntimeError):
    """Base class for every fail-closed sidecar refusal.

    Every subclass carries a stable ``code`` so a CLI or MCP surface can report
    a structured refusal rather than a bare traceback.
    """

    code: str = "sidecar_error"


class SidecarMissingError(SidecarError):
    """No sidecar could be located at all (or a named one does not exist)."""

    code = "sidecar_missing"


class SidecarIntegrityError(SidecarError):
    """A sidecar was located but does not match its integrity manifest."""

    code = "sidecar_integrity"


class NodeVersionError(SidecarError):
    """Node is absent, or older than :data:`MINIMUM_NODE`."""

    code = "node_incompatible"


class NodeMissingError(NodeVersionError):
    """No ``node`` on PATH at all.

    Split from :class:`NodeTooOldError` — both keep ``node_incompatible`` as
    their bridge code, so nothing that catches :class:`NodeVersionError` or
    reads ``.code`` changes — because ``INTERFACE.md`` §7A.8's closed
    ``agent_unavailable`` cause vocabulary distinguishes ``node_missing`` from
    ``node_too_old``, and the two need different sentences from an operator's
    point of view: install Node, or upgrade it. Deriving that distinction by
    matching on an exception *message* would put a machine-readable refusal at
    the mercy of a sentence edit.
    """


class NodeTooOldError(NodeVersionError):
    """Node exists but is older than :data:`MINIMUM_NODE` (or unreadable)."""


def _str_map(value: object) -> dict[str, str] | None:
    """A ``{str: str}`` view of a JSON object, or ``None`` if it is not one.

    The manifest is read *before* the tree it describes is trusted, so its own
    shape gets checked rather than assumed: a manifest whose entries are not
    plain strings is a corrupt manifest, not a crash site.
    """
    if not isinstance(value, dict):
        return None
    items = cast("dict[object, object]", value)
    return {str(k): str(v) for k, v in items.items()}


@dataclass(frozen=True, slots=True)
class SidecarManifest:
    """The build-time integrity record shipped at the root of a sidecar tree."""

    version: str
    algorithm: str
    #: ``relative posix path -> sha256 hex``. Excludes the manifest itself.
    entries: dict[str, str]
    #: Logical name -> relative posix path (``main``, ``runner``).
    entrypoints: dict[str, str]

    @staticmethod
    def load(path: Path) -> SidecarManifest:
        """Parse ``MANIFEST.json``, refusing anything structurally unusable."""
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SidecarIntegrityError(f"sidecar manifest is unreadable: {path} ({exc})") from exc
        if not isinstance(raw, dict):
            raise SidecarIntegrityError(f"sidecar manifest is not an object: {path}")
        doc = cast("dict[str, object]", raw)
        algorithm = doc.get("algorithm")
        if algorithm != "sha256":
            raise SidecarIntegrityError(
                f"sidecar manifest declares unsupported algorithm {algorithm!r}: {path}"
            )
        entries = _str_map(doc.get("entries"))
        entrypoints = _str_map(doc.get("entrypoints"))
        if entries is None or entrypoints is None:
            raise SidecarIntegrityError(f"sidecar manifest is missing entries/entrypoints: {path}")
        missing = [name for name in ENTRYPOINTS if name not in entrypoints]
        if missing:
            raise SidecarIntegrityError(
                f"sidecar manifest declares no {'/'.join(missing)} entrypoint: {path}"
            )
        return SidecarManifest(
            version=str(doc.get("version", "")),
            algorithm="sha256",
            entries=entries,
            entrypoints=entrypoints,
        )


@dataclass(frozen=True, slots=True)
class SidecarResolution:
    """A verified sidecar: where it came from, and the entries to spawn."""

    root: Path
    #: ``"override"`` | ``"packaged"`` | ``"development"`` — which branch won.
    source: str
    manifest: SidecarManifest

    @property
    def main(self) -> Path:
        """The session sidecar entry (``main.js``)."""
        return self.root / self.manifest.entrypoints["main"]

    @property
    def runner(self) -> Path:
        """The workflow-runner entry (``workflows/runner.js``)."""
        return self.root / self.manifest.entrypoints["runner"]

    @property
    def packaged(self) -> bool:
        """Whether this sidecar came from inside the installed distribution."""
        return self.source == "packaged"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk(root: Path) -> Iterator[Path]:
    """Every regular file under ``root``, manifest excluded, in sorted order."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != MANIFEST_NAME:
            yield path


def verify_sidecar(root: Path) -> SidecarManifest:
    """Verify ``root`` against its manifest, or raise a named refusal.

    Bidirectional by construction: a missing file, a changed byte, *and* an
    unexpected extra file are all integrity failures. The extra-file direction
    matters as much as the others — the bundle is a chunk graph, so a planted
    module is reachable the moment an existing chunk names it.
    """
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise SidecarIntegrityError(f"sidecar has no {MANIFEST_NAME}: {root}")
    manifest = SidecarManifest.load(manifest_path)

    on_disk = {path.relative_to(root).as_posix(): path for path in _walk(root)}
    expected = set(manifest.entries)
    actual = set(on_disk)

    if missing := sorted(expected - actual):
        raise SidecarIntegrityError(
            f"sidecar is missing {len(missing)} manifested file(s): {', '.join(missing[:5])}"
        )
    if extra := sorted(actual - expected):
        raise SidecarIntegrityError(
            f"sidecar carries {len(extra)} file(s) absent from its manifest: {', '.join(extra[:5])}"
        )
    for rel in sorted(expected):
        digest = _sha256(on_disk[rel])
        if digest != manifest.entries[rel]:
            raise SidecarIntegrityError(
                f"sidecar file {rel} does not match its manifest digest "
                f"(expected {manifest.entries[rel][:12]}…, got {digest[:12]}…)"
            )
    for name in ENTRYPOINTS:
        entry = root / manifest.entrypoints[name]
        if not entry.is_file():
            raise SidecarIntegrityError(f"sidecar {name} entrypoint is absent: {entry}")
    return manifest


def write_manifest(root: Path, *, version: str) -> SidecarManifest:
    """Hash every file under ``root`` and write ``MANIFEST.json`` beside them.

    Called by the staging step, not at runtime. Kept here, next to
    :func:`verify_sidecar`, so the producer and the consumer of the format can
    never drift apart.
    """
    entries = {path.relative_to(root).as_posix(): _sha256(path) for path in _walk(root)}
    entrypoints = {"main": "main.js", "runner": "workflows/runner.js"}
    for name, rel in entrypoints.items():
        if rel not in entries:
            raise SidecarMissingError(f"cannot manifest a sidecar with no {name} entry: {rel}")
    manifest = SidecarManifest(
        version=version, algorithm="sha256", entries=entries, entrypoints=entrypoints
    )
    payload = {
        "version": version,
        "algorithm": "sha256",
        "entrypoints": entrypoints,
        "entries": dict(sorted(entries.items())),
    }
    (root / MANIFEST_NAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def packaged_sidecar_root() -> Path | None:
    """The sidecar shipped inside this distribution, or ``None`` if unpackaged.

    Anchored with :mod:`importlib.resources` on :data:`SIDECAR_PACKAGE` so the
    answer is "wherever this package actually lives" — a wheel in
    ``site-packages``, an editable install, a zip — rather than a guess derived
    from ``__file__`` and a parent count that only holds inside a checkout.
    """
    try:
        anchor = resources.files(SIDECAR_PACKAGE)
    except (ModuleNotFoundError, TypeError):  # pragma: no cover - defensive
        return None
    candidate = anchor / SIDECAR_DIRNAME
    # `as_file` would materialise a zip-backed tree into a temp dir that vanishes
    # on context exit; a spawned child outlives that. Requiring a real directory
    # is the honest constraint, and every wheel install satisfies it.
    try:
        path = Path(str(candidate))
    except TypeError:  # pragma: no cover - non-filesystem loader
        return None
    return path if path.is_dir() else None


def development_sidecar_root() -> Path | None:
    """``<repo>/agent/build/sidecar`` when running from a source checkout.

    Located by walking up from this file looking for the ``agent/package.json``
    that declares the private sidecar package — a marker, not a fixed parent
    count, so the answer survives the tree being reorganised.
    """
    for parent in Path(__file__).resolve().parents:
        marker = parent / "agent" / "package.json"
        if not marker.is_file():
            continue
        try:
            name = json.loads(marker.read_text(encoding="utf-8")).get("name")
        except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
            continue
        if name != "@hephaestus/agent":
            continue
        root = parent / "agent" / "build" / "sidecar"
        return root if root.is_dir() else None
    return None


def resolve_sidecar(override: Path | str | None = None) -> SidecarResolution:
    """Locate and verify the sidecar to spawn, or raise a named refusal.

    See the module docstring for the ordered policy. The one subtlety worth
    restating: the development branch is reachable only when *no* packaged
    sidecar directory exists. A packaged sidecar that fails verification is a
    refusal, so the machine most able to notice tampering is not the one machine
    that silently routes around it.
    """
    named = override if override is not None else os.environ.get(SIDECAR_ENV) or None
    if named is not None:
        root = Path(named).expanduser().resolve()
        if not root.is_dir():
            raise SidecarMissingError(f"{SIDECAR_ENV} names no sidecar directory: {root}")
        return SidecarResolution(root=root, source="override", manifest=verify_sidecar(root))

    packaged = packaged_sidecar_root()
    if packaged is not None:
        return SidecarResolution(
            root=packaged, source="packaged", manifest=verify_sidecar(packaged)
        )

    development = development_sidecar_root()
    if development is not None:
        return SidecarResolution(
            root=development, source="development", manifest=verify_sidecar(development)
        )

    raise SidecarMissingError(
        "no packaged sidecar in this installation and no built sidecar in a source "
        "checkout (run `pnpm --dir agent run bundle` then "
        "`uv run python scripts/stage_sidecar.py`). Refusing to fall back to a "
        "global pi/thread-phase install."
    )


_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _node_version(executable: str) -> tuple[int, int, int]:
    try:
        proc = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except OSError as exc:
        raise NodeTooOldError(f"could not execute node at {executable}: {exc}") from exc
    match = _VERSION_RE.search(proc.stdout.strip())
    if proc.returncode != 0 or match is None:
        raise NodeTooOldError(
            f"`{executable} --version` did not report a version "
            f"(exit {proc.returncode}, output {proc.stdout.strip()!r})"
        )
    return int(match[1]), int(match[2]), int(match[3])


def node_executable() -> str:
    """The interpreter to spawn the sidecar with, after the ≥22.19 check.

    `repo_conventions.md` requires "an explicit startup compatibility check".
    Before Stage 7H the bridge only checked that *some* ``node`` existed, so an
    older runtime surfaced as an unexplained child crash on modern syntax.

    **The version gate applies to the Node we discover on PATH, not to an
    explicit** ``$HEPHAESTUS_NODE``. That variable is not a hint about where
    Node lives — it is the standing "spawn exactly this" override, and the test
    harness relies on it to run a *scripted Python* fake sidecar with no Node
    involved at all. Version-gating an explicitly named interpreter would break
    that contract while protecting nobody: an operator who names a binary has
    already decided. This mirrors ``BridgeRuntime(dist_main=…)``, where naming
    an exact entry file likewise bypasses sidecar resolution.

    The gate therefore guards the case it exists for — a real installation
    picking up whatever ``node`` happens to be first on PATH.
    """
    override = os.environ.get(NODE_ENV)
    if override:
        return override

    executable = shutil.which("node")
    if executable is None:
        raise NodeMissingError(
            f"node executable not found (set {NODE_ENV} or install Node "
            f">={MINIMUM_NODE[0]}.{MINIMUM_NODE[1]})"
        )
    major, minor, patch = _node_version(executable)
    if (major, minor) < MINIMUM_NODE:
        raise NodeTooOldError(
            f"node {major}.{minor}.{patch} at {executable} is older than the required "
            f">={MINIMUM_NODE[0]}.{MINIMUM_NODE[1]} (agent/package.json engines.node)"
        )
    return executable
