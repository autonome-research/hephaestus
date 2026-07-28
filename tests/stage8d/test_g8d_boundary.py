"""G8D: the boundary rule (``EXTERNAL_EVAL.md`` Gate G8D, last clause).

Gate clause: *boundary rules hold (the adapter lives in bench, imports
geom/bench freely, and the engine never imports it)*.

The direction is the point. An adapter is allowed to know about the engine; an
engine that knew about a benchmark would be an engine with a benchmark-shaped
hole in its design, and the next external evaluation would be tempted to widen
it. Both halves are checked: statically (no engine package names the adapter)
and dynamically (importing the engine CLI in a fresh interpreter does not drag
the adapter in).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hephaestus.agent_bridge.app import repo_root

ENGINE_PACKAGES = ("opstore", "core", "contract", "server", "agent")

_PROBE = """
import json, sys
import hephaestus.core.cli  # the engine's whole CLI surface

print(json.dumps(sorted(m for m in sys.modules if "cadgenbench" in m)))
"""


def test_no_engine_package_names_the_adapter() -> None:
    root = repo_root()
    offenders: list[str] = []
    for package in ENGINE_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            if "cadgenbench" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(root)))
    assert not offenders, "engine source names the bench adapter:\n" + "\n".join(offenders)


def test_importing_the_engine_cli_does_not_load_the_adapter() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []


def test_the_adapter_lives_entirely_in_bench() -> None:
    """Every module of it is under ``bench/src``; nothing leaked into the engine."""
    from hephaestus.bench import cadgenbench

    package_dir = Path(cadgenbench.__file__ or "").parent
    assert package_dir.parts[-4:] == ("src", "hephaestus", "bench", "cadgenbench")
    assert (repo_root() / "bench") in package_dir.parents
