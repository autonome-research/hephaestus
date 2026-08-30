# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G12C: the round trip, in two clauses that measure two different things (§6.6).

tessellate → export → ``import_mesh`` → compare back to the analytic solid.

Gate clauses covered here:

* **45 — identity.** ``scan_to_part_max_mm <= MESH_ROUNDTRIP_EPS_MM``. This is a
  **corruption check and NOT a fidelity check**, and the distinction is the
  whole reason §6.6 is two clauses: OCCT's tessellator places its nodes *on* the
  surface, so this direction is ~0 by construction and has five orders of
  magnitude of slack. It asserts exactly what it can — that every node survived
  export, re-import, unit scaling and welding still lying on the surface it came
  from — and a negative control (vertices scaled by 1.001) pins that it can
  still fail. Also here: the volume's sign and bias, and the two-process
  canonical-hash identity.
* **46 — fidelity.** ``part_to_scan_max_mm`` inside the two-sided window
  ``0.5 x LINEAR_DEFLECTION <= x <= 1.10 x LINEAR_DEFLECTION``, with the method
  asserted **first**. This is the clause that actually binds the declared
  deflection, and the one clause 45 structurally cannot be — finding 6's point:
  a direction whose deviation is structurally zero cannot bound anything.

**The constants, and where they come from.** ``MESH_ROUNDTRIP_EPS_MM`` and
``MESH_TESSELLATION_VOLUME_BIAS`` are **derived at import from the archived
pinned-image measurement** (``evidence/pinned_measurements.json``,
``hephaestus.testing.pinned_image``), not typed in beside a claim about where
they came from. Clause 45's words are "value from a recorded pinned-image
measurement", and a transcribed number can drift from its record in silence
while every assertion around it stays green — so neither constant can exist
without the record, and a record taken outside a pinned image is refused by
name. ``LINEAR_DEFLECTION`` keeps its own rule: read from ``tessellate.py``,
never copied.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from _g12c import SPHERE_R, Fixtures, canonical_arrays
from hephaestus.core.render.tessellate import LINEAR_DEFLECTION
from hephaestus.geom.compare import scan_distance
from hephaestus.geom.mesh import (
    SCAN_METHOD_EXACT,
    facts_to_json,
    mesh_asset_from_staged,
)
from hephaestus.testing.pinned_image import load_pinned

REPO = Path(__file__).resolve().parents[2]

#: The pinned image's own measurement of this loop. A refusal rather than a
#: default when it is missing or was recorded outside a pinned image.
PINNED = load_pinned(Path(__file__).resolve().parent / "evidence", REPO)

#: The two ceilings as they stood BEFORE the image measured them. Kept named so
#: the derivations below can be held to mission rule 4's direction: a budget
#: tightens and never loosens, and a re-measurement that raised one would be a
#: regression wearing a measurement's clothes.
PRE_MEASUREMENT_EPS_MM: float = 1e-3
PRE_MEASUREMENT_VOLUME_BIAS: float = 0.01

#: §6.6 identity: kernel precision, order 1e-3 mm — **derived** from the pinned
#: image's recorded 9.3686e-7 mm on the reference loop, with three orders of
#: magnitude of headroom rounded up to the next power of ten. Three orders is
#: not slack that was needed; it is the measurement saying this direction is
#: structurally zero, which is exactly what makes clause 45 a corruption check
#: and not a fidelity one (clause 46 is the fidelity one, and it binds a
#: two-sided window instead).
MESH_ROUNDTRIP_EPS_MM: float = 10.0 ** math.ceil(
    math.log10(1_000.0 * PINNED.number("roundtrip_scan_to_part_max_mm"))
)

#: §6.6 volume: the polyhedron is **inscribed**, so its volume is below the
#: analytic one ALWAYS, by no more than this *relative* bias — **derived** from
#: the pinned image's recorded 0.70650% at the pinned 0.1 mm deflection, plus a
#: quarter's headroom. A quarter because the bias is a property of the declared
#: deflection rather than of the run (the spec's own reference figures fall with
#: its square: -0.36% at 0.05 mm, -0.073% at 0.01 mm), so a tessellation of the
#: same declared deflection has no business drifting far, and doubling the
#: deflection must fail this rather than fit inside it.
MESH_TESSELLATION_VOLUME_BIAS: float = 1.25 * PINNED.number("tessellation_volume_bias")

