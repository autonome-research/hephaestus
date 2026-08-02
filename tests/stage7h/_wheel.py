# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Stage 7H helpers: build the wheels, install them, and probe the install.

G7H's central claim is "the wheel uses its packaged sidecar". That is only
testable against a *real installation*: an in-repo import would resolve the
development sidecar and prove nothing. So this module owns the expensive parts —
one `uv build` and one throwaway venv per session — and every lane test asserts
against subprocesses run with the installed interpreter.

The venv is created with `--no-project` and installed from `--find-links` over a
local wheelhouse. Nothing in these tests may import `hephaestus` in the *test*
process and pass it off as evidence about the wheel.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: The aggregate distribution the mission names as "the PyPI wheel".
DISTRIBUTION = "hephaestus-cad"


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:  # pragma: no cover - uv is the documented toolchain
        pytest.skip("uv is not on PATH; the wheel lanes need it to build and install")
    return uv


def _run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(list(argv), capture_output=True, text=True, check=False, **kwargs)
    if proc.returncode != 0:
        raise AssertionError(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc


def build_wheelhouse(out: Path) -> Path:
    """Build every workspace distribution into ``out`` and return it.

    ``$HEPHAESTUS_WHEELHOUSE`` short-circuits the build and uses that directory
    instead. The release lanes set it to the artifact the `wheelhouse` job
    produced, so every lane measures *the bytes that would be published* rather
    than a second build of the same tree. It is a pointer, not a relaxation:
    the directory must already contain wheels, and the assertions below are
    unchanged.
    """
    prebuilt = os.environ.get("HEPHAESTUS_WHEELHOUSE")
    if prebuilt:
        given = Path(prebuilt)
        wheels = list(given.glob("*.whl"))
        assert wheels, f"$HEPHAESTUS_WHEELHOUSE={given} contains no wheels"
        return given
    _run([_uv(), "build", "--all-packages", "--out-dir", str(out)], cwd=REPO)
    wheels = list(out.glob("*.whl"))
    assert wheels, f"uv build produced no wheels in {out}"
    return out


#: Distributions that make up the headless product. `hephaestus-bench` is
#: deliberately absent: it is evaluation tooling behind the `bench` extra, and a
#: lane that installed it would not be measuring the product wheel.
PRODUCT_WHEELS = (
    "hephaestus_cad",
    "hephaestus_core",
    "hephaestus_contract",
    "hephaestus_server",
    "opstore",
)


def install_wheel(venv: Path, wheelhouse: Path, distribution: str) -> Path:
    """Create ``venv`` and install the product wheels **by explicit local path**.

    Naming the files, rather than passing ``--find-links`` and a distribution
    name, is what keeps this honest once these names exist on PyPI: a resolver
    free to reach the index could satisfy `hephaestus-cad` from a *published*
    release and the lane would cheerfully report that some other artifact uses
    its packaged sidecar. Third-party dependencies still resolve from the index
    normally — only the Hephaestus distributions are pinned to the build.
    """
    uv = _uv()
    _run([uv, "venv", "--no-project", "--python", sys.executable, str(venv)])

    local: list[str] = []
    for name in PRODUCT_WHEELS:
        matches = sorted(wheelhouse.glob(f"{name}-*.whl"))
        assert matches, f"the build produced no wheel for {name} in {wheelhouse}"
        local.append(str(matches[-1]))
    assert any(distribution.replace("-", "_") in path for path in local), (
        f"{distribution} is not among the product wheels {PRODUCT_WHEELS}"
    )

    _run([uv, "pip", "install", "--python", str(venv_python(venv)), *local])
    return venv


def venv_python(venv: Path) -> Path:
    """The interpreter inside ``venv``."""
    candidate = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    return candidate


def venv_script(venv: Path, name: str) -> Path:
    """A console script (e.g. ``heph``) inside ``venv``."""
    return venv / ("Scripts" if os.name == "nt" else "bin") / name


def run_in_venv(
    venv: Path, code: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``code`` with the venv's interpreter, from a neutral directory.

    ``cwd`` is deliberately the venv, never the repo: running from the tree lets
    `hephaestus` be importable from source and would quietly invalidate every
    "the installed wheel does X" assertion in this suite.
    """
    return subprocess.run(
        [str(venv_python(venv)), "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(venv),
        env=env,
    )


def json_in_venv(venv: Path, code: str, *, env: dict[str, str] | None = None) -> object:
    """Run ``code`` in the venv and parse the single JSON object it prints."""
    proc = run_in_venv(venv, code, env=env)
    if proc.returncode != 0:
        raise AssertionError(f"probe failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def clean_env(venv: Path, **extra: str) -> dict[str, str]:
    """A minimal environment for a venv subprocess, with the venv on PATH."""
    env = {
        "PATH": f"{venv_script(venv, '').parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    env.update(extra)
    return env


def node_missing_env(venv: Path) -> dict[str, str]:
    """An environment with the venv's scripts but **no Node anywhere on PATH**.

    Lane (a) claims the Node-free verbs work with no Node. Asserting that on a
    developer machine that has Node installed requires actually removing it from
    PATH, not trusting that it happens to be absent.
    """
    scripts = str(venv_script(venv, "").parent)
    keep = [scripts]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        if (Path(entry) / "node").exists():
            continue
        keep.append(entry)
    return {
        "PATH": os.pathsep.join(keep),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
