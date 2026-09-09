# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Registering a subcommand costs nothing — asserted, not commented.

J-cli-startup-6. Three comments in ``core/src/hephaestus/core/cli.py`` asserted
that registering a subcommand is free; all three were false for months, and no
test, lint or job checked the claim. Registration by import gives no signal: a
registration that pulls in the CAD kernel still produces correct help text and
correct behaviour, so every functional test passes and the only observable is
wall time — which nothing measured, and which is the wrong thing to assert on
anyway, because it is a property of the runner.

**The closure is asserted; the clock is not.** A module-name set is exact and
stable across machines; a second is neither. If a time bound is ever wanted it
belongs in the bench with a generous ceiling. The technique is the repository's
own: ``tests/stage0a/test_import_boundary.py`` runs a subprocess and inspects
``sys.modules``, precisely because an in-process assertion measures whatever the
test session already imported rather than the boundary.

The help goldens ride along in the same module deliberately. A deferred import
is easy to write in a way that silently drops an argument from a subparser — the
verb still exists, its handler still works, and only the help text says so.
Byte-identical goldens catch that in the same run that catches a heavy import.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GOLDENS = Path(__file__).with_name("goldens")

#: Top-level packages the parser build must not pull in, and what each one is.
#: Every one of them is a *handler's* dependency: the verb that needs it imports
#: it when it runs, which is where the cost belongs.
FORBIDDEN: dict[str, str] = {
    "OCC": "the OCCT CAD kernel",
    "OCP": "the OCCT CAD kernel binding",
    "build123d": "the modelling DSL",
    "fastmcp": "the MCP server stack",
    "mcp": "the MCP protocol stack",
    "starlette": "the web/ASGI stack",
    "uvicorn": "the ASGI server",
    "trimesh": "the mesh ingest stack",
    "scipy": "the solver's numerics",
    "PIL": "the raster stack",
}

#: The verbs whose registration used to reach for one of the above. A golden per
#: verb, so a deferred import that drops an argument is caught by name.
GOLDEN_VERBS: tuple[str, ...] = ("", "build", "export", "import", "render")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONWARNINGS": "ignore", "COLUMNS": "100"}
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, env=env
    )


def test_building_the_parser_imports_no_handler_stack() -> None:
    """The whole point: `heph --help` must not pay for what it does not run."""
    proc = _run(
        "import sys, json\n"
        "from hephaestus.core.cli import build_parser\n"
        "build_parser()\n"
        "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))\n"
    )
    assert proc.returncode == 0, proc.stderr
    loaded = set(json.loads(proc.stdout.splitlines()[-1]))
    intruders = {name: why for name, why in FORBIDDEN.items() if name in loaded}
    assert not intruders, (
        "building the argument parser imported "
        + ", ".join(f"{name} ({why})" for name, why in sorted(intruders.items()))
        + ". A subcommand module registered by the parser builder may import, at "
        "module level or inside its registration, only modules whose closure "
        "excludes these stacks; the handler is where the real import belongs "
        "(repo_conventions.md, docs/cli.md's startup budget)."
    )


def test_the_forbidden_stacks_are_reachable_at_all() -> None:
    """Non-vacuity: the assertion above is about DEFERRAL, not about absence.

    A closure test that passes because the dependency is not installed asserts
    nothing. This proves the same interpreter can import the two that matter
    most, so the pass above is a statement about when they load.
    """
    proc = _run("import build123d, OCP\nprint('ok')\n")
    if proc.returncode != 0:
        pytest.skip("the CAD kernel is not installed in this environment")
    assert "ok" in proc.stdout


@pytest.mark.parametrize("verb", GOLDEN_VERBS, ids=lambda v: v or "heph")
def test_help_output_is_byte_identical_to_its_golden(verb: str) -> None:
    """Help text is the parser's observable. Pin it, or a deferred import can
    quietly drop an argument and every functional test still passes."""
    proc = _run(
        "import sys\n"
        "from hephaestus.core.cli import build_parser\n"
        "parser = build_parser()\n"
        f"verb = {verb!r}\n"
        "target = parser\n"
        "if verb:\n"
        "    subparsers = [a for a in parser._actions if getattr(a, 'choices', None)]\n"
        "    target = subparsers[0].choices[verb]\n"
        "sys.stdout.write(target.format_help())\n"
    )
    assert proc.returncode == 0, proc.stderr
    golden = GOLDENS / f"help_{verb or 'heph'}.txt"
    if not golden.is_file():  # pragma: no cover - first recording
        golden.write_text(proc.stdout, encoding="utf-8")
        pytest.fail(f"recorded a new golden at {golden}; re-run to assert against it")
    assert proc.stdout == golden.read_text(encoding="utf-8"), (
        f"`heph {verb} --help`".replace("  ", " ")
        + f" no longer matches {golden.relative_to(GOLDENS.parents[2])}. If the change "
        "is intended, re-record it in the same PR that made it."
    )
