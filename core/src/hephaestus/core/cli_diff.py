"""``heph diff`` — the operator's view of one solid comparison (COMPARE.md §2).

The same resolution and the same numbers the ``compare_solids`` tool returns
(:mod:`hephaestus.core.project_compare`), printed for a human. ``--json`` emits
the tool's exact result document, so a script and a model read one shape.

```
heph diff bracket import:target.step --align principal --json
```

Exit codes match the engine CLI: 0 success, 1 error, 2 usage. Note what the
exit code does NOT mean: it says the comparison ran, never that the part is
close enough. This command reports facts; "iou >= 0.995 is a pass" is a claim,
and claims belong to a ``CHECKS`` predicate or a bench task policy that names
its tolerance (``COMPARE.md`` §1).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import Any, cast

from hephaestus.core.cli_errors import guard, project_root_or_refuse
from hephaestus.core.project_compare import (
    ALIGN_MODES,
    CompareChildDied,
    CompareCutShort,
    ProjectComparer,
    SolidComparison,
)
from hephaestus.core.project_store.layout import load_project, open_store

__all__ = ["add_subparsers", "format_comparison", "format_timeout"]


def _number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _section(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}


def _extent(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, list | tuple):
        return "-"
    items = list(cast("list[Any]", value))
    return " x ".join(f"{float(cast('float', item)):.3f}" for item in items)


def _operand(side: Mapping[str, Any]) -> str:
    if side.get("kind") == "import":
        return f"import:{side.get('path')} ({side.get('sha256')})"
    return f"part:{side.get('name')} ({side.get('artifact_ref')})"


def format_comparison(comparison: SolidComparison) -> str:
    """The human report: every fact, with the alignment mode never implicit."""
    diff = comparison.diff
    volume = _section(diff, "volume")
    surface = _section(diff, "surface")
    topology = _section(diff, "topology")
    lines = [
        f"a: {_operand(comparison.a.to_json())}",
        f"b: {_operand(comparison.b.to_json())}",
        f"align: {comparison.align}",
        "",
        "volume (mm^3)",
        f"  common      {_number(volume, 'common_mm3'):.6f}",
        f"  a only      {_number(volume, 'a_only_mm3'):.6f}",
        f"  b only      {_number(volume, 'b_only_mm3'):.6f}",
        f"  iou         {_number(volume, 'iou'):.6f}",
        "",
        "surface (mm)",
        f"  chamfer     {_number(surface, 'chamfer_mm'):.6f}",
        f"  a -> b mean {_number(surface, 'a_to_b_mean_mm'):.6f}",
        f"  b -> a mean {_number(surface, 'b_to_a_mean_mm'):.6f}",
        f"  max dev     {_number(surface, 'max_deviation_mm'):.6f}",
        f"  samples     a={surface.get('a_samples', 0)} b={surface.get('b_samples', 0)}",
        "",
        "topology (delta = b - a)",
        f"  solids      {topology.get('solids_delta', 0):+d}",
        f"  faces       {topology.get('faces_delta', 0):+d}",
        f"  edges       {topology.get('edges_delta', 0):+d}",
        f"  genus       {topology.get('genus_delta', 0):+d}",
        f"  sealed      {'changed' if topology.get('sealed_changed') else 'unchanged'}",
        "",
        f"a volume {_number(diff, 'a_volume_mm3'):.6f} mm^3   bbox {_extent(diff, 'a_bbox_mm')} mm",
        f"b volume {_number(diff, 'b_volume_mm3'):.6f} mm^3   bbox {_extent(diff, 'b_bbox_mm')} mm",
    ]
    if comparison.align == "principal":
        # The bboxes are the shapes AS POSED by the caller; only the volume and
        # surface figures were computed in the canonical frame. Saying so is the
        # difference between a caveat and a silently misread number.
        lines.append(
            "note: bboxes are as-posed; only volume/surface were compared in the principal frame"
        )
    return "\n".join(lines)


def format_timeout(refusal: CompareCutShort) -> str:
    """A cut-short comparison for a human: the partial facts, then what was lost.

    ``COMPARE.md`` §5: an operator gets the same signal the model gets — the
    cheap facts that arrived before the kill, and the names of the halves that
    did not — never a silently absent number.

    The closing note is the one line that must differ between the two reasons.
    A ceiling is fixed by allowing more time; a dead child is not, and printing
    "raise HEPHAESTUS_COMPARE_TIMEOUT_S" over a crash sends the reader to a
    setting that has nothing to do with it.
    """
    died = isinstance(refusal, CompareChildDied)
    headline = "comparison subprocess died" if died else "comparison timed out"
    lines = [f"{headline}: {refusal.message}", ""]
    partial = refusal.partial
    if partial is None:
        lines.append("partial facts: none arrived before the kill")
    else:
        topology = _section(partial, "topology")
        lines.extend(
            [
                "partial facts (streamed before the kill)",
                "  topology (delta = b - a)",
                f"    solids      {topology.get('solids_delta', 0):+d}",
                f"    faces       {topology.get('faces_delta', 0):+d}",
                f"    edges       {topology.get('edges_delta', 0):+d}",
                f"    genus       {topology.get('genus_delta', 0):+d}",
                f"    sealed      {'changed' if topology.get('sealed_changed') else 'unchanged'}",
                f"  a volume {_number(partial, 'a_volume_mm3'):.6f} mm^3   "
                f"bbox {_extent(partial, 'a_bbox_mm')} mm",
                f"  b volume {_number(partial, 'b_volume_mm3'):.6f} mm^3   "
                f"bbox {_extent(partial, 'b_bbox_mm')} mm",
            ]
        )
    lines.append(f"lost: {', '.join(refusal.lost)}")
    lines.append(
        f"note: the diff subprocess exited with code {refusal.exit_code}; "
        "no ceiling fired, so allowing more time will not help (COMPARE.md §5)"
        if isinstance(refusal, CompareChildDied)
        else "note: raise HEPHAESTUS_COMPARE_TIMEOUT_S to allow more time (COMPARE.md §5)"
    )
    return "\n".join(lines)


def _cmd_diff(args: argparse.Namespace) -> int:
    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    try:
        comparison = ProjectComparer(layout, store).compare(
            cast("str", args.part),
            cast("str", args.target),
            align=cast("str", args.align),
        )
    except CompareCutShort as exc:
        # COMPARE.md §5: the partial facts are the report; the exit code says
        # the comparison did not complete. Caught as the carriage, so the
        # ceiling and the dead-child reasons both land here and neither can be
        # missed by a catch that names only one of them.
        if bool(args.json):
            print(json.dumps(exc.to_json(), sort_keys=True))
        else:
            print(format_timeout(exc))
        return 1
    finally:
        store.close()
    if bool(args.json):
        print(json.dumps(comparison.to_json(), sort_keys=True))
    else:
        print(format_comparison(comparison))
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``diff`` verb on an existing subparser set."""
    diff = sub.add_parser("diff", help="compare a part against another part or an import")
    diff.add_argument("part", help="part whose current build is the 'a' side")
    diff.add_argument("target", help="'part:<name>' or 'import:<path under imports/>'")
    diff.add_argument(
        "--align",
        choices=list(ALIGN_MODES),
        default="as_posed",
        help="comparison frame (default: as_posed — a moved part IS different)",
    )
    diff.add_argument("--json", action="store_true", help="emit the comparison document as JSON")
    diff.set_defaults(func=guard(_cmd_diff))
