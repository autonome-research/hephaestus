# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G9B: the posed-scene render and swept-envelope preview (``KINEMATICS.md`` §6).

The gate clauses of the two §6 preview bullets:

* *multi-part placement* — the joint forest's parts, placed by forward
  kinematics into ONE scene: two parts at a limit pose render differently
  than at zero. Asserted as a within-run pixel comparison plus a determinism
  twin — deliberately NO golden byte pinning, following the CI scope rule
  (`.github/workflows/ci.yml`): committed golden PNGs are pinned to an exact
  Mesa/llvmpipe build and only ``tests/render`` carries them; every stage
  suite renders live and compares against itself.
* *provenance* — the published binding document carries EVERY source artifact
  ref, the joint-set + pose-set generations, and the assignment.
* *preview-only* — no part's current build moves; the artifacts are
  content-addressed blobs and nothing else changes.
* *the explicit-assignment form* — a sweep's worst sample is not a named
  pose; rendering it goes through explicit ``{joint_id: value}`` and places
  identically to a pose that binds the same values.
* *envelope publication* — the union of the moving compound at each grid
  sample, published as a content-addressed preview labeled with its sample
  count.
* *``heph render --pose <id>``* — the human invocation, with ``--pose`` plus
  a part argument refused coherently.

Everything runs against the real published ``_g9b`` mechanism: reloaded BReps
placed by forward kinematics, rendered through the surfaceless-EGL pipeline —
the same path CI provisions for every stage suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from _g9b import assumed, open_sweep_project
from hephaestus.core.errors import AddressingError
from hephaestus.core.motion import SweepEvaluator
from hephaestus.core.project_store.kinematics import JointSet, MotionCheckSet, PoseSet
from hephaestus.core.project_store.layout import ProjectLayout
from hephaestus.core.project_store.publication import Publisher
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.render.posed import (
    POSED_RENDER_KIND,
    POSED_SCENE_KIND,
    SWEEP_ENVELOPE_BREP_KIND,
    SWEEP_ENVELOPE_KIND,
    PosedSceneError,
    PosedSceneResult,
    publish_sweep_envelope,
    render_posed_scene,
)

from opstore import OpStore

Project = tuple[ProjectLayout, OpStore]

#: The forest parts of the fixture mechanism (``unbuilt`` rides no joint).
FOREST_PARTS = ("arm", "base", "slider")


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Project:
    """The ``_g9b`` mechanism with joints, poses, and one sweep declared."""
    layout, store = open_sweep_project(tmp_path_factory.mktemp("posed-proj"))
    joints = JointSet(layout, store)
    joints.declare(
        {
            "id": "j-hinge",
            "kind": "revolute",
            "parent": "base:hinge_bore",
            "child": "arm:hinge_pin",
            "limits": {"min": -180.0, "max": 180.0},
            "provenance": {"requirement": "r-1"},
        }
    )
    joints.declare(
        {
            "id": "j-slide",
            "kind": "prismatic",
            "parent": "base:slide_face",
            "child": "slider:foot_face",
            "limits": {"min": -1.0, "max": 20.0},
            "provenance": assumed("slide travel is a fixture assumption"),
        }
    )
    poses = PoseSet(layout, store, joints)
    poses.declare({"id": "p-zero", "joints": {}, "provenance": {"requirement": "r-1"}})
    poses.declare(
        {"id": "p-swung", "joints": {"j-hinge": -90.0}, "provenance": {"requirement": "r-1"}}
    )
    checks = MotionCheckSet(layout, store, joints)
    checks.declare(
        {
            "id": "mc-env",
            "kind": "sweep_no_interference",
            "a": "arm",
            "b": "base",
            "sweep": {"j-hinge": {"from": -90.0, "to": 0.0}},
            "samples": 3,
            "provenance": {"requirement": "r-1"},
        }
    )
    return layout, store


@pytest.fixture(scope="module")
def zero_scene(project: Project) -> PosedSceneResult:
    layout, store = project
    return render_posed_scene(layout, store, pose_id="p-zero", views=("iso",))


