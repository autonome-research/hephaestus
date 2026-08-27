# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Posed-scene rendering and swept-envelope artifacts (``KINEMATICS.md`` §6).

Two Stage 9B preview surfaces, and WHY each is new machinery rather than a
flag on an existing one:

**Posed-scene render.** Every render path before this module —
:func:`~hephaestus.core.render.inspect.inspect_part`, ``heph render <part>``
— loads exactly ONE part's artifact, and a pose is a *relative* configuration
of several: no existing surface can show "the arm at -90 deg over the base"
because no existing surface has ever placed two artifacts in one frame. §6
therefore names the posed-scene render as new engine-internal machinery.
:func:`render_posed_scene` takes the joint forest's parts' CURRENT artifact
refs, the joint-set + pose-set generations, and a parameter assignment — a
declared pose id, or explicit ``{joint_id: value}`` (a sweep's worst sample
is a fact about a check, not a named pose, so the reviewer renders it through
the explicit form) — places each part with the forward-kinematics transforms
of :mod:`hephaestus.core.motion` / :mod:`hephaestus.geom.kinematics`, and
feeds ONE scene to the existing camera/channel machinery
(:func:`~hephaestus.core.render.channels.render_channel` — this module
generalizes scene *construction* to N placed compounds and adds no render
code). The output is a PREVIEW artifact (:data:`POSED_SCENE_KIND`) whose
provenance document binds ALL source artifact refs plus the generations and
the assignment, so a reviewer can always answer "which geometry, which
declared state, which configuration is this picture of". It is exposed
through ``heph render --pose <id>`` and the reviewer context — it is NOT a
model tool and NOT a parameter on ``inspect_part`` in Stage 9 (§6 defers the
per-profile dispatch rule).

**Swept-envelope artifact.** Evaluating a sweep may additionally publish the
union of the moving compound at each grid sample
(:func:`publish_sweep_envelope`) — a visualization and packaging FACT labeled
with its sample count, never a claim about continuous motion: "does the
mechanism stay inside its enclosure" remains a ``sweep_clearance`` against
that enclosure, not a measurement of the envelope solid (§6). The union rides
build123d's fuse — the existing boolean path — and a null result raises the
:class:`~hephaestus.geom.CompareBooleanError` the comparison service coined
for exactly this OCCT failure mode: reporting a partial envelope the kernel
never computed would state a fact nobody measured. The grid is
:func:`~hephaestus.core.motion.sweep_axis_values` — the SAME samples the
check evaluates, so the label never claims samples the geometry did not
visit.

