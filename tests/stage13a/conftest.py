# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Gate G13A pose-solving evidence suite.

One fixture, built **once per session**. The cast is eight real part scripts
built through the executor and published through the project store, and each
solve additionally spawns a verification process that reloads them
(``SOLVER.md`` §7) — so rebuilding it per test would spend minutes proving
nothing this suite is about. Every clause reads the same published geometry,
which is also the honest arrangement: the solves are independent of each other,
and a fixture rebuilt between them would hide an accidental dependency rather
than expose one.

Nothing in this suite writes to the project through a solve, because nothing in
Stage 13A can: ``solve_pose`` declares no pose, publishes no artifact and
advances no generation. The clauses that assert that read the generations
before and after.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _g13a import open_arm_project

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore


@pytest.fixture(scope="session")
def arm_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built, published, declared arm project — scaffolded exactly once."""
    root = tmp_path_factory.mktemp("g13a") / "proj"
    _layout, store = open_arm_project(root)
    store.close()
    return root


@pytest.fixture
def arm(arm_root: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """A fresh handle on the session project (the store is not shared)."""
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(arm_root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()
