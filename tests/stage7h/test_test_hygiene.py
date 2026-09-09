# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""What runs, where it runs, and what a test may not do while waiting.

Four audit findings share one shape: a test exists, is correct, and runs
nowhere — or runs everywhere including the one machine it cannot pass on. None
of them is visible from a green build, because a suite that is never collected
reports nothing at all.

* J-mirrors-and-dx-22 — ``testpaths`` discovered two of the five directories
  that hold tests, so the most natural command a contributor types silently ran
  a subset. Widened; kept wide by :func:`test_every_test_directory_is_collected`.
* J-mirrors-and-dx-30 — ``contract/tests`` was named by no CI job at all, so its
  tool-surface pin and both import-direction assertions ran only if a developer
  typed the second documented pytest command. Given a lane; kept by
  :func:`test_every_test_directory_is_named_by_a_ci_job`.
* J-mirrors-and-dx-18 — the renderer-pinned modules were deselected from CI by a
  hand-maintained ``--ignore=`` path list, which the documented command did not
  share and which silently loses a module that grows a golden. Replaced by the
  ``pinned_image`` marker; both directions asserted below.
* J-mirrors-and-dx-13 — six ``@settings`` blocks ran under the per-example
  wall-clock deadline, which measures the runner rather than the property, while
  every later block in the tree disables it.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"

#: This module quotes both the marker and the settings decorator it censuses,
#: so it must exclude itself or it becomes its own only finding.
SELF = Path(__file__).resolve()

#: Directories that hold ``test_*.py`` files but are deliberately not collected
#: by ``testpaths``, each with the reason. The repository's documented-exclusion
#: standard: an entry with no reason beside it is an oversight, not a decision.
UNCOLLECTED: dict[str, str] = {
    # A frozen Stage S evidence tree, not a suite: the modules there are the
    # recorded spike, and ruff excludes them for the same reason.
    "spikes": "frozen Stage S evidence, not a suite (see [tool.ruff] extend-exclude)",
}

#: Directories collected by ``testpaths`` that no CI job names by path. Empty on
#: purpose: an entry here is a suite that runs on nobody's machine but a
#: developer's, which is what J-mirrors-and-dx-30 was.
UNGATED: dict[str, str] = {}


def _pyproject() -> dict[str, Any]:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _pytest_ini() -> dict[str, Any]:
    section: dict[str, Any] = _pyproject()["tool"]["pytest"]["ini_options"]
    return section


def _ci() -> dict[str, Any]:
    doc = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _test_directories() -> set[str]:
    """Every directory in the repository that directly holds ``test_*.py``."""
    found: set[str] = set()
    for path in REPO.rglob("test_*.py"):
        relative = path.relative_to(REPO)
        parts = relative.parts
        if any(part in {"node_modules", ".git", ".venv", "__pycache__", "dist"} for part in parts):
            continue
        found.add(str(relative.parent))
    return found


def _pytest_steps() -> list[tuple[str, str]]:
    """``(job name, command)`` for every ``pytest`` invocation in ci.yml."""
    steps: list[tuple[str, str]] = []
    for job_id, job in _ci()["jobs"].items():
        name = str(job.get("name", job_id))
        for step in job.get("steps", []):
            if not isinstance(step, dict) or "run" not in step:
                continue
            body = " ".join(str(step["run"]).split())
            for command in re.findall(r"uv run pytest [^\n;&|]*", body):
                steps.append((name, command.strip()))
    return steps


