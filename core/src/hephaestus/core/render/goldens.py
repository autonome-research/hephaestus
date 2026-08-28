"""Golden render generation + provenance (verification.md Tier 2 / meta-tests).

``heph goldens --update`` regenerates the committed golden PNGs for the public
clean-room fixtures and writes a provenance sidecar next to each one (the
generating script's hash, the GL renderer string, the tessellation deflection
constants, and the image size). Goldens are valid only for a
``(container image, renderer version, hephaestus render version)`` tuple, so the
sidecar records exactly what produced the bytes.

Meta-test contract (verification.md §"Meta-tests"): regeneration happens *only*
through this path and it **refuses to run on a dirty git tree**, so a golden can
never be silently updated to mask a regression — the update and the code change
that motivated it must be committed together.

This module is a developer/CI tool: it builds the fixture parts through an
execution backend and renders them via :func:`hephaestus.core.render.inspect.inspect_part`,
so it imports the (untyped) render stack. Test suites exercise the dirty-tree
refusal and the provenance shape; full regeneration is invoked manually.
"""

# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.render.inspect import InspectResult, RenderProject, inspect_part
from hephaestus.core.render.offscreen import OffscreenSession
from hephaestus.core.render.tessellate import ANGULAR_DEFLECTION, LINEAR_DEFLECTION
from opstore.types import JSONValue

__all__ = [
    "DEFAULT_GOLDEN_DIR",
    "GOLDEN_HEIGHT",
    "GOLDEN_SPECS",
    "GOLDEN_WIDTH",
    "DirtyTreeError",
    "GoldenSpec",
    "git_is_dirty",
    "renderer_string",
    "script_hash",
    "sync_hc_projection",
    "update_goldens",
]

#: Golden render size (small, deterministic, cheap to diff).
GOLDEN_WIDTH = 480
GOLDEN_HEIGHT = 360

#: Default golden output directory (repo-relative), per the task brief.
DEFAULT_GOLDEN_DIR = Path("tests/render/goldens")


class DirtyTreeError(RuntimeError):
    """``heph goldens --update`` refused because the git tree is dirty."""


@dataclass(frozen=True)
class GoldenSpec:
    """One golden render: which fixture/part/view/channel to produce."""

    name: str
    fixture: str  # directory under corpus/public_fixtures/
    part: str
    views: tuple[str, ...] = ("iso", "+X")
    channel: str = "rgb"
    mask_mode: str = "solid"
    section_plane: str | None = None
    explode: float = 0.0
    globals_relative: bool = True  # fixture has a top-level globals.py
    extra_parts: tuple[str, ...] = field(default_factory=tuple)
    #: Render size. Defaults to the small, cheap-to-diff golden size; a golden
    #: whose consumer is a *client* that cannot choose its own size must be
    #: baselined at the size that client will receive, or the comparison is
    #: between two resamplings rather than between two renders. ``INTERFACE.md``
    #: §5.3 makes the browser a viewer of server pixels, and the section plate it
    #: fetches comes back at ``render/offscreen.py``'s defaults.
    width: int = GOLDEN_WIDTH
    height: int = GOLDEN_HEIGHT


#: The public clean-room golden set: assembly ``primary`` at iso/+X in every
#: channel (rgb/mask/section) plus an exploded variant (G1: explode differs).
GOLDEN_SPECS: tuple[GoldenSpec, ...] = (
    GoldenSpec(name="assembly_primary_rgb", fixture="assembly", part="primary", channel="rgb"),
    GoldenSpec(name="assembly_primary_mask", fixture="assembly", part="primary", channel="mask"),
    GoldenSpec(
        name="assembly_primary_section",
        fixture="assembly",
        part="primary",
        channel="section",
        section_plane="+Z@c",
    ),
    GoldenSpec(
        name="assembly_primary_explode",
        fixture="assembly",
        part="primary",
        channel="rgb",
        explode=1.0,
    ),
)


