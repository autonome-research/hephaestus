# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph scan`` — the operator's view of one mesh's facts (``MESH_INGEST.md`` §7.3).

The same admission, the same canonicalization and the same quality record a
build would compute for an ``import_mesh`` statement, printed for a human before
anything is built. ``--json`` emits the record document, so a script and a
person read one shape.

```
heph scan limb-l.stl --units mm --json
```

Two things this command deliberately does NOT do:

- **It does not default the unit.** ``--units`` is required, because STL, PLY,
  OBJ, OFF and XYZ carry none and the engine is millimetres throughout (§1.3).
  A default here would be the harness guessing a scale on the operator's behalf,
  which is the one thing the whole section exists to forbid.
- **It does not read an arbitrary filesystem path.** The argument is relative to
  the project's ``imports/`` and goes through the same confined,
  ``O_NOFOLLOW``-walked read a build uses, under the same §1.6 byte ceiling —
  so what the operator inspects is exactly what a build would admit, refusals
  included.

Exit codes match the engine CLI: 0 success, 1 error, 2 usage. What a 0 does NOT
mean: it says the facts were computed, never that the scan is good enough. This
command reports facts; "watertight and under 2 mm of hole perimeter is
acceptable" is a claim, and claims belong to a ``CHECKS`` predicate that names
its tolerance.

``heph scan check <part> <path> --units mm`` — the ``ScanDistance`` half — lands
at 12C with the distance machinery it prints (§7.3). The facts subcommand landed
at 12A because it needed nothing but admission and canonicalization, and a facts
view that waited for scoring it does not use would have been useless for the
whole of 12A and 12B.

The file must already live under ``imports/``. Admit it with
``heph import add FILE --units …`` (and ``--part NAME`` to seed the Stage 12
``import_mesh`` + ``mesh_to_solid`` script). This verb does not copy, drop,
or reconstruct.

```
heph scan check socket limb-l.stl --units mm --json
```

The check form resolves the same two operands the ``compare_to_scan`` tool does,
through the same :mod:`hephaestus.core.scan_compare` code, so the number an
operator sees and the number a model sees are the same number. ``--units`` is
required in **both** forms and for the same reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

from hephaestus.core.errors import HephaestusError
from hephaestus.core.project_store.layout import find_project_root, load_project

if TYPE_CHECKING:
    from hephaestus.geom.mesh import MeshAsset, PointCloudAsset

__all__ = ["CHECK_VERB", "add_subparsers", "format_distance", "format_mesh", "format_points"]


def _quality_lines(asset: MeshAsset) -> list[str]:
    q = asset.quality
    pairs = "not measured" if q.self_intersecting_pairs is None else str(q.self_intersecting_pairs)
    return [
        "quality (measured and named; nothing was repaired):",
        f"  welded vertex pairs      {q.welded_vertex_pairs}  (at {q.weld_tol_mm} mm)",
        f"  degenerate dropped       {q.degenerate_triangles_dropped}",
        f"  boundary edges / loops   {q.boundary_edge_count} / {q.boundary_loop_count}",
        f"  largest hole perimeter   {q.largest_hole_perimeter_mm:.6f} mm",
        f"  non-manifold edges       {q.nonmanifold_edge_count}",
        f"  non-manifold vertices    {q.nonmanifold_vertex_count}",
        f"  connected components     {q.connected_component_count}",
        f"  inverted-normal tris     {q.inverted_normal_triangles}",
        f"  self-intersecting pairs  {pairs}  [{q.self_intersection_method}]",
    ]


def format_mesh(asset: MeshAsset) -> str:
    """The human report: every fact, with what each field's NAME promises.

    ``tessellated_volume_mm3`` prints as ``n/a`` and never as ``0`` when the
    mesh is not watertight: a volume computed from an open surface is not a
    small error, it is not a volume (§2.2).
    """
    volume = (
        "n/a (not watertight at the weld tolerance)"
        if asset.tessellated_volume_mm3 is None
        else f"{asset.tessellated_volume_mm3:.6f} mm^3 (polyhedron, inscribed — low)"
    )
    extent = " x ".join(f"{value:.6f}" for value in asset.bbox_mm)
    lines = [
        f"scan {asset.source_path}  units declared {asset.units_declared}",
        f"  canonical hash           {asset.canonical_hash}",
        f"  vertices as read/welded  {asset.vertex_count_as_read} / {asset.vertex_count}",
        f"  triangles                {asset.triangle_count}",
        f"  bbox                     {extent} mm",
        f"  tessellated area         {asset.tessellated_area_mm2:.6f} mm^2",
        f"  tessellated volume       {volume}",
        f"  watertight at weld tol   {asset.watertight_at_weld_tol}",
        f"  euler characteristic     {asset.euler_characteristic}  (V - E + F of the file)",
        *_quality_lines(asset),
        "note: these are facts about the FILE. No surface was reconstructed, no "
        "defect was repaired, and nothing here is a clinical claim "
        "(MESH_INGEST.md §3, §11.3)",
    ]
    return "\n".join(lines)


