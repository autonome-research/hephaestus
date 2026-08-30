# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Take (or re-verify) the Stage 12 measurements that must come from the image.

``MESH_INGEST.md`` §Gates clauses G12A.19, G12B.25, G12B.33 and G12C.45 say
their numbers are measured **in the pinned image**, and mission rule 4
(``mission_plan.md``) says the constants those clauses enforce are set from that
measurement. This script is the command that takes them, and the command that
re-takes them.

Two modes, and the difference matters:

``--write``
    Measure everything and archive it, stamped with the world it was measured in
    (``hephaestus.testing.pinned_image``). Refuses outright outside a pinned
    image, so a developer-host run can never be committed as an image
    measurement. This is what a re-record PR runs.

``--check``
    Measure everything again and compare against the committed record, writing
    nothing. This is what the ``stage12 measurements (pinned image)`` CI lane
    runs on every PR: a recorded number nobody re-takes is a number nobody is
    accountable for, and the image can move under a record without anybody
    noticing. Kernel figures must agree closely; wall-clock figures are allowed
    a generous drift band, because a busy runner is not a regression and an
    order-of-magnitude blowup is. A record from a **different OCCT** is not
    compared at all — it is refused, on the §8 Tier 3 rule a sew golden already
    follows, because a difference under a moved kernel says nothing about the
    code under test. A different *image digest* under the same OCCT is reported
    and compared: two builds of one digest-pinned Dockerfile ship one wheel.

**How to run it here.** Inside the pinned image, exactly as ``ci.yml`` does. On
a machine that cannot pull the GHCR digest (a private package answers 403
without ``read:packages``), build the image from the repository's own unchanged
``docker/ci/Dockerfile`` — whose ``FROM`` is digest-pinned — following
``docker/ci/README.md``, and export both

    HEPHAESTUS_CI_IMAGE_DIGEST=<the local image's own content digest>
    HEPHAESTUS_CI_IMAGE_REF=<how it was obtained, in words>

The record then says which of the two routes produced it, and
:func:`~hephaestus.testing.pinned_image.load_pinned` re-reads the Dockerfile's
``FROM`` digest at test time so a base bump invalidates it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from hephaestus.testing.pinned_image import CLOCK_HEADROOM, PinnedMeasurementError

REPO = Path(__file__).resolve().parents[1]

#: Wall-clock figures may drift by this factor before ``--check`` calls it a
#: regression. Read from :data:`~hephaestus.testing.pinned_image.CLOCK_HEADROOM`
#: rather than chosen again here: the gate clause derives its ceiling from the
#: same band, and two independently chosen factors would eventually disagree
#: about what a regression is.
CLOCK_DRIFT_FACTOR = CLOCK_HEADROOM
CLOCK_DRIFT_FLOOR_S = 0.5

#: Kernel figures are deterministic within one OCCT build, so they are compared
#: at the precision the arithmetic actually has rather than loosely.
KERNEL_REL_TOLERANCE = 1e-9

#: The three suites' evidence directories, and the spec sentence each record
#: exists for. One record per suite: a suite is a gate command, and a gate that
#: reads another gate's directory is coupling.
SUITES: dict[str, str] = {
    "stage12a": "MESH_INGEST.md §Gates G12A.19 — parse + canonicalize + quality budget",
    "stage12b": "MESH_INGEST.md §Gates G12B.25, G12B.33 — ShapeFix disposition, sew determinism",
    "stage12c": "MESH_INGEST.md §Gates G12C.45 — round-trip identity constants",
}


def _suite_path(suite: str) -> Path:
    return REPO / "tests" / suite


def _on_path(suite: str) -> None:
    """Make one suite's fixture module importable, the way pytest does."""
    path = str(_suite_path(suite))
    if path not in sys.path:
        sys.path.insert(0, path)


# --------------------------------------------------------------------------
# the measurements themselves


def measure_stage12a() -> dict[str, Any]:
    """G12A.19: parse + canonicalize + quality for the reference fixture scan.

    The same reference mesh the clause uses — an icosphere at subdivision 5, so
    the figure is about a scan-sized triangle count rather than about a cube.
    """
    import trimesh
    from hephaestus.geom.mesh import canonicalize_mesh

    sphere = trimesh.creation.icosphere(subdivisions=5, radius=100.0)
    payload = sphere.export(file_type="ply")
    data = payload if isinstance(payload, bytes) else payload.encode()

    started = time.perf_counter()
    canonical = canonicalize_mesh("reference.ply", data, "mm")
    elapsed = time.perf_counter() - started
    assert canonical.quality.connected_component_count == 1
    return {
        "parse_canonicalize_quality_s": round(elapsed, 4),
        "reference_triangles": len(sphere.faces),
    }


