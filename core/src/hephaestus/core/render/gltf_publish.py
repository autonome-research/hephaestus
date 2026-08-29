# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""GLB export and publication for one build artifact ref (``INTERFACE.md`` §5.1).

``INTERFACE.md`` §19 item 12, named new work. Before this module,
:func:`hephaestus.core.render.gltf.export_gltf` had **no production caller
anywhere** — tests only — and could not have had one: its ``bundle_ref``,
``source_artifact_ref``, ``selection_table_ref`` and :class:`SelectionCatalog`
are all mandatory, and those refs exist only *after* an
``inspect_part(channel="mask", mask_mode="selection")`` has minted a bundle for
that exact build. So for a freshly built — or pinned but never inspected —
artifact, the only GLB a server could have produced was an **unlinked** one,
which §12.3 requires be rejected. The viewport's first station would have been
pickable but unresolvable: the worst possible failure, because it looks like it
works.

This module is the producer §5.1 requires instead:

> ``GET /artifacts/{ref}/gltf`` **resolves, or publishes on demand, the
> selection bundle for that exact build ref** — re-tessellating from the stored
> BREP — and publishes the GLB under the existing ``gltf`` artifact kind. It
> **never returns an unlinked GLB**; if the bundle cannot be minted the route
> refuses rather than degrading.

Three consequences that are load-bearing rather than incidental:

* **Publication under a real artifact kind is what makes §2.6's ``ETag: <ref>``
  / ``immutable`` claim honest.** The ref is content-addressed because there is
  a stored artifact behind it, not because the route says so.
* **Every publication is verified before it is published.** The bundle is
  re-resolved through :func:`~hephaestus.core.render.bundle.resolve_selection`
  against the *expected* source ref, and the GLB is re-parsed through
  :func:`~hephaestus.core.render.gltf.validate_gltf` and required to carry the
  bundle link, before a single byte enters the store. An unlinked GLB is
  therefore not merely un-served: it is never minted.
* **Nothing here is a second implementation.** Source resolution is
  :mod:`hephaestus.core.render.inspect`'s, the ID namespace is
  :func:`~hephaestus.core.render.selection.build_selection_catalog`'s, the
  bundle is :meth:`~hephaestus.core.render.bundle.RenderStore.
  publish_selection_bundle`'s, and the GLB is ``export_gltf``'s. This module
  joins them and stores the result.

