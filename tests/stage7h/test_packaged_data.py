# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""The installed wheel carries `schemas/bridge_limits.json`, byte-identical.

Three Python modules and the Node sidecar read this one file, which is what
stops a §5 numeric limit from being raised on one side of the bridge alone.
Packaging is where that property is easiest to lose: the naive fix for "the
wheel can't find it" is to commit a copy under each `src/`, and copies drift.

Instead the build stages the repo's single copy into each distribution. These
tests assert the staged copies are the *same bytes* as the source — the only
assertion that actually protects the invariant.

They also pin the regression that made this necessary. The modules read the file
at **import** time, and the old walk-up search climbed out of `site-packages`,
so before Stage 7H `import hephaestus.core` raised `FileNotFoundError` in every
wheel install.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from _wheel import json_in_venv, node_missing_env

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "schemas" / "bridge_limits.json"

_PROBE = """
import hashlib, json
from pathlib import Path
import hephaestus.core.limits as core_limits
import hephaestus.contract.tools_decl as contract_decl
from hephaestus.agent_bridge.limits import limits_path as bridge_limits_path
from hephaestus.agent_bridge.sidecar import resolve_sidecar

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

sidecar = resolve_sidecar().root / "schemas" / "bridge_limits.json"
print(json.dumps({
    "core": str(core_limits.limits_path()),
    "core_sha": digest(core_limits.limits_path()),
    "contract_sha": digest(contract_decl._find_limits_file()),
    "bridge": str(bridge_limits_path()),
    "bridge_sha": digest(bridge_limits_path()),
    "sidecar_sha": digest(sidecar),
}))
"""


@pytest.fixture(scope="module")
def probe(installed_venv: Path) -> dict[str, object]:
    # Deliberately Node-free: reading the limits document must never depend on
    # the runtime it configures.
    result = json_in_venv(installed_venv, _PROBE, env=node_missing_env(installed_venv))
    assert isinstance(result, dict)
    return result


def test_every_packaged_copy_matches_the_repository_source(
    probe: dict[str, object],
) -> None:
    expected = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    for key in ("core_sha", "contract_sha", "bridge_sha", "sidecar_sha"):
        assert probe[key] == expected, (
            f"{key} diverged from {SOURCE}: the staged copy is stale, and the "
            "bridge's limits now differ between components"
        )


def test_the_bridge_and_the_engine_read_the_same_file(probe: dict[str, object]) -> None:
    """`agent_bridge.limits` delegates rather than carrying its own resolver.

    It used to duplicate the walk-up search — two resolvers for one file, and
    both wrong in a wheel.
    """
    assert probe["bridge"] == probe["core"]


def test_the_packaged_copies_live_inside_the_installed_distributions(
    probe: dict[str, object],
) -> None:
    core = Path(str(probe["core"]))
    assert core.name == "bridge_limits.json"
    assert core.parent.name == "_data"
    assert core.parent.parent.name == "core"
    assert not core.is_relative_to(REPO), "the wheel is reading the repo's copy"
