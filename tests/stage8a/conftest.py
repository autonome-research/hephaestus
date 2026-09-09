"""Fixtures for the Gate G8A (ingest) evidence suite.

Two heavy fixtures, both session-scoped: the STEP fixture bytes (authored once
because OCCT stamps a timestamp into the header, and identical bytes are the
whole point) and the packaged Node sidecar the two bench clauses drive.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _g8a import StepFixtures, make_step_fixtures
from hephaestus.testing.sidecar import build_agent_dist
from hephaestus.testing.tools_fixture import Project, make_project


@pytest.fixture(scope="session")
def steps(tmp_path_factory: pytest.TempPathFactory) -> StepFixtures:
    return make_step_fixtures(tmp_path_factory.mktemp("step-fixtures"))


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    """A real project + dispatcher, ledger seeded so builds are not gated."""
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def bare_project(tmp_path: Path) -> Iterator[Project]:
    """The same, with no ledger: for the clauses whose subject *is* the ledger."""
    p = make_project(tmp_path / "proj", seed_ledger=False)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="session")
def sidecar_dist() -> Path:
    """The staged sidecar, built once per session through the ONE resolver.

    ``hephaestus.testing.sidecar.build_agent_dist`` is the resolver every other
    sidecar-backed suite uses (J-mirrors-and-dx-25): it finds pnpm the way
    ``scripts/bootstrap.sh`` does, honours ``HEPHAESTUS_SKIP_SIDECAR_BUILD``
    against a freshness-checked stage, and refuses by name under
    ``HEPHAESTUS_REQUIRE_SIDECAR``. This fixture used to run ``pnpm --dir agent
    build`` itself — an invocation no document teaches, because ``--dir``
    bypasses the ``packageManager`` pin — and so was one CI's guards could not
    see.
    """
    built = build_agent_dist()
    if built is None:
        pytest.skip("no Node/pnpm toolchain; this suite needs the packaged sidecar")
    return built[0]
