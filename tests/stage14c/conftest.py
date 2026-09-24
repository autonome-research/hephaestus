# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Gate G14C evidence suite.

One built project, **once per session** (the stage14b rationale: six real
kernel builds prove nothing per-test). Every test that declares CAM state
takes ``bench_copy`` — a byte copy — so the session project stays exactly
what the read-only clauses measured. ``ref_project`` is a second session
project carrying the declared REFERENCE SETUP (clauses 3, 16, 21, 22): its
declarations are part of what those clauses measure, so it is scaffolded once
and treated read-only.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _g14c import declare_reference_setup, open_bench_project

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore


@pytest.fixture(scope="session")
def bench_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built, published bench project — scaffolded exactly once."""
    root = tmp_path_factory.mktemp("g14c") / "proj"
    _layout, store = open_bench_project(root)
    store.close()
    return root


@pytest.fixture(scope="session")
def ref_root(tmp_path_factory: pytest.TempPathFactory, bench_root: Path) -> Path:
    """A byte copy of the bench carrying the declared reference setup."""
    from hephaestus.core.project_store.cam import CamState
    from hephaestus.core.project_store.layout import load_project, open_store

    root = tmp_path_factory.mktemp("g14c-ref") / "proj"
    shutil.copytree(bench_root, root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        declare_reference_setup(CamState(layout, store))
    finally:
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


@pytest.fixture
def ref(ref_root: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """A fresh handle on the reference-setup project (read-only by contract)."""
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(ref_root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()


@pytest.fixture
def ref_copy(ref_root: Path, tmp_path: Path) -> Iterator[tuple[ProjectLayout, OpStore]]:
    """A private byte copy of the reference project, for tests that mutate it."""
    from hephaestus.core.project_store.layout import load_project, open_store

    root = tmp_path / "refcopy"
    shutil.copytree(ref_root, root)
    layout = load_project(root)
    store = open_store(layout)
    try:
        yield layout, store
    finally:
        store.close()
