# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G7H lane (d): with no passing secure backend, script execution REFUSES.

The lane's whole point is that the refusal is *asserted*, never inferred from a
skipped test. So every case here runs the installed wheel on a machine where the
secure backend cannot pass its probe — bubblewrap is removed from PATH — and
requires a named refusal on the way out.

Three things must hold together, and each has failed in some released tool:

* the executing verbs refuse, naming ``sandbox_unavailable``;
* they do **not** quietly fall back to the unsafe local backend;
* the non-executing surface (``--version``, ``lint``, schema/contract reads)
  still works, because fail-closed is a statement about *script execution*, not
  about the tool going dark.

The CI lane (``.github/workflows/release.yml``, job ``lane-d``) runs on a runner
with no bubblewrap installed at all; this suite reproduces that locally by
sanitising PATH, so a developer machine gets the same signal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from _wheel import json_in_venv, run_in_venv, venv_script

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "corpus" / "public_fixtures" / "assembly"


def no_backend_env(venv: Path) -> dict[str, str]:
    """The venv's scripts on PATH, with every bubblewrap-bearing entry removed.

    Removing the binary is what makes the probe fail; faking a failing probe
    would test the fake. Docker/Podman are left alone deliberately — see
    ``test_bwrap_is_still_the_only_secure_backend``.
    """
    scripts = str(venv_script(venv, "").parent)
    keep = [scripts]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or (Path(entry) / "bwrap").exists():
            continue
        keep.append(entry)
    return {
        "PATH": os.pathsep.join(keep),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }


def _project(tmp_path: Path) -> Path:
    """A private copy of the public clean-room fixture (builds write to it)."""
    project = tmp_path / "proj"
    shutil.copytree(FIXTURE, project)
    return project


def _heph(
    venv: Path, *args: str, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(venv_script(venv, "heph")), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        cwd=str(cwd),
        env=env,
    )


# --------------------------------------------------------------------------
# the refusal itself


def test_heph_build_refuses_and_names_the_missing_sandbox(
    installed_venv: Path, tmp_path: Path
) -> None:
    project = _project(tmp_path)
    proc = _heph(
        installed_venv,
        "build",
        "primary",
        "--json",
        cwd=project,
        env=no_backend_env(installed_venv),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"build succeeded with no secure backend:\n{combined}"
    assert "sandbox_unavailable" in combined, combined


def test_the_refusal_is_not_a_silent_fallback_to_the_unsafe_backend(
    installed_venv: Path, tmp_path: Path
) -> None:
    """The unsafe backend prints a warning when it runs. It must never appear.

    This is the failure mode the gate exists for: a tool that "helpfully"
    degrades to running untrusted part scripts on the host when its sandbox is
    missing has no security boundary at all.
    """
    project = _project(tmp_path)
    proc = _heph(
        installed_venv,
        "build",
        "primary",
        cwd=project,
        env=no_backend_env(installed_venv),
    )
    combined = proc.stdout + proc.stderr
    assert "WITHOUT OS sandboxing" not in combined, combined
    # No artifact was published either — a refusal that still wrote geometry
    # would mean the script ran before the check.
    assert not list(project.glob(".heph/**/*.step")), "the refused build published"


def test_serve_may_never_use_the_unsafe_backend(installed_venv: Path) -> None:
    """``heph serve`` and registry content are refused the escape hatch outright.

    Not "refused when a sandbox is missing" — refused always, flag or no flag
    (architecture.md §Sandboxing).
    """
    payload = json_in_venv(
        installed_venv,
        """
import json
from hephaestus.core.executor.sandbox.probe import refuse_unsafe
out = {}
for label, kwargs in (
    ("serve", {"registry_content": False, "serve": True}),
    ("registry", {"registry_content": True, "serve": False}),
    ("plain_debug", {"registry_content": False, "serve": False}),
):
    try:
        refuse_unsafe(**kwargs)
    except Exception as exc:
        out[label] = type(exc).__name__
    else:
        out[label] = "allowed"
print(json.dumps(out))
""",
        env=no_backend_env(installed_venv),
    )
    assert isinstance(payload, dict)
    assert payload["serve"] == "UnsafeRefusedError"
    assert payload["registry"] == "UnsafeRefusedError"
    # The user-invoked core debugging path stays available; that asymmetry is
    # the whole design, and a test that lost it would be testing nothing.
    assert payload["plain_debug"] == "allowed"


def test_the_secure_factory_itself_refuses_rather_than_returning_something(
    installed_venv: Path, tmp_path: Path
) -> None:
    proc = run_in_venv(
        installed_venv,
        f"""
from pathlib import Path
from hephaestus.core.executor.sandbox.probe import secure_backend
try:
    secure_backend(Path({str(tmp_path / "store")!r}))
except Exception as exc:
    print(type(exc).__name__ + ": " + str(exc))
else:
    print("RETURNED A BACKEND")
""",
        env=no_backend_env(installed_venv),
    )
    assert proc.returncode == 0, proc.stderr
    assert "RETURNED A BACKEND" not in proc.stdout
    assert "sandbox_unavailable" in proc.stdout, proc.stdout


def test_bwrap_is_still_the_only_secure_backend(installed_venv: Path) -> None:
    """Lane (d)'s validity condition — and, since the 2026-08-13 G7H amendment,
    the amendment's own tripwire — asserted rather than assumed.

    The CI lane proves "no passing secure backend" by not installing bubblewrap
    — while Docker *is* present on the hosted image. That argument holds only
    while ``secure_backend`` can construct nothing but ``BwrapBackend``.

    Repointed under the G7H amendment (2026-08-13, ``mission_plan.md``
    §"Stage 7H"): v0.1.0-headless supports secure script execution on Linux
    x86_64 via probed bubblewrap ONLY, and macOS via an OCI backend is
    DEFERRED to Stage 7. This test now pins that decision from the product
    side: the day an OCI backend lands, it fails and forces the deferral
    record (``tests/stage7h/CI_ONLY.md`` §3, ``release.yml``'s lane (c)
    comment block) to be revisited and lane (d) to disable the new backend
    too, instead of either lane silently becoming a lie.
    """
    payload = json_in_venv(
        installed_venv,
        """
import inspect, json
from hephaestus.core.executor.sandbox import probe
src = inspect.getsource(probe.secure_backend)
print(json.dumps({
    "returns": probe.secure_backend.__annotations__.get("return", ""),
    "constructs": [n for n in ("BwrapBackend", "OciBackend", "DockerBackend")
                   if n + "(" in src],
}))
""",
    )
    assert isinstance(payload, dict)
    assert payload["constructs"] == ["BwrapBackend"], (
        "secure_backend can now construct another backend; lane (d) must be "
        "updated to disable it before this test is relaxed"
    )


# --------------------------------------------------------------------------
# what still works


def test_the_non_executing_surface_survives_the_missing_backend(
    installed_venv: Path,
) -> None:
    env = no_backend_env(installed_venv)
    version = subprocess.run(
        [str(venv_script(installed_venv, "heph")), "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(installed_venv),
        env=env,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip()

    lint = _heph(
        installed_venv,
        "lint",
        str(FIXTURE / "parts" / "bracket.py"),
        cwd=installed_venv,
        env=env,
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