Both surfaces are preview-only by construction: they publish content-
addressed blobs and GC links, and never touch a publication pointer — nothing
here can become a part's current build (the §0 rule: a pose exists only
inside an evaluation).
"""

# build123d ships no type stubs; the reportUnknown* relaxations for this
# package are declared in root pyproject executionEnvironments, matching
# inspect.py / channels.py.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from hephaestus.core.assembly import AnchorResolver
from hephaestus.core.errors import AddressingError, ValidationError
from hephaestus.core.motion import (
    BOUND_POSE_REFUSALS,
    BoundPoseError,
    MotionResolution,
    sweep_axis_values,
)
from hephaestus.core.project_store.kinematics import (
    JointSet,
    MotionCheckEntry,
    MotionCheckSet,
    PoseSet,
)
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import artifact_ref as make_artifact_ref
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.bundle import RenderStore
from hephaestus.core.render.cameras import parse_view
from hephaestus.core.render.channels import RenderOptions, render_channel, scene_from_shape
from hephaestus.core.render.inspect import DEFAULT_VIEWS, MAX_VIEWS
from hephaestus.core.render.offscreen import DEFAULT_HEIGHT, DEFAULT_WIDTH
from opstore.types import JSONValue

from opstore import OpStore, canonical_json

if TYPE_CHECKING:
    from hephaestus.geom import RigidTransform

__all__ = [
    "POSED_RENDER_KIND",
    "POSED_SCENE_KIND",
    "POSED_SCENE_REFUSALS",
    "SWEEP_ENVELOPE_BREP_KIND",
    "SWEEP_ENVELOPE_KIND",
    "PosedImage",
    "PosedSceneError",
    "PosedSceneResult",
    "SweepEnvelope",
    "publish_sweep_envelope",
    "render_posed_scene",
]

#: Artifact kind of the posed-scene binding document — THE preview artifact of
#: §6: its provenance carries every source artifact ref, both generations, and
#: the parameter assignment.
POSED_SCENE_KIND: Final[str] = "posed-scene"

#: Artifact kind of each rendered posed-scene PNG (one per view), GC-linked to
#: its binding document in both directions on the selection-bundle precedent.
POSED_RENDER_KIND: Final[str] = "posed-render"

#: Artifact kind of the swept-envelope binding document (§6, envelope bullet)
#: — labeled with its sample count.
SWEEP_ENVELOPE_KIND: Final[str] = "sweep-envelope"

#: Artifact kind of the envelope geometry itself (lossless BRep of the union).
SWEEP_ENVELOPE_BREP_KIND: Final[str] = "sweep-envelope-brep"

#: Why a posed scene or envelope could not be produced — a closed set, on the
#: motion vocabulary wherever the fault is a motion fault (same failure, same
#: name as the §2/§4 outcomes):
#:
#: * the :data:`~hephaestus.core.motion.BOUND_POSE_REFUSALS` spellings
#:   verbatim, for the pose-id form (``unknown_pose``, ``orphaned_pose``,
#:   ``unresolvable_joint``, ``joint_limit_exceeded``, ``invalid_pose``);
#: * ``unknown_joint`` — an explicit assignment names a joint the forest does
#:   not carry (geom's own spelling; never ignored);
#: * ``no_current_build`` — a forest part has no published build to place;
#: * ``no_joints`` — the project declares no active joints, so there is no
#:   forest to pose (a single part is the existing ``heph render <part>``);
#: * ``orphaned_sweep`` / ``invalid_motion_check`` — the envelope twin of the
#:   §4 sweep reasons (a swept joint withdrawn or never declared; a check
#:   with no moving compound, or one that is withdrawn);
#: * ``invalid_render_request`` — the request itself is malformed (both or
#:   neither of pose id and explicit assignment, out-of-bounds views).
POSED_SCENE_REFUSALS: Final[tuple[str, ...]] = (
    *BOUND_POSE_REFUSALS,
    "unknown_joint",
    "no_current_build",
    "no_joints",
    "orphaned_sweep",
    "invalid_motion_check",
    "invalid_render_request",
)


class PosedSceneError(ValidationError):
    """A posed scene or envelope cannot be produced — a NAMED reason plus detail.

    ``reason`` is one of :data:`POSED_SCENE_REFUSALS`; nothing in this module
    ever guesses a placement, substitutes a frame, or renders a scene the
    declared state cannot honestly place.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message, kind="contract")
        self.reason: str = reason


# --------------------------------------------------------------------------
# results


@dataclass(frozen=True)
class PosedImage:
    """One rendered posed-scene view: its published ref and PNG bytes."""

    view: str
    render_ref: str
    png: bytes

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "view": self.view,
            "render_artifact_ref": self.render_ref,
            "size_bytes": len(self.png),
        }


@dataclass(frozen=True)
class PosedSceneResult:
    """A published posed-scene preview: the §6 binding restated, typed.

    ``scene_ref`` names the binding document (:data:`POSED_SCENE_KIND`) whose
    stored JSON carries exactly what this record restates: every source
    artifact ref, the joint-set and pose-set generations, and the assignment
    (with ``pose_id`` when the assignment came from a declared pose).
    """

    scene_ref: str
    pose_id: str | None
    assignment: Mapping[str, float]
    joint_generation: int
    pose_generation: int
    source_artifact_refs: Mapping[str, str]
    images: tuple[PosedImage, ...]

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "scene_ref": self.scene_ref,
            "pose_id": self.pose_id,
            "assignment": {name: self.assignment[name] for name in sorted(self.assignment)},
            "joint_generation": self.joint_generation,
            "pose_generation": self.pose_generation,
            "source_artifact_refs": {
                part: self.source_artifact_refs[part] for part in sorted(self.source_artifact_refs)
            },
            "images": [image.to_json() for image in self.images],
        }


