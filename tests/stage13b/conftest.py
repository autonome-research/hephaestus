# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Gate G13B placement-proposal evidence suite.

One built project, **once per session**. The cast is six real part scripts
built through the executor and published through the project store, and every
solve additionally spawns a verification process that reloads them
(``SOLVER.md`` §7) — so rebuilding it per test would spend minutes proving
nothing this suite is about.

A solve in this stage DOES write one thing, and exactly one: an immutable
proposal document plus its index generation. Nothing else — no script, no
parameter, no republished artifact, no build made current. Tests that need a
project whose *geometry* changes underneath a proposal (the staleness clause)
take :func:`bench_copy`, a byte copy of the session project, so the session
fixture stays the thing every other clause measured against.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _g13b import open_bench_project

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore


@pytest.fixture(scope="session")
def bench_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built, published, declared bench project — scaffolded exactly once."""
    root = tmp_path_factory.mktemp("g13b") / "proj"
    _layout, store = open_bench_project(root)
    store.close()
    return root


@pytest.fixture
def bench(bench_root: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """A fresh handle on the session project (the store is not shared)."""
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(bench_root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()


@pytest.fixture
def bench_copy(bench_root: Path, tmp_path: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """A private byte copy of the session project, for tests that mutate it.

    Copied rather than rebuilt because a rebuild costs minutes of kernel time
    to produce the identical artifacts — and copied rather than shared because
    a test that republishes geometry underneath a proposal must not leave the
    other clauses measuring a project that moved.
    """
    from hephaestus.core.project_store.layout import load_project, open_store

    root = tmp_path / "copy"
    shutil.copytree(bench_root, root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()