@pytest.fixture(scope="module")
def swung_scene(project: Project) -> PosedSceneResult:
    layout, store = project
    return render_posed_scene(layout, store, pose_id="p-swung", views=("iso",))


def manifest_of(store: OpStore, scene_ref: str) -> dict[str, Any]:
    """The stored binding document a posed-scene ref names."""
    payload: dict[str, Any] = json.loads(
        store.blobs.get(blob_hash_of_ref(scene_ref)).decode("utf-8")
    )
    return payload


# ==========================================================================
# multi-part placement: a limit pose is a DIFFERENT picture than zero


class TestMultiPartPlacement:
    def test_limit_pose_renders_differently_than_zero(
        self, zero_scene: PosedSceneResult, swung_scene: PosedSceneResult
    ) -> None:
        """The arm at -90 deg moves the paddle onto the stop: the pixels move."""
        assert zero_scene.images[0].view == swung_scene.images[0].view == "iso"
        assert zero_scene.images[0].png != swung_scene.images[0].png
        assert zero_scene.scene_ref != swung_scene.scene_ref

    def test_every_forest_part_is_in_the_scene(self, zero_scene: PosedSceneResult) -> None:
        assert tuple(sorted(zero_scene.source_artifact_refs)) == FOREST_PARTS

    def test_published_kinds_are_the_posed_preview_kinds(
        self, zero_scene: PosedSceneResult
    ) -> None:
        assert zero_scene.scene_ref.startswith(f"artifact:{POSED_SCENE_KIND}:sha256:")
        for image in zero_scene.images:
            assert image.render_ref.startswith(f"artifact:{POSED_RENDER_KIND}:sha256:")

    def test_rendering_the_same_pose_is_deterministic_and_content_addressed(
        self, project: Project, zero_scene: PosedSceneResult
    ) -> None:
        layout, store = project
        again = render_posed_scene(layout, store, pose_id="p-zero", views=("iso",))
        assert again.images[0].png == zero_scene.images[0].png
        assert again.scene_ref == zero_scene.scene_ref


# ==========================================================================
# provenance: ALL source refs + both generations + the assignment


class TestProvenanceBinding:
    def test_manifest_binds_every_source_ref_generations_and_assignment(
        self, project: Project, swung_scene: PosedSceneResult
    ) -> None:
        layout, store = project
        publisher = Publisher(layout, store)
        joints = JointSet(layout, store)
        poses = PoseSet(layout, store, joints)

        manifest = manifest_of(store, swung_scene.scene_ref)
        expected_refs = {}
        for part in FOREST_PARTS:
            current = publisher.current_result(part)
            assert current is not None and current.artifact_ref is not None
            expected_refs[part] = current.artifact_ref
        assert manifest["source_artifact_refs"] == expected_refs
        assert manifest["joint_generation"] == joints.state().generation
        assert manifest["pose_generation"] == poses.state().generation
        assert manifest["pose_id"] == "p-swung"
        assert manifest["assignment"] == {"j-hinge": -90.0}
        assert [img["render_ref"] for img in manifest["images"]] == [
            image.render_ref for image in swung_scene.images
        ]
        # The typed result restates exactly the stored document's binding.
        assert swung_scene.source_artifact_refs == expected_refs
        assert swung_scene.assignment == {"j-hinge": -90.0}

    def test_source_blobs_are_gc_linked_from_the_scene(
        self, project: Project, swung_scene: PosedSceneResult
    ) -> None:
        """Pinning the scene must retain its sources and images (§3.5 rule)."""
        _, store = project
        scene_blob = blob_hash_of_ref(swung_scene.scene_ref)
        links = {target for source, target in store.gc.links() if source == scene_blob}
        for ref in swung_scene.source_artifact_refs.values():
            assert blob_hash_of_ref(ref) in links
        for image in swung_scene.images:
            assert blob_hash_of_ref(image.render_ref) in links


# ==========================================================================
# preview-only: nothing becomes current


