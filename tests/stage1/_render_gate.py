# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""Shared helpers for the Gate G1 (Stage 1) render/selection test suite.

Every helper drives the *real* engine path: parts are built through the
executor (``UnsafeLocalBackend`` — a separate process, so determinism holds)
and published through the ordinary :class:`Publisher`, so the refs, tags,
labels, and source-build bindings a test inspects are the genuine artifacts an
agent would see. Rendering then goes through the shared render service exactly
as ``inspect_part`` / ``heph render`` use it.

These helpers cover the public clean-room ``assembly`` fixture only (Gate G1
uses no private evidence); ``assembly/primary`` is a six-solid open-frame shelf
(``bottom_deck``, ``top_deck``, four ``post`` solids) with two tagged faces
(``deck_top``, ``base_bottom``).
"""

from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path

import numpy as np
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.project_store.layout import ProjectLayout, load_project, open_store
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.goldens import sync_hc_projection
from hephaestus.core.render.inspect import RenderProject
from hephaestus.core.render.palette import rgb_to_id
from PIL import Image

from opstore import OpStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"

#: Small deterministic render size (cheap to diff; still exercises every pass).
W, H = 200, 150

#: ``assembly/primary`` solid count and provenance (see module docstring).
PRIMARY_SOLIDS = 6
PRIMARY_LABELS = {"bottom_deck", "top_deck", "post"}
PRIMARY_TAGS = {"deck_top", "base_bottom"}


def build_and_publish(
    layout: ProjectLayout,
    store: OpStore,
    part: str,
    *,
    part_overrides: dict[str, int | float | str] | None = None,
) -> str:
    """Build+publish ``part`` through the real executor/publisher; return its ref."""
    publisher = Publisher(layout, store)
    script = layout.part_path(part).read_text(encoding="utf-8")
    globals_source = layout.globals_path.read_text(encoding="utf-8")
    out_dir = layout.store_root / "b" / f"{part}-{uuid.uuid4().hex[:8]}"
    try:
        build = run_build(
            BuildRequest(
                part=part,
                script=script,
                globals_source=globals_source,
                part_overrides=part_overrides or {},
            ),
            backend=UnsafeLocalBackend(),
            out_dir=out_dir,
        )
        assert build.result.status == "ok", build.result.to_json()
        sync_hc_projection(publisher, build.worker_result.get("hc_state"))
        publisher.publish_build(build, op_id=f"op-{uuid.uuid4().hex}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    current = publisher.current_result(part)
    assert current is not None and current.artifact_ref is not None
    return current.artifact_ref


def assembly_project(root: Path) -> RenderProject:
    """Copy the ``assembly`` fixture into ``root`` and build+publish ``primary``."""
    shutil.copytree(ASSEMBLY, root, dirs_exist_ok=True)
    layout = load_project(root)
    store = open_store(layout)
    build_and_publish(layout, store, "primary")
    return RenderProject(layout=layout, store=store)


def current_artifact_ref(project: RenderProject, part: str) -> str:
    current = project.publisher().current_result(part)
    assert current is not None and current.artifact_ref is not None
    return current.artifact_ref


def blob_present(store: OpStore, ref: str) -> bool:
    return store.blobs.has(blob_hash_of_ref(ref))


def pass_png(store: OpStore, ref: str) -> bytes:
    """The raw PNG bytes of a published (pass/render/preview) artifact ref."""
    return store.blobs.get(blob_hash_of_ref(ref))


def decode_ids(png: bytes) -> set[int]:
    """Every non-background selection ID present in a palette-exact pass PNG.

    Also proves the *palette-exact non-antialiased* contract: every distinct
    non-black colour must be a valid, decodable selection ID (a blended /
    anti-aliased pixel would raise inside :func:`rgb_to_id`).
    """
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    ids: set[int] = set()
    for pixel in np.unique(arr.reshape(-1, 3), axis=0):
        triple = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        if triple != (0, 0, 0):
            ids.add(rgb_to_id(triple))
    return ids


def silhouette(png: bytes) -> int:
    """Non-background pixel count of a rendered PNG."""
    arr = np.array(Image.open(io.BytesIO(png)).convert("RGB"))
    return int((arr != 0).any(axis=2).sum())