def format_points(asset: PointCloudAsset) -> str:
    """The human report for a point cloud: five facts, and no borrowed ones.

    No volume, no area, no watertightness, no topology — a point cloud has none
    of them, and the record does not carry the names (§2.3).
    """
    extent = " x ".join(f"{value:.6f}" for value in asset.bbox_mm)
    return "\n".join(
        [
            f"point cloud {asset.source_path}  units declared {asset.units_declared}",
            f"  canonical hash           {asset.canonical_hash}",
            f"  points                   {asset.point_count}",
            f"  bbox                     {extent} mm",
            "note: a point cloud is not a shape — it has no volume, no area and no "
            "topology, and none of those fields exist on this record "
            "(MESH_INGEST.md §2.3)",
        ]
    )


#: The literal first positional that selects the ``ScanDistance`` form. argparse
#: cannot express "a path, OR the word check plus two more positionals" without
#: nested subparsers that would break the bare form's own positional, so the
#: routing is one explicit comparison here rather than a parser that silently
#: reads ``check`` as a filename.
CHECK_VERB = "check"


def format_distance(comparison: object) -> str:
    """The human report for one ``ScanDistance``, with every method named.

    Both directions print their own numbers and neither is averaged into the
    other: one of them may be an upper bound, and the mean of an exact number
    and a bound has no defined meaning (§6.4). A ``vertex_nn_upper_bound``
    direction says so on its own line, with the refusal that produced it.
    """
    from hephaestus.core.scan_compare import ScanComparison

    assert isinstance(comparison, ScanComparison)
    distance = comparison.distance
    exact_mean = distance.get("part_to_scan_mean_mm")
    exact_max = distance.get("part_to_scan_max_mm")
    bound = distance.get("part_to_scan_upper_bound_mm")
    if exact_mean is None:
        refusal = distance.get("part_to_scan_refusal") or "no exact refinement"
        part_line = f"  part -> scan            upper bound {bound} mm  [{refusal}]"
    else:
        part_line = f"  part -> scan            mean {exact_mean} mm   max {exact_max} mm"
    return "\n".join(
        [
            f"scan check {comparison.part} against {comparison.scan.path}  "
            f"units {comparison.scan.units}  align {comparison.align}",
            f"  part artifact            {comparison.part_artifact_ref}",
            f"  scan file sha256         {comparison.scan.sha256}",
            f"  scan canonical hash      {comparison.scan.canonical_hash}",
            f"  scan -> part            mean {distance.get('scan_to_part_mean_mm')} mm   "
            f"max {distance.get('scan_to_part_max_mm')} mm",
            f"  scan samples             {distance.get('scan_samples')}",
            part_line,
            f"  part samples             {distance.get('part_samples')}",
            f"  part -> scan method      {distance.get('part_to_scan_method')} "
            f"(bias {distance.get('part_to_scan_bias')})",
            "note: this is a geometric distance at named samples. It is NOT a fit: "
            "rectification is clinical judgement the harness cannot verify, and "
            "nothing here evidences that a socket is safe to wear "
            "(MESH_INGEST.md §11.3)",
        ]
    )