#: The §6.6 window's two multipliers. ``LINEAR_DEFLECTION`` is READ from
#: ``tessellate.py`` and never copied, so a change to the pinned deflection
#: moves the window with it rather than leaving a stale number behind.
WINDOW_LOW: float = 0.5
WINDOW_HIGH: float = 1.10


def _sphere() -> Any:
    from build123d import Sphere

    return Sphere(SPHERE_R)


def _analytic_volume() -> float:
    return 4.0 / 3.0 * math.pi * SPHERE_R**3


def _round_trip(blob: bytes) -> Any:
    """One loop: canonicalize the exported mesh, measure it against the solid."""
    vertices, triangles, _canonical = canonical_arrays(blob, path="sphere.stl")
    return scan_distance(cast("Any", _sphere()), vertices, triangles)


# ==========================================================================
# clause 45 — identity (a corruption check, and labelled as one)


def test_both_constants_are_set_from_a_recorded_pinned_image_measurement() -> None:
    """Clause 45's provenance half, asserted rather than described.

    "Value from a recorded pinned-image measurement" is a claim about where a
    number came from, and no amount of passing the loop below can establish it.
    So it is asserted against the record itself: the record exists, it was taken
    inside a pinned image (``pinned_stamp`` refuses to write one anywhere else),
    it was taken against the ``docker/ci/Dockerfile`` base this checkout still
    declares — ``load_pinned`` re-reads that ``FROM`` digest, which is what ties
    a record to the image *definition* on a machine that cannot pull the
    registry digest — and both constants are exactly the recorded figures times
    their declared headroom.

    Direction is pinned too: neither derived ceiling may exceed the one that
    stood before the image measured anything. Budgets tighten, never loosen.
    """
    from hephaestus.core.mesh_solid import UNPINNED_IMAGE

    assert PINNED.image_digest != UNPINNED_IMAGE
    assert PINNED.image_digest.startswith("sha256:")
    assert "7.9" in PINNED.occt_version

    identity = PINNED.number("roundtrip_scan_to_part_max_mm")
    bias = PINNED.number("tessellation_volume_bias")
    assert 10.0 ** math.ceil(math.log10(1_000.0 * identity)) == MESH_ROUNDTRIP_EPS_MM
    assert 1.25 * bias == MESH_TESSELLATION_VOLUME_BIAS
    # The recorded figures sit inside the ceilings they generate — a derivation
    # that produced a ceiling below its own measurement would be arithmetic
    # nobody checked.
    assert identity < MESH_ROUNDTRIP_EPS_MM
    assert 0.0 < bias < MESH_TESSELLATION_VOLUME_BIAS
    assert MESH_ROUNDTRIP_EPS_MM <= PRE_MEASUREMENT_EPS_MM
    assert MESH_TESSELLATION_VOLUME_BIAS <= PRE_MEASUREMENT_VOLUME_BIAS

    # The image measured the fidelity direction on the same loop, so clause 46's
    # window has a recorded figure inside it too — a two-sided window whose only
    # evidence was the developer host would be the same gap one clause over.
    fidelity = PINNED.number("roundtrip_part_to_scan_max_mm")
    assert PINNED.measurements["roundtrip_part_to_scan_method"] == SCAN_METHOD_EXACT
    assert WINDOW_LOW * LINEAR_DEFLECTION <= fidelity <= WINDOW_HIGH * LINEAR_DEFLECTION


def test_the_tessellation_nodes_still_lie_on_the_surface_they_came_from(
    meshes: Fixtures,
) -> None:
    """CORRUPTION CHECK, not a fidelity check.

    A scale error, a coordinate-order bug, a corrupted writer or a weld that
    moved a vertex fails this. A coarse tessellation does **not**, and must not:
    a coarse tessellation's nodes are still on the surface.
    """
    record = _round_trip(meshes.sphere_stl)
    assert record.scan_to_part_max_mm <= MESH_ROUNDTRIP_EPS_MM
    assert record.scan_samples > 500, "measured over the whole mesh, not a corner of it"


def test_a_coarse_tessellation_still_passes_the_identity_clause(meshes: Fixtures) -> None:
    """The control that proves clause 45 is NOT measuring fidelity.

    The coarse mesh's sampled deviation is three times the declared deflection —
    it fails clause 46 outright below — and it passes this one, because its
    nodes are on the sphere too. A single clause that passed here and claimed to
    bind the deflection would be the defect §6.6 splits itself to avoid.
    """
    record = _round_trip(meshes.sphere_coarse_stl)
    assert record.scan_to_part_max_mm <= MESH_ROUNDTRIP_EPS_MM


