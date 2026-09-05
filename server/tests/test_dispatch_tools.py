"""Per-tool dispatch coverage over a real tmp project (unsafe backend).

Every non-registry tool declared in ``schemas/tools/*.schema.json`` is exercised
here through the real :class:`~hephaestus.agent_bridge.dispatch.ToolDispatcher`
against a real opstore-backed project: a happy path plus at least one error
variant each, the digest semantics that make each tool trustworthy (all-or-nothing
parameter merges, stale-hash conflicts, generation protocols, UTF-8 cursor safety,
export invariants), and the per-family idempotency contract (replay + same-key/
different-payload mismatch).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.agent_bridge.cad_ops import EXPORT_FORMATS, CadOps
from hephaestus.agent_bridge.dispatch import DispatchError
from hephaestus.core.project_store.publication import build_bundle_pointer
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.testing.tools_fixture import (
    ORCH,
    PART_WIDGET,
    Project,
    make_project,
)
from opstore.errors import KeyPayloadMismatchError


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    p = make_project(tmp_path / "proj")
    try:
        yield p
    finally:
        p.close()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """A project whose two parts are already built (shared by read-only tools)."""
    p = make_project(tmp_path_factory.mktemp("built") / "proj")
    p.build("widget", "bracket")
    try:
        yield p
    finally:
        p.close()


# ==========================================================================
# set_params


def test_set_params_part_happy_and_replay(project: Project) -> None:
    project.build("widget")
    state = project.cad.param_state_hash("part", "widget")
    args: dict[str, Any] = {
        "values": {"width": 50.0},
        "expected_state_hash": state,
        "scope": "part",
        "name": "widget",
    }
    first = project.call("set_params", args, entry="sp")
    assert first["effective"] == {"width": 50.0}
    assert first["rejected"] == []
    assert first["state_hash"] != state
    assert first["journal_ref"].startswith("artifact:param-journal:")
    # Replay on the SAME trusted invocation returns the recorded state.
    second = project.call("set_params", args, entry="sp")
    assert second["state_hash"] == first["state_hash"]
    # The persisted override is a real build input (not a preview override).
    rebuilt = project.call("build_part", {"name": "widget"})
    assert rebuilt["status"] == "ok"
    assert rebuilt["current"] is True
    assert rebuilt["effective_params"]["width"] == 50.0


def test_set_params_same_invocation_different_payload_mismatches(project: Project) -> None:
    project.build("widget")
    state = project.cad.param_state_hash("part", "widget")
    project.call(
        "set_params",
        {"values": {"width": 50.0}, "expected_state_hash": state, "name": "widget"},
        entry="dup",
    )
    with pytest.raises(KeyPayloadMismatchError):
        project.call(
            "set_params",
            {
                "values": {"width": 60.0},
                "expected_state_hash": project.cad.param_state_hash("part", "widget"),
                "name": "widget",
            },
            entry="dup",
        )


def test_set_params_all_or_nothing_out_of_bounds(project: Project) -> None:
    project.build("widget")
    state = project.cad.param_state_hash("part", "widget")
    result = project.call(
        "set_params",
        {
            "values": {"width": 500.0},
            "expected_state_hash": state,
            "name": "widget",
        },
    )
    assert result["rejected"] == [
        {"name": "width", "reason": "out_of_bounds", "value": 500.0, "min": 10.0, "max": 80.0}
    ]
    # Nothing persisted: the state hash never moved.
    assert project.cad.param_state_hash("part", "widget") == state


def test_set_params_unknown_parameter_rejected(project: Project) -> None:
    project.build("widget")
    result = project.call(
        "set_params",
        {
            "values": {"nope": 1.0, "width": 42.0},
            "expected_state_hash": project.cad.param_state_hash("part", "widget"),
            "name": "widget",
        },
    )
    reasons = {entry["name"]: entry["reason"] for entry in result["rejected"]}
    assert reasons == {"nope": "unknown_parameter"}
    # All-or-nothing: the valid sibling was not persisted either.
    assert project.cad.params.read("part", "widget").values == {}


def test_set_params_null_clears_override(project: Project) -> None:
    project.build("widget")
    project.call(
        "set_params",
        {
            "values": {"width": 55.0},
            "expected_state_hash": project.cad.param_state_hash("part", "widget"),
            "name": "widget",
        },
    )
    assert project.cad.params.read("part", "widget").values == {"width": 55.0}
    cleared = project.call(
        "set_params",
        {
            "values": {"width": None},
            "expected_state_hash": project.cad.param_state_hash("part", "widget"),
            "name": "widget",
        },
    )
    assert cleared["rejected"] == []
    assert project.cad.params.read("part", "widget").values == {}


def test_set_params_stale_state_hash_is_a_conflict(project: Project) -> None:
    project.build("widget")
    result = project.call(
        "set_params",
        {
            "values": {"width": 44.0},
            "expected_state_hash": "sha256:" + "0" * 64,
            "name": "widget",
        },
    )
    assert "conflict" in result
    assert result["conflict"]["current_state_hash"] == project.cad.param_state_hash(
        "part", "widget"
    )
    assert project.cad.params.read("part", "widget").values == {}


def test_set_params_project_scope_marks_consumers_stale(project: Project) -> None:
    project.build("widget", "bracket")
    result = project.call(
        "set_params",
        {
            "values": {"wall": 4.0},
            "expected_state_hash": project.cad.param_state_hash("project", None),
            "scope": "project",
        },
    )
    assert result["effective"] == {"wall": 4.0}
    # Dependency tracking, not a blanket invalidation: both parts read hc.wall.
    assert sorted(result["stale_parts"]) == ["bracket", "widget"]
    rebuilt = project.call("build_part", {"name": "widget"})
    assert rebuilt["status"] == "ok"


def test_set_params_project_scope_rejects_named_part(project: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        project.call(
            "set_params",
            {
                "values": {"wall": 3.0},
                "expected_state_hash": "x",
                "scope": "project",
                "name": "widget",
            },
        )
    assert ei.value.reason == "invalid_params"


# ==========================================================================
# build_part idempotency (the publication flip is keyed by the invocation)


def test_build_part_retry_on_the_same_invocation_replays_the_publication(
    project: Project,
) -> None:
    first = project.call("build_part", {"name": "widget"}, entry="bp")
    assert first["status"] == "ok"
    second = project.call("build_part", {"name": "widget"}, entry="bp")
    assert second["artifact_ref"] == first["artifact_ref"]
    assert second["current"] is True


def test_build_part_same_invocation_different_source_mismatches(project: Project) -> None:
    read = project.call("read_part", {"name": "widget"})
    project.call("build_part", {"name": "widget"}, entry="bp2")
    project.call(
        "edit_part",
        {
            "name": "widget",
            "expected_hash": read["content_hash"],
            "old_str": "20.0",
            "new_str": "26.0",
        },
    )
    with pytest.raises(KeyPayloadMismatchError):
        project.call("build_part", {"name": "widget"}, entry="bp2")


# ==========================================================================
# measure


@pytest.mark.parametrize(
    ("kind", "units"),
    [("bbox", "mm"), ("volume", "mm^3"), ("mass", "g"), ("sealed", "bool"), ("genus", "count")],
)
def test_measure_unary_kinds(built: Project, kind: str, units: str) -> None:
    out = built.call("measure", {"kind": kind, "a": "part", "part": "widget"})
    assert out["units"] == units
    assert out["resolved_artifact_refs"]
    assert out["detail"]["kind"] == kind


def test_measure_cross_part_uses_a_coherent_snapshot(built: Project) -> None:
    out = built.call("measure", {"kind": "interference", "a": "widget/part", "b": "bracket/part"})
    assert out["units"] == "mm^3"
    assert out["value"] > 0.0  # both boxes sit on the origin
    refs = out["resolved_artifact_refs"]
    assert any(ref.startswith("artifact:project-snapshot:") for ref in refs)
    assert sorted(out["detail"]["parts"]) == ["bracket", "widget"]


def test_measure_explicit_artifact_ref(built: Project) -> None:
    current = built.call("measure", {"kind": "bbox", "a": "part", "part": "widget"})
    ref = current["resolved_artifact_refs"][0]
    pinned = built.call(
        "measure", {"kind": "bbox", "a": "part", "part": "widget", "artifact_ref": ref}
    )
    assert pinned["resolved_artifact_refs"] == [ref]
    assert pinned["value"] == current["value"]


def test_measure_arity_error_variant(built: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call("measure", {"kind": "bbox", "a": "part", "b": "other", "part": "widget"})
    assert ei.value.reason == "invalid_params"


def test_measure_incoherent_project_snapshot(project: Project) -> None:
    project.build("widget", "bracket")
    project.call(
        "set_params",
        {
            "values": {"wall": 5.0},
            "expected_state_hash": project.cad.param_state_hash("project", None),
            "scope": "project",
        },
    )
    # Both parts are now stale against the live hc projection.
    with pytest.raises(DispatchError) as ei:
        project.call("measure", {"kind": "interference", "a": "widget/part", "b": "bracket/part"})
    assert ei.value.reason == "incoherent_project_snapshot"
    assert ei.value.data["issues"]


def test_measure_addressing_error_lists_candidates(built: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call("measure", {"kind": "bbox", "a": "no_such_tag", "part": "widget"})
    assert ei.value.reason == "invalid_part"


# ==========================================================================
# run_checks


def test_run_checks_part_reexecutes_and_never_becomes_current(project: Project) -> None:
    built = project.build("widget")["widget"]
    out = project.call("run_checks", {"name": "widget"})
    assert out["status"] == "ok"
    assert out["scope"] == "part"
    assert out["checks"]["wide_enough"]["pass"] is True
    # The re-run publishes as a PREVIEW: the current pointer is untouched.
    assert project.cad.param_state_hash("part", "widget")  # store still readable
    current = project.call("measure", {"kind": "bbox", "a": "part", "part": "widget"})
    assert current["resolved_artifact_refs"] == [built["artifact_ref"]]


def test_run_checks_project_scope_reports_generation_provenance(project: Project) -> None:
    project.build("widget", "bracket")
    project.call("create_project_check", {"name": "fit", "description": "cross-part fit"})
    out = project.call("run_checks", {"scope": "project"})
    assert out["status"] == "ok"
    assert out["scope"] == "project"
    assert out["check_set_ref"].startswith("artifact:check-bundle:")
    assert out["project_snapshot_ref"].startswith("artifact:project-snapshot:")
    assert out["file_hashes"].keys() == {"fit.py"}
    assert out["checks"]["fit:placeholder"]["pass"] is True


def test_run_checks_project_fails_closed_on_invalid_generation(project: Project) -> None:
    project.build("widget", "bracket")
    # An externally imported check file that cannot even parse.
    (project.root / "checks" / "bad.py").write_text("def (:\n", encoding="utf-8")
    out = project.call("run_checks", {"scope": "project"})
    assert out["status"] == "invalid_check_generation"
    assert out["diagnostics_ref"].startswith("artifact:check-diagnostics:")
    assert "checks" not in out  # never a partial normal report


def test_run_checks_part_missing_part_errors(project: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        project.call("run_checks", {"name": "ghost"})
    assert ei.value.reason == "invalid_part"


# ==========================================================================
# inspect_part


def test_inspect_part_rgb_returns_bounded_images(built: Project) -> None:
    out = built.call("inspect_part", {"name": "widget", "views": ["iso", "+X"]})
    assert out["status"] == "ok"
    assert len(out["images"]) == 2
    assert len(out["render_artifact_refs"]) == 2
    for image in out["images"]:
        assert image["mime_type"] == "image/png"
        assert image["data"]


def test_inspect_part_mask_channel_carries_a_legend(built: Project) -> None:
    out = built.call("inspect_part", {"name": "widget", "channel": "mask", "views": ["iso"]})
    assert out["status"] == "ok"
    legend = out.get("mask_legend") or out.get("mask_legend_ref")
    assert legend, out
    assert out["mask_legend_truncated"] is False


def test_inspect_part_selection_mode_publishes_bundles(built: Project) -> None:
    out = built.call(
        "inspect_part",
        {"name": "widget", "channel": "mask", "mask_mode": "selection", "views": ["iso"]},
    )
    assert out["selection_table_ref"].startswith("artifact:")
    assert out["selection_bundles"]
    # The selection legend always pages through a ref (never only inline).
    assert out["mask_legend_ref"].startswith("artifact:mask-legend:")


def test_inspect_part_section_channel(built: Project) -> None:
    out = built.call(
        "inspect_part",
        {"name": "widget", "channel": "section", "section_plane": "+Z@mid", "views": ["iso"]},
    )
    assert out["status"] == "ok"
    assert out["images"]


def test_inspect_part_conditional_violation_is_typed(built: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call(
            "inspect_part",
            {
                "name": "widget",
                "channel": "mask",
                "mask_mode": "selection",
                "section_plane": "+Z@mid",
            },
        )
    assert ei.value.reason == "invalid_params"


# ==========================================================================
# read_artifact


def test_read_artifact_text_paging_and_cursor_progress(built: Project) -> None:
    snap = built.call("read_part", {"name": "widget"})
    ref = snap["snapshot_ref"]
    first = built.call("read_artifact", {"ref": ref, "max_bytes": 16})
    assert first["mime_type"] == "text/x-python"
    assert first["truncated"] is True
    assert first["next_offset_bytes"] == len(first["content"].encode("utf-8"))
    rest = built.call("read_artifact", {"ref": ref, "offset_bytes": first["next_offset_bytes"]})
    assert first["content"] + rest["content"] == snap["script"]
    assert rest["truncated"] is False
    assert rest["total_bytes"] == first["total_bytes"]


def test_read_artifact_rejects_a_mid_codepoint_offset(built: Project) -> None:
    payload = "héllo wörld".encode()
    blob = built.store.blobs.put(payload)
    ref = f"artifact:build-result:{blob}"
    out = built.call("read_artifact", {"ref": ref, "offset_bytes": 2})
    assert out == {
        "error": "invalid_utf8_offset",
        "offset_bytes": 2,
        "total_bytes": len(payload),
    }


def test_read_artifact_binary_returns_metadata_only(built: Project) -> None:
    measured = built.call("measure", {"kind": "bbox", "a": "part", "part": "widget"})
    out = built.call("read_artifact", {"ref": measured["resolved_artifact_refs"][0]})
    assert out["content"] == ""
    assert out["mime_type"] == "application/octet-stream"
    assert out["total_bytes"] > 0
    assert out["truncated"] is False


def test_read_artifact_unknown_ref(built: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call("read_artifact", {"ref": "artifact:build:sha256:" + "0" * 64})
    assert ei.value.reason == "invalid_ref"


# ==========================================================================
# read_globals / edit_globals


def test_edit_globals_applies_and_syncs_projections(project: Project) -> None:
    project.build("widget")
    snap = project.call("read_globals", {})
    assert snap["numbered_script"].startswith("1  PARAMS")
    assert snap["project_param_state_hash"].startswith("sha256:")
    out = project.call(
        "edit_globals",
        {
            "expected_hash": snap["content_hash"],
            "old_str": "SHELF_W = 100.0",
            "new_str": "SHELF_W = 120.0",
        },
    )
    assert out["status"] == "applied"
    assert out["content_hash"] != snap["content_hash"]
    assert out["journal_ref"].startswith("artifact:globals-journal:")
    assert "120.0" in (project.root / "globals.py").read_text(encoding="utf-8")


def test_edit_globals_retry_on_the_same_invocation_replays(project: Project) -> None:
    snap = project.call("read_globals", {})
    args: dict[str, Any] = {
        "expected_hash": snap["content_hash"],
        "old_str": "SHELF_W = 100.0",
        "new_str": "SHELF_W = 120.0",
    }
    first = project.call("edit_globals", args, entry="eg")
    assert first["status"] == "applied"
    # The opkey is claimed BEFORE the live hash is read, so a lost-response retry
    # replays `applied` instead of reporting the conflict it created itself.
    second = project.call("edit_globals", args, entry="eg")
    assert second["status"] == "applied"
    assert second["content_hash"] == first["content_hash"]
    assert second["replayed"] is True


def test_edit_globals_stale_hash_is_a_conflict(project: Project) -> None:
    out = project.call(
        "edit_globals",
        {
            "expected_hash": "sha256:" + "0" * 64,
            "old_str": "SHELF_W = 100.0",
            "new_str": "SHELF_W = 120.0",
        },
    )
    assert out["status"] == "conflict"
    assert out["kind"] == "stale_hash"
    assert "SHELF_W = 100.0" in (project.root / "globals.py").read_text(encoding="utf-8")


def test_edit_globals_syntax_error_commits_nothing(project: Project) -> None:
    snap = project.call("read_globals", {})
    out = project.call(
        "edit_globals",
        {
            "expected_hash": snap["content_hash"],
            "old_str": "SHELF_W = 100.0",
            "new_str": "SHELF_W = (",
        },
    )
    assert out["status"] == "validation_error"
    assert out["kind"] == "syntax"
    assert (project.root / "globals.py").read_text(encoding="utf-8") == snap["script"]


def test_edit_globals_invalid_overrides_when_a_live_param_disappears(project: Project) -> None:
    project.build("widget")
    project.call(
        "set_params",
        {
            "values": {"wall": 3.0},
            "expected_state_hash": project.cad.param_state_hash("project", None),
            "scope": "project",
        },
    )
    snap = project.call("read_globals", {})
    out = project.call(
        "edit_globals",
        {
            "expected_hash": snap["content_hash"],
            "old_str": '    "wall": Param(2.0, min=1.0, max=6.0),\n',
            "new_str": "",
        },
    )
    assert out["status"] == "validation_error"
    assert out["kind"] == "invalid_overrides"
    assert (project.root / "globals.py").read_text(encoding="utf-8") == snap["script"]


# ==========================================================================
# project checks


def test_project_check_lifecycle(project: Project) -> None:
    empty = project.call("list_project_checks", {})
    assert empty["status"] == "ok"
    assert empty["items"] == []
    created = project.call("create_project_check", {"name": "fit", "description": "fit check"})
    assert created["content_hash"].startswith("sha256:")
    assert "CHECKS" in created["initial_script"]
    read = project.call("read_project_check", {"name": "fit"})
    assert read["script"] == created["initial_script"]
    edited = project.call(
        "edit_project_check",
        {
            "name": "fit",
            "expected_hash": read["content_hash"],
            "old_str": '    "placeholder": lambda m: True,\n',
            "new_str": '    "sealed": lambda m: m.sealed("widget/part"),\n',
        },
    )
    assert edited["status"] == "applied"
    listed = project.call("list_project_checks", {})
    assert [item["name"] for item in listed["items"]] == ["fit"]
    assert listed["items"][0]["summary"] == "Project check: fit check"
    assert listed["items"][0]["content_hash"] == edited["content_hash"]


def test_project_check_retries_never_duplicate_a_generation(project: Project) -> None:
    """A retry resolves to a discriminated result, never a second mutation.

    The check-set generation WAL lives in ``hephaestus.core.checks.engine``, whose
    idempotency key is claimed *inside* ``write_check``; the no-replace / CAS gate
    in front of it runs first, so a retry after a committed mutation surfaces
    ``already_exists`` (create) or ``conflict(kind="stale_hash")`` (edit) rather
    than replaying ``applied``. Either way nothing is written twice and no bytes
    are discarded — the caller reconciles from the returned live hash.
    """
    project.call("create_project_check", {"name": "fit"}, entry="cpc")
    generation = project.call("list_project_checks", {})["check_set_generation"]
    with pytest.raises(DispatchError) as ei:
        project.call("create_project_check", {"name": "fit"}, entry="cpc")
    assert ei.value.reason == "already_exists"

    read = project.call("read_project_check", {"name": "fit"})
    edit: dict[str, Any] = {
        "name": "fit",
        "expected_hash": read["content_hash"],
        "old_str": '    "placeholder": lambda m: True,\n',
        "new_str": '    "sealed": lambda m: m.sealed("widget/part"),\n',
    }
    applied = project.call("edit_project_check", edit, entry="epc")
    assert applied["status"] == "applied"
    after = project.call("list_project_checks", {})["check_set_generation"]
    assert int(after) == int(generation) + 1
    retry = project.call("edit_project_check", edit, entry="epc")
    assert retry["status"] == "conflict"
    assert retry["current_hash"] == applied["content_hash"]
    # No second generation advance: the mutation did not re-run.
    assert project.call("list_project_checks", {})["check_set_generation"] == after


def test_create_project_check_is_no_replace(project: Project) -> None:
    project.call("create_project_check", {"name": "fit"})
    with pytest.raises(DispatchError) as ei:
        project.call("create_project_check", {"name": "fit"})
    assert ei.value.reason == "already_exists"


def test_edit_project_check_rejects_unparseable_candidate(project: Project) -> None:
    project.call("create_project_check", {"name": "fit"})
    read = project.call("read_project_check", {"name": "fit"})
    out = project.call(
        "edit_project_check",
        {
            "name": "fit",
            "expected_hash": read["content_hash"],
            "old_str": "CHECKS = {",
            "new_str": "CHECKS = (((",
        },
    )
    assert out["status"] == "validation_error"
    assert out["kind"] == "syntax"
    assert project.call("read_project_check", {"name": "fit"})["script"] == read["script"]


def test_edit_project_check_stale_hash_conflict(project: Project) -> None:
    project.call("create_project_check", {"name": "fit"})
    out = project.call(
        "edit_project_check",
        {
            "name": "fit",
            "expected_hash": "sha256:" + "0" * 64,
            "old_str": "CHECKS",
            "new_str": "CHECKS",
        },
    )
    assert out["status"] == "conflict"
    assert out["kind"] == "stale_hash"


def test_read_project_check_missing(project: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        project.call("read_project_check", {"name": "ghost"})
    assert ei.value.reason == "invalid_part"


def test_list_project_checks_pages_a_frozen_index(project: Project) -> None:
    for name in ("alpha", "beta", "gamma"):
        project.call("create_project_check", {"name": name})
    first = project.call("list_project_checks", {"limit": 2})
    assert [item["name"] for item in first["items"]] == ["alpha", "beta"]
    assert first["total"] == 3
    cursor = first["next_cursor"]
    # A concurrent mutation lands in a LATER generation; the cursor's frozen
    # index is unaffected.
    project.call("create_project_check", {"name": "delta"})
    second = project.call("list_project_checks", {"cursor": cursor, "limit": 2})
    assert [item["name"] for item in second["items"]] == ["gamma"]
    assert second["check_set_ref"] == first["check_set_ref"]
    assert second["total"] == 3
    assert "next_cursor" not in second


def test_list_project_checks_rejects_a_malformed_cursor(project: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        project.call("list_project_checks", {"cursor": "not-a-cursor"})
    assert ei.value.reason == "invalid_cursor"


def test_list_project_checks_invalid_generation_variant(project: Project) -> None:
    (project.root / "checks" / "bad.py").write_text("CHECKS = 5\n", encoding="utf-8")
    out = project.call("list_project_checks", {})
    assert out["status"] == "invalid_check_generation"
    assert out["diagnostics_ref"].startswith("artifact:check-diagnostics:")
    assert "items" not in out


# ==========================================================================
# export_part


def test_export_step_freezes_source_and_pins_a_gc_root(built: Project) -> None:
    out = built.call("export_part", {"name": "widget", "format": "step"}, entry="exp-step")
    rel = Path(out["paths"][0])
    assert rel.parts[:2] == (".heph", "exports")
    path = built.layout.exports_dir / rel.name
    assert path.is_file()
    assert out["source_artifact_ref"].startswith("artifact:build:")
    assert out["source_input_hashes"]["script"].startswith("sha256:")
    assert next(iter(out["export_hashes"].values())).startswith("sha256:")
    # Pinned as a GC root until explicit unpin.
    export_blob = next(iter(out["export_hashes"].values()))
    assert export_blob in built.store.gc.pins()


@pytest.mark.parametrize("fmt", sorted(EXPORT_FORMATS))
def test_export_every_stage2_format(built: Project, fmt: str) -> None:
    target = f"formats/{fmt}.{EXPORT_FORMATS[fmt]}"
    out = built.call(
        "export_part", {"name": "widget", "format": fmt, "target": target}, entry=f"fmt-{fmt}"
    )
    assert out["paths"] == [str(Path(".heph") / "exports" / target)]
    path = built.layout.exports_dir / target
    assert path.is_file()
    assert path.stat().st_size > 0


def test_export_retry_on_the_same_invocation_reconciles(built: Project) -> None:
    args = {"name": "widget", "format": "stl", "target": "retry/widget.stl"}
    first = built.call("export_part", args, entry="retry")
    second = built.call("export_part", args, entry="retry")
    assert second["paths"] == first["paths"]
    assert second["source_artifact_ref"] == first["source_artifact_ref"]
    assert second["replayed"] is True


def test_export_same_invocation_different_payload_mismatches(built: Project) -> None:
    built.call("export_part", {"name": "widget", "format": "stl", "target": "mm/a.stl"}, entry="mm")
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part", {"name": "widget", "format": "step", "target": "mm/b.step"}, entry="mm"
        )
    assert ei.value.reason == "key_payload_mismatch"


def test_export_target_is_create_only_across_operations(built: Project) -> None:
    built.call(
        "export_part", {"name": "widget", "format": "stl", "target": "once.stl"}, entry="once-a"
    )
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part", {"name": "widget", "format": "stl", "target": "once.stl"}, entry="once-b"
        )
    assert ei.value.reason == "target_exists"


def test_export_rejects_a_symlinked_parent_at_operation_time(
    built: Project, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    built.layout.exports_dir.mkdir(parents=True, exist_ok=True)
    link = built.layout.exports_dir / "escape"
    if not link.exists():
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part",
            {"name": "widget", "format": "stl", "target": "escape/widget.stl"},
            entry="escape",
        )
    assert ei.value.reason == "path_confinement"
    assert not (outside / "widget.stl").exists()


@pytest.mark.parametrize("target", ["/abs.step", "../up.step", "a/../b.step", ""])
def test_export_rejects_traversal_targets(built: Project, target: str) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part",
            {"name": "widget", "format": "step", "target": target},
            entry=f"trav-{target}",
        )
    assert ei.value.reason == "invalid_target"


def test_export_nested_sheet_nests_onto_a_declared_blank(built: Project) -> None:
    """Stage 6 implemented ``nested_sheet``; the layout is no longer deferred.

    ``widget`` declares no ``part.blank_size``, so the caller states the blank —
    and a blank nothing fits on is a structured refusal, not an overlap.
    (Profile extraction and packing are covered in ``test_nested_sheet.py``.)
    """
    result = built.call(
        "export_part",
        {
            "name": "widget",
            "format": "dxf",
            "layout": "nested_sheet",
            "blank": {"width_mm": 120.0, "height_mm": 80.0},
        },
        entry="nested",
    )
    assert len(result["paths"]) == 1
    assert str(result["paths"][0]).endswith(".dxf")
    assert result["source_artifact_ref"].startswith("artifact:build:")
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part",
            {
                "name": "widget",
                "format": "dxf",
                "layout": "nested_sheet",
                "blank": {"width_mm": 10.0, "height_mm": 10.0},
            },
            entry="nested-tiny",
        )
    assert ei.value.reason == "profile_too_large"
    assert ei.value.data["blank"]["width_mm"] == 10.0


def test_export_rejects_a_checkpoint_only_ref(built: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        built.call(
            "export_part",
            {
                "name": "widget",
                "format": "step",
                "artifact_ref": "artifact:build-checkpoint:sha256:" + "0" * 64,
            },
            entry="ckpt",
        )
    assert ei.value.reason == "invalid_source"


def test_export_refuses_a_stale_current_artifact(project: Project) -> None:
    project.build("widget")
    project.call(
        "set_params",
        {
            "values": {"wall": 5.5},
            "expected_state_hash": project.cad.param_state_hash("project", None),
            "scope": "project",
        },
    )
    with pytest.raises(DispatchError) as ei:
        project.call("export_part", {"name": "widget", "format": "step"})
    assert ei.value.reason == "stale_source"


def test_export_without_a_current_build(project: Project) -> None:
    with pytest.raises(DispatchError) as ei:
        project.call("export_part", {"name": "widget", "format": "step"})
    assert ei.value.reason == "invalid_part"


def test_export_unpin_releases_the_gc_root(built: Project) -> None:
    out = built.call(
        "export_part", {"name": "widget", "format": "stl", "target": "pinned.stl"}, entry="pin"
    )
    blob = next(iter(out["export_hashes"].values()))
    assert blob in built.store.gc.pins()
    built.cad.unpin_export(blob)
    assert blob not in built.store.gc.pins()


# ==========================================================================
# query_snapshot


class _FakeSnapshotCaller:
    """A scripted ``query.snapshot`` peer (no sidecar, no model)."""

    def __init__(self, answer: str = "the shelf is 100 mm wide") -> None:
        self.answer = answer
        self.requests: list[Any] = []

    async def call(self, request: Any) -> Any:
        from hephaestus.agent_bridge.query_snapshot import SnapshotResult, SnapshotUsage

        self.requests.append(request)
        return SnapshotResult(
            text=self.answer,
            refs=request.image_refs,
            usage=SnapshotUsage(output_tokens=12, turns=1),
        )


def test_query_snapshot_without_a_provider_is_a_capability_result(built: Project) -> None:
    out = built.call("query_snapshot", {"name": "widget", "question": "how wide?"})
    assert out == {
        "status": "capability_error",
        "code": "capability_not_available",
        "message": "no multimodal snapshot provider is configured for this runtime",
    }


def test_query_snapshot_runs_the_ephemeral_child(tmp_path: Path) -> None:
    caller = _FakeSnapshotCaller()
    p = make_project(tmp_path / "qs", snapshot_caller=caller)
    try:
        p.build("widget")
        out = p.call("query_snapshot", {"name": "widget", "question": "how wide?"})
        assert out["status"] == "ok"
        assert out["answer"] == caller.answer
        # Text + artifact refs only: no image blocks reach the parent result.
        assert out["render_artifacts"]
        assert "images" not in out
        assert out["usage"]["output_tokens"] == 12
        request = caller.requests[0]
        assert request.max_turns == 1
        assert request.max_output_tokens == 1024
        assert request.timeout_s == 60.0
    finally:
        p.close()


def test_query_snapshot_question_over_the_prompt_cap(tmp_path: Path) -> None:
    p = make_project(tmp_path / "qs2", snapshot_caller=_FakeSnapshotCaller())
    try:
        p.build("widget")
        with pytest.raises(DispatchError) as ei:
            p.call("query_snapshot", {"name": "widget", "question": "x" * 40_000})
        assert ei.value.reason == "prompt_too_large"
    finally:
        p.close()


# ==========================================================================
# cross-cutting: the CadOps seam is optional


def test_tools_report_not_implemented_without_the_cad_core(tmp_path: Path) -> None:
    from hephaestus.agent_bridge.dispatch import CAD_TOOLS, ToolDispatcher
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.store import ProjectStore
    from hephaestus.testing.tools_fixture import scaffold

    root = scaffold(tmp_path / "bare")
    layout = load_project(root)
    store = open_store(layout)
    try:
        dispatcher = ToolDispatcher(ProjectStore(layout, store))
        for tool in sorted(CAD_TOOLS):
            with pytest.raises(DispatchError) as ei:
                dispatcher.dispatch(
                    ORCH,
                    {
                        "session_id": "orch",
                        "run_id": "r",
                        "tool": tool,
                        "arguments": _minimal_args(tool),
                        "invocation": {"entry_id": "e", "ordinal": 1, "provider_call_id": "c"},
                    },
                )
            assert ei.value.reason == "not_implemented", tool
    finally:
        store.close()


def _minimal_args(tool: str) -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {
        "build_part": {"name": "widget"},
        "inspect_part": {"name": "widget"},
        "set_params": {"values": {}, "expected_state_hash": "x", "name": "widget"},
        "edit_globals": {"expected_hash": "x", "old_str": "a", "new_str": "b"},
        "list_project_checks": {},
        "create_project_check": {"name": "fit"},
        "read_project_check": {"name": "fit"},
        "edit_project_check": {
            "name": "fit",
            "expected_hash": "x",
            "old_str": "a",
            "new_str": "b",
        },
        "measure": {"kind": "bbox", "a": "part", "part": "widget"},
        # COMPARE.md §2 — read-only, and equally unreachable without CadOps.
        "compare_solids": {"part": "widget", "target": "part:widget"},
        # MESH_INGEST.md §7.2 — the scan half, same terms. ``units`` is required
        # by the schema (§1.3: a scan carries none), so it is in the minimum.
        "compare_to_scan": {"part": "widget", "scan": "limb.stl", "units": "mm"},
        # ASSEMBLY.md §3 — the constraint quartet needs the engine just as much.
        "declare_constraint": {
            "id": "c-fit",
            "kind": "clearance_min",
            "a": "widget",
            "b": "widget",
            "value_mm": 0.2,
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "update_constraint": {"id": "c-fit", "patch": {"value_mm": 0.3}, "reason": "fixture"},
        "read_constraints": {},
        "check_assembly": {},
        # KINEMATICS.md Stage 9A (§6) — the kinematics tools need the engine
        # just as much.
        "declare_joint": {
            "id": "j-mount",
            "kind": "fixed",
            "parent": "widget",
            "child": "bracket",
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "update_joint": {"id": "j-mount", "patch": {"note": "n"}, "reason": "fixture"},
        "read_joints": {},
        "declare_pose": {
            "id": "p-zero",
            "joints": {},
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "update_pose": {"id": "p-zero", "patch": {"note": "n"}, "reason": "fixture"},
        "read_poses": {},
        "declare_motion_check": {
            "id": "mc-air",
            "kind": "sweep_clearance",
            "a": "widget",
            "b": "bracket",
            "min_mm": 0.2,
            "sweep": {"j-mount": {"from": 0.0, "to": 1.0}},
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "update_motion_check": {
            "id": "mc-air",
            "patch": {"note": "n"},
            "reason": "fixture",
        },
        "read_motion_checks": {},
        "check_motion": {},
        # KINEMATICS.md Stage 9C (§5/§6) — the coupling triplet, same rule.
        "declare_coupling": {
            "id": "cp-drive",
            "parent": "j-motor",
            "child": "j-wrist",
            "ratio": 0.2,
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "update_coupling": {"id": "cp-drive", "patch": {"note": "n"}, "reason": "fixture"},
        "read_couplings": {},
        # SOLVER.md §11 (Stage 13A) — the pose solver is equally unreachable
        # without CadOps: it measures against published artifacts, and writes
        # nothing at all either way.
        "solve_pose": {
            "targets": [{"form": "constraint", "constraint_id": "c-mount"}],
            "tol": 0.001,
            "weighting": "unit_scaled_v1",
            "regularization": "min_norm_from_start",
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        # SOLVER.md §11 (Stage 13B) — the placement proposer and the proposal
        # reader, unreachable for the same reason: both speak about published
        # artifacts, and neither applies anything either way.
        "propose_placement": {
            "space": "transform",
            "constraints": ["c-mount"],
            "free": ["widget"],
            "tol": 0.001,
            "weighting": "unit_scaled_v1",
            "regularization": "min_norm_from_start",
            "provenance": {"assumed": True, "reason": "fixture"},
        },
        "read_proposals": {},
        "run_checks": {"name": "widget"},
        "record_requirements": {
            "entries": [
                {
                    "id": "R1",
                    "text": "t",
                    "source": "assumed",
                    "rationale": "r",
                    "material": False,
                }
            ]
        },
        "read_requirements": {},
        "update_requirement": {"id": "R1", "value": 1.0},
        "read_artifact": {"ref": "artifact:build:sha256:" + "0" * 64},
        # INGEST.md §2 — read-only, and equally unreachable without CadOps.
        "list_references": {},
        "read_reference": {"name": "sheet.pdf"},
        "export_part": {"name": "widget", "format": "step"},
        "query_snapshot": {"name": "widget", "question": "?"},
        "run_dfm": {"name": "widget"},
        "generate_drawing": {"name": "widget", "kind": "dimensioned"},
        "generate_doc": {"name": "widget", "kind": "bom"},
    }
    return table[tool]


def test_part_session_scope_holds_for_every_newly_wired_tool(built: Project) -> None:
    """A bound part session cannot reach another part through any wired tool."""
    denials: list[tuple[str, dict[str, Any]]] = [
        ("build_part", {"name": "bracket"}),
        ("inspect_part", {"name": "bracket"}),
        ("measure", {"kind": "bbox", "a": "bracket/part"}),
        ("measure", {"kind": "interference", "a": "part", "b": "bracket/part"}),
        ("run_checks", {"name": "bracket"}),
        ("export_part", {"name": "bracket", "format": "step"}),
        ("query_snapshot", {"name": "bracket", "question": "?"}),
        ("run_dfm", {"name": "bracket"}),
        ("generate_drawing", {"name": "bracket", "kind": "dimensioned"}),
        ("generate_doc", {"name": "bracket", "kind": "bom"}),
        ("set_params", {"values": {}, "expected_state_hash": "x", "name": "bracket"}),
        ("run_checks", {"scope": "project"}),
        ("set_params", {"values": {}, "expected_state_hash": "x", "scope": "project"}),
    ]
    for tool, args in denials:
        with pytest.raises(DispatchError) as ei:
            built.call(tool, args, principal=PART_WIDGET)
        assert ei.value.reason == "scope_denied", (tool, args)


def test_cad_ops_param_state_hash_is_stable_for_an_unset_scope(tmp_path: Path) -> None:
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.testing.tools_fixture import scaffold

    root = scaffold(tmp_path / "hashes")
    layout = load_project(root)
    store = open_store(layout)
    try:
        cad = CadOps(layout, store)
        a = cad.param_state_hash("part", "widget")
        b = cad.param_state_hash("part", "bracket")
        assert a == b  # both empty documents hash identically
        assert json.loads(json.dumps(a)) == a
    finally:
        store.close()


# ==========================================================================
# section 7 addressing through the measure tool (audit-2026-09-04 B-1)
#
# A published artifact is BRep bytes: labels, tags and bindings live only in
# the worker that built the shape, and what makes a reloaded artifact
# addressable is what publication recorded beside it. Until 2026-09-04
# ``measure``, ``heph check`` and project-scope ``run_checks`` built that index
# EMPTY, so the literal ``"part"`` selector was the only one they could answer
# -- while the identical tag and label resolved inside the same part's own
# ``CHECKS`` during the build, and while constraint anchors resolved them
# against the very same artifact. The refusal came out as "resolves to nothing"
# with no candidates, which reads as a typo in the selector rather than as a
# hole in the tool, and that is how it stayed hidden for fourteen months.
#
# These pin the join at the tool boundary, which is where a model meets it:
# the parity with the in-worker value, the candidates a refusal must offer (and
# the one name it must never offer), and the single namespace the tool honestly
# cannot supply.

#: A tag, a label, and a binding (``body``) that is section 7 rule 4 -- the one
#: rule a published artifact cannot answer, since publication records label
#: runs and tag placements and no binding-to-solid mapping. Each check makes
#: exactly ONE measurement, so its recorded ``measured`` value IS the bbox the
#: worker saw for that selector.
ADDRESSABLE_PLATE_SRC = """PARAMS = {}