**Resolution before minting, and how a prior publication is found.** Publication
records the ``gltf → bundle`` and ``gltf → source build`` GC edges, mirroring
:meth:`RenderStore.publish_selection_bundle`'s own link discipline (pinning the
GLB retains its whole provenance chain). :func:`resolve_published_gltf` walks
those edges *backwards* — every blob that links **to** the source build — and
returns the first that parses as a GLB whose ``asset.extras`` name this exact
build and whose bundle still resolves. No new pointer namespace and no new
protected GC root is introduced: a published GLB is retained exactly as long as
something pins it or its bundle, which is the same retention every other
derived render artifact has.
"""

# pygltflib / trimesh / pyrender ship no type stubs; the relaxations for this
# package are declared in root pyproject executionEnvironments (render dir).
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass

from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.artifact_geometry import load_brep_shape
from hephaestus.core.project_store.artifact_kinds import record_artifact_kind
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import (
    RenderStore,
    SelectionBundle,
    StaleSelectionError,
    resolve_selection,
)
from hephaestus.core.render.cameras import camera_framing, parse_view
from hephaestus.core.render.channels import scene_from_shape
from hephaestus.core.render.gltf import export_gltf, validate_gltf
from hephaestus.core.render.inspect import (
    RenderProject,
    RenderSource,
    build_solid_labels,
    resolve_build_artifact,
    scene_tessellation,
    tag_placements_from_source_map,
)
from hephaestus.core.render.offscreen import DEFAULT_HEIGHT, DEFAULT_WIDTH, OffscreenSession
from hephaestus.core.render.selection import (
    SelectionCatalog,
    build_selection_catalog,
    encode_png,
    render_selection_view,
)
from hephaestus.core.render.tessellate import Tessellation

from opstore import OpStore

__all__ = [
    "GLB_MAGIC",
    "GLTF_KIND",
    "GLTF_VIEW",
    "PublishedGltf",
    "publish_gltf_for_build",
    "resolve_published_gltf",
]

#: The artifact kind a published GLB is stored under. Already enumerated by
#: ``INTERFACE.md`` §2.6's byte route; this module is what finally mints one.
GLTF_KIND = "gltf"

#: The single view whose ID passes back a viewport GLB's bundle. The GLB itself
#: is view-independent (the client's camera is the client's), but a
#: :class:`~hephaestus.core.render.bundle.SelectionBundle` is per-view by
#: construction, so one canonical view is minted rather than four: the table is
#: global and identical across views, and it is the table a raycast resolves
#: through. ``iso`` because it is the default first view everywhere else.
GLTF_VIEW = "iso"

#: The 4-byte GLB container magic. Used to skip non-GLB blobs while walking GC
#: edges, before anything tries to parse one.
GLB_MAGIC = b"glTF"


@dataclass(frozen=True)
class PublishedGltf:
    """One published, **linked** GLB and the provenance it is bound to."""

    ref: str
    blob_hash: str
    data: bytes
    source_artifact_ref: str
    bundle_ref: str
    selection_table_ref: str
    mesh_count: int
    #: ``True`` when this call minted the GLB, ``False`` when it resolved one
    #: published earlier. The route reports it so a cache hit is observable
    #: rather than inferred from a stopwatch.
    minted: bool


def resolve_published_gltf(store: OpStore, source_artifact_ref: str) -> PublishedGltf | None:
    """A previously published GLB for **exactly** this build ref, or ``None``.

    Walks the ``gltf → source build`` GC edges backwards. A candidate is accepted
    only if it parses, names this exact source ref, carries a bundle ref, and
    that bundle still resolves against this source — so a GLB whose bundle has
    aged out is *not* returned and the caller mints a fresh one instead of
    serving a link that no longer resolves.

    Deterministic on the pathological tie (two byte-identical publications of the
    same build): candidates are visited in sorted blob order, exactly as
    ``bundle.py::_bundle_blob_for_pass`` resolves its own ambiguity.
    """
    source_blob = blob_hash_of_ref(source_artifact_ref)
    if not store.blobs.has(source_blob):
        return None
    candidates = sorted(source for source, target in store.gc.links() if target == source_blob)
    for blob in candidates:
        if not store.blobs.has(blob):
            continue
        data = store.blobs.get(blob)
        if data[:4] != GLB_MAGIC:
            continue
        published = _accept(store, data, blob, source_artifact_ref, minted=False)
        if published is not None:
            return published
    return None


def publish_gltf_for_build(
    project: RenderProject,
    source_artifact_ref: str,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    view: str = GLTF_VIEW,
) -> PublishedGltf:
    """Resolve or mint the published GLB for ``source_artifact_ref``.

    The whole of §5.1's route contract. Minting: resolve the ref to its stored
    BREP and (when the ref is some part's current build) its labels and tag
    placements; re-tessellate; build the one shared selection catalog; render and
    publish the selection bundle for that exact ref; export the GLB bound to it;
    verify; store.

    Raises ``validation_error`` if the ref is not a durably stored artifact, if
    the mesh count disagrees with the published build result's solid count, or if
    the minted GLB fails verification. Raises
    :class:`~hephaestus.core.render.bundle.StaleSelectionError` if the bundle it
    just published does not resolve against this build. **In no case is an
    unlinked GLB returned or stored.**
    """
    existing = resolve_published_gltf(project.store, source_artifact_ref)
    if existing is not None:
        return existing

    resolved: RenderSource = resolve_build_artifact(project, source_artifact_ref)
    shape = load_brep_shape(resolved.brep)
    scene = scene_from_shape(shape)
    tess = scene_tessellation(scene)
    _check_solid_count(resolved, len(tess.solids))

    labels = build_solid_labels(resolved.result, len(tess.solids))
    placements = tag_placements_from_source_map(resolved.source_map)
    catalog = build_selection_catalog(tess, placements=placements, labels=labels)

    bundle = _mint_bundle(
        project.store,
        resolved.source_artifact_ref,
        tess=tess,
        catalog=catalog,
        view=view,
        width=width,
        height=height,
    )
    # The link is checked before the GLB is built, not after: a bundle that does
    # not resolve against this build must never reach `export_gltf`'s
    # `bundle_ref`, because that is precisely how an unlinked GLB is born.
    resolve_selection(
        project.store,
        bundle.bundle_ref,
        expected_source_artifact_ref=resolved.source_artifact_ref,
    )

    data = export_gltf(
        shape,
        catalog,
        bundle_ref=bundle.bundle_ref,
        source_artifact_ref=resolved.source_artifact_ref,
        selection_table_ref=bundle.selection_table_ref,
        tess=tess,
        labels=labels,
        scene=scene,
    )
    validate_gltf(data, expected_solid_count=len(tess.solids))

    blob = project.store.blobs.put(data)
    bundle_blob = blob_hash_of_ref(bundle.bundle_ref)
    source_blob = blob_hash_of_ref(resolved.source_artifact_ref)
    # gltf -> bundle / source build: pinning the GLB retains everything a pick
    # resolves through. Deliberately NOT `source -> gltf`: that edge would make
    # every published GLB permanently reachable from a protected build root, a
    # retention growth this module has no mandate to introduce. Discovery uses
    # these edges in reverse (`resolve_published_gltf`).
    project.store.gc.link(blob, bundle_blob)
    project.store.gc.link(blob, source_blob)
    # §2.6's CORRECTION / §19.24: bind `gltf` to these bytes in the store, so the
    # ref this function returns is checkable rather than merely well spelled.
    record_artifact_kind(project.store, GLTF_KIND, blob)

    published = _accept(project.store, data, blob, resolved.source_artifact_ref, minted=True)
    if published is None:  # pragma: no cover - `validate_gltf` above already ran
        raise ValidationError(
            f"minted GLB for {resolved.source_artifact_ref} is not linked to its bundle",
            kind="contract",
        )
    return published


# --------------------------------------------------------------------------
# internals


def _check_solid_count(resolved: RenderSource, tessellated: int) -> None:
    """The mesh-count == solid-count invariant, checked against the *build result*.

    §5.1: "one mesh per solid (mesh count equals solid count — a G1 assertion)".
    ``export_gltf`` emits one mesh per tessellated solid, so the assertion that
    can still fail is the one between the tessellation and the published
    ``BuildResult``. It is checked here, where a mismatch can still refuse,
    rather than left to a client counting rows.
    """
    if resolved.result is None:
        return
    declared = sum(max(entry.solids, 0) for entry in resolved.result.geometries)
    if declared != tessellated:
        raise ValidationError(
            f"build result for {resolved.source_artifact_ref} declares {declared} solid(s) "
            f"but its stored BREP tessellates to {tessellated}",
            kind="contract",
        )


def _mint_bundle(
    store: OpStore,
    source_artifact_ref: str,
    *,
    tess: Tessellation,
    catalog: SelectionCatalog,
    view: str,
    width: int,
    height: int,
) -> SelectionBundle:
    """Render and publish the selection bundle for this exact build ref.

    The three ID passes are genuinely rendered — the same
    :func:`~hephaestus.core.render.selection.render_selection_view` the
    ``inspect_part`` selection path calls — because a bundle whose pass refs
    addressed fabricated bytes would resolve while lying about what it shows.
    The composite preview is skipped: it is a human-facing image the GLB route
    has no use for, and it is optional in the bundle by construction.
    """
    framing = camera_framing(*tess.bounds(), parse_view(view), width=width, height=height)
    with OffscreenSession(width, height) as session:
        arrays = render_selection_view(session, tess, catalog, framing, include_preview=False)
    return RenderStore(store).publish_selection_bundle(
        view=view,
        source_artifact_ref=source_artifact_ref,
        solid_png=encode_png(arrays.solid),
        face_png=encode_png(arrays.face),
        edge_png=encode_png(arrays.edge),
        entries=catalog.entries,
    )


def _accept(
    store: OpStore,
    data: bytes,
    blob: str,
    source_artifact_ref: str,
    *,
    minted: bool,
) -> PublishedGltf | None:
    """A :class:`PublishedGltf` iff ``data`` is a GLB **linked** to this build.

    The one gate every returned GLB passes, whether freshly minted or resolved
    from a prior publication. ``None`` means "not this build's linked GLB" — a
    parse failure, a missing or mismatched ``asset.extras``, or a bundle that no
    longer resolves against this source.
    """
    try:
        validation = validate_gltf(data)
    except ValidationError:
        return None
    if validation.source_artifact_ref != source_artifact_ref:
        return None
    bundle_ref = validation.bundle_ref
    if bundle_ref is None:
        return None
    try:
        resolution = resolve_selection(
            store, bundle_ref, expected_source_artifact_ref=source_artifact_ref
        )
    except StaleSelectionError:
        return None
    return PublishedGltf(
        ref=make_artifact_ref(GLTF_KIND, blob),
        blob_hash=blob,
        data=data,
        source_artifact_ref=source_artifact_ref,
        bundle_ref=resolution.bundle_ref,
        selection_table_ref=resolution.selection_table_ref,
        mesh_count=validation.mesh_count,
        minted=minted,
    )
