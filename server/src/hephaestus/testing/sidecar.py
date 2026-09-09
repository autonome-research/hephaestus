# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Locating and building the packaged Node sidecar a bridge harness drives.

Every end-to-end bridge test must run the artifact a release would ship — never
a globally installed ``pi``/``thread-phase``. Through Stage 7G that artifact was
``agent/dist/`` from a plain ``tsc`` build, which is *not* what ships: ``dist/``
resolves four bare specifiers by walking up into ``agent/node_modules``, so it
could only ever run inside the repo. The wheel ships the bundled, integrity-
manifested sidecar instead, and this module now builds and stages exactly that,
so an in-repo suite and a wheel install exercise the same bytes.

:func:`build_agent_dist` runs the build at most once per process and returns
``None`` when Node or pnpm is absent, leaving the *skip vs fail* policy to each
suite, but raises when the toolchain is present and the build is broken so a
gate can never pass by silently skipping a broken sidecar.

Three properties this module owes its callers, each one an audit finding:

* **pnpm is resolved the way the documented bootstrap resolves it**
  (J-mirrors-and-dx-25). ``scripts/bootstrap.sh`` deliberately does *not*
  require a ``pnpm`` on PATH — ``CONTRIBUTING.md`` and ``docs/install.md`` each
  spend a paragraph on why that is unreliable under corepack — so a guard that
  asks ``shutil.which("pnpm")`` answered "no sidecar" on exactly the checkout
  the documentation tells a contributor to create. :func:`pnpm_command`
  implements the script's preference order and returns a command *list*, because
  two of the four routes are not a single path.
* **a skip that should not have happened is loud.** With
  ``HEPHAESTUS_REQUIRE_SIDECAR=1`` — set by every CI job that installs Node, and
  by the bootstrap lane — an unavailable toolchain raises instead of returning
  ``None``, so a regression that would once have quietly skipped twenty
  assertions fails by name. Same fail-rather-than-skip policy the renderer gate
  applies.
* **the build skip does not silently run stale TypeScript**
  (J-mirrors-and-dx-17). ``HEPHAESTUS_SKIP_SIDECAR_BUILD=1`` exists to make
  sidecar-backed lanes affordable, and it removed the only thing coupling the
  staged output to the source it was built from: the integrity manifest hashes
  the *staged* files, which is a tamper proof, never a freshness proof.
  :func:`sidecar_source_digest` hashes the *inputs*; staging records it and the
  skip path compares it.

In an installed wheel there is no ``agent/`` tree and no pnpm. The build
functions report that honestly (``None``); :func:`sidecar_main` and
:func:`workflow_runner_main` keep working, because they ask the resolver, which
finds the packaged sidecar.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

from hephaestus.agent_bridge.app import repo_root
from hephaestus.agent_bridge.sidecar import (
    NodeVersionError,
    SidecarError,
    resolve_sidecar,
)
from hephaestus.agent_bridge.sidecar import (
    node_executable as _checked_node_executable,
)

__all__ = [
    "REQUIRE_SIDECAR_ENV",
    "SidecarUnavailable",
    "agent_dir",
    "build_agent_dist",
    "node_available",
    "node_executable",
    "pnpm_command",
    "sidecar_main",
    "sidecar_root",
    "sidecar_source_digest",
    "workflow_runner_main",
]

#: Set by every CI job that installs Node. When it is ``"1"`` an unavailable
#: toolchain is a FAILURE rather than a skip: on a machine that installed the
#: toolchain, "node or pnpm unavailable" is a regression, not an environment
#: fact (J-mirrors-and-dx-25).
REQUIRE_SIDECAR_ENV = "HEPHAESTUS_REQUIRE_SIDECAR"

#: Overrides the pnpm resolution entirely, as a command line
#: (``HEPHAESTUS_PNPM="corepack pnpm"``). First in the same preference order
#: ``scripts/bootstrap.sh`` documents.
PNPM_ENV = "HEPHAESTUS_PNPM"

#: Skips the bundle+stage and uses whatever is already staged.
SKIP_BUILD_ENV = "HEPHAESTUS_SKIP_SIDECAR_BUILD"


