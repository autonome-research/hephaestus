"""The dependency runs server/agent -> contract, never core -> contract.

:mod:`hephaestus.core` is the CAD engine and is engine-first: it knows nothing
about agents or the tool surface. Importing any engine package must therefore
leave :mod:`hephaestus.contract` unloaded.

The two compatibility facades ``hephaestus.core.tools_decl`` and
``hephaestus.core.toolgen`` do re-export the contract, so they are deliberately
excluded — they exist for out-of-tree importers and are never reached from an
engine path (this test proves that by importing every engine package and
checking ``sys.modules``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Final

#: Every importable engine package/module reachable from ordinary CAD use.
ENGINE_MODULES: Final[tuple[str, ...]] = (
    "hephaestus.core",
    "hephaestus.core.checks",
    "hephaestus.core.cli",
    "hephaestus.core.dfm",
    "hephaestus.core.executor",
    "hephaestus.core.kernel",
    "hephaestus.core.limits",
    "hephaestus.core.project_store",
    "hephaestus.core.registry",
    "hephaestus.core.render",
)

_PROBE: Final[str] = """
import importlib, json, sys

for name in {modules!r}:
    importlib.import_module(name)

print(json.dumps(sorted(m for m in sys.modules if m.startswith("hephaestus.contract"))))
"""


def test_core_does_not_import_contract() -> None:
    """Importing the whole engine never pulls :mod:`hephaestus.contract` in."""
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE.format(modules=list(ENGINE_MODULES))],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked: list[str] = json.loads(completed.stdout.strip().splitlines()[-1])
    assert leaked == [], (
        "hephaestus.core must not depend on hephaestus.contract (engine-first); "
        f"these contract modules were loaded by importing the engine: {leaked}"
    )


def test_facades_still_re_export_the_contract() -> None:
    """The old import paths keep working for out-of-tree consumers."""
    from hephaestus.contract import toolgen as contract_toolgen
    from hephaestus.contract import tools_decl as contract_decl
    from hephaestus.core import toolgen as facade_toolgen
    from hephaestus.core import tools_decl as facade_decl

    assert facade_decl.TOOLS is contract_decl.TOOLS
    assert facade_decl.get_tool is contract_decl.get_tool
    assert facade_toolgen.schema_document is contract_toolgen.schema_document
    assert facade_toolgen.main is contract_toolgen.main
