# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``measure(kind="mass")`` must not invent a density (J-agent-results-1).

Today ``core/src/hephaestus/core/checks/facade.py``'s ``Measurement.mass``
falls back to ``DEFAULT_DENSITY = 1.0`` when nothing binds a real one, so a
40x20x6mm box's mass comes back as 4799.999... grams — numerically identical
to its volume in mm^3 and about 370x the true mass of that box in aluminium,
with no density, material or assumption disclosed anywhere in the result.

The fix (PHYSICS.md, ledger-specified): delete the default, raise a named
refusal when neither an explicit density nor a bound part density resolves,
and bind a real density through the same pinned-materials-registry path the
bill-of-materials builder already uses
(``server/src/hephaestus/agent_bridge/cad_ops/_doc.py``:
``density_kg_m3 * volume_mm3 * 1e-6 = mass_g``) — asserted here as a
cross-path parity so the two conversion sites cannot drift apart.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.testing.tools_fixture import Project, make_project

#: Resolves in the bundled ``materials`` registry (the ``test_drawings_docs.py``
#: precedent) without pinning a project-local registry tree.
_RESOLVABLE_MATERIAL_SPEC = "18 mm Baltic birch plywood"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


class TestMassWithNoMaterial:
    def test_refuses_by_name_rather_than_assuming_a_density(self, project: Project) -> None:
        project.build("widget")  # tools_fixture's widget declares no material_spec
        with pytest.raises(DispatchError) as excinfo:
            project.call("measure", {"kind": "mass", "a": "part", "part": "widget"})
        assert excinfo.value.reason == "mass_density_unbound"

    def test_mass_and_volume_disagree_for_any_bound_non_unit_density(
        self, project: Project
    ) -> None:
        """The regression that would have caught the original bug on day one:
        an explicit non-unit density must not report the same number as the
        volume in the sibling units (mm^3 vs g).
        """
        project.build("widget")
        volume = project.call("measure", {"kind": "volume", "a": "part", "part": "widget"})
        mass = project.call(
            "measure", {"kind": "mass", "a": "part", "part": "widget", "density": 2.7}
        )
        assert mass["value"] != volume["value"]
        assert mass["units"] == "g"


class TestMassWithExplicitDensity:
    def test_explicit_density_is_an_exact_product(self, project: Project) -> None:
        project.build("widget")
        volume = project.call("measure", {"kind": "volume", "a": "part", "part": "widget"})
        mass = project.call(
            "measure", {"kind": "mass", "a": "part", "part": "widget", "density": 2.7}
        )
        # geom/measure.py's own contract: grams when density is g/mm^3.
        assert mass["value"] == pytest.approx(volume["value"] * 2.7)

    def test_the_disclosure_names_the_density_it_used(self, project: Project) -> None:
        """The fix's disclosure clause — the density, the material and its
        source — structural in the tool result, never a bare float
        (J-agent-results-1). Exact field names are an implementer choice;
        this asserts the density value is discoverable somewhere in ``detail``.
        """
        project.build("widget")
        mass = project.call(
            "measure", {"kind": "mass", "a": "part", "part": "widget", "density": 2.7}
        )
        assert 2.7 in mass["detail"].values() or any(v == 2.7 for v in _flatten(mass["detail"]))


class TestMassWithRegistryMaterial:
    def test_a_registry_bound_material_converts_the_same_way_as_the_bom(
        self, project: Project
    ) -> None:
        """Cross-path parity: ``measure`` and ``generate_doc(kind="bom")`` must
        compute the identical mass for the identical solid from the identical
        registry record — one conversion, not two that can drift.
        """
        _set_material_spec(project, "widget", _RESOLVABLE_MATERIAL_SPEC)
        project.build("widget")
        mass = project.call("measure", {"kind": "mass", "a": "part", "part": "widget"})
        bom = project.call("generate_doc", {"name": "widget", "kind": "bom"})
        body = json.loads((project.root / bom["json"]).read_bytes().decode("utf-8"))
        rows = body["rows"]
        assert rows and rows[0]["material_id"] is not None
        assert mass["value"] == pytest.approx(sum(r["mass_g"] for r in rows), rel=1e-6)


def _flatten(value: Any) -> Iterator[Any]:
    if isinstance(value, dict):
        for v in value.values():  # type: ignore[union-attr]
            yield from _flatten(v)
    elif isinstance(value, list):
        for v in value:  # type: ignore[union-attr]
            yield from _flatten(v)
    else:
        yield value


def _set_material_spec(project: Project, part: str, spec: str) -> None:
    read = project.call("read_part", {"name": part})
    script = read["script"]
    new_script = script.rstrip("\n") + f'\npart.material_spec = "{spec}"\n'
    project.call(
        "edit_part",
        {
            "name": part,
            "expected_hash": read["content_hash"],
            "old_str": script,
            "new_str": new_script,
        },
    )
