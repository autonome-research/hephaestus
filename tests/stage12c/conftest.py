# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the Gate G12C (scan scoring, surface, corpus) suite.

Session-scoped meshes, because every one is a pure function of a tessellation
the renderer produces once: rebuilding them per test would buy nothing and cost
a tessellation plus a trimesh export per case.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _g12c import Fixtures, make_fixtures
from hephaestus.testing.tools_fixture import Project, make_project


@pytest.fixture(scope="session")
def meshes() -> Fixtures:
    return make_fixtures()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """A real project + dispatcher, ledger seeded so builds are not gated."""
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()