def test_a_mesh_whose_vertices_moved_fails_the_identity_clause(meshes: Fixtures) -> None:
    """The negative control §6.6 asks for by name: vertices scaled by 1.001.

    0.1% of a 20 mm sphere is 20 µm — twenty times the tolerance and four orders
    of magnitude above the measured value, so the clause has real reach and is
    not merely satisfied by floating-point luck.
    """
    record = _round_trip(meshes.sphere_scaled_stl)
    assert record.scan_to_part_max_mm > MESH_ROUNDTRIP_EPS_MM
    assert record.scan_to_part_max_mm == pytest.approx(SPHERE_R * 0.001, rel=0.05)


def test_the_tessellated_volume_is_strictly_below_the_analytic_one(meshes: Fixtures) -> None:
    """The SIGN is the claim; the bias is the budget (§2.2, §6.6).

    Facets are inscribed, so a tessellated volume above the analytic one is not
    a small error — it means the field is measuring something else.
    """
    vertices, _triangles, canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="sphere.stl", units="mm"
    )
    analytic = _analytic_volume()
    assert asset.tessellated_volume_mm3 is not None
    assert asset.tessellated_volume_mm3 < analytic
    bias = (analytic - asset.tessellated_volume_mm3) / analytic
    assert 0.0 < bias <= MESH_TESSELLATION_VOLUME_BIAS
    assert vertices.shape[0] > 0


def test_the_field_is_named_tessellated_volume_not_volume(meshes: Fixtures) -> None:
    """§2.2's mechanism, restated where the bias is measured: the NAME carries it."""
    _v, _t, canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="sphere.stl", units="mm"
    )
    assert hasattr(asset, "tessellated_volume_mm3")
    assert not hasattr(asset, "volume")


_HASH_CHILD = """
import hashlib, sys
sys.path.insert(0, {tests!r})
from _g12c import make_fixtures
from hephaestus.geom.mesh import canonicalize_mesh

blob = canonicalize_mesh("sphere.stl", make_fixtures().sphere_stl, "mm").blob
print(hashlib.sha256(blob).hexdigest())
"""


