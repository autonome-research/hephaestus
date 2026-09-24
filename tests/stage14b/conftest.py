# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Gate G14B evidence suite.

One built project, **once per session** (the stage13b rationale: two real
kernel builds prove nothing per-test). Every test that declares CAM state
takes ``bench_copy`` — a byte copy — so the session project stays exactly what
the read-only clauses measured; the ledger clauses would otherwise leave each
other's generations behind.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _g14b import open_bench_project

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore


@pytest.fixture(scope="session")
def bench_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built, published bench project — scaffolded exactly once."""
    root = tmp_path_factory.mktemp("g14b") / "proj"
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
    """A private byte copy of the session project, for tests that declare state."""
    from hephaestus.core.project_store.layout import load_project, open_store

    root = tmp_path / "copy"
    shutil.copytree(bench_root, root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()
