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
- ``heph render --pose <id> [--views ...] [--out DIR] [--json]`` renders the
  POSED SCENE (``KINEMATICS.md`` §6, Stage 9B): every joint-forest part's
  current build placed by forward kinematics at the declared pose, published
  as a preview whose provenance binds all source refs, the generations, and
  the assignment (:mod:`hephaestus.core.render.posed`). ``--pose`` and a part
  argument are mutually exclusive — a part render shows one artifact, a posed
  scene is a relative configuration of several — as are the single-part-only
  flags (``--channel``/``--mask-mode``/``--section-plane``/``--explode``/
  ``--focus``/``--last-good``/``--artifact-ref``), refused by name rather
  than silently ignored.
- ``heph goldens --update [--dir tests/render/goldens] [--fixtures-dir DIR]``
  regenerates the golden corpus; it refuses to run on a dirty git tree
  (verification.md meta-test) and, since ledger B-10, refuses by name when
  there is no fixture corpus to render — the corpus is repository content, so
  the verb runs inside a Hephaestus checkout unless ``--fixtures-dir`` points
  it at a fork's own corpus of the same shape.

Exit codes match the engine CLI: 0 success, 1 error (no build, dirty tree),
2 usage (argparse, an ``--out`` that cannot be written, golden regeneration
with no corpus). ``--out`` is validated before any view is rendered, so an
unwritable directory never costs a GL session. Render itself never rebuilds —
it reads the published current build, so a build must have run first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from hephaestus.core.cli_errors import (
    dispatch,
    ensure_writable_dir,
    guard,
    json_listing,
    project_root_or_refuse,
)
from hephaestus.core.project_store.layout import load_project, open_store
from opstore.types import JSONValue

__all__ = ["add_subparsers", "main"]


def _slug(view: str) -> str:
    return view.replace("+", "p").replace("-", "m")


def _cmd_render(args: argparse.Namespace) -> int:
    from hephaestus.core.errors import ValidationError

    part = cast("str | None", args.part)
    pose = cast("str | None", args.pose)
    views = cast("list[str]", args.views) or ["iso", "+X"]
    json_out = bool(args.json)
    # The output precondition runs before the branch, so one call covers both
    # the single-part and the posed-scene command (ledger B-10: the unguarded
    # `mkdir` was *copied* into the posed command, which is evidence on its own
    # that a shared helper is the right shape). It must CREATE rather than
    # refuse a missing path: `--out` defaults to the relative `render/`, which
    # has never had to exist beforehand. Validating here also means an
    # unwritable directory is reported before a single view is rendered —
    # today the images are produced, held in memory, and then discarded.
    out_dir = ensure_writable_dir(Path(cast("str", args.out)), flag="--out")

    if pose is not None:
        return _cmd_render_pose(args, pose, views, out_dir, json_out)
    if part is None:
        raise ValidationError("render: a part name or --pose <id> is required", kind="contract")

    # Imported here, below the precondition: pulling in the render stack
    # (trimesh/pyrender/OCP) is not free, and an unwritable --out does not need
    # it to be refused.
    from hephaestus.core.render.inspect import RenderProject, inspect_part

    root = project_root_or_refuse()
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