body = Box(40.0, 20.0, 6.0)
body.label = "wb"
tag(body.faces().sort_by(Axis.Z)[-1], "top_face")
part.geometry = body

CHECKS = {
    "bbox_part": lambda m: m.bbox("part")[0] > 0.0,
    "bbox_wb": lambda m: m.bbox("wb")[0] > 0.0,
    "bbox_top_face": lambda m: m.bbox("top_face")[0] > 0.0,
}
"""

ADDRESSABLE_PIN_SRC = """PARAMS = {}

shank = Box(4.0, 4.0, 30.0)
shank.label = "pin_shank"
part.geometry = shank
"""

#: The silent-red half of B-1: a project check addressing another part's label
#: and tag. Every one of these read as a failing check (or an errored one)
#: while the parent-side index was empty.
CROSS_PART_CHECK_SRC = """# Project check: cross-part label and tag selectors.

CHECKS = {
    "label": lambda m: m.bbox("plate/wb")[2] > 5.9,
    "tag": lambda m: m.bbox("plate/top_face")[2] < 0.001,
    "clearance": lambda m: m.clearance("plate/top_face", "pin/part") < 0.001,
}
"""

#: ``"bbox_<selector>"`` -> the selector, one per section 7 rule the parent side
#: can answer: rule 1 (``part``), rule 3 (a label), rule 2 (a tag).
ADDRESSABLE_SELECTORS: dict[str, str] = {
    "bbox_part": "part",
    "bbox_wb": "wb",
    "bbox_top_face": "top_face",
}


@pytest.fixture(scope="module")
def addressable(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Project]:
    """A built project whose parts carry a tag, a label and a rule-4 binding."""
    p = make_project(tmp_path_factory.mktemp("addressable") / "proj")
    (p.root / "parts" / "plate.py").write_text(ADDRESSABLE_PLATE_SRC, encoding="utf-8")
    (p.root / "parts" / "pin.py").write_text(ADDRESSABLE_PIN_SRC, encoding="utf-8")
    (p.root / "checks" / "cross.py").write_text(CROSS_PART_CHECK_SRC, encoding="utf-8")
    # Every part must be current for the project-scope snapshot to assemble.
    p.build("widget", "bracket", "plate", "pin")
    try:
        yield p
    finally:
        p.close()


def test_measure_agrees_with_the_in_worker_checks_value_for_every_selector(
    addressable: Project,
) -> None:
    """The B-1 parity: one selector, two evaluators, the same number.

    ``run_checks`` re-executes the part and measures INSIDE the worker, where
    the labels and tags still exist; ``measure`` measures the published artifact
    from the parent. Both must answer the same thing for the same name, or the
    model is being told two different truths about one part.
    """
    report = addressable.call("run_checks", {"name": "plate"})
    assert report["status"] == "ok"
    for check, selector in ADDRESSABLE_SELECTORS.items():
        entry = report["checks"][check]
        assert entry["pass"] is True, check
        out = addressable.call("measure", {"kind": "bbox", "a": selector, "part": "plate"})
        assert out["value"] == entry["measured"], selector
        assert out["detail"]["measured"] == entry["measured"], selector
    # Not vacuous: the three selectors name three different pieces of geometry,
    # so the parity above cannot be satisfied by one shared fallback answer.
    values = {
        selector: addressable.call("measure", {"kind": "bbox", "a": selector, "part": "plate"})[
            "value"
        ]
        for selector in ADDRESSABLE_SELECTORS.values()
    }
    assert values["part"] == values["wb"] == [40.0, 20.0, 6.0]
    assert values["top_face"] == [40.0, 20.0, 0.0]  # a face has no thickness


def test_measure_refusal_lists_the_namespace_and_never_a_rule_4_binding(
    addressable: Project,
) -> None:
    """An unknown selector gets the resolvable namespace -- and no binding name.

    ``addressing.py`` draws its near misses from the part's whole recorded
    namespace, so ``"bdy"`` near-misses the binding ``body``; the parent side
    cannot answer a rule-4 binding at all, and offering one would be the same
    failure as the empty candidate tuple, wearing help's clothes. The names are
    stated TWICE -- in ``candidates`` and verbatim in the prose -- so both are
    asserted here: a fix that corrects only the structured field leaves the
    sentence advertising exactly what the list dropped, and a model reads the
    sentence.
    """
    with pytest.raises(DispatchError) as ei:
        addressable.call("measure", {"kind": "bbox", "a": "bdy", "part": "plate"})
    assert ei.value.reason == "invalid_part"
    candidates = ei.value.data["candidates"]
    assert candidates == ["part", "top_face", "wb"]
    assert "body" not in candidates
    assert "body" not in ei.value.message
    # The near-miss clause named only `body`, so it is gone rather than empty.
    assert "near misses" not in ei.value.message


def test_measure_refusal_keeps_a_genuine_near_miss(addressable: Project) -> None:
    """Narrowing the unanswerable names must not swallow the answerable ones."""
    with pytest.raises(DispatchError) as ei:
        addressable.call("measure", {"kind": "bbox", "a": "top_fce", "part": "plate"})
    assert ei.value.data["candidates"] == ["top_face"]
    assert ei.value.message.endswith("near misses: top_face")


def test_measure_cross_part_refusal_qualifies_every_candidate(addressable: Project) -> None:
    """More than one part addressed: a bare candidate would resolve elsewhere.

    In a cross-part call an unqualified name resolves against whichever part is
    *current*, not the part its namespace came from, so a bare suggestion is a
    suggestion the caller cannot act on.
    """
    with pytest.raises(DispatchError) as ei:
        addressable.call("measure", {"kind": "clearance", "a": "plate/bdy", "b": "pin/part"})
    assert ei.value.reason == "invalid_part"
    candidates = ei.value.data["candidates"]
    assert candidates, "a refusal with no alternatives at all is B-1's own symptom"
    assert all("/" in name for name in candidates), candidates
    # The parts the call actually named come first; the list is capped, and an
    # alphabetical project walk can spend the whole cap before reaching them.
    assert candidates[:3] == ["plate/part", "plate/top_face", "plate/wb"]
    assert "pin/part" in candidates
    assert "plate/body" not in candidates
    assert "body" not in ei.value.message


def test_measure_refuses_namespace_unrecorded_rather_than_reporting_nothing(
    project: Project,
) -> None:
    """No stored bundle is a different fact from "that name matches nothing".

    An artifact published before bundles were durable, or one whose bundle has
    been collected, genuinely has no recorded section 7 namespace. Spelling that
    the same way as a dangling selector is what sent a reader hunting for a typo
    that was not there. ``"part"`` (rule 1) still resolves on the same artifact,
    because BRep bytes carry the whole compound on their own.
    """
    plate = project.root / "parts" / "plate.py"
    plate.write_text(ADDRESSABLE_PLATE_SRC, encoding="utf-8")
    stale_ref = project.call("build_part", {"name": "plate"})["artifact_ref"]
    # Move the part off that build so only the durable pointer answers for it...
    plate.write_text(ADDRESSABLE_PLATE_SRC.replace("Box(40.0", "Box(41.0"), encoding="utf-8")
    assert project.call("build_part", {"name": "plate"})["artifact_ref"] != stale_ref
    # ...then collect the bundle, leaving the artifact bytes durably stored.
    pointer = build_bundle_pointer("plate", blob_hash_of_ref(stale_ref))
    stored = project.store.blobs.read_pointer(pointer)
    assert stored is not None
    project.store.blobs.cas_swap(pointer, stored, None)

    pinned = {"kind": "bbox", "part": "plate", "artifact_ref": stale_ref}
    with pytest.raises(DispatchError) as ei:
        project.call("measure", {**pinned, "a": "wb"})
    assert ei.value.reason == "namespace_unrecorded"
    assert ei.value.data["part"] == "plate"
    assert ei.value.data["selector"] == "wb"
    assert "resolves to nothing" not in ei.value.message
    survivor = project.call("measure", {**pinned, "a": "part"})
    assert survivor["value"] == [40.0, 20.0, 6.0]
    assert survivor["resolved_artifact_refs"] == [stale_ref]


def test_project_checks_resolve_cross_part_labels_and_tags(addressable: Project) -> None:
    """The regression pin for B-1's silent half: these read as FAILING checks.

    A project check addressing ``"<part>/<label>"`` or ``"<part>/<tag>"`` ran
    against the same empty parent-side index, so a correct model-authored check
    reported a red result nobody could explain from the check's own text.
    """
    out = addressable.call("run_checks", {"scope": "project"})
    assert out["status"] == "ok"
    assert out["file_hashes"].keys() == {"cross.py"}
    checks = out["checks"]
    assert checks["cross:label"]["pass"] is True
    assert checks["cross:tag"]["pass"] is True
    assert checks["cross:clearance"]["pass"] is True
    # The measured values, not just the verdicts: a check that measured the
    # whole part for every selector would pass "label" for the wrong reason.
    assert checks["cross:label"]["measured"] == [40.0, 20.0, 6.0]
    assert checks["cross:tag"]["measured"] == [40.0, 20.0, 0.0]
