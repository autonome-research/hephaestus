# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Fixtures for the Gate G13C parameter-solve evidence suite.

One built project, **once per session**, and — more importantly — **one full
two-``Param`` solve, once per session**. This suite is the first whose subject
spends kernel time per iterate: a parameter-space candidate is a preview build
(``SOLVER.md`` §2C), so a single converged solve costs tens of builds and about
a minute. Re-running it per clause would spend twenty minutes proving the same
record twelve times.

Every solve here takes the ``UnsafeLocalBackend`` for the same reason every
other fixture suite does — the sandbox probe is not what these clauses are
about. The **verification** pass does not: it builds its own probed secure
backend inside its own process and takes nothing from the caller, which is part
of what §7's independence means.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from _g13c import copy_project, open_bench_project, param_request

if TYPE_CHECKING:
    from hephaestus.core.project_store.layout import ProjectLayout

    from opstore import OpStore


#: The solve budget this suite runs under, in seconds. The engine's default
#: wall-clock ceiling (``SOLVE_TIMEOUT_S``, 60 s) is a PRODUCTION bound and is
#: exercised by name in Stage 13B; here it is not the subject, and it is the one
#: number that makes these clauses depend on the machine rather than on the
#: code. A two-``Param`` solve is tens of preview builds, and on a laptop on
#: battery (CPU held near 1 GHz) the same solve that takes ~50 s on mains takes
#: ~240 s and fails "the wall-clock ceiling fired after 2 iterations" on every
#: commit. The suite therefore declares its own budget (J-mirrors-and-dx-23:
#: a wall-clock budget a test depends on is stated, not inherited), generous
#: enough that a genuinely hung solve still fails by name within the pytest
#: timeout. An operator's explicit override in the environment wins.
SOLVE_BUDGET_S = "600"


@pytest.fixture(scope="session", autouse=True)
def solve_budget() -> Iterator[None]:
    """State the suite's solve ceiling for every in-process and child solve.

    Set in the environment rather than passed per call because the
    determinism clauses solve in fresh interpreters (``test_g13c_determinism``)
    that must see the same ceiling as the session fixture — the environment is
    what both read.
    """
    name = "HEPHAESTUS_SOLVE_TIMEOUT_S"
    previous = os.environ.get(name)
    if previous is None:
        os.environ[name] = SOLVE_BUDGET_S
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


@pytest.fixture(scope="session")
def bench_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built, published, declared bench project — scaffolded exactly once."""
    root = tmp_path_factory.mktemp("g13c") / "proj"
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
    """A private byte copy of the session project, for tests that mutate it."""
    layout, store = copy_project(bench_root, tmp_path / "copy")
    try:
        yield layout, store
    finally:
        store.close()


def _run(root: Path, request: Any) -> Any:
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
    from hephaestus.core.placement import propose_placement
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(root)
    store = open_store(layout)
    try:
        return propose_placement(layout, store, request, backend=UnsafeLocalBackend())
    finally:
        store.close()


@pytest.fixture(scope="session")
def optimum_record(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The clause-44 solve: the determined two-``Param`` pair, run once.

    Its own copy of the project rather than the shared one, because a solve
    writes a proposal generation and half this suite's clauses are about what
    the project looks like *after* a solve — a shared record and a shared
    project would make "nothing was written" unfalsifiable.
    """
    root = tmp_path_factory.mktemp("g13c-optimum") / "proj"
    _layout, store = open_bench_project(root)
    store.close()
    record = _run(root, param_request(("c-seat", "c-lift"), ("hc.shelf_z", "post.post_h")))
    return record, root


@pytest.fixture(scope="session")
def fit_record(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The ``fit``-driven solve: the kind admitted here and refused in 13B."""
    root = tmp_path_factory.mktemp("g13c-fit") / "proj"
    _layout, store = open_bench_project(root)
    store.close()
    record = _run(root, param_request(("c-fit",), ("cap.spigot_r",)))
    return record, root