@dataclass(frozen=True)
class SweepEnvelope:
    """A published swept-envelope preview, labeled with its sample count (§6)."""

    envelope_ref: str
    brep_ref: str
    check_id: str
    check_kind: str
    #: The grid total actually unioned — the §6 label. Every sample of the
    #: check's declared grid, or the publication refuses; a partial union
    #: labeled with the full count would be a lie in both directions.
    samples: int
    samples_per_axis: int
    label: str
    sweep: Mapping[str, tuple[float, float]]
    source_artifact_refs: Mapping[str, str]
    joint_generation: int
    check_generation: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "envelope_ref": self.envelope_ref,
            "brep_ref": self.brep_ref,
            "check_id": self.check_id,
            "check_kind": self.check_kind,
            "samples": self.samples,
            "samples_per_axis": self.samples_per_axis,
            "label": self.label,
            "sweep": {
                joint_id: {"from": self.sweep[joint_id][0], "to": self.sweep[joint_id][1]}
                for joint_id in sorted(self.sweep)
            },
            "source_artifact_refs": {
                part: self.source_artifact_refs[part] for part in sorted(self.source_artifact_refs)
            },
            "joint_generation": self.joint_generation,
            "check_generation": self.check_generation,
        }


# --------------------------------------------------------------------------
# shared plumbing