class SidecarUnavailable(AssertionError):
    """Raised instead of skipping when :data:`REQUIRE_SIDECAR_ENV` is set."""


def _required() -> bool:
    return os.environ.get(REQUIRE_SIDECAR_ENV) == "1"


def _unavailable(reason: str) -> None:
    """Return quietly, or raise by name when the caller declared it must work."""
    if _required():
        raise SidecarUnavailable(
            f"{reason}. {REQUIRE_SIDECAR_ENV}=1 says this machine installed the "
            "toolchain, so this is a regression rather than an environment fact "
            "(docs/audit-2026-09-04-janky.md, J-mirrors-and-dx-25). Resolution "
            f"attempted: node={node_executable()!r}, pnpm={pnpm_command()!r}."
        )


def node_executable() -> str | None:
    """The Node binary to spawn the sidecar with, or ``None`` when unusable.

    Folds in the ≥22.19 compatibility check: a Node too old to run the sidecar
    is reported the same as no Node at all, so a suite skips rather than failing
    with an unexplained child crash.
    """
    try:
        return _checked_node_executable()
    except NodeVersionError:
        return None


def node_available() -> bool:
    """Whether a compatible Node binary can be found at all."""
    return bool(node_executable())


def agent_dir() -> Path:
    """The ``agent/`` workspace holding the sidecar sources (source tree only)."""
    return repo_root() / "agent"


def sidecar_root() -> Path:
    """The root of the verified sidecar tree this installation would spawn."""
    return resolve_sidecar().root


def sidecar_main() -> Path:
    """The built sidecar entry the supervisor spawns."""
    return resolve_sidecar().main


def workflow_runner_main() -> Path:
    """The built workflow runner entry the workflow supervisor spawns."""
    return resolve_sidecar().runner


#: The pnpm resolution's own memo. A NEGATIVE result is deliberately not cached
#: here: :data:`_DIST_CACHE` used to store ``None``, so once any call in a
#: process found no toolchain every later call skipped even after the situation
#: changed — which is how a fixture that stages a sidecar mid-session was
#: invisible to the rest of the run (J-mirrors-and-dx-17).
_DIST_CACHE: dict[str, tuple[Path, Path]] = {}


def pnpm_command() -> list[str] | None:
    """How to invoke pnpm, in ``scripts/bootstrap.sh``'s order of preference.

    Returned as a command LIST, because two of the four routes are not a single
    path. The order, and the reason for it, is the script's:

    1. :data:`PNPM_ENV`, so a harness can pin one exactly;
    2. whatever ``scripts/bootstrap.sh`` recorded on its last full run, so the
       script and these guards agree BY CONSTRUCTION rather than by two
       implementations of one preference order happening to match;
    3. a ``pnpm`` on PATH — including corepack's shim, which is a ``pnpm`` for
       this purpose: invoked from *inside* the package it re-execs the pinned
       version out of the ``packageManager`` field;
    4. ``corepack pnpm``, which fetches the pin on first use;
    5. ``npx --yes pnpm@<pin>``, with the pin read from the sidecar's manifest —
       never restated here, because a second copy of a version is a second thing
       to drift (``docs/install.md``).

    ``None`` only when none of them exists, which is a machine with no Node
    tooling at all.
    """
    override = os.environ.get(PNPM_ENV)
    if override:
        return shlex.split(override)
    recorded = _bootstrap_pnpm()
    if recorded is not None:
        return recorded
    on_path = shutil.which("pnpm")
    if on_path is not None:
        return [on_path]
    if shutil.which("corepack") is not None:
        return ["corepack", "pnpm"]
    if shutil.which("npx") is not None:
        pin = pnpm_pin()
        if pin is not None:
            return ["npx", "--yes", f"pnpm@{pin}"]
    return None


#: Where ``scripts/bootstrap.sh`` records the pnpm it resolved.
_BOOTSTRAP_RECORD = "agent/build/bootstrap_pnpm.json"