def _run_git(args: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        # git missing, or cwd does not exist: report failure (callers fail closed).
        return subprocess.CompletedProcess(
            args=["git", *args], returncode=127, stdout="", stderr=""
        )


def git_is_dirty(root: Path) -> bool:
    """True when ``git status --porcelain`` reports any change under ``root``.

    A non-repository (or unavailable git) is treated as *dirty* — fail closed,
    so regeneration never proceeds without a clean, committed baseline.
    """
    result = _run_git(["status", "--porcelain"], cwd=root)
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def script_hash() -> str:
    """``sha256:<hex>`` of this generator's own source (golden provenance)."""
    source = Path(__file__).read_bytes()
    return "sha256:" + hashlib.sha256(source).hexdigest()


def renderer_string() -> str:
    """The GL_RENDERER string of the pinned software rasterizer (llvmpipe)."""
    with OffscreenSession(16, 16) as session:
        return session.gl_renderer


def _fixtures_root(repo_root: Path) -> Path:
    return repo_root / "corpus" / "public_fixtures"


def _prepare_project(
    spec: GoldenSpec, repo_root: Path, scratch: Path, backend: ExecBackend
) -> tuple[RenderProject, str]:
    """Copy a fixture into ``scratch``, build+publish its parts, return the handle."""
    source_dir = _fixtures_root(repo_root) / spec.fixture
    project_dir = scratch / spec.fixture
    shutil.copytree(source_dir, project_dir)
    layout: ProjectLayout = load_project(project_dir)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    globals_source = (
        layout.globals_path.read_text(encoding="utf-8") if layout.globals_path.is_file() else None
    )
    for part in (spec.part, *spec.extra_parts):
        script = layout.part_path(part).read_text(encoding="utf-8")
        out_dir = layout.store_root / "builds" / f"{part}-{uuid.uuid4().hex[:12]}"
        try:
            build = run_build(
                BuildRequest(part=part, script=script, globals_source=globals_source),
                backend=backend,
                out_dir=out_dir,
            )
            sync_hc_projection(publisher, build.worker_result.get("hc_state"))
            publisher.publish_build(build, op_id=f"goldens-{uuid.uuid4().hex}")
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
    return RenderProject(layout=layout, store=store), spec.part


def sync_hc_projection(publisher: Publisher, hc_state_raw: object) -> None:
    """Persist the live ``hc`` projection so publication revalidation passes.

    Mirrors the ``heph build`` projection sync: without it, a freshly built part
    has no recorded projection, so publication revalidation reports every
    consumed ``hc`` name as missing and the build is rejected as ``raced``.
    """
    if not isinstance(hc_state_raw, dict):
        return
    from opstore import canonical_json

    hc_state = cast("dict[str, JSONValue]", hc_state_raw)
    live = publisher.projections.state().hc_state
    if canonical_json(dict(live)) != canonical_json(hc_state):
        publisher.projections.apply_hc_state(
            hc_state, reason="goldens: globals.py or project parameters"
        )


def render_golden(project: RenderProject, spec: GoldenSpec) -> InspectResult:
    """Render ``spec`` against a prepared project (all channels via inspect_part)."""
    return inspect_part(
        project,
        spec.part,
        views=spec.views,
        channel=spec.channel,
        mask_mode=spec.mask_mode,
        section_plane=spec.section_plane,
        explode=spec.explode,
        width=spec.width,
        height=spec.height,
    )


def _sidecar(
    spec: GoldenSpec, view: str, png: bytes, *, renderer: str, source_ref: str
) -> dict[str, object]:
    return {
        "golden": spec.name,
        "fixture": spec.fixture,
        "part": spec.part,
        "view": view,
        "channel": spec.channel,
        "mask_mode": spec.mask_mode,
        "section_plane": spec.section_plane,
        "explode": spec.explode,
        "width": spec.width,
        "height": spec.height,
        "linear_deflection_mm": LINEAR_DEFLECTION,
        "angular_deflection_rad": ANGULAR_DEFLECTION,
        "gl_renderer": renderer,
        "goldens_script_sha256": script_hash(),
        "source_artifact_ref": source_ref,
        "png_sha256": "sha256:" + hashlib.sha256(png).hexdigest(),
    }


def update_goldens(
    *,
    out_dir: Path = DEFAULT_GOLDEN_DIR,
    repo_root: Path | None = None,
    backend: ExecBackend | None = None,
    specs: Sequence[GoldenSpec] = GOLDEN_SPECS,
    force: bool = False,
    scratch_root: Path | None = None,
) -> list[Path]:
    """Regenerate golden PNGs + provenance sidecars; refuse on a dirty tree.

    Returns the list of written files (PNGs and sidecars). ``force`` bypasses the
    dirty-tree guard (tests/tooling only — never the ``heph goldens`` path).
    """
    root = repo_root or _git_root()
    if not force and git_is_dirty(root):
        raise DirtyTreeError(
            "refusing to regenerate goldens on a dirty git tree; commit or stash first "
            "(golden updates must be committed alongside the change that motivates them)"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    exec_backend = backend or UnsafeLocalBackend()
    renderer = renderer_string()
    written: list[Path] = []
    scratch_base = scratch_root or (root / ".heph-golden-scratch")
    scratch_base.mkdir(parents=True, exist_ok=True)
    try:
        for spec in specs:
            scratch = scratch_base / f"{spec.name}-{uuid.uuid4().hex[:8]}"
            project, _part = _prepare_project(spec, root, scratch, exec_backend)
            result = render_golden(project, spec)
            for image in result.images:
                stem = f"{spec.name}_{_slug(image.view)}_{spec.channel}"
                png_path = out_dir / f"{stem}.png"
                png_path.write_bytes(image.png)
                sidecar_path = out_dir / f"{stem}.json"
                sidecar_path.write_text(
                    json.dumps(
                        _sidecar(
                            spec,
                            image.view,
                            image.png,
                            renderer=renderer,
                            source_ref=result.source_artifact_ref,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                written.extend([png_path, sidecar_path])
    finally:
        shutil.rmtree(scratch_base, ignore_errors=True)
    return written


def _slug(view: str) -> str:
    return view.replace("+", "p").replace("-", "m")


def _git_root() -> Path:
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=Path.cwd())
    if result.returncode != 0:
        raise DirtyTreeError("not inside a git repository; cannot verify a clean tree")
    return Path(result.stdout.strip())