def _current_shapes(
    publisher: Publisher,
    store: OpStore,
    parts: Sequence[str],
    scratch: Path,
) -> tuple[dict[str, str], dict[str, Any]]:
    """``({part: current artifact ref}, {part: loaded shape})`` or a refusal.

    CURRENT artifacts only — the §6 input contract. A forest part without a
    current successful build is a named refusal (``no_current_build``, the §2
    spelling), never a scene quietly missing a part.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape

    refs: dict[str, str] = {}
    shapes: dict[str, Any] = {}
    for part in parts:
        current = publisher.current_result(part)
        if current is None or current.artifact_ref is None:
            raise PosedSceneError(
                f"part {part!r} has no current successful build to place "
                "(KINEMATICS.md §2: posed evaluation reads CURRENT artifacts)",
                reason="no_current_build",
            )
        refs[part] = current.artifact_ref
        data = store.blobs.get(blob_hash_of_ref(current.artifact_ref))
        shapes[part] = load_brep_shape(data, scratch_dir=scratch)
    return refs, shapes


def _resolution(
    layout: ProjectLayout, store: OpStore, publisher: Publisher, scratch: Path
) -> MotionResolution:
    """One consistent read of the joint and pose sets, resolved over ``scratch``."""
    joints = JointSet(layout, store)
    poses = PoseSet(layout, store, joints)
    resolver = AnchorResolver(layout, store, publisher, scratch)
    return MotionResolution(joints.state(), poses.state(), resolver)


# --------------------------------------------------------------------------
# the posed-scene render (§6, second bullet)


def render_posed_scene(
    layout: ProjectLayout,
    store: OpStore,
    *,
    pose_id: str | None = None,
    assignment: Mapping[str, float] | None = None,
    views: Sequence[str] = DEFAULT_VIEWS,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    scratch: Path | None = None,
) -> PosedSceneResult:
    """Render the joint forest's parts placed at one configuration (§6).

    Exactly one of ``pose_id`` (a declared pose — the ``heph render --pose``
    form) and ``assignment`` (explicit ``{joint_id: value}`` — the form the
    reviewer wiring uses for a sweep's worst sample, which is not a named
    pose) selects the configuration. Every part of the forest is placed by
    its forward-kinematics transform — static forest roots at identity — into
    ONE scene rendered through the existing ``rgb`` channel machinery, and
    the result is published as a preview: per-view PNGs plus a binding
    document whose provenance carries all source artifact refs, both
    generations, and the assignment. Raises :class:`PosedSceneError` (reasons
    in :data:`POSED_SCENE_REFUSALS`) whenever the declared state cannot
    honestly place the scene — never a guessed frame, never a partial scene.
    """
    if (pose_id is None) == (assignment is None):
        raise PosedSceneError(
            "exactly one of pose_id and assignment selects the configuration "
            "(KINEMATICS.md §6: a pose id, or explicit values)",
            reason="invalid_render_request",
        )
    if not views or len(views) > MAX_VIEWS:
        raise PosedSceneError(
            f"views must name between 1 and {MAX_VIEWS} cameras, got {len(views)}",
            reason="invalid_render_request",
        )
    resolved_views = tuple(dict.fromkeys(views))
    for view in resolved_views:
        parse_view(view)  # rejects unknown names with candidates/grammar

    publisher = Publisher(layout, store)
    if scratch is not None:
        return _render_in(
            layout, store, publisher, pose_id, assignment, resolved_views, width, height, scratch
        )
    layout.store_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heph-posed-", dir=layout.store_root) as tmp:
        return _render_in(
            layout, store, publisher, pose_id, assignment, resolved_views, width, height, Path(tmp)
        )


def _render_in(
    layout: ProjectLayout,
    store: OpStore,
    publisher: Publisher,
    pose_id: str | None,
    assignment: Mapping[str, float] | None,
    views: tuple[str, ...],
    width: int,
    height: int,
    scratch: Path,
) -> PosedSceneResult:
    resolution = _resolution(layout, store, publisher, scratch)
    parts = resolution.joint_state.parts
    if not parts:
        raise PosedSceneError(
            "no active joints are declared, so there is no forest to pose "
            "(a single part renders through `heph render <part>`)",
            reason="no_joints",
        )
    transforms, bound = _placements(resolution, pose_id, assignment, parts)
    refs, shapes = _current_shapes(publisher, store, parts, scratch)

    # ONE scene of N placed compounds, each labeled with its part name so the
    # existing per-solid attribution (and any mask legend) names the part.
    from build123d import Compound

    placed: list[Any] = []
    for part in parts:  # already lexically sorted (JointState.parts)
        moved = _transformed(shapes[part], transforms[part])
        moved.label = part
        placed.append(moved)
    scene = scene_from_shape(Compound(children=placed))
    rendered = render_channel(scene, list(views), "rgb", RenderOptions(width=width, height=height))

    render_store = RenderStore(store)
    images: list[PosedImage] = []
    for view in views:
        png = rendered[view].png()
        artifact = render_store.publish_render(png, kind=POSED_RENDER_KIND)
        images.append(PosedImage(view=view, render_ref=artifact.ref, png=png))

    # The binding document — the §6 preview artifact: provenance carries ALL
    # source refs plus the generations and the assignment.
    document: dict[str, JSONValue] = {
        "kind": "posed_scene",
        "version": 1,
        "pose_id": pose_id,
        "assignment": {name: bound[name] for name in sorted(bound)},
        "joint_generation": resolution.joint_state.generation,
        "pose_generation": resolution.pose_state.generation,
        "source_artifact_refs": {part: refs[part] for part in sorted(refs)},
        "images": [{"view": image.view, "render_ref": image.render_ref} for image in images],
    }
    scene_blob = store.blobs.put(canonical_json(document).encode("utf-8"))
    scene_ref = make_artifact_ref(POSED_SCENE_KIND, scene_blob)
    # GC transitivity on the selection-bundle precedent: pinning the scene
    # keeps its images and sources; pinning an image keeps its scene.
    image_blobs = [blob_hash_of_ref(image.render_ref) for image in images]
    for target in (*image_blobs, *(blob_hash_of_ref(ref) for ref in refs.values())):
        store.gc.link(scene_blob, target)
    for image_blob in image_blobs:
        store.gc.link(image_blob, scene_blob)

    return PosedSceneResult(
        scene_ref=scene_ref,
        pose_id=pose_id,
        assignment=dict(bound),
        joint_generation=resolution.joint_state.generation,
        pose_generation=resolution.pose_state.generation,
        source_artifact_refs=refs,
        images=tuple(images),
    )


def _placements(
    resolution: MotionResolution,
    pose_id: str | None,
    assignment: Mapping[str, float] | None,
    parts: Sequence[str],
) -> tuple[dict[str, RigidTransform], dict[str, float]]:
    """``({part: world transform}, bound values)`` for one configuration.

    The pose form rides :meth:`MotionResolution.transforms` verbatim (every
    forest joint is on some requested part's chain, so every §2/§3 refusal
    surfaces with its own name). The explicit form requires every active
    joint resolved — an unresolvable joint would place its child part at a
    frame nobody agreed on — then evaluates forward kinematics directly, with
    geom's own refusals (``joint_limit_exceeded``, ``unknown_joint``) passed
    through by name, never clamped and never ignored.
    """
    from hephaestus.geom import (
        IDENTITY_TRANSFORM,
        JointDeclarationError,
        JointLimitError,
        forward_kinematics,
    )

    if pose_id is not None:
        try:
            transforms = resolution.transforms(pose_id, parts)
        except BoundPoseError as exc:
            raise PosedSceneError(exc.detail, reason=exc.reason) from exc
        pose = resolution.pose_state.by_id[pose_id]  # transforms() proved it active
        return transforms, dict(pose.joints)

    values = dict(assignment or {})
    for entry in resolution.joint_state.active:
        failure = resolution.joint_failure(entry.id)
        if failure is not None:
            raise PosedSceneError(
                f"joint {entry.id!r} is unresolvable ({failure[0]}): {failure[1]}",
                reason="unresolvable_joint",
            )
    frames = tuple(resolution.frame(entry.id) for entry in resolution.joint_state.active)
    try:
        world = forward_kinematics(frames, values)
    except JointLimitError as exc:
        raise PosedSceneError(exc.message, reason="joint_limit_exceeded") from exc
    except JointDeclarationError as exc:
        reason = "unknown_joint" if exc.reason == "unknown_joint" else "invalid_pose"
        raise PosedSceneError(exc.message, reason=reason) from exc
    return {part: world.get(part, IDENTITY_TRANSFORM) for part in parts}, values


def _transformed(shape: Any, transform: RigidTransform) -> Any:
    from hephaestus.geom import transformed_shape

    return transformed_shape(shape, transform)


# --------------------------------------------------------------------------
# the swept-envelope artifact (§6, third bullet)


def publish_sweep_envelope(
    layout: ProjectLayout,
    store: OpStore,
    check_id: str,
    *,
    scratch: Path | None = None,
) -> SweepEnvelope:
    """Publish the union of one sweep's moving compound at each sample (§6).

    The moving compound is every anchored part of the check whose parent
    chain rides a swept joint, placed by forward kinematics at EXACTLY the
    grid samples the check evaluates
    (:func:`~hephaestus.core.motion.sweep_axis_values`) and fused through the
    existing boolean path — a null fuse raises
    :class:`~hephaestus.geom.CompareBooleanError`, never a partial solid. The
    result is a content-addressed preview: the envelope BRep plus a binding
    document labeled with its sample count. A packaging and visualization
    fact only — measuring against an enclosure stays a ``sweep_clearance``.
    """
    publisher = Publisher(layout, store)
    if scratch is not None:
        return _envelope_in(layout, store, publisher, check_id, scratch)
    layout.store_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heph-envelope-", dir=layout.store_root) as tmp:
        return _envelope_in(layout, store, publisher, check_id, Path(tmp))


def _envelope_in(
    layout: ProjectLayout,
    store: OpStore,
    publisher: Publisher,
    check_id: str,
    scratch: Path,
) -> SweepEnvelope:
    from hephaestus.core.executor.artifact_geometry import write_brep_shape
    from hephaestus.geom import (
        IDENTITY_TRANSFORM,
        JointDeclarationError,
        JointLimitError,
        forward_kinematics,
    )

    joints = JointSet(layout, store)
    check_state = MotionCheckSet(layout, store, joints).state()
    entry = check_state.by_id.get(check_id)
    if entry is None:
        raise AddressingError(
            f"no motion check {check_id!r} declared",
            selector=check_id,
            candidates=tuple(sorted(check_state.by_id)),
        )
    if entry.withdrawn:
        raise PosedSceneError(
            f"motion check {check_id!r} is withdrawn ({entry.withdrawn_reason}); "
            "a withdrawn check is never evaluated, so it has no envelope",
            reason="invalid_motion_check",
        )
    resolution = _resolution(layout, store, publisher, scratch)
    frames = _swept_frames(entry, resolution)
    moving = _moving_parts(entry, resolution, frames)
    refs, shapes = _current_shapes(publisher, store, moving, scratch)

    axes = [
        (joint_id, sweep_axis_values(rng.start, rng.stop, entry.samples))
        for joint_id, rng in sorted(entry.sweep.items())
    ]
    frame_tuple = tuple(frames.values())
    envelope: Any = None
    for combo in product(*[values for _, values in axes]):
        sample = {joint_id: value for (joint_id, _), value in zip(axes, combo, strict=True)}
        try:
            world = forward_kinematics(frame_tuple, cast("Any", sample))
        except JointLimitError as exc:
            raise PosedSceneError(exc.message, reason="joint_limit_exceeded") from exc
        except JointDeclarationError as exc:
            raise PosedSceneError(exc.message, reason="invalid_motion_check") from exc
        for part in moving:
            placed = _transformed(shapes[part], world.get(part, IDENTITY_TRANSFORM))
            envelope = placed if envelope is None else _fused(envelope, placed)

    brep_path = scratch / f"envelope-{entry.id}.brep"
    write_brep_shape(envelope, brep_path)
    brep_blob = store.blobs.put(brep_path.read_bytes())
    brep_ref = make_artifact_ref(SWEEP_ENVELOPE_BREP_KIND, brep_blob)

    grid_total = entry.grid_total
    label = f"swept envelope of {entry.id} at {grid_total} samples"
    document: dict[str, JSONValue] = {
        "kind": "sweep_envelope",
        "version": 1,
        "check_id": entry.id,
        "check_kind": entry.kind,
        "samples": grid_total,
        "samples_per_axis": entry.samples,
        "label": label,
        "sweep": {
            joint_id: {"from": rng.start, "to": rng.stop}
            for joint_id, rng in sorted(entry.sweep.items())
        },
        "brep_ref": brep_ref,
        "source_artifact_refs": {part: refs[part] for part in sorted(refs)},
        "joint_generation": resolution.joint_state.generation,
        "check_generation": check_state.generation,
    }
    envelope_blob = store.blobs.put(canonical_json(document).encode("utf-8"))
    envelope_ref = make_artifact_ref(SWEEP_ENVELOPE_KIND, envelope_blob)
    for target in (brep_blob, *(blob_hash_of_ref(ref) for ref in refs.values())):
        store.gc.link(envelope_blob, target)
    store.gc.link(brep_blob, envelope_blob)

    return SweepEnvelope(
        envelope_ref=envelope_ref,
        brep_ref=brep_ref,
        check_id=entry.id,
        check_kind=entry.kind,
        samples=grid_total,
        samples_per_axis=entry.samples,
        label=label,
        sweep={joint_id: (rng.start, rng.stop) for joint_id, rng in entry.sweep.items()},
        source_artifact_refs=refs,
        joint_generation=resolution.joint_state.generation,
        check_generation=check_state.generation,
    )


def _swept_frames(entry: MotionCheckEntry, resolution: MotionResolution) -> dict[str, Any]:
    """The resolved frames of the check's swept joints, or the §4 refusal.

    Exactly the sweep evaluator's precedence: an orphaned or unresolvable
    SWEPT joint — the check's subject — is named before anything else, with
    the §4 reason spellings (same failure, same name).
    """
    declared = resolution.joint_state.by_id
    frames: dict[str, Any] = {}
    for joint_id in sorted(entry.sweep):
        joint = declared.get(joint_id)
        if joint is None:
            raise PosedSceneError(
                f"motion check {entry.id} sweeps joint {joint_id!r}, which is not declared",
                reason="orphaned_sweep",
            )
        if joint.withdrawn:
            raise PosedSceneError(
                f"motion check {entry.id} sweeps withdrawn joint {joint_id!r} "
                f"({joint.withdrawn_reason})",
                reason="orphaned_sweep",
            )
        failure = resolution.joint_failure(joint_id)
        if failure is not None:
            raise PosedSceneError(
                f"motion check {entry.id} sweeps joint {joint_id!r}, which is "
                f"unresolvable ({failure[0]}): {failure[1]}",
                reason="unresolvable_joint",
            )
        frames[joint_id] = resolution.frame(joint_id)
    return frames


def _moving_parts(
    entry: MotionCheckEntry, resolution: MotionResolution, frames: dict[str, Any]
) -> tuple[str, ...]:
    """The check's anchored parts that actually ride a swept joint, in order.

    Walking each anchored part's parent chain collects every chain frame into
    ``frames`` (an omitted chain joint still places the part — at zero, the
    §3 rule) and refuses a broken chain joint by name. Parts whose chain
    never meets a swept joint are static under this sweep; a check with NO
    moving part has no moving compound, which is a fact about the stored
    entry, refused rather than an empty union.
    """
    moving: list[str] = []
    for part in entry.parts:
        current = part
        rides_sweep = False
        chain: list[tuple[str, Any]] = []
        visited: set[str] = set()
        while True:
            chain_entry = resolution.parent_joint(current)
            if chain_entry is None or current in visited:
                break
            visited.add(current)
            failure = resolution.joint_failure(chain_entry.id)
            if failure is not None:
                raise PosedSceneError(
                    f"part {part!r} rides joint {chain_entry.id!r}, which is "
                    f"unresolvable ({failure[0]}): {failure[1]}",
                    reason="unresolvable_joint",
                )
            chain.append((chain_entry.id, resolution.frame(chain_entry.id)))
            if chain_entry.id in entry.sweep:
                rides_sweep = True
            current = chain_entry.anchors[0].part
        if rides_sweep:
            moving.append(part)
            for joint_id, frame in chain:
                frames.setdefault(joint_id, frame)
    if not moving:
        raise PosedSceneError(
            f"motion check {entry.id}: no anchored part rides a swept joint, so "
            "there is no moving compound to envelope",
            reason="invalid_motion_check",
        )
    return tuple(moving)


def _fused(a: Any, b: Any) -> Any:
    """``a + b`` through build123d's fuse, with the null-shape guard.

    The :class:`~hephaestus.geom.CompareBooleanError` precedent applied to
    the union: OCCT signals a failed boolean with a null ``TopoDS_Shape``
    (build123d surfaces it as ``ValueError("Null TopoDS_Shape object")``),
    and publishing a partial envelope for that would state a solid the kernel
    never computed.
    """
    from hephaestus.geom import CompareBooleanError

    try:
        return a + b
    except ValueError as exc:
        if "Null TopoDS_Shape" in str(exc):
            raise CompareBooleanError("fuse") from exc
        raise