def _bootstrap_pnpm() -> list[str] | None:
    """The bootstrap's own resolution, when it still names something runnable."""
    record = repo_root() / _BOOTSTRAP_RECORD
    if not record.is_file():
        return None
    try:
        command = [str(word) for word in json.loads(record.read_text(encoding="utf-8"))["command"]]
    except (ValueError, KeyError, TypeError):
        return None
    if not command or shutil.which(command[0]) is None:
        # The recorded route has since left this machine; fall through rather
        # than fail, so a stale record can never be worse than no record.
        return None
    return command


def pnpm_pin() -> str | None:
    """The pinned pnpm version, read from ``agent/package.json``.

    The manifest field is the single source (``docs/install.md``); the workflow
    variable is the documented fallback and is asserted equal to it by
    ``tests/stage7h/test_tooling_config.py``.
    """
    manifest = agent_dir() / "package.json"
    if not manifest.is_file():
        return None
    try:
        field = str(json.loads(manifest.read_text(encoding="utf-8"))["packageManager"])
    except (ValueError, KeyError):
        return None
    name, _, version = field.partition("@")
    return version if name == "pnpm" and version else None


#: The sidecar's build INPUTS. Hashing these answers "was the staged tree built
#: from this source?", which the integrity manifest — a hash over the staged
#: OUTPUTS — cannot answer however carefully it is verified.
_SOURCE_INPUTS: tuple[str, ...] = (
    "agent/src",
    "agent/package.json",
    "agent/pnpm-lock.yaml",
    "agent/tsconfig.json",
    "agent/scripts/bundle.mjs",
    "schemas/bridge_limits.json",
)

#: Where the staging step's source digest is recorded. Outside the staged tree
#: on purpose: :func:`hephaestus.agent_bridge.sidecar.verify_sidecar` is
#: bidirectional, so an unmanifested file inside the sidecar root is an
#: integrity FAILURE. Gitignored build state, like the bundle beside it.
_DIGEST_RECORD = "agent/build/staged_source_digest.json"


def _source_files() -> dict[str, str] | None:
    """``{repo-relative path: sha256}`` for every input the bundle is built from."""
    root = repo_root()
    if not (root / "agent" / "src").is_dir():
        return None
    files: dict[str, str] = {}
    for entry in _SOURCE_INPUTS:
        path = root / entry
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root).as_posix()
            files[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return files


def sidecar_source_digest() -> str | None:
    """A sorted-path SHA-256 over every input the bundle is built from.

    ``None`` in an installed wheel, where there is no ``agent/`` tree — the
    packaged sidecar has no source to be stale against.
    """
    files = _source_files()
    if files is None:
        return None
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(files[relative]))
    return digest.hexdigest()


def record_staged_source_digest() -> None:
    """Record what the CURRENTLY staged sidecar was built from.

    The staging step's companion, and it must run wherever staging runs. The
    in-process build path below calls it directly; CI stages by invoking
    ``scripts/stage_sidecar.py``, which knows nothing about this record, so the
    workflow calls this module as ``python -m hephaestus.testing.sidecar``
    immediately afterwards. Without that, every CI job that later sets
    ``HEPHAESTUS_SKIP_SIDECAR_BUILD=1`` takes :func:`_check_staged_is_fresh`'s
    warn-once *unknown* branch and the freshness guard is inert exactly where it
    matters most (J-mirrors-and-dx-17).
    ``tests/stage7h/test_sidecar_toolchain.py`` asserts the pairing.
    """
    files = _source_files()
    if files is None:
        return
    record = repo_root() / _DIGEST_RECORD
    record.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source_digest": sidecar_source_digest(), "files": files}
    record.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_staleness_warned = False


