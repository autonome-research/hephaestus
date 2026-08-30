# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the Gate G12A (mesh and scan ingest) evidence suite.

The mesh fixtures are session-scoped and authored once: every one is a pure
function of the vertex arrays in ``_g12a.py``, so building them per test would
buy nothing and cost a trimesh export per case.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _g12a import MeshFixtures, make_mesh_fixtures
from hephaestus.testing.tools_fixture import Project, make_project


@pytest.fixture(scope="session")
def meshes() -> MeshFixtures:
    return make_mesh_fixtures()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """A real project + dispatcher, ledger seeded so builds are not gated."""
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()