def _cmd_render_pose(
    args: argparse.Namespace, pose: str, views: list[str], out_dir: Path, json_out: bool
) -> int:
    """``heph render --pose <id>``: the posed-scene preview (KINEMATICS.md §6)."""
    from hephaestus.core.errors import ValidationError
    from hephaestus.core.render.posed import render_posed_scene

    if args.part is not None:
        raise ValidationError(
            f"--pose {pose!r} renders the whole posed scene; a part argument "
            f"({cast('str', args.part)!r}) is the single-part render — pass one or the other",
            kind="contract",
        )
    # The single-part flags have no posed-scene meaning yet; refused by name
    # rather than silently ignored (the §6 surface is rgb views only).
    part_only = (
        ("--channel", cast("str", args.channel) != "rgb"),
        ("--mask-mode", cast("str", args.mask_mode) != "solid"),
        ("--section-plane", args.section_plane is not None),
        ("--explode", float(cast("float", args.explode)) != 0.0),
        ("--focus", args.focus is not None),
        ("--last-good", bool(args.last_good)),
        ("--artifact-ref", args.artifact_ref is not None),
    )
    offending = [flag for flag, given in part_only if given]
    if offending:
        raise ValidationError(
            f"--pose renders the rgb posed scene; {', '.join(offending)} "
            "applies only to a single-part render",
            kind="contract",
        )

    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)
    result = render_posed_scene(layout, store, pose_id=pose, views=views)

    image_records: list[dict[str, object]] = []
    for image in result.images:
        filename = f"pose-{pose}_{_slug(image.view)}_rgb.png"
        path = out_dir / filename
        path.write_bytes(image.png)
        image_records.append(
            {
                "view": image.view,
                "channel": "rgb",
                "file": str(path),
                "render_artifact_ref": image.render_ref,
            }
        )

    metadata: dict[str, object] = dict(result.to_json())
    metadata["images"] = image_records
    metadata_path = out_dir / f"pose-{pose}_render.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if json_out:
        print(json.dumps(metadata))
    else:
        print(f"pose {pose}: rendered {len(result.images)} image(s) -> {out_dir}")
        for record in image_records:
            print(f"  {record['view']} [{record['channel']}] {record['file']}")
        print(f"  scene_ref: {result.scene_ref}")
        for part_name in sorted(result.source_artifact_refs):
            print(f"  source {part_name}: {result.source_artifact_refs[part_name]}")
    return 0


def _golden_rows(out_dir: Path) -> list[dict[str, JSONValue]]:
    """One verification row per golden image: the sidecar checked against disk.

    The three facts a golden's sidecar records are exactly the three that make a
    pinned render reproducible — the generator's own source hash, the GL
    renderer string, and the digest of the bytes — so verifying is reading them
    back rather than re-rendering. A missing golden is drift too: a spec with no
    committed image is a claim nothing backs.

    Verification stays a pure read of committed bytes: the GL renderer is probed
    for the advisory row below, and a machine with no usable software EGL simply
    does not get that row. `renderer_string()` opens a real GL context and
    raises `RenderUnavailableError`, which is a `RuntimeError` rather than a
    `HephaestusError` — letting it out would traceback a verb whose two *failing*
    checks (the digest and the generator hash) need no GL at all.
    """
    from hephaestus.core.render.goldens import (
        GOLDEN_SPECS,
        renderer_string,
        script_hash,
    )
    from hephaestus.core.render.offscreen import RenderUnavailableError

    expected_script = script_hash()
    try:
        renderer: str | None = renderer_string()
    except RenderUnavailableError:
        renderer = None
    rows: list[dict[str, JSONValue]] = []
    for spec in GOLDEN_SPECS:
        for view in spec.views:
            stem = f"{spec.name}_{_slug(view)}_{spec.channel}"
            row: dict[str, JSONValue] = {"golden": stem, "status": "ok"}
            png_path = out_dir / f"{stem}.png"
            sidecar_path = out_dir / f"{stem}.json"
            if not png_path.is_file() or not sidecar_path.is_file():
                row["status"] = "missing"
                row["detail"] = f"no committed golden at {png_path}"
                rows.append(row)
                continue
            try:
                raw: object = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                row["status"] = "unreadable"
                row["detail"] = f"{sidecar_path} is not valid JSON: {exc}"
                rows.append(row)
                continue
            if not isinstance(raw, dict):
                row["status"] = "unreadable"
                row["detail"] = f"{sidecar_path} must be a JSON object"
                rows.append(row)
                continue
            sidecar = cast("Mapping[str, object]", raw)
            digest = "sha256:" + hashlib.sha256(png_path.read_bytes()).hexdigest()
            if sidecar.get("png_sha256") != digest:
                row["status"] = "drifted"
                row["detail"] = f"{png_path.name} hashes to {digest}, sidecar says "
                row["detail"] = f"{row['detail']}{sidecar.get('png_sha256')}"
            elif sidecar.get("goldens_script_sha256") != expected_script:
                row["status"] = "stale_generator"
                row["detail"] = (
                    "recorded against a different goldens.py "
                    f"({sidecar.get('goldens_script_sha256')}, now {expected_script})"
                )
            elif renderer is not None and sidecar.get("gl_renderer") != renderer:
                # Reported, never failing: the corpus is pinned to the CI
                # container's rasterizer, so a different GL_RENDERER says this
                # machine cannot re-render these bytes — not that the committed
                # bytes are wrong. Failing here would make the verb red on every
                # developer machine, which is a gate nobody can act on.
                row["status"] = "renderer_mismatch"
                row["detail"] = (
                    f"recorded on {sidecar.get('gl_renderer')!r}, this machine is {renderer!r}: "
                    "pixels are only reproducible under the pinned render container"
                )
            rows.append(row)
    return rows


