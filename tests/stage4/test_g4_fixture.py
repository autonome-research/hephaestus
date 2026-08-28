# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Gate G4's server-side half over the public workspace fixture.

``INTERFACE.md`` §16 maps four G4 clauses to a **pytest** rather than to the
browser, each time for the same reason: the browser assertion alone has a hole
that only a server-side check closes.

* **G4.2** — the e2e compares DOM rows to ``geometry_count`` *over HTTP*. That
  says nothing about whether ``geometry_count`` is the right number. §6.1 names
  three candidates and picks ``len(BuildResult.geometries)``; the invariant that
  all three agree is asserted here, "and when it breaks a Python test fails
  rather than an e2e".
* **G4.3** — the e2e asserts set equality between the DOM's ``data-field`` nodes
  and the projection's keys. A thin projection would make that trivially true, so
  the projection is separately pinned to the enumerated ``part.*`` contract
  (§6.2's assertion 2).
* **G4.4** — the badges the browser reads must come from **the same serializer**
  ``heph check --json`` uses. Byte-parity between a subprocess and the route is
  asserted on the canonical JSON here; the browser then only has to agree with
  the route.
* **G4.7** — the section plate is a *server* render (§5.3), so the golden
  comparison is a comparison of server bytes. That assertion lives in its own
  module, ``test_g4_section_golden.py``, because it is renderer-pinned and CI
  defers renderer-pinned suites (see that module's header).

Everything in this module runs against the same materialized fixture the browser
gate opens, so a fixture change that breaks a browser clause breaks a pytest
first.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from hephaestus.testing.workspace_fixture import SUBJECT_PART, TAGGED_FACE

# --------------------------------------------------------------------------
# G4.2 — the geometry count, and the invariant behind it


def test_the_three_candidate_geometry_counts_agree_for_the_fixture(workspace: Any) -> None:
    """§6.1: ``geometry_count`` is ``len(BuildResult.geometries)``, and the other
    two candidate numbers — GLTF mesh nodes and ``kind="solid"`` selection-table
    entries — agree with it for this fixture.

    Agreement is an **invariant**, not G4.2's clause. G4.2 is "tree rows equal
    ``geometry_count``" and is asserted in the browser; this test is what makes a
    disagreement fail as a Python test instead of as a mystifying e2e diff.
    """
    from hephaestus.core.render.bundle import resolve_selection

    build = workspace.get(f"/parts/{SUBJECT_PART}/build")
    served = int(build["geometry_count"])
    assert served == len(build["geometries"]) == 3

    published = workspace.runtime.cad.publish_gltf(build["artifact_ref"])
    assert published.mesh_count == served, "GLTF mesh nodes disagree with geometry_count"

    resolution = resolve_selection(workspace.runtime.store, published.bundle_ref)
    solids = [entry for entry in resolution.entries.values() if entry.kind == "solid"]
    assert len(solids) == served, "selection-table solids disagree with geometry_count"


def test_every_geometry_entry_is_one_solid_so_a_visibility_toggle_is_unambiguous(
    workspace: Any,
) -> None:
    """§5.4 keys visibility by geometry-entry **label**, so G4.5's target row must
    own exactly one solid or the pixel clause is about a group.

    The fixture is built that way on purpose (``README.md``); this pins it, because
    relabelling two solids alike is a one-word edit that would silently widen the
    mask the browser test compares against.
    """
    build = workspace.get(f"/parts/{SUBJECT_PART}/build")
    labels = [entry["label"] for entry in build["geometries"]]
    assert labels == ["tread", "cleat_left", "cleat_right"]
    assert all(entry["solids"] == 1 for entry in build["geometries"])
    assert len(set(labels)) == len(labels), "two entries share a label; the toggle would group them"


# --------------------------------------------------------------------------
# G4.3 — properties: projection versus the contract


def test_the_properties_projection_is_exactly_the_enumerated_part_metadata(
    workspace: Any,
) -> None:
    """§6.2's assertion (2): projection ↔ the closed ``part.*`` contract.

    Without this the browser's set-equality assertion is satisfied by a projection
    that serves one field and a panel that renders one field.
    """
    from hephaestus.core.executor.namespace import METADATA_FIELDS

    document = workspace.get(f"/parts/{SUBJECT_PART}/properties")
    assert tuple(document["fields"]) == METADATA_FIELDS
    assert set(document["properties"]) == set(METADATA_FIELDS), (
        "the fixture must declare every one of the nine names, in both directions"
    )


def test_the_properties_come_from_the_build_record_not_the_static_parse(
    workspace: Any,
) -> None:
    """One fixture field is an f-string, so the AST parse cannot see it.

    ``blank_size`` is computed from ``hc.*`` at build time. A projection reading
    the static parse would serve eight of nine fields and G4.3's set equality
    would fail — which is exactly why the fixture writes it that way.
    """
    document = workspace.get(f"/parts/{SUBJECT_PART}/properties")
    assert document["source"] == "build_record"
    assert document["build_artifact_ref"] is not None
    assert "mm" in document["properties"]["blank_size"]
    script = workspace.get(f"/parts/{SUBJECT_PART}/script")["script"]
    assert 'blank_size = f"' in script, "the f-string is the point of this fixture field"


# --------------------------------------------------------------------------
# G4.4 — one serializer, two callers


def test_the_route_and_heph_check_json_are_byte_identical(
    workspace: Any, fixture_project: Path
) -> None:
    """§6.3: "one serializer, two callers, no second implementation".

    The browser compares its badges against a subprocess ``heph check --json``.
    That comparison is only meaningful if the route and the subprocess serialize
    the same report the same way, which is what is asserted here — on the
    canonical JSON, byte for byte.
    """
    from opstore import canonical_json

    served = workspace.get("/checks")
    completed = subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", "check", "--json"],
        cwd=fixture_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode in (0, 1), completed.stderr
    printed = json.loads(completed.stdout)
    assert canonical_json(served["report"]) == canonical_json(printed)


def test_the_fixture_produces_every_reachable_badge_state(workspace: Any) -> None:
    """§6.3's vocabulary is closed at four; three of them have producers.

    ``not_run`` is **not** reachable from a run and this fixture does not fake
    one — see ``corpus/public_fixtures/workspace/README.md`` for why (the check
    engine runs every check it loads, so declared == run by construction). The
    fourth badge is exercised at the projection instead, in the next test.
    """
    badges = workspace.get("/checks")["badges"]
    assert set(badges.values()) == {"pass", "fail", "error"}
    assert badges["tread_checks:tread_is_one_sheet_thick"] == "pass"
    assert badges["tread_checks:tread_fits_a_100_mm_sheet"] == "fail"
    assert badges["tread_checks:tread_clears_the_absent_stringer"] == "error"


def test_not_run_is_reachable_at_the_projection_and_never_reads_as_a_pass(
    workspace: Any,
) -> None:
    """§6.3: "silence never reads as a pass" — asserted where the state exists.

    A declared name the report does not carry badges ``not_run``, distinct from
    every other value, and the three real outcomes are unchanged by supplying it.
    """
    from hephaestus.core.checks.report import BADGES, project_check_report
    from hephaestus.http.projections import checks_projection

    report = project_check_report(workspace.runtime.layout, workspace.runtime.store)
    projected = checks_projection(report, declared=["tread_checks:never_reached"])
    assert projected["badges"]["tread_checks:never_reached"] == "not_run"
    assert set(projected["badges"].values()) == set(BADGES)


# --------------------------------------------------------------------------
# G4.X (deferred from G6) — DFM findings over an artifact-bound descriptor


def test_run_dfm_reports_every_shipped_laser_cut_rule_with_topology_descriptors(
    workspace: Any,
) -> None:
    """§6.4: findings carry **descriptors**, not bare mask ids, and each names the
    artifact it was measured against.

    The fixture violates all three rules the ``laser_cut`` pack ships, so the
    browser's DFM panel has one finding per rule to render and the "toggle
    surfaces findings" clause is not satisfied by an empty list.
    """
    result = workspace.post(f"/parts/{SUBJECT_PART}/dfm", {})
    assert result["status"] == "ok", result
    rules = {rule["rule_id"]: rule for rule in result["rules"]}
    assert set(rules) == {
        "laser_cut.min_feature_vs_kerf",
        "laser_cut.min_internal_radius",
        "laser_cut.sheet_thickness_match",
    }
    assert all(rule["status"] == "violations" for rule in rules.values())
    for finding in result["findings"]:
        assert finding["source_artifact_ref"].startswith("artifact:build:")
        for descriptor in finding["topology"]:
            assert set(descriptor) >= {"kind", "solid_id", "topology_index"}


# --------------------------------------------------------------------------
# G4.6 — the server-declared displacement the client applies


def test_the_gltf_carries_one_explode_offset_per_solid_and_they_are_distinct(
    workspace: Any,
) -> None:
    """§1/§5.2: the client applies ``offset · t`` and computes nothing.

    G4.6 reads pairwise centroid distances out of the browser's scene graph; that
    is only a test of anything if the server's offsets are distinct, which needs
    the ≥3-solid fixture §14 requires. Byte-equivalence with
    ``channels._explode_offset`` is asserted in ``server/tests/test_http_gltf.py``;
    what is asserted here is that this *fixture* makes the clause non-vacuous.
    """
    from hephaestus.core.render.gltf import validate_gltf

    build = workspace.get(f"/parts/{SUBJECT_PART}/build")
    published = workspace.runtime.cad.publish_gltf(build["artifact_ref"])
    offsets = validate_gltf(published.data).explode_offsets
    assert len(offsets) == 3
    assert len(set(offsets)) == 3, "two solids share a displacement; distances would not grow"


# --------------------------------------------------------------------------
# the fixture's remaining §14 requirements, pinned where they are cheap


def test_the_tagged_face_resolves_to_a_creating_line(workspace: Any) -> None:
    """§14's ``tread_top`` requirement, and the line G5.4 will join against."""
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.inspect import tag_placements_from_source_map

    build = workspace.get(f"/parts/{SUBJECT_PART}/build")
    blob = workspace.runtime.store.blobs.get(blob_hash_of_ref(build["source_map_ref"]))
    placements = tag_placements_from_source_map(json.loads(blob.decode("utf-8")))
    assert TAGGED_FACE in placements
    placement = placements[TAGGED_FACE]
    assert placement.kind == "face"
    script_lines = workspace.get(f"/parts/{SUBJECT_PART}/script")["script"].splitlines()
    assert f'"{TAGGED_FACE}"' in script_lines[placement.line - 1]


def test_groove_count_is_declared_with_the_bounds_the_fixture_requires(
    workspace: Any,
) -> None:
    """§14: ``groove_count = Param(5, min=2, max=10)`` — G5.2/G5.3's operand."""
    params = {row["name"]: row for row in workspace.get(f"/parts/{SUBJECT_PART}/params")["params"]}
    groove = params["groove_count"]
    assert (groove["default"], groove["min"], groove["max"]) == (5, 2, 10)


def test_the_kerf_card_legend_exceeds_the_inline_cap(workspace: Any) -> None:
    """§14's oversized-legend requirement (G5.8's operand), measured not assumed.

    The part is not built by the browser harness — 90 boolean cuts are time G4
    does not need — so this test builds it once and asserts the legend really does
    page through a ref rather than inlining.
    """
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.inspect import INLINE_LEGEND_CAP_BYTES

    result = workspace.post("/parts/kerf_card/build", {})
    assert result["status"] == "ok", result
    document = workspace.post(
        "/parts/kerf_card/inspect",
        {"views": ["iso"], "channel": "mask", "mask_mode": "selection", "focus": "kerf_card"},
    )
    assert document["mask_legend_truncated"] is True
    assert document.get("mask_legend") is None
    blob = workspace.runtime.store.blobs.get(blob_hash_of_ref(document["mask_legend_ref"]))
    assert len(blob) > INLINE_LEGEND_CAP_BYTES