def test_the_canonical_hash_is_identical_in_a_second_independent_process(
    meshes: Fixtures,
) -> None:
    """§6.6's last bullet, and Tier 1 (§8): the same bytes, the same identity."""
    import hashlib

    _v, _t, canonical = canonical_arrays(meshes.sphere_stl, path="sphere.stl")
    here = hashlib.sha256(canonical.blob).hexdigest()
    source = _HASH_CHILD.format(tests=str(Path(__file__).resolve().parent))
    completed = subprocess.run(
        [sys.executable, "-c", source],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert completed.stdout.strip().splitlines()[-1] == here


# ==========================================================================
# clause 46 — fidelity (the clause that binds the declared deflection)


def test_the_imported_mesh_holds_the_deflection_the_pipeline_declared(
    meshes: Fixtures,
) -> None:
    """The two-sided window, with the METHOD asserted first.

    An upper-bound method fails this clause outright rather than satisfying it
    loosely: a bound compared against a window is not a measurement (§6.6). The
    upper half catches a tessellation coarser than declared; the lower half
    catches an implausibly-zero result — which in this loop means the
    measurement did not run, sampled nothing, or silently compared the solid to
    itself, the failure a one-sided ceiling can never see.
    """
    record = _round_trip(meshes.sphere_stl)

    assert record.part_to_scan_method == SCAN_METHOD_EXACT
    assert record.part_to_scan_max_mm is not None
    assert record.part_samples > 0

    low = WINDOW_LOW * LINEAR_DEFLECTION
    high = WINDOW_HIGH * LINEAR_DEFLECTION
    assert low <= record.part_to_scan_max_mm <= high, (
        f"measured {record.part_to_scan_max_mm} outside [{low}, {high}] — the window is "
        "not widened when the measurement lands outside it; the pipeline is wrong "
        "(MESH_INGEST.md §6.6)"
    )


def test_a_coarser_tessellation_exceeds_the_window(meshes: Fixtures) -> None:
    """Upper negative control: a mesh coarser than declared must FAIL."""
    record = _round_trip(meshes.sphere_coarse_stl)
    assert record.part_to_scan_max_mm is not None
    assert record.part_to_scan_max_mm > WINDOW_HIGH * LINEAR_DEFLECTION


def test_a_dense_re_tessellation_falls_under_the_window(meshes: Fixtures) -> None:
    """Lower negative control: an implausibly small figure must FAIL too.

    This is the half a one-sided ceiling cannot have. A measurement that did not
    run, or that compared the solid to itself, lands here — and so does a mesh
    that is simply much finer than the pipeline declared, which is equally a
    statement that the number is not describing the declared tessellation.
    """
    record = _round_trip(meshes.sphere_dense_stl)
    assert record.part_to_scan_max_mm is not None
    assert record.part_to_scan_max_mm < WINDOW_LOW * LINEAR_DEFLECTION


def test_the_window_is_read_from_the_pinned_deflection_never_copied() -> None:
    """A change to ``tessellate.py``'s constant moves the window with it."""
    source = (REPO / "core" / "src" / "hephaestus" / "core" / "render" / "tessellate.py").read_text(
        encoding="utf-8"
    )
    assert f"LINEAR_DEFLECTION = {LINEAR_DEFLECTION}" in source
    module = Path(__file__).read_text(encoding="utf-8")
    assert "from hephaestus.core.render.tessellate import LINEAR_DEFLECTION" in module
    assert f"LINEAR_DEFLECTION = {LINEAR_DEFLECTION}" not in module, (
        "the deflection is read from the renderer, never restated here"
    )


def test_the_two_clauses_measure_two_different_things(meshes: Fixtures) -> None:
    """Finding 6, as an assertion: the identity direction cannot bound fidelity.

    On the same loop, the identity direction is five orders of magnitude smaller
    than the fidelity direction. A single clause binding
    ``1.10 x LINEAR_DEFLECTION`` on the identity direction would pass with that
    much slack even if the tessellation had lost its shape entirely — which is
    precisely why §6.6 binds the OTHER direction.
    """
    record = _round_trip(meshes.sphere_stl)
    assert record.part_to_scan_max_mm is not None
    assert record.scan_to_part_max_mm < record.part_to_scan_max_mm / 1e4

    coarse = _round_trip(meshes.sphere_coarse_stl)
    assert coarse.scan_to_part_max_mm <= WINDOW_HIGH * LINEAR_DEFLECTION, (
        "the coarse mesh passes a 1.10 x deflection bound on the IDENTITY "
        "direction while failing it on the fidelity direction: the exact "
        "confusion finding 6 names"
    )
    assert coarse.part_to_scan_max_mm is not None
    assert coarse.part_to_scan_max_mm > WINDOW_HIGH * LINEAR_DEFLECTION


def test_the_measured_constants_say_where_their_values_came_from() -> None:
    """Mission rule 4, repointed with the measurement that discharged it.

    This clause used to pin the *debt*: the module said "repository venv" and
    "OWED", and `MESH_INGEST.md` carried an "Owed, in those words" paragraph.
    The measurement was taken in the pinned image on 2026-08-30 and the
    constants are now derived from the archived record, so pinning the debt
    would pin a sentence that is no longer true — and a doc-pin asserting a
    stale claim is worse than none. It pins the replacement instead: the module
    names the record it derives from, and the spec's §6.6 says where the two
    values live. The amendment is `MESH_INGEST.md` §"The second repair pass"
    and the `mission_plan.md` Stage 12 block's "Constants set from the pinned
    image's own measurement, under rule 4 — TAKEN, 2026-08-30".
    """
    module = Path(__file__).read_text(encoding="utf-8")
    assert "pinned_measurements.json" in module
    assert "derived at import" in module
    manifest = " ".join((REPO / "MESH_INGEST.md").read_text(encoding="utf-8").split())
    assert "Where the two constants' values live" in manifest
    assert "MESH_ROUNDTRIP_EPS_MM" in manifest
    # Whitespace-normalised: the plan is hard-wrapped prose and a line break can
    # fall anywhere inside a sentence, so a raw substring pin would be an
    # assertion about the wrap rather than about the claim.
    plan = " ".join((REPO / "mission_plan.md").read_text(encoding="utf-8").split())
    assert "Constants set from the pinned image's own measurement" in plan
    assert "TAKEN, 2026-08-30" in plan
    # …and the record it names is the one this module actually loaded.
    assert PINNED.spec.startswith("MESH_INGEST.md §Gates G12C.45")


def test_the_round_trip_record_is_json_serialisable_for_the_archive(
    meshes: Fixtures,
) -> None:
    """Mission rule 2: the measurement travels, not an opinion about it."""
    payload = _round_trip(meshes.sphere_stl).to_json()
    assert json.loads(json.dumps(payload))["part_to_scan_method"] == SCAN_METHOD_EXACT