def _paths_of(command: str) -> list[str]:
    tokens = command.split()[3:]
    paths: list[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in {"-k", "-m"}:
            skip = True
            continue
        if token.startswith("-"):
            continue
        paths.append(token)
    return paths


# --------------------------------------------------------------------------
# J-mirrors-and-dx-22 / -30: the census


def test_every_test_directory_is_collected() -> None:
    """A directory holding tests is inside ``testpaths`` or is excused by name."""
    configured = [str(entry) for entry in _pytest_ini()["testpaths"]]
    stray = {
        directory
        for directory in _test_directories()
        if not any(directory == root or directory.startswith(f"{root}/") for root in configured)
        and not any(directory == root or directory.startswith(f"{root}/") for root in UNCOLLECTED)
    }
    assert not stray, (
        f"these directories hold tests that a bare `pytest` never collects: {sorted(stray)}. "
        "Add them to testpaths, or to UNCOLLECTED with the reason."
    )


def test_bench_is_absent_from_testpaths_on_purpose() -> None:
    """The omission is documented rather than forgotten — the standard ci.yml
    already holds itself to. When ``bench`` grows tests this test is what fails.
    """
    configured = [str(entry) for entry in _pytest_ini()["testpaths"]]
    assert "bench" not in configured
    assert not [d for d in _test_directories() if d.startswith("bench")], (
        "bench has tests now; add it to testpaths and delete this test"
    )


def test_every_test_directory_is_named_by_a_ci_job() -> None:
    """A suite no job runs is a suite that gates nothing."""
    named: set[str] = set()
    for _, command in _pytest_steps():
        for path in _paths_of(command):
            named.add(path.split("::")[0].rstrip("/"))
    ungated = set()
    for directory in _test_directories():
        if any(directory == root or directory.startswith(f"{root}/") for root in UNCOLLECTED):
            continue
        if any(directory == path or directory.startswith(f"{path}/") for path in named):
            continue
        if any(path.startswith(f"{directory}/") for path in named):
            # A job names individual modules inside the directory.
            continue
        ungated.add(directory)
    assert ungated <= set(UNGATED), (
        f"these test directories are named by no ci.yml job: {sorted(ungated - set(UNGATED))}"
    )


# --------------------------------------------------------------------------
# J-mirrors-and-dx-18: the pinned-image marker, both directions


def _pinned_modules() -> set[str]:
    marked: set[str] = set()
    for path in REPO.rglob("test_*.py"):
        parts = path.relative_to(REPO).parts
        if any(part in {"node_modules", ".git", ".venv", "__pycache__"} for part in parts):
            continue
        if path.resolve() == SELF:
            continue
        if "pytest.mark.pinned_image" in path.read_text(encoding="utf-8"):
            marked.add(str(path.relative_to(REPO)))
    return marked


def test_the_marker_is_declared_and_used() -> None:
    markers = [str(entry) for entry in _pytest_ini()["markers"]]
    assert any(entry.startswith("pinned_image:") for entry in markers)
    assert _pinned_modules(), "nothing carries the marker; the selector asserts nothing"


def test_the_default_marker_expression_deselects_the_pinned_modules() -> None:
    """This is what makes the documented `uv run pytest` green off the image."""
    addopts = str(_pytest_ini()["addopts"])
    assert "not pinned_image" in addopts, (
        "pyproject.toml's default -m no longer deselects pinned_image, so the "
        "first command CONTRIBUTING.md gives a contributor is red on every "
        "machine that is not the pinned image (J-mirrors-and-dx-18)"
    )
    assert "not slow" in addopts


def test_no_stock_lane_collects_a_pinned_image_test() -> None:
    """The stock lanes must deselect the marker, not ignore a path list."""
    pinned = _pinned_modules()
    for job, command in _pytest_steps():
        if "pinned image" in job:
            continue
        selection = re.search(r'-m\s+"([^"]+)"', command)
        for path in _paths_of(command):
            path = path.split("::")[0].rstrip("/")
            touches = [m for m in pinned if m == path or m.startswith(f"{path}/")]
            if not touches:
                continue
            # No `-m` at all is correct: pyproject.toml's default expression
            # deselects the marker, and the test above pins that. An EXPLICIT
            # `-m` replaces the default rather than adding to it, so a lane that
            # spells one must spell this half too.
            assert selection is None or "not pinned_image" in selection.group(1), (
                f"the stock lane {job!r} collects {touches} under an explicit "
                f"`-m` that does not deselect the marker: {command!r}"
            )
        assert "--ignore=" not in command, (
            f"{job!r} still deselects by path: {command!r}. A path list is a second, "
            "hand-maintained copy of which tests are image-scoped"
        )


def test_the_golden_lane_selects_every_pinned_module() -> None:
    """A marker cannot silently lose a module the way a path list can — but only
    while the lane that owns them actually names each one."""
    covered: set[str] = set()
    for job, command in _pytest_steps():
        if "pinned image" not in job:
            continue
        selection = re.search(r"-m\s+\"?([A-Za-z_ ]+)\"?", command)
        if selection is None or "pinned_image" not in selection.group(1):
            continue
        for path in _paths_of(command):
            path = path.split("::")[0].rstrip("/")
            covered.update(m for m in _pinned_modules() if m == path or m.startswith(f"{path}/"))
    missing = _pinned_modules() - covered
    assert not missing, (
        f"these renderer-pinned modules run in no pinned-image lane: {sorted(missing)}"
    )


# --------------------------------------------------------------------------
# J-mirrors-and-dx-13: no property test re-enables the wall-clock deadline
#
# Two mechanisms, and the ORDER matters. The authority is the repository
# profile in `hephaestus.testing.hypothesis_profile`, loaded as a pytest `-p`
# plugin from `[tool.pytest.ini_options] addopts`, which sets `deadline=None`
# for every property in the tree — including the ones nobody has written yet.
# The per-site census below is the second line: it keeps the intent readable at
# the call site and it keeps holding if somebody runs pytest with the ini's
# addopts overridden (`-o addopts=...`), which a downstream packager or an
# ad-hoc invocation may do (the CI lanes override only `-m`).


def test_the_repository_hypothesis_profile_is_the_loaded_one() -> None:
    """Registered is not loaded, and loaded is not effective.

    Asserted three ways, because the two cheap ways can both pass while the
    property is still on a 200 ms clock: the plugin is imported at startup, the
    resolved default carries no deadline, and — the only one that cannot be
    faked — a property whose single example sleeps past the stock deadline
    actually passes. Reproduce the pre-fix red with
    ``uv run pytest <this file> -o addopts=-ra``.
    """
    # Read sys.modules BEFORE the import below: importing the module registers
    # AND loads the profile as a side effect, so asking afterwards would answer
    # "yes" in a session that never loaded the plugin. Verified by running this
    # file with `-o addopts=-ra`, which must red on exactly this line.
    loaded_at_startup = "hephaestus.testing.hypothesis_profile" in sys.modules

    from hephaestus.testing.hypothesis_profile import PROFILE
    from hypothesis import given, settings
    from hypothesis import strategies as st

    assert loaded_at_startup, (
        "the repository Hypothesis profile is not loaded: `[tool.pytest.ini_options] "
        "addopts` must carry `-p hephaestus.testing.hypothesis_profile`"
    )
    assert settings.default.deadline is None, (
        f"profile {PROFILE!r} registered but did not load: the resolved Hypothesis "
        f"default still carries a wall-clock deadline ({settings.default.deadline!r})"
    )

    @settings(max_examples=1)
    @given(st.just(0))
    def sleeps_past_the_stock_deadline(_: int) -> None:
        time.sleep(0.25)  # the stock deadline is 200 ms per example

    sleeps_past_the_stock_deadline()


def test_the_hypothesis_plugin_costs_nothing_at_startup() -> None:
    """Why :mod:`hephaestus.testing`'s re-exports are lazy (PEP 562).

    A ``-p`` plugin is imported before collection, so an eager package body
    would charge EVERY pytest session in the repository for the CAD kernel —
    measured at ~4.4 s, including ``contract/tests``, a ~3.5 s lane with no
    ``hephaestus.testing`` consumer in it. Asked in a subprocess because this
    session has long since imported the kernel for other reasons.
    """
    probe = (
        "import sys, hephaestus.testing.hypothesis_profile as p; "
        "print(p.PROFILE); "
        "print(sorted(m for m in sys.modules if m.startswith('hephaestus.core')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    profile, kernel = done.stdout.splitlines()[:2]
    assert profile == "hephaestus"
    assert kernel == "[]", (
        "importing the Hypothesis plugin now pulls the CAD kernel at pytest "
        f"startup: {kernel}. Keep `hephaestus.testing`'s re-exports lazy."
    )


#: ``@settings`` blocks that still omit ``deadline``, each with the reason.
#: An entry here is debt, not a decision — the convention is that a per-test
#: settings block never re-enables the deadline, because the deadline measures
#: the runner rather than the property.
SETTINGS_DEBT: dict[str, str] = {
    # The highest-risk site in the repository (2000 examples). One keyword; the
    # edit is pending because this file is outside the lane that found it
    # (docs/audit-2026-09-04-janky.md, J-mirrors-and-dx-13). The repository
    # profile above already makes this site safe in practice — the entry is
    # about the call site READING as if the deadline were on. Delete it together
    # with the edit.
    "core/tests/test_render_palette.py": "one-keyword edit pending, see J-mirrors-and-dx-13",
}

_SETTINGS_RE = re.compile(r"@settings\((?P<body>[^)]*)\)", re.MULTILINE | re.DOTALL)


def test_no_settings_block_re_enables_the_wall_clock_deadline() -> None:
    offenders: dict[str, int] = {}
    for path in REPO.rglob("test_*.py"):
        parts = path.relative_to(REPO).parts
        if any(part in {"node_modules", ".git", ".venv", "__pycache__"} for part in parts):
            continue
        if path.resolve() == SELF:
            continue
        text = path.read_text(encoding="utf-8")
        if "@settings(" not in text:
            continue
        bad = sum(
            1 for match in _SETTINGS_RE.finditer(text) if "deadline" not in match.group("body")
        )
        if bad:
            offenders[str(path.relative_to(REPO))] = bad
    unexcused = {name: count for name, count in offenders.items() if name not in SETTINGS_DEBT}
    assert not unexcused, (
        "these @settings blocks omit `deadline`, so a descheduled example on a "
        f"loaded runner reds the build for a reason unrelated to the property: {unexcused}"
    )

    # Self-clearing, on the same discipline as `scripts/docs_check.py`'s
    # COMMAND_FORM_EXCLUSIONS: an excuse may not outlive the defect it excuses.
    # Without this, a file that is later fixed simply drops out of `offenders`
    # and its entry sits here for good, reading as a live exemption.
    stale = sorted(name for name in SETTINGS_DEBT if name not in offenders)
    assert not stale, (
        "SETTINGS_DEBT excuses a file that no longer omits `deadline` (or no "
        f"longer exists): {stale}. Delete the entry — an exemption that outlives "
        "its defect silently excuses the NEXT one to appear in that file."
    )


# J-mirrors-and-dx-21 (one free-port helper, and it retries) is covered in its
# own dedicated module, ``test_free_port_helper.py`` — that module is the one
# this census file's docstring would otherwise duplicate; see it for the
# retry-past-a-collision and non-collision-failure assertions.