class TestPreviewOnly:
    def test_no_current_pointer_moves(self, project: Project) -> None:
        layout, store = project
        publisher = Publisher(layout, store)
        before = {
            part: cast("Any", publisher.current_result(part)).artifact_ref for part in FOREST_PARTS
        }
        render_posed_scene(layout, store, pose_id="p-swung", views=("iso",))
        after = {
            part: cast("Any", publisher.current_result(part)).artifact_ref for part in FOREST_PARTS
        }
        assert after == before
        assert publisher.current_result("unbuilt") is None


# ==========================================================================
# the explicit-assignment form (a sweep's worst sample is not a named pose)


class TestExplicitAssignment:
    def test_worst_sample_assignment_renders_and_binds(
        self, project: Project, swung_scene: PosedSceneResult
    ) -> None:
        layout, store = project
        result = SweepEvaluator(layout, store).evaluate(["mc-env"])[0]
        assert result.verdict == "violated"  # the paddle lands on the stop at -90
        assert result.worst is not None
        assert result.worst.values == {"j-hinge": -90.0}

        scene = render_posed_scene(layout, store, assignment=result.worst.values, views=("iso",))
        assert scene.pose_id is None
        assert scene.assignment == {"j-hinge": -90.0}
        manifest = manifest_of(store, scene.scene_ref)
        assert manifest["pose_id"] is None
        assert manifest["assignment"] == {"j-hinge": -90.0}
        # Same values, same transforms, same deterministic pixels as the pose
        # that binds them — the explicit form IS the same placement machinery.
        assert scene.images[0].png == swung_scene.images[0].png

    def test_exactly_one_configuration_selector(self, project: Project) -> None:
        layout, store = project
        with pytest.raises(PosedSceneError) as both:
            render_posed_scene(
                layout, store, pose_id="p-zero", assignment={"j-hinge": 0.0}, views=("iso",)
            )
        assert both.value.reason == "invalid_render_request"
        with pytest.raises(PosedSceneError) as neither:
            render_posed_scene(layout, store, views=("iso",))
        assert neither.value.reason == "invalid_render_request"

    def test_unknown_pose_is_refused_by_name(self, project: Project) -> None:
        layout, store = project
        with pytest.raises(PosedSceneError) as excinfo:
            render_posed_scene(layout, store, pose_id="p-nope", views=("iso",))
        assert excinfo.value.reason == "unknown_pose"
        assert "p-nope" in excinfo.value.message

    def test_out_of_limits_assignment_is_refused_never_clamped(self, project: Project) -> None:
        layout, store = project
        with pytest.raises(PosedSceneError) as excinfo:
            render_posed_scene(layout, store, assignment={"j-hinge": 200.0}, views=("iso",))
        assert excinfo.value.reason == "joint_limit_exceeded"

    def test_assignment_naming_an_undeclared_joint_is_refused(self, project: Project) -> None:
        layout, store = project
        with pytest.raises(PosedSceneError) as excinfo:
            render_posed_scene(layout, store, assignment={"j-nope": 1.0}, views=("iso",))
        assert excinfo.value.reason == "unknown_joint"


# ==========================================================================
# the swept-envelope preview, labeled with its sample count


