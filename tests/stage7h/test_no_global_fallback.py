# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H: "not a global Pi or thread-phase installation" — proven by execution.

The gate sentence is two claims, and only the first had a local proof. That the
wheel *uses its packaged sidecar* is `test_packaged_sidecar.py`. That it does not
use **a global `pi` or `thread-phase`** is the other half, and "the resolver has
no code path to one" is an argument about source, not a measurement: an indirect
spawn through a wrapper, a `pnpm`/`npx` shell-out inside the bundle, or a Pi
extension autoloaded from `$HOME` would all satisfy that argument and still
violate the clause.

So this module measures it the way `release.yml`'s lane (a) does — plant hostile
`pi` and `thread-phase` executables **first on PATH**, run the product, and fail
if either recorded an invocation. The shims append to a witness file and exit
97; anything that execs one either leaves the witness behind or dies loudly.

Two things this deliberately does not do. It does not shim `node`: Node is how
the sidecar legitimately runs, and a fake one would only prove the fake was
called. And the hostile directory is prepended, never appended — a shim that
only wins when nothing else matches proves nothing about precedence.

`repo_conventions.md` §"Framework boundaries" and mission rule 7 ("Global Pi
extensions, coding tools, thread-phase pipelines … MUST NOT affect a Hephaestus
run") are the normative statements this enforces.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from _wheel import clean_env, json_in_venv, run_in_venv, venv_script

pytestmark = pytest.mark.slow

#: Every global the conventions forbid `heph` from reaching for. `npx` and
#: `pnpm` are here because they are the plausible *indirect* route: a bundle
#: that shelled out to one would be reaching outside the wheel just as surely.
HOSTILE: Final[tuple[str, ...]] = ("pi", "thread-phase", "npx", "pnpm")


class Hostile:
    """A directory of poisoned globals, plus the witness they write to."""

    def __init__(self, bindir: Path, witness: Path) -> None:
        self.bindir = bindir
        self.witness = witness

    def invocations(self) -> list[str]:
        if not self.witness.exists():
            return []
        return [line for line in self.witness.read_text(encoding="utf-8").splitlines() if line]

    def env(self, venv: Path, **extra: str) -> dict[str, str]:
        """The venv environment with the hostile directory **first** on PATH."""
        env = clean_env(venv, **extra)
        env["PATH"] = f"{self.bindir}{os.pathsep}{env['PATH']}"
        return env


@pytest.fixture(scope="module")
def hostile(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Hostile]:
    root = tmp_path_factory.mktemp("hostile")
    bindir = root / "bin"
    bindir.mkdir()
    witness = root / "invoked"
    for name in HOSTILE:
        shim = bindir / name
        shim.write_text(
            f'#!/bin/sh\necho "$0 $@" >> "{witness}"\nexit 97\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
    yield Hostile(bindir, witness)


def test_the_shims_are_actually_reachable(hostile: Hostile, installed_venv: Path) -> None:
    """The lane is only worth running if the poison is genuinely on PATH first.

    Without this, a broken fixture (unset PATH, lost +x bit) would make every
    assertion below pass vacuously — the exact failure mode that makes
    "nothing was invoked" tests worthless.
    """
    env = hostile.env(installed_venv)
    for name in HOSTILE:
        found = shutil.which(name, path=env["PATH"])
        assert found == str(hostile.bindir / name), f"{name} shim is not first on PATH: {found}"

    proc = subprocess.run(
        [str(hostile.bindir / "pi"), "--version"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 97
    assert hostile.invocations(), "the witness did not record a direct call; the fixture is inert"
    hostile.witness.unlink()


def test_resolving_the_sidecar_never_consults_a_global(
    hostile: Hostile, installed_venv: Path
) -> None:
    """Resolution picks the packaged tree with hostile globals in front of it."""
    payload = json_in_venv(
        installed_venv,
        (
            "import json, sysconfig\n"
            "from hephaestus.agent_bridge.sidecar import resolve_sidecar\n"
            "r = resolve_sidecar()\n"
            'print(json.dumps({"source": r.source, "root": str(r.root),'
            ' "purelib": sysconfig.get_paths()["purelib"]}))\n'
        ),
        env=hostile.env(installed_venv),
    )
    assert isinstance(payload, dict)
    assert payload["source"] == "packaged"
    assert Path(str(payload["root"])).is_relative_to(Path(str(payload["purelib"])))
    assert hostile.invocations() == []


def test_resolution_does_not_depend_on_path_at_all(installed_venv: Path) -> None:
    """With PATH emptied to a nonexistent directory, resolution still succeeds.

    A resolver that located the sidecar *through* a globally installed tool
    would fail here. This is the positive form of the previous test: not merely
    "the hostile binary went uncalled", but "no PATH lookup participates in
    finding the sidecar in the first place".
    """
    env = {
        "PATH": "/nonexistent-path-for-stage7h",
        "HOME": os.environ.get("HOME", ""),
        "LANG": "C.UTF-8",
    }
    proc = run_in_venv(
        installed_venv,
        (
            "from hephaestus.agent_bridge.sidecar import resolve_sidecar, verify_sidecar\n"
            "r = resolve_sidecar()\n"
            "verify_sidecar(r.root)\n"
            "print(r.source)\n"
        ),
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "packaged"


def test_the_node_free_surface_invokes_no_global(
    hostile: Hostile, installed_venv: Path, tmp_path: Path
) -> None:
    """Lane (a)'s real work — `heph lint` on a fixture — touches no global.

    Lint parses and analyses a genuine part script, so this is the Node-free
    half of the product doing actual work with the poison in place.
    """
    fixture = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures" / "assembly"
    project = tmp_path / "project"
    shutil.copytree(fixture, project)
    shutil.rmtree(project / ".heph", ignore_errors=True)

    heph = venv_script(installed_venv, "heph")
    proc = subprocess.run(
        [str(heph), "lint", "parts/bracket.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project),
        env=hostile.env(installed_venv),
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert hostile.invocations() == [], f"a global was invoked: {hostile.invocations()}"
    assert not (project / ".heph").exists(), "lint executed the script"


@pytest.mark.skipif(shutil.which("node") is None, reason="the agent path needs Node")
def test_a_full_agent_session_invokes_no_global(
    hostile: Hostile, installed_venv: Path, tmp_path: Path
) -> None:
    """The strongest form: a completed prompt round trip with the poison in place.

    This is the clause's real target. The sidecar is *spawned* here — a Node
    process runs the packaged bundle, which loads Pi from inside the wheel. If
    any part of that chain reached a globally installed Pi or thread-phase (an
    autoloaded extension, a `pnpm`/`npx` shell-out from the bundle, a wrapper
    script), the witness would name it.
    """
    workdir = tmp_path / "agent"
    program = f"""
import json
from pathlib import Path
from hephaestus.agent_bridge.app import BridgeRuntime
from hephaestus.testing.fake_openai import start_fake_openai
from hephaestus.testing.projects import scaffold_project
from hephaestus.testing.stream_assertions import text

project = scaffold_project(Path({str(workdir)!r}), name="hostile",
                           globals_src="PARAMS = {{}}\\n")
fake = start_fake_openai([text("answered under hostile PATH")])
runtime = BridgeRuntime(project_root=project, providers=[fake.provider_spec()])
runtime.start()
try:
    session = runtime.create_session("orchestrator", session_id="hostile")
    result = runtime.prompt(session, "say something", timeout=300)
    r = runtime.sidecar
    print(json.dumps({{
        "status": result.status,
        "source": None if r is None else r.source,
    }}))
finally:
    runtime.close()
    fake.close()
"""
    payload = json_in_venv(installed_venv, program, env=hostile.env(installed_venv))
    assert isinstance(payload, dict)
    assert payload["status"] == "completed", payload
    assert payload["source"] == "packaged", payload
    assert hostile.invocations() == [], (
        f"the agent session reached a global binary: {hostile.invocations()}"
    )
