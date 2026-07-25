"""Fixtures for the Stage-2 gate suite.

The heavy fixture is :func:`sidecar_dist`: it builds the packaged Node sidecar
once per session so every bridge test drives the same artifact a release would
ship (never a global ``pi``/``thread-phase`` install).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _g2 import G2Harness, Project, build_sidecar, make_project, scaffold_project


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    return build_sidecar()


@pytest.fixture
def harness(tmp_path: Path, sidecar_dist: Path) -> Iterator[G2Harness]:
    """A fully-wired bridge over a fresh, empty project."""
    project = scaffold_project(tmp_path / "proj")
    h = G2Harness(project, sidecar_dist)
    try:
        yield h
    finally:
        h.close()
        h.assert_no_orphans()


@pytest.fixture
def harness_factory(tmp_path: Path, sidecar_dist: Path) -> Iterator[Any]:
    """Build bespoke harnesses (text-only model, no wiring, hostile env, …)."""
    made: list[G2Harness] = []

    def build(name: str = "proj", **kwargs: Any) -> G2Harness:
        project = scaffold_project(tmp_path / name)
        h = G2Harness(project, sidecar_dist, **kwargs)
        made.append(h)
        return h

    try:
        yield build
    finally:
        for h in made:
            h.close()
            h.assert_no_orphans()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """A scaffolded project + real dispatcher (no sidecar) for authz-level tests."""
    p = make_project(tmp_path / "dispatch-proj")
    try:
        yield p
    finally:
        p.close()