def _cmd_goldens(args: argparse.Namespace) -> int:
    from hephaestus.core.render.goldens import (
        DEFAULT_GOLDEN_DIR,
        DirtyTreeError,
        GoldenCorpusUnavailableError,
        update_goldens,
    )

    out_dir = Path(cast("str", args.dir)) if args.dir else DEFAULT_GOLDEN_DIR
    if not bool(args.update):
        # A bare verb with one useful mode refused rather than doing it, so the
        # flag added a step without adding a decision (ledger
        # J-cli-robustness-13). Verification is the read-only mode, shaped like
        # `heph registry verify`: a per-golden table, exit 1 on drift.
        rows = _golden_rows(out_dir)
        drifted = [row for row in rows if row["status"] not in ("ok", "renderer_mismatch")]
        if bool(args.json):
            print(json_listing("goldens", rows, status="error" if drifted else "ok"))
            return 1 if drifted else 0
        for row in rows:
            print(f"{row['golden']}: {row['status']}")
            detail = row.get("detail")
            if isinstance(detail, str):
                print(f"  {detail}")
        if not rows:
            print("no goldens declared")
        return 1 if drifted else 0
    fixtures_dir = cast("str | None", args.fixtures_dir)
    try:
        written = update_goldens(
            out_dir=out_dir,
            fixtures_root=Path(fixtures_dir) if fixtures_dir else None,
        )
    except DirtyTreeError as exc:
        print(f"heph: error (dirty_tree): {exc}", file=sys.stderr)
        return 1
    except GoldenCorpusUnavailableError as exc:
        # A refused capability, not a failed run: exit 2, the same code bad
        # usage gets, because regenerating goldens outside a checkout with a
        # corpus is asking for something impossible (docs/cli.md exit codes).
        print(f"heph: {exc}", file=sys.stderr)
        return 2
    pngs = [path for path in written if path.suffix == ".png"]
    print(f"regenerated {len(pngs)} golden(s) under {out_dir}")
    return 0


def add_subparsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
) -> None:
    """Register the ``render`` and ``goldens`` verbs on an existing subparser set."""
    render = sub.add_parser(
        "render", help="render a part's current build, or a posed scene, to PNG(s)"
    )
    render.add_argument(
        "part", nargs="?", default=None, help="part name to render (omit with --pose)"
    )
    render.add_argument(
        "--pose",
        default=None,
        metavar="POSE_ID",
        help="render the posed scene at a declared pose (mutually exclusive with a part)",
    )
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
    render.set_defaults(func=guard(_cmd_render))

    goldens = sub.add_parser(
        "goldens",
        help="verify the golden corpus against its sidecars (--update regenerates it)",
    )
    goldens.add_argument(
        "--update",
        action="store_true",
        help="regenerate the golden corpus (refuses on a dirty tree)",
    )
    goldens.add_argument(
        "--dir",
        default=None,
        metavar="DIR",
        help="golden output directory (default tests/render/goldens)",
    )
    goldens.add_argument("--json", action="store_true", help="emit the verification rows")
    goldens.add_argument(
        "--fixtures-dir",
        default=None,
        dest="fixtures_dir",
        metavar="DIR",
        help="fixture corpus to render (default: corpus/public_fixtures in this checkout)",
    )
    goldens.set_defaults(func=guard(_cmd_goldens))


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point (``python -m hephaestus.core.cli_render``) for tests.

    Goes through :func:`hephaestus.core.cli_errors.dispatch`, so the condition
    ``heph`` refuses in one line refuses here in the same line with the same
    exit code instead of raising a traceback — a test exercising a module
    ``main()`` observes the product's behaviour (ledger J-cli-robustness-20).
    """
    parser = argparse.ArgumentParser(prog="heph", description="Hephaestus render verbs")
    sub = parser.add_subparsers(dest="command", required=True)
    add_subparsers(sub)
    args = parser.parse_args(argv)
    return dispatch(cast("Callable[[argparse.Namespace], int]", args.func), args)


if __name__ == "__main__":
    sys.exit(main())
