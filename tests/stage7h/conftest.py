# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Session fixtures for the Stage 7H wheel lanes.

The helpers live in ``_wheel.py`` (the ``_g2.py`` convention used elsewhere in
this tree); only the two expensive session-scoped fixtures live here, so a whole
run pays for one ``uv build`` and one venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _wheel import DISTRIBUTION, build_wheelhouse, install_wheel, venv_python


@pytest.fixture(scope="session")
def wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory of freshly built wheels for every workspace distribution.

    Built from the working tree, not from ``dist/``, so a stale artifact from an
    earlier run can never be what the gate measures.
    """
    return build_wheelhouse(tmp_path_factory.mktemp("wheelhouse"))


@pytest.fixture(scope="session")
def installed_venv(wheelhouse: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A fresh venv with ``hephaestus-cad`` installed from the wheelhouse."""
    venv = tmp_path_factory.mktemp("venv") / "heph"
    install_wheel(venv, wheelhouse, DISTRIBUTION)
    assert venv_python(venv).exists()
    return venv
