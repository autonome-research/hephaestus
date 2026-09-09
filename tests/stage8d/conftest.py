"""Fixtures for the Gate G8D (external evaluation) evidence suite.

One heavy fixture — the packaged Node sidecar the FakeModel run clause drives —
built once per session and skipped cleanly when Node is not available, exactly
as the G8A/G8B suites do it. Everything else in this suite is pure and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.testing.sidecar import build_agent_dist


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