def measure_stage12b() -> dict[str, Any]:
    """G12B.25 (the ShapeFix disposition) and G12B.33 (two-process sew counts).

    Clause 33's whole content is that two *separate processes* agree, so the
    record carries both children's projections rather than one and a claim: a
    reader can see the equality rather than take it.
    """
    _on_path("stage12b")
    from _g12b import canonical_arrays, make_fixtures  # pyright: ignore[reportMissingImports]
    from _g12b_subprocess import run_json  # pyright: ignore[reportMissingImports]
    from hephaestus.geom.mesh_solid import sew_to_solid, shapefix_probe

    fixtures = make_fixtures()
    solid, report = sew_to_solid(
        fixtures.sphere_raw_vertices, fixtures.sphere_raw_faces, source="sphere-raw"
    )
    assert report.is_valid is False, "the §4.5 experiment needs something to repair"
    outcomes = [
        shapefix_probe(solid, fixer=name).to_json()
        for name in ("ShapeFix_Shape", "ShapeFix_Solid", "ShapeFix_Shell")
    ]

    # Imported from the clause's own module so the two can never measure
    # different things.
    from test_g12b_goldens_and_determinism import (  # pyright: ignore[reportMissingImports]
        SEW_CHILD,
    )

    first = run_json(SEW_CHILD)
    second = run_json(SEW_CHILD)

    canonical_v, canonical_f, _canonical = canonical_arrays(fixtures.sphere_stl, path="sphere.stl")
    _canonical_solid, canonical_report = sew_to_solid(canonical_v, canonical_f, source="sphere.stl")
    return {
        "shapefix_outcomes": outcomes,
        "shapefix_reached_valid": [bool(outcome["reached_valid"]) for outcome in outcomes],
        "shapefix_max_seconds": round(max(float(o["seconds"]) for o in outcomes), 4),
        "sew_two_process": {"first": first, "second": second},
        "sew_canonical_key": canonical_report.determinism_key(),
    }


def measure_stage12c() -> dict[str, Any]:
    """G12C.45: the round-trip identity and volume-bias figures.

    Both directions are recorded, because clause 46 reads the second one and a
    record that carried only the constant-bearing half would leave the fidelity
    window unevidenced in this world.
    """
    import math

    _on_path("stage12c")
    from _g12c import (  # pyright: ignore[reportMissingImports]
        SPHERE_R,
        canonical_arrays,
        make_fixtures,
    )
    from build123d import Sphere
    from hephaestus.geom.compare import scan_distance
    from hephaestus.geom.mesh import facts_to_json, mesh_asset_from_staged

    fixtures = make_fixtures()
    vertices, triangles, canonical = canonical_arrays(fixtures.sphere_stl, path="sphere.stl")
    record = scan_distance(Sphere(SPHERE_R), vertices, triangles)
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path="sphere.stl", units="mm"
    )
    analytic = 4.0 / 3.0 * math.pi * SPHERE_R**3
    tessellated = asset.tessellated_volume_mm3
    assert tessellated is not None, "the round-trip fixture must be watertight"
    return {
        "roundtrip_scan_to_part_max_mm": record.scan_to_part_max_mm,
        "roundtrip_part_to_scan_max_mm": record.part_to_scan_max_mm,
        "roundtrip_part_to_scan_method": record.part_to_scan_method,
        "tessellated_volume_mm3": tessellated,
        "analytic_volume_mm3": analytic,
        "tessellation_volume_bias": (analytic - tessellated) / analytic,
    }


MEASURERS = {
    "stage12a": measure_stage12a,
    "stage12b": measure_stage12b,
    "stage12c": measure_stage12c,
}

#: Keys whose value is a wall clock, and therefore compared with drift headroom
#: rather than as a kernel figure.
CLOCK_KEYS = frozenset({"parse_canonicalize_quality_s", "shapefix_max_seconds", "seconds"})


# --------------------------------------------------------------------------
# write / check


def _write(image_ref: str | None) -> int:
    from hephaestus.testing.pinned_image import write_pinned

    for suite, spec in SUITES.items():
        measurements = MEASURERS[suite]()
        path = write_pinned(
            _suite_path(suite) / "evidence",
            REPO,
            spec=spec,
            measurements=measurements,
            image_ref=image_ref,
        )
        print(f"wrote {path.relative_to(REPO)}")
        print(json.dumps(measurements, indent=2, sort_keys=True))
    return 0