def _check_staged_is_fresh() -> None:
    """On the build-skip path, refuse a staged tree built from other sources.

    The escape hatch that makes sidecar-backed lanes affordable also made them
    assert against stale TypeScript in silence (J-mirrors-and-dx-17). This is the
    only thing that couples the staged output back to its inputs.

    A checkout whose staging predates this record is treated as *unknown* and
    warns exactly once, so nobody's tree breaks on upgrade.
    """
    global _staleness_warned
    current = sidecar_source_digest()
    if current is None:
        return
    record = repo_root() / _DIGEST_RECORD
    if not record.is_file():
        if not _staleness_warned:
            _staleness_warned = True
            warnings.warn(
                f"{SKIP_BUILD_ENV}=1 and the staged sidecar records no source digest, "
                "so its freshness is UNKNOWN. Re-stage once to start checking: "
                "`(cd agent && pnpm run bundle) && uv run python scripts/stage_sidecar.py"
                " && uv run python -m hephaestus.testing.sidecar`.",
                RuntimeWarning,
                stacklevel=2,
            )
        return
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
        recorded = str(payload["source_digest"])
        recorded_files: dict[str, str] = dict(payload.get("files") or {})
    except (ValueError, KeyError, TypeError):
        return
    if recorded == current:
        return
    now = _source_files() or {}
    changed = sorted(
        set(recorded_files) ^ set(now)
        | {name for name in set(recorded_files) & set(now) if recorded_files[name] != now[name]}
    )
    raise AssertionError(
        f"{SKIP_BUILD_ENV}=1 but the staged sidecar was built from different sources: "
        f"{len(changed)} input file(s) differ, first {', '.join(changed[:5])}. The "
        "integrity manifest cannot see this — it hashes the staged OUTPUT, which is a "
        "tamper proof, not a freshness proof. One command fixes it:\n"
        "    (cd agent && pnpm run bundle) && uv run python scripts/stage_sidecar.py"
        " && uv run python -m hephaestus.testing.sidecar"
    )


def build_agent_dist() -> tuple[Path, Path] | None:
    """Build+stage the sidecar once and return ``(main.js, workflows/runner.js)``.

    Returns ``None`` when the toolchain or the source tree is unavailable — the
    caller decides whether that is a skip, unless :data:`REQUIRE_SIDECAR_ENV`
    says it must not be, in which case this raises by name. Fails loudly when
    the build itself is broken. A successful result is cached for the process so
    a whole suite pays for at most one bundle; an unsuccessful one is NOT, so a
    later call sees a toolchain that has since appeared.
    """
    cached = _DIST_CACHE.get("built")
    if cached is not None:
        return cached
    result = _build_agent_dist()
    if result is not None:
        _DIST_CACHE["built"] = result
    return result


def _run(argv: list[str], *, what: str, cwd: Path | None = None) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, check=False, cwd=cwd)
    if proc.returncode != 0:
        raise AssertionError(f"{what} failed:\n{proc.stdout}\n{proc.stderr}")


def _build_agent_dist() -> tuple[Path, Path] | None:
    if node_executable() is None:
        _unavailable("no Node >= 22.19 on this machine")
        return None
    pnpm = pnpm_command()
    if pnpm is None:
        _unavailable("no pnpm, corepack or npx on this machine")
        return None
    agent = agent_dir()
    stage_script = repo_root() / "scripts" / "stage_sidecar.py"
    if not agent.is_dir() or not stage_script.is_file():
        # An installed wheel: nothing to build. Whatever is packaged is what runs.
        return None
    if os.environ.get(SKIP_BUILD_ENV) == "1":
        _check_staged_is_fresh()
    else:
        # From INSIDE agent/, never `--dir`: `--dir` moves the install but not the
        # version resolution, because corepack picks `packageManager` by walking
        # up from the current directory (CONTRIBUTING.md, "pnpm: the pin").
        _run([*pnpm, "run", "bundle"], what="sidecar bundle", cwd=agent)
        _run([sys.executable, str(stage_script)], what="sidecar staging")
        record_staged_source_digest()
    try:
        resolution = resolve_sidecar()
    except SidecarError as exc:  # pragma: no cover - a broken build must be loud
        raise AssertionError(f"sidecar unusable after build: {exc}") from exc
    return resolution.main, resolution.runner


if __name__ == "__main__":  # pragma: no cover - the CI staging step's companion
    # `python -m hephaestus.testing.sidecar`, run straight after
    # `scripts/stage_sidecar.py` in a workflow. A module entry point rather than
    # a `-c` one-liner in YAML so the invocation is greppable from the code.
    record_staged_source_digest()
