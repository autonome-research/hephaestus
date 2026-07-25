"""``heph render`` and ``heph goldens`` CLI verbs (Stage 1 render service).

Kept in a separate module from :mod:`hephaestus.core.cli` so the render stack
(trimesh/pyrender/OCP) is imported only when a render verb actually runs;
``cli.build_parser`` registers these subparsers through :func:`add_subparsers`
and every existing verb (build/check/lint) is untouched.

- ``heph render <part> [--views ...] [--channel rgb|mask|section]
  [--mask-mode solid|selection] [--section-plane S] [--explode T]
  [--focus F] [--last-good | --artifact-ref REF] [--out DIR] [--json]``
  renders the part's current build (or an explicit/last-good artifact) and
  writes one PNG per image plus a metadata JSON sidecar under ``--out``.
- ``heph goldens --update [--dir tests/render/goldens]`` regenerates the golden
  corpus; it refuses to run on a dirty git tree (verification.md meta-test).

Exit codes match the engine CLI: 0 success, 1 error (no build, dirty tree),
2 usage (argparse). Render itself never rebuilds — it reads the published
current build, so a build must have run first.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from hephaestus.core.project_store.layout import find_project_root, load_project, open_store

__all__ = ["add_subparsers", "main"]


def _slug(view: str) -> str:
    return view.replace("+", "p").replace("-", "m")


def _cmd_render(args: argparse.Namespace) -> int:
    from hephaestus.core.render.inspect import RenderProject, inspect_part

    part = cast("str", args.part)
    views = cast("list[str]", args.views) or ["iso", "+X"]
    out_dir = Path(cast("str", args.out))
    json_out = bool(args.json)

    root = find_project_root(Path.cwd())
    layout = load_project(root)
    store = open_store(layout)
    project = RenderProject(layout=layout, store=store)

    result = inspect_part(
        project,
        part,
        views=views,
        channel=cast("str", args.channel),
        mask_mode=cast("str", args.mask_mode),
        section_plane=cast("str | None", args.section_plane),
        explode=float(cast("float", args.explode)),
        last_good=bool(args.last_good),
        artifact_ref=cast("str | None", args.artifact_ref),
        focus=cast("str | None", args.focus),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    image_records: list[dict[str, object]] = []
    for image in result.images:
        filename = f"{part}_{_slug(image.view)}_{image.channel}.png"
        path = out_dir / filename
        path.write_bytes(image.png)
        image_records.append(
            {
                "view": image.view,
                "channel": image.channel,
                "file": str(path),
                "render_artifact_ref": image.render_ref,
                "palette_decodable": image.palette_decodable,
            }
        )

    metadata: dict[str, object] = dict(result.to_json())
    metadata["images"] = image_records
    metadata["part"] = part
    metadata_path = out_dir / f"{part}_render.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if json_out:
        print(json.dumps(metadata))
    else:
        print(f"{part}: rendered {len(result.images)} image(s) -> {out_dir}")
        for record in image_records:
            print(f"  {record['view']} [{record['channel']}] {record['file']}")
        print(f"  source_artifact_ref: {result.source_artifact_ref}")
    return 0


def _cmd_goldens(args: argparse.Namespace) -> int:
    from hephaestus.core.render.goldens import DEFAULT_GOLDEN_DIR, DirtyTreeError, update_goldens

    if not bool(args.update):
        print("heph goldens: nothing to do (pass --update to regenerate)", file=sys.stderr)
        return 2
    out_dir = Path(cast("str", args.dir)) if args.dir else DEFAULT_GOLDEN_DIR
    try:
        written = update_goldens(out_dir=out_dir)
    except DirtyTreeError as exc:
        print(f"heph: error (dirty_tree): {exc}", file=sys.stderr)
        return 1
    pngs = [path for path in written if path.suffix == ".png"]
    print(f"regenerated {len(pngs)} golden(s) under {out_dir}")
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``render`` and ``goldens`` verbs on an existing subparser set."""
    render = sub.add_parser("render", help="render a part's current build to PNG(s)")
    render.add_argument("part", help="part name to render")
    render.add_argument(
        "--views",
        nargs="+",
        default=["iso", "+X"],
        metavar="VIEW",
        help="named cameras or az<deg>_el<deg> (<=4)",
    )
    render.add_argument(
        "--channel", choices=["rgb", "mask", "section"], default="rgb", help="render channel"
    )
    render.add_argument(
        "--mask-mode",
        choices=["solid", "selection"],
        default="solid",
        dest="mask_mode",
        help="mask ID domain (selection requires --channel mask)",
    )
    render.add_argument(
        "--section-plane",
        default=None,
        dest="section_plane",
        metavar="PLANE",
        help="section plane [+-]AXIS@OFFSET, e.g. +Z@c or +Z@30 (requires --channel section)",
    )
    render.add_argument(
        "--explode", type=float, default=0.0, metavar="T", help="explode factor in [0, 1]"
    )
    render.add_argument(
        "--focus",
        default=None,
        metavar="LABEL_OR_TAG",
        help="center/zoom on a labeled solid or tag",
    )
    render.add_argument(
        "--last-good",
        action="store_true",
        dest="last_good",
        help="render the most recent failed build's last-good checkpoint",
    )
    render.add_argument(
        "--artifact-ref",
        default=None,
        dest="artifact_ref",
        metavar="REF",
        help="render an explicit immutable build/checkpoint artifact",
    )
    render.add_argument("--out", default="render", metavar="DIR", help="output directory for PNGs")
    render.add_argument("--json", action="store_true", help="emit the render metadata JSON")
    render.set_defaults(func=_cmd_render)

    goldens = sub.add_parser("goldens", help="regenerate golden renders (refuses on a dirty tree)")
    goldens.add_argument("--update", action="store_true", help="regenerate the golden corpus")
    goldens.add_argument(
        "--dir",
        default=None,
        metavar="DIR",
        help="golden output directory (default tests/render/goldens)",
    )
    goldens.set_defaults(func=_cmd_goldens)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point (``python -m hephaestus.core.cli_render``) for tests."""
    parser = argparse.ArgumentParser(prog="heph", description="Hephaestus render verbs")
    sub = parser.add_subparsers(dest="command", required=True)
    add_subparsers(sub)
    args = parser.parse_args(argv)
    func = cast("object", args.func)
    return cast("int", func(args))  # type: ignore[operator]


if __name__ == "__main__":
    sys.exit(main())