def _compare(key: str, recorded: Any, fresh: Any, problems: list[str], where: str) -> None:
    """One recorded figure against its re-measurement, by what kind it is."""
    if isinstance(recorded, bool) or isinstance(fresh, bool):
        if recorded != fresh:
            problems.append(f"{where}.{key}: recorded {recorded!r}, measured {fresh!r}")
        return
    if isinstance(recorded, int | float) and isinstance(fresh, int | float):
        if key in CLOCK_KEYS:
            ceiling = float(recorded) * CLOCK_DRIFT_FACTOR + CLOCK_DRIFT_FLOOR_S
            if float(fresh) > ceiling:
                problems.append(
                    f"{where}.{key}: recorded {recorded}, measured {fresh} — past the "
                    f"{CLOCK_DRIFT_FACTOR:g}x drift band ({ceiling:.3f})"
                )
            return
        scale = max(abs(float(recorded)), abs(float(fresh)), 1e-12)
        if abs(float(recorded) - float(fresh)) / scale > KERNEL_REL_TOLERANCE:
            problems.append(f"{where}.{key}: recorded {recorded}, measured {fresh}")
        return
    if isinstance(recorded, dict) and isinstance(fresh, dict):
        for sub in sorted(set(recorded) | set(fresh)):
            _compare(sub, recorded.get(sub), fresh.get(sub), problems, f"{where}.{key}")
        return
    if isinstance(recorded, list) and isinstance(fresh, list):
        if len(recorded) != len(fresh):
            problems.append(
                f"{where}.{key}: recorded {len(recorded)} entries, measured {len(fresh)}"
            )
            return
        for index, (a, b) in enumerate(zip(recorded, fresh, strict=True)):
            _compare(str(index), a, b, problems, f"{where}.{key}")
        return
    if recorded != fresh:
        problems.append(f"{where}.{key}: recorded {recorded!r}, measured {fresh!r}")


def _check() -> int:
    from hephaestus.testing.pinned_image import load_pinned, pinned_stamp

    stamp = pinned_stamp(REPO)
    print(f"re-measuring in {stamp['image_digest']} ({stamp['image_ref']})")
    problems: list[str] = []
    for suite in SUITES:
        record = load_pinned(_suite_path(suite) / "evidence", REPO)
        fresh = MEASURERS[suite]()
        if record.image_digest != stamp["image_digest"]:
            # NOT a failure. The record may legitimately come from the other
            # route to the same image definition (local build vs GHCR pull), and
            # the base-image pin load_pinned() already enforced is what ties the
            # two together. Printed so a re-record PR has the digest to quote.
            print(
                f"  {suite}: recorded in {record.image_digest} ({record.image_ref}); "
                f"this run is {stamp['image_digest']}"
            )
        if record.occt_version != stamp["occt_version"]:
            # This one IS a failure, and it is the §8 Tier 3 rule rather than a
            # convenience: OCCT's sewing and tessellation are what these figures
            # measure, so a difference under a moved kernel would say nothing
            # about the code under test — exactly the reason a sew golden refuses
            # to compare across a moved pair. The resolution is the same: re-take
            # the measurement and commit it with the bump.
            problems.append(
                f"{suite}: recorded under OCCT {record.occt_version!r} and this run is "
                f"{stamp['occt_version']!r}. The record is INVALID for this kernel and "
                "is not compared."
            )
            continue
        for key in sorted(set(record.measurements) | set(fresh)):
            _compare(key, record.measurements.get(key), fresh.get(key), problems, suite)
        print(f"  {suite}: {len(record.measurements)} recorded figures re-measured")
    if problems:
        print("\nthe committed pinned-image record no longer describes this image:")
        for problem in problems:
            print(f"  - {problem}")
        print(
            "\nRe-take it with --write inside the image and commit the diff with the "
            "change that caused it (MESH_INGEST.md §8 Tier 3, verification.md)."
        )
        return 1
    print("\nevery recorded pinned-image figure still holds")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="measure and archive")
    group.add_argument("--check", action="store_true", help="re-measure and compare")
    parser.add_argument(
        "--image-ref",
        default=None,
        help="how this image was obtained, in words (defaults to $HEPHAESTUS_CI_IMAGE_REF)",
    )
    args = parser.parse_args(argv)
    try:
        return _write(args.image_ref) if args.write else _check()
    except PinnedMeasurementError as refusal:
        # Printed rather than raised: this is a refusal an operator is meant to
        # read and act on ("run it in the image"), and a traceback buries the
        # one sentence that says what to do.
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
