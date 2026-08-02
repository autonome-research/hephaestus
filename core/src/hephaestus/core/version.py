# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The single source of truth for the version ``heph --version`` reports.

There is no ``__version__`` literal anywhere in this project, deliberately. The
release is five Python distributions plus a private npm package that must all
ship the same number; a literal in one module is a sixth place to forget. The
authority is **installed distribution metadata** — the number the build backend
read out of ``pyproject.toml`` and stamped into the wheel — so the reported
version cannot drift from the artifact a user actually installed.

``hephaestus-core`` is the anchor because it owns the ``heph`` entry point: it
is present in every installation that has a CLI to ask.

Coordination across the other distributions is enforced by a test
(``tests/stage7h/test_version_coherence.py``), which reads every
``pyproject.toml`` and ``agent/package.json`` in the tree and requires one
value. That keeps the *declarations* honest at development time without adding
runtime machinery that could disagree with the metadata at install time.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from typing import Final

__all__ = ["DISTRIBUTION", "version"]

#: The distribution whose metadata carries the version.
DISTRIBUTION: Final[str] = "hephaestus-core"

#: Reported when the package is imported from a source tree with no metadata at
#: all (a bare ``PYTHONPATH`` run). Never reached from a wheel or an editable
#: install, both of which install metadata.
_UNINSTALLED: Final[str] = "0+unknown"


def version() -> str:
    """The installed version of Hephaestus, or ``0+unknown`` when uninstalled."""
    try:
        return _distribution_version(DISTRIBUTION)
    except PackageNotFoundError:
        return _UNINSTALLED