def _cmd_scan_check(args: argparse.Namespace) -> int:
    from hephaestus.core.project_store.layout import open_store
    from hephaestus.core.scan_compare import SCAN_TARGET_PREFIX, ProjectScanComparer

    rest = cast("list[str]", args.rest)
    if len(rest) != 2:
        print(
            "heph: usage: heph scan check <part> <path under imports/> --units {mm,cm,m,in}",
            file=sys.stderr,
        )
        return 2
    part, path = rest
    align = cast("str", args.align)
    raw = cast("str | None", args.transform)
    transform: list[float] | None = None
    if raw is not None:
        try:
            transform = [float(value) for value in raw.split(",")]
        except ValueError:
            print(
                "heph: --transform takes 16 comma-separated numbers (row-major 4x4)",
                file=sys.stderr,
            )
            return 2
    if align == "declared" and transform is None:
        print(
            "heph: --align declared requires --transform: an alignment this record "
            "does not name would be a normalization nobody declared",
            file=sys.stderr,
        )
        return 2
    layout = load_project(find_project_root(Path.cwd()))
    store = open_store(layout)
    try:
        comparer = ProjectScanComparer(layout, store)
        comparison = comparer.compare(
            part,
            f"{SCAN_TARGET_PREFIX}{path}",
            units=cast("str", args.units),
            align=align,
            declared_transform=transform,
        )
    finally:
        store.close()
    print(
        json.dumps(comparison.to_json(), sort_keys=True)
        if args.json
        else format_distance(comparison)
    )
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    if cast("str", args.path) == CHECK_VERB:
        return _cmd_scan_check(args)
    if cast("list[str]", args.rest):
        print(
            "heph: usage: heph scan <path under imports/> --units {mm,cm,m,in} "
            "| heph scan check <part> <path> --units {mm,cm,m,in}",
            file=sys.stderr,
        )
        return 2
    return _cmd_scan_facts(args)


def _cmd_scan_facts(args: argparse.Namespace) -> int:
    from hephaestus.core.executor.imports import max_bytes_for_kind, read_import
    from hephaestus.geom.mesh import (
        canonicalize_mesh,
        canonicalize_points,
        extension_kind,
        facts_to_json,
        mesh_asset_from_staged,
        point_cloud_asset_from_staged,
        sniff_format,
    )

    path = cast("str", args.path)
    units = cast("str", args.units)
    layout = load_project(find_project_root(Path.cwd()))
    kind = extension_kind(path) or "mesh"
    data = read_import(layout.imports_dir, path, max_bytes=max_bytes_for_kind(kind))
    # Admission decides the kind from the bytes, not from the guess above: a
    # ``.xyz`` is a point cloud whatever anybody assumed.
    admitted, _fmt = sniff_format(path, data)
    if admitted == "points":
        cloud = canonicalize_points(path, data, units)
        points = point_cloud_asset_from_staged(cloud.blob, source_path=path, units=units)
        print(json.dumps(points.to_json(), sort_keys=True) if args.json else format_points(points))
        return 0
    canonical = canonicalize_mesh(path, data, units)
    asset = mesh_asset_from_staged(
        canonical.blob, facts_to_json(canonical), source_path=path, units=units
    )
    print(json.dumps(asset.to_json(), sort_keys=True) if args.json else format_mesh(asset))
    return 0


def _guard(args: argparse.Namespace) -> int:
    try:
        return _cmd_scan(args)
    except HephaestusError as exc:
        print(f"heph: error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``scan`` verb on an existing subparser set."""
    from hephaestus.core.checks.facade import SCAN_ALIGN_MODES
    from hephaestus.geom.mesh import MESH_UNITS

    scan = sub.add_parser(
        "scan",
        help="print the facts of a mesh or point cloud already under imports/ "
        "(admit with heph import add; no reconstruction)",
    )
    scan.add_argument(
        "path",
        help="path under imports/ (the same confined read a build uses), "
        "or the literal 'check' for the scan-distance form",
    )
    scan.add_argument(
        "rest",
        nargs="*",
        metavar="ARGS",
        help="for the check form: <part> <path under imports/>",
    )
    scan.add_argument(
        "--units",
        required=True,
        choices=list(MESH_UNITS),
        help="declared unit of the file — required, because these formats carry none "
        "and inferring one from the bounding box is a guess dressed as a measurement",
    )
    scan.add_argument(
        "--transform",
        default=None,
        metavar="M",
        help="16 comma-separated numbers: the row-major 4x4 rigid transform for "
        "--align declared. Validated as rigid (orthonormal, det +1) or refused by "
        "name — an alignment may rotate a scan, never mirror or scale it",
    )
    scan.add_argument(
        "--align",
        default="as_posed",
        choices=list(SCAN_ALIGN_MODES),
        help="scan-check alignment: where the operator placed the scan, or a declared "
        "rigid transform. 'principal' is refused by name — a limb scan is always "
        "partial, so its sampled principal axes are not the object's",
    )
    scan.add_argument("--json", action="store_true", help="emit the facts document as JSON")
    scan.set_defaults(func=_guard)
