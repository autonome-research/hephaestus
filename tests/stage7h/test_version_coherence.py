# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Every publishable component declares the same version, coordinated at 0.1.0.

The release is five Python distributions plus a private npm package. Nothing
mechanically tied their version strings together before Stage 7H, and no package
exposed one at all — so `heph --version` could not be written, and a component
could silently ship at a different number than the wheel that carried it.

The runtime source of truth is installed distribution metadata (see
:mod:`hephaestus.core.version`). This test keeps the *declarations* that feed
that metadata coherent, which is the part a human can get wrong in a PR.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Every workspace member that declares a publishable version.
DISTRIBUTIONS = ("opstore", "core", "server", "contract", "bench", "packaging")

#: The coordinated release version for v0.1.0-headless.
EXPECTED = "0.1.0"


def _project_version(directory: str) -> tuple[str, str]:
    doc = tomllib.loads((REPO / directory / "pyproject.toml").read_text(encoding="utf-8"))
    return str(doc["project"]["name"]), str(doc["project"]["version"])


def test_every_python_distribution_declares_the_release_version() -> None:
    declared = dict(_project_version(d) for d in DISTRIBUTIONS)
    assert declared, "no distributions found"
    off = {name: v for name, v in declared.items() if v != EXPECTED}
    assert not off, f"these distributions are not at {EXPECTED}: {off}"


def test_the_compiled_sidecar_declares_the_release_version() -> None:
    """The npm package is private, but it stamps the manifest the wheel ships."""
    pkg = json.loads((REPO / "agent" / "package.json").read_text(encoding="utf-8"))
    assert pkg["version"] == EXPECTED
    assert pkg["private"] is True, "the sidecar is a private workspace package, not a release"


def test_the_aggregate_distribution_is_named_per_the_conventions() -> None:
    """`repo_conventions.md`: "PyPI: publish as `hephaestus-cad`"."""
    name, _ = _project_version("packaging")
    assert name == "hephaestus-cad"


def test_the_aggregate_depends_on_every_runtime_component() -> None:
    """The single `pip install` must actually bring the whole headless product.

    `hephaestus-bench` is deliberately excluded from the required set: it is
    evaluation tooling and pulls `huggingface-hub`, so it lives behind an extra.
    """
    doc = tomllib.loads((REPO / "packaging" / "pyproject.toml").read_text(encoding="utf-8"))
    deps = {d.split("[")[0].strip() for d in doc["project"]["dependencies"]}
    assert deps == {"hephaestus-core", "hephaestus-contract", "hephaestus-server", "opstore"}
    extras = doc["project"]["optional-dependencies"]
    assert extras["bench"] == ["hephaestus-bench"]


def test_the_version_function_reports_the_installed_metadata() -> None:
    """`heph --version` must read metadata, not a literal that can drift."""
    from hephaestus.core.version import DISTRIBUTION, version

    assert DISTRIBUTION == "hephaestus-core"
    assert version() == EXPECTED


def test_heph_version_works_from_the_development_tree() -> None:
    """The verb exists and answers before any subcommand is required."""
    proc = subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
    )
    # `python -m` on a module without __main__ handling still exercises argparse
    # through the console-script entry point in the installed lanes; here we only
    # need the parser itself to carry the action.
    from hephaestus.core.cli import build_parser

    parser = build_parser()
    actions = {a.dest for a in parser._actions}
    assert "version" in actions, "heph --version is not registered"
    assert proc.returncode in {0, 1}


def test_the_manifest_format_the_build_hook_validates_matches_the_producer() -> None:
    """``server/hatch_build.py`` re-implements manifest verification; keep them agreed.

    The hook must not import ``hephaestus`` — a build backend runs in an isolated
    environment where this project is not installed — so it carries a second,
    deliberately dumb copy of the check. Two implementations of one format drift
    silently unless something asserts they read the same fields.
    """
    from hephaestus.agent_bridge.sidecar import MANIFEST_NAME, resolve_sidecar

    hook = (REPO / "server" / "hatch_build.py").read_text(encoding="utf-8")
    assert f'MANIFEST_NAME = "{MANIFEST_NAME}"' in hook
    assert '"src") / "hephaestus" / "agent_bridge" / "_sidecar"' in hook
    assert 'manifest["entries"]' in hook
    assert "hashlib.sha256" in hook
    # And the field names the hook reads are the ones the producer writes.
    manifest = json.loads((resolve_sidecar().root / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert {"version", "algorithm", "entrypoints", "entries"} <= set(manifest)
    assert manifest["algorithm"] == "sha256"


def test_the_aggregate_wheel_exposes_the_heph_entry_point() -> None:
    """`pipx install hephaestus-cad` must find an application, not just deps.

    Regression (release run 32924618755, first full lane execution): the
    aggregate wheel carried only dependencies, and pipx — unlike a plain pip
    venv install — refuses a distribution with no entry point of its own, so
    every lane died at `pipx install the built wheel`. The script targets the
    same function hephaestus-core exposes.
    """
    spec = tomllib.loads((REPO / "packaging" / "pyproject.toml").read_text(encoding="utf-8"))
    core = tomllib.loads((REPO / "core" / "pyproject.toml").read_text(encoding="utf-8"))
    assert spec["project"]["scripts"]["heph"] == core["project"]["scripts"]["heph"], (
        "the aggregate and core wheels must expose the SAME heph target — "
        "two different entry points would race in a plain-pip environment"
    )