class TestSweepEnvelope:
    def test_envelope_is_published_with_its_sample_count(self, project: Project) -> None:
        layout, store = project
        envelope = publish_sweep_envelope(layout, store, "mc-env")
        assert envelope.check_id == "mc-env"
        assert envelope.samples == 3  # 3 per axis ** 1 joint — the grid total
        assert envelope.samples_per_axis == 3
        assert "3 samples" in envelope.label
        assert envelope.envelope_ref.startswith(f"artifact:{SWEEP_ENVELOPE_KIND}:sha256:")
        assert envelope.brep_ref.startswith(f"artifact:{SWEEP_ENVELOPE_BREP_KIND}:sha256:")

        manifest = manifest_of(store, envelope.envelope_ref)
        assert manifest["samples"] == 3
        assert manifest["label"] == envelope.label
        assert manifest["brep_ref"] == envelope.brep_ref
        assert manifest["sweep"] == {"j-hinge": {"from": -90.0, "to": 0.0}}
        # The moving compound is the arm (the base is the sweep's static side).
        assert sorted(manifest["source_artifact_refs"]) == ["arm"]

    def test_envelope_solid_is_the_union_over_the_samples(self, project: Project) -> None:
        """The fused solid holds the arm's swept positions: strictly more
        material than the arm alone (three paddle stations, one pin)."""
        from hephaestus.core.executor.artifact_geometry import load_brep_shape

        layout, store = project
        envelope = publish_sweep_envelope(layout, store, "mc-env")
        fused = cast("Any", load_brep_shape(store.blobs.get(blob_hash_of_ref(envelope.brep_ref))))
        publisher = Publisher(layout, store)
        arm_current = publisher.current_result("arm")
        assert arm_current is not None and arm_current.artifact_ref is not None
        arm = cast(
            "Any", load_brep_shape(store.blobs.get(blob_hash_of_ref(arm_current.artifact_ref)))
        )
        # One extra paddle station alone adds 216 mm^3; two add 432.
        assert fused.volume > arm.volume + 400.0

    def test_envelope_publication_is_preview_only(self, project: Project) -> None:
        """The §6 "as preview" half of the envelope clause: publishing the
        envelope moves no part's current build — the envelope and its binding
        document are content-addressed blobs and nothing else changes."""
        layout, store = project
        publisher = Publisher(layout, store)
        before = {
            part: cast("Any", publisher.current_result(part)).artifact_ref for part in FOREST_PARTS
        }
        publish_sweep_envelope(layout, store, "mc-env")
        after = {
            part: cast("Any", publisher.current_result(part)).artifact_ref for part in FOREST_PARTS
        }
        assert after == before
        assert publisher.current_result("unbuilt") is None

    def test_envelope_is_content_addressed(self, project: Project) -> None:
        layout, store = project
        first = publish_sweep_envelope(layout, store, "mc-env")
        second = publish_sweep_envelope(layout, store, "mc-env")
        assert second.envelope_ref == first.envelope_ref
        assert second.brep_ref == first.brep_ref

    def test_unknown_check_is_addressing_error_listing_the_declared(self, project: Project) -> None:
        layout, store = project
        with pytest.raises(AddressingError) as excinfo:
            publish_sweep_envelope(layout, store, "mc-nope")
        assert "mc-env" in excinfo.value.candidates


# ==========================================================================
# heph render --pose: the human invocation


class TestCliPose:
    def run(self, root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
        from hephaestus.core.cli import main

        monkeypatch.chdir(root)
        return main(list(argv))

    def test_pose_invocation_writes_pngs_and_names_the_scene(
        self,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Path,
    ) -> None:
        layout, _ = project
        out = tmp_path / "renders"
        code = self.run(
            layout.root,
            monkeypatch,
            "render",
            "--pose",
            "p-swung",
            "--views",
            "iso",
            "--out",
            str(out),
        )
        captured = capsys.readouterr()
        assert code == 0, captured.err
        assert (out / "pose-p-swung_iso_rgb.png").is_file()
        metadata = json.loads((out / "pose-p-swung_render.json").read_text(encoding="utf-8"))
        assert metadata["pose_id"] == "p-swung"
        assert sorted(metadata["source_artifact_refs"]) == list(FOREST_PARTS)
        assert "pose p-swung" in captured.out
        assert "scene_ref" in captured.out

    def test_pose_with_part_argument_is_refused_coherently(
        self,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, _ = project
        code = self.run(layout.root, monkeypatch, "render", "base", "--pose", "p-swung")
        captured = capsys.readouterr()
        assert code == 1
        assert "--pose" in captured.err
        assert "base" in captured.err

    def test_pose_with_single_part_flags_is_refused_by_name(
        self,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, _ = project
        code = self.run(
            layout.root, monkeypatch, "render", "--pose", "p-swung", "--channel", "mask"
        )
        captured = capsys.readouterr()
        assert code == 1
        assert "--channel" in captured.err

    def test_render_without_part_or_pose_is_refused(
        self,
        project: Project,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        layout, _ = project
        code = self.run(layout.root, monkeypatch, "render")
        captured = capsys.readouterr()
        assert code == 1
        assert "--pose" in captured.err
