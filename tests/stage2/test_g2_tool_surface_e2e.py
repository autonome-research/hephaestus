"""G2: a scripted fake model drives EVERY generated tool through the real bridge.

Gate clause: *"Tests use a scripted fake model to drive every generated Pi custom
tool through the real Node/Python bridge, including images, ``ask_user`` …"*.

One orchestrator session, one prompt, one chain of 30 turns — every tool in
``tools_decl`` is called exactly once, in a dependency-respecting order, with the
arguments built from the *previous* tool's real result (hashes, refs, ids). The
model never sees a stub: each call travels model -> Pi loop -> ToolProxy (TypeBox
validation + trusted invocation) -> ``py.tool_dispatch``/``py.delegate``/
``py.ask_user`` -> ``hephaestus.core`` and back through result validation.

Coverage the gate names explicitly and this chain exercises:

* **images** — ``inspect_part`` renders ride back inline as public ``image``
  events and as image content blocks in the model request;
* **ask_user** — a real suspension answered by a scripted answerer;
* **registry family** — skills/materials/parts-store served from the hash-pinned
  ``registries/`` tree, with skill text inside provenance delimiters;
* **delegation family** — ``delegate_part_agent`` over ``py.delegate`` with a
  durable child terminal, then ``get_delegation_status`` / ``cancel_delegation``;
* **export** — a frozen source artifact with source/export hashes on disk.

The per-tool *semantics* are covered by the package-local suites; what this file
adds is the end-to-end proof that the full declared surface is reachable through
the packaged sidecar with schema-valid arguments and schema-valid results.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from _g2 import (
    G2Harness,
    RequestInfo,
    assert_stream_shape,
    called_tools,
    events_of,
    last_tool_result,
    payload_of,
    text,
    tool_call,
)
from hephaestus.core import tools_decl

WIDGET_SCRIPT = """PARAMS = {
    "width": Param(40.0, min=10.0, max=80.0),
}

body = Box(p.width, 20.0, 6.0)
body.label = "widget_body"
part.geometry = body
part.description = "G2 surface widget"

CHECKS = {
    "wide_enough": lambda m: m.bbox("part")[0] >= 10.0,
}
"""

#: (tool, build-arguments-from-what-we-have-seen). Order is dependency order.
Step = tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]


def _steps() -> list[Step]:
    def seen_get(seen: dict[str, Any], tool: str, key: str, default: Any = None) -> Any:
        result = cast("dict[str, Any]", seen.get(tool) or {})
        return result.get(key, default)

    return [
        # -- registry (contextual + executable) ----------------------------
        ("list_skills", lambda seen: {}),
        ("load_skill", lambda seen: {"name": "build123d-idioms", "limit_lines": 40}),
        ("search_materials", lambda seen: {"query": "plywood"}),
        # -- references (INGEST.md §2): read-only, operator-registered --------
        ("list_references", lambda seen: {}),
        (
            "read_reference",
            lambda seen: {
                "name": str(cast("list[Any]", seen["list_references"])[0]["name"]),
                "page": 1,
            },
        ),
        ("search_parts_store", lambda seen: {"query": "screw", "max_results": 3}),
        (
            "instance_store_part",
            lambda seen: {
                "id": str(cast("list[Any]", seen["search_parts_store"])[0]["id"]),
                "params": {},
            },
        ),
        # -- authoring -----------------------------------------------------
        ("create_part", lambda seen: {"name": "widget", "template": "blank"}),
        (
            "write_part",
            lambda seen: {
                "name": "widget",
                "expected_hash": seen_get(seen, "create_part", "content_hash"),
                "script": WIDGET_SCRIPT,
            },
        ),
        ("read_part", lambda seen: {"name": "widget"}),
        (
            "edit_part",
            lambda seen: {
                "name": "widget",
                "expected_hash": seen_get(seen, "read_part", "content_hash"),
                "old_str": "G2 surface widget",
                "new_str": "G2 surface widget (edited)",
            },
        ),
        # -- project globals ------------------------------------------------
        ("read_globals", lambda seen: {}),
        (
            "edit_globals",
            lambda seen: {
                "expected_hash": seen_get(seen, "read_globals", "content_hash"),
                "old_str": "PARAMS = {}",
                "new_str": "PARAMS = {}\n\nSHELF_W = 100.0",
            },
        ),
        # -- requirement ledger (VALIDATION.md §2, before any geometry) ------
        (
            "record_requirements",
            lambda seen: {
                "entries": [
                    {
                        "id": "R1",
                        "text": "widget is 40 mm wide in X",
                        "source": "specified",
                        "quote": "exercise the whole tool surface",
                        "value": 40.0,
                        "unit": "mm",
                        "applies_to": "widget",
                    },
                    {
                        "id": "R2",
                        "text": "widget stays at least 10 mm wide",
                        "source": "derived",
                        "from": ["R1"],
                        "value": 10.0,
                        "unit": "mm",
                        "applies_to": "widget",
                    },
                ]
            },
        ),
        ("read_requirements", lambda seen: {}),
        (
            "update_requirement",
            lambda seen: {"id": "R1", "value": 44.0, "text": "widget is 44 mm wide in X"},
        ),
        # -- parameters + geometry -----------------------------------------
        (
            "set_params",
            lambda seen: {
                "scope": "part",
                "name": "widget",
                "values": {"width": 44.0},
                "expected_state_hash": seen_get(seen, "read_part", "part_param_state_hash"),
            },
        ),
        ("build_part", lambda seen: {"name": "widget"}),
        ("inspect_part", lambda seen: {"name": "widget", "views": ["iso"]}),
        ("measure", lambda seen: {"kind": "bbox", "a": "part", "part": "widget"}),
        # The convergence signal (COMPARE.md §2). No import is registered in this
        # project — the model has no tool that could add one — so the target the
        # chain can reach is a part, and comparing the widget with itself is the
        # identity case the diff must report as a perfect match.
        (
            "compare_solids",
            lambda seen: {"part": "widget", "target": "part:widget", "align": "as_posed"},
        ),
        # The scan half of the same signal (MESH_INGEST.md §6/§7.2). The scan is
        # seeded into imports/ operator-side by ``_seed_scan`` — the model has no
        # tool that could add one, exactly as with a reference — and ``units`` is
        # required because STL carries none (§1.3). The scan is a 30 x 10 x 5 box
        # inside the widget, so every scanned corner sits exactly 0.5 mm from the
        # widget's nearest face (see SCAN_CLEARANCE_MM).
        (
            "compare_to_scan",
            lambda seen: {"part": "widget", "scan": SCAN_NAME, "units": "mm"},
        ),
        # -- declared constraints (ASSEMBLY.md §3) --------------------------
        # One part is enough to exercise the quartet end to end: the widget's
        # distance to itself is 0 mm, resolved through the `part` anchor rule and
        # measured against the artifact the build above published — a real
        # evaluation with a real (satisfied) residual, not a stub. (A
        # no_interference self-constraint would be *violated*, correctly: a solid
        # overlaps itself entirely.)
        (
            "declare_constraint",
            lambda seen: {
                "id": "c-widget-solid",
                "kind": "distance",
                "a": "widget",
                "b": "widget",
                "value_mm": 0.0,
                "tol_mm": 0.01,
                "provenance": {"requirement": "R1"},
                "note": "the widget is where it is",
            },
        ),
        (
            "update_constraint",
            lambda seen: {
                "id": "c-widget-solid",
                "patch": {"note": "kept as a self-check of the addressing layer"},
                "reason": "clarified what the constraint is for",
            },
        ),
        ("read_constraints", lambda seen: {}),
        ("check_assembly", lambda seen: {}),
        # -- declared joints, poses and motion checks (KINEMATICS.md §1/§3/§4,
        # Stage 9A/9B) --------------------------------------------------------
        # Declaration is structural, exactly like a constraint's: whether the
        # named parts have builds is an EVALUATION question with its own named
        # unresolvable states. This one-part project has no second part to
        # anchor, so the joint honestly resolves to `missing_part` below (the
        # PARENT anchor names the absent part — resolution is parent-first) — a
        # real named refusal through the real engine, not a stub — while the
        # empty-binding pose ("everything as built", §3) really resolves. The
        # joint is prismatic (Stage 9B: a motion check may only sweep a
        # scalar-DOF joint, so a `fixed` mount could not carry the sweep step).
        (
            "declare_joint",
            lambda seen: {
                "id": "j-mount",
                "kind": "prismatic",
                "parent": "carriage",
                "child": "widget",
                "limits": {"min": 0.0, "max": 20.0},
                "provenance": {"requirement": "R1"},
                "note": "the widget rides the carriage",
            },
        ),
        (
            "update_joint",
            lambda seen: {
                "id": "j-mount",
                "patch": {"note": "kept as a mount-point claim"},
                "reason": "clarified what the joint is for",
            },
        ),
        ("read_joints", lambda seen: {}),
        (
            "declare_pose",
            lambda seen: {
                "id": "p-zero",
                "joints": {},
                "provenance": {"requirement": "R1"},
                "note": "everything as built",
            },
        ),
        (
            "update_pose",
            lambda seen: {
                "id": "p-zero",
                "patch": {"note": "the reference configuration"},
                "reason": "clarified what the pose is for",
            },
        ),
        ("read_poses", lambda seen: {}),
        # A sweep over the declared prismatic joint (KINEMATICS.md §4). The
        # swept joint's parent part does not exist, so the check honestly
        # evaluates `unresolvable` below — through the real engine.
        (
            "declare_motion_check",
            lambda seen: {
                "id": "mc-travel",
                "kind": "sweep_clearance",
                "a": "widget",
                "b": "carriage",
                "min_mm": 1.0,
                "sweep": {"j-mount": {"from": 0.0, "to": 20.0}},
                "samples": 3,
                "provenance": {"requirement": "R1"},
            },
        ),
        (
            "update_motion_check",
            lambda seen: {
                "id": "mc-travel",
                "patch": {"note": "kept as a travel-clearance claim"},
                "reason": "clarified what the check is for",
            },
        ),
        ("read_motion_checks", lambda seen: {}),
        # -- couplings (KINEMATICS.md §5, Stage 9C). The coupling drives the
        # fixture-seeded j-feed from the chain-declared j-mount — a coupling
        # relates TWO declared joints, and this chain calls declare_joint
        # exactly once, so the second joint is seeded engine-side by the
        # fixture (the _register_reference rationale). j-mount stays FREE (a
        # coupling PARENT is free), so the sweep above still binds it.
        (
            "declare_coupling",
            lambda seen: {
                "id": "cp-feed",
                "parent": "j-mount",
                "child": "j-feed",
                "ratio": 0.5,
                "offset": 0.0,
                "provenance": {"requirement": "R1"},
                "note": "the table tracks the carriage at half speed",
            },
        ),
        (
            "update_coupling",
            lambda seen: {
                "id": "cp-feed",
                "patch": {"note": "kept as a transmission claim"},
                "reason": "clarified what the coupling is for",
            },
        ),
        ("read_couplings", lambda seen: {}),
        ("check_motion", lambda seen: {}),
        # -- pose solving (SOLVER.md §2A, Stage 13A). Same shape as the joint
        # and motion-check steps above and for the same reason: this one-part
        # project has no second part to anchor a joint frame on, so the solve
        # honestly comes back `unresolvable` — verdict SIX of the closed
        # seven-spelling pose set (§6.1), reported IN the record rather than
        # hidden behind a transport error, exactly as an unresolvable
        # constraint row is. It writes nothing either way, which is the whole
        # of what the no-solver amendment bought.
        (
            "solve_pose",
            lambda seen: {
                "targets": [
                    {
                        "form": "anchor_point",
                        "id": "t_mount",
                        "anchor": "widget",
                        "point_mm": [0.0, 0.0, 10.0],
                        "tol_mm": 0.05,
                    }
                ],
                "free_joints": ["j-mount"],
                "tol": 0.01,
                "weighting": "unit_scaled_v1",
                "regularization": "min_norm_from_start",
                "provenance": {"requirement": "R1"},
            },
        ),
        # -- placement proposal (SOLVER.md §2B, Stage 13B). This one-part
        # project's only declared constraint is a `distance`, which §3.2
        # refuses as an objective term in transform space by name and with its
        # reason (`kernel_extremum`: `measure.distance` is piecewise smooth
        # with a witness pair that switches discontinuously as surfaces slide,
        # and the kink sits exactly where mates live). So the honest answer
        # here is that named refusal, arriving as a tool error rather than as a
        # verdict — a refusal is NOT a verdict, and dressing one as an outcome
        # is what SOLVER.md §6.3 exists to prevent. Nothing is written either
        # way, and `read_proposals` below confirms it: no proposal exists.
        (
            "propose_placement",
            lambda seen: {
                "space": "transform",
                "constraints": ["c-widget-solid"],
                "free": ["widget"],
                "tol": 0.01,
                "weighting": "unit_scaled_v1",
                "regularization": "min_norm_from_start",
                "provenance": {"requirement": "R1"},
            },
        ),
        ("read_proposals", lambda seen: {}),
        ("run_checks", lambda seen: {"scope": "part", "name": "widget"}),
        (
            "read_artifact",
            lambda seen: {
                "ref": seen_get(seen, "build_part", "artifact_ref"),
                "max_bytes": 4096,
            },
        ),
        ("export_part", lambda seen: {"name": "widget", "format": "stl"}),
        ("run_dfm", lambda seen: {"name": "widget", "process": "laser_cut"}),
        ("generate_drawing", lambda seen: {"name": "widget", "kind": "dimensioned"}),
        ("generate_doc", lambda seen: {"name": "widget", "kind": "bom"}),
        (
            "query_snapshot",
            lambda seen: {"name": "widget", "question": "does the widget look square?"},
        ),
        # -- project checks -------------------------------------------------
        ("list_project_checks", lambda seen: {}),
        (
            "create_project_check",
            lambda seen: {"name": "cross_part_fit", "description": "widget stays wide"},
        ),
        ("read_project_check", lambda seen: {"name": "cross_part_fit"}),
        (
            "edit_project_check",
            lambda seen: {
                "name": "cross_part_fit",
                "expected_hash": seen_get(seen, "read_project_check", "content_hash"),
                "old_str": '"placeholder": lambda m: True,',
                "new_str": '"widget_wide": lambda m: m.bbox("widget/part")[0] >= 10.0,',
            },
        ),
        # -- delegation -----------------------------------------------------
        (
            "delegate_part_agent",
            lambda seen: {
                "part": "widget",
                "prompt": "tighten the widget fillets",
                "delivery": "prompt",
                "deadline_seconds": 60,
            },
        ),
        (
            "get_delegation_status",
            lambda seen: {
                "delegation_ref": seen_get(seen, "delegate_part_agent", "delegation_ref")
            },
        ),
        (
            "cancel_delegation",
            lambda seen: {
                "delegation_ref": seen_get(seen, "delegate_part_agent", "delegation_ref")
            },
        ),
        # -- interaction ----------------------------------------------------
        (
            "ask_user",
            lambda seen: {
                "question": "Ship it?",
                "options": ["yes", "no"],
                "allow_free_text": False,
            },
        ),
    ]


class Chain:
    """Drives the step list, feeding each tool the previous tool's real result."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = steps
        self.index = 0
        self.seen: dict[str, Any] = {}
        self.failure: str | None = None

    def __call__(self, info: RequestInfo) -> dict[str, Any]:
        if self.index > 0:
            result = last_tool_result(info)
            # Array-valued results (the registry search tools) arrive wrapped.
            unwrapped = result["_value"] if set(result) == {"_value"} else result
            self.seen[self.steps[self.index - 1][0]] = unwrapped
        if self.index >= len(self.steps):
            return text("SURFACE COMPLETE")
        name, build = self.steps[self.index]
        self.index += 1
        try:
            arguments = build(self.seen)
        except Exception as exc:
            self.failure = f"{name}: could not build arguments from prior results: {exc!r}"
            return text("SURFACE ABORTED")
        return tool_call(name, arguments, f"call_{self.index}")


#: The one operator-supplied reference this chain reads (INGEST.md §2). Markdown,
#: so the extraction needed to register it is core's own — no server-side parser
#: is in play here; what is exercised is that the *model* can list and read it.
REFERENCE_NAME = "datasheet.md"
REFERENCE_TEXT = "# Widget datasheet\n\nOverall width 40.0 mm.\n"

#: The operator-seeded scan the compare_to_scan step measures against.
SCAN_NAME = "fixture.stl"

#: Its hand-computed clearance to the widget. The widget is ``Box(44, 20, 6)``
#: after the chain's own ``set_params`` (centred on the origin, so +/-22, +/-10,
#: +/-3) and the scan is a 30 x 10 x 5 box (+/-15, +/-5, +/-2.5) inside it. Each
#: of the scan's eight corners is 7 mm from the nearest x face, 5 mm from the
#: nearest y face and **0.5 mm** from the nearest z face, so the minimum and the
#: maximum are both 0.5 — one subtraction, checkable by eye.
SCAN_CLEARANCE_MM = 0.5


def _register_reference(project_root: Any) -> None:
    """Register a reference the way an operator does — before any session runs.

    Deliberately not a tool call: INGEST.md §2 gives the model no way to add a
    reference, so the chain below can only ever list and read this one.
    """
    from hephaestus.core.project_store.layout import load_project, open_store
    from hephaestus.core.project_store.references import ReferenceRegistry

    layout = load_project(project_root)
    store = open_store(layout)
    try:
        ReferenceRegistry(layout, store).add_bytes(
            REFERENCE_TEXT.encode("utf-8"), name=REFERENCE_NAME
        )
    finally:
        store.close()


def _seed_scan(project_root: Any) -> None:
    """Put a scan under ``imports/`` the way an operator does — before any session.

    Deliberately not a tool call: MESH_INGEST.md gives the model no way to add an
    import, so the chain below can only ever measure against this one. The
    ``_register_reference`` rationale, applied to the other operator-supplied
    input kind.
    """
    import numpy as np
    import trimesh

    half = np.array([15.0, 5.0, 2.5])
    corners = (
        np.array(
            [
                [-1.0, -1.0, -1.0],
                [1.0, -1.0, -1.0],
                [1.0, 1.0, -1.0],
                [-1.0, 1.0, -1.0],
                [-1.0, -1.0, 1.0],
                [1.0, -1.0, 1.0],
                [1.0, 1.0, 1.0],
                [-1.0, 1.0, 1.0],
            ]
        )
        * half
    )
    faces: Any = np.array(
        [
            [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
            [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7],
        ],
        dtype=np.int64,
    )  # fmt: skip
    mesh: Any = trimesh.Trimesh(vertices=corners, faces=faces, process=False)
    data: Any = mesh.export(file_type="stl")
    imports = Path(project_root) / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    (imports / SCAN_NAME).write_bytes(
        data.encode("utf-8") if isinstance(data, str) else bytes(data)
    )


def _declare_feed_joint(project_root: Any) -> None:
    """Seed the second joint the coupling steps need — engine-side, once.

    KINEMATICS.md §5: a coupling relates TWO declared joints, and this chain
    calls every tool exactly once, so its single ``declare_joint`` step cannot
    supply both. The second joint is declared through the engine the way an
    earlier session would have — the ``_register_reference`` rationale: a
    precondition of the chain, never its subject.
    """
    from hephaestus.core.project_store.kinematics import JointSet
    from hephaestus.core.project_store.layout import load_project, open_store

    layout = load_project(project_root)
    store = open_store(layout)
    try:
        JointSet(layout, store).declare(
            {
                "id": "j-feed",
                "kind": "prismatic",
                "parent": "table",
                "child": "carriage",
                "limits": {"min": -100.0, "max": 100.0},
                "provenance": {"assumed": True, "reason": "seeded for the coupling steps"},
            }
        )
    finally:
        store.close()


@pytest.fixture
def surface(tmp_path: Any, sidecar_dist: Any) -> Any:
    from _g2 import scaffold_project

    # The chain records its own ledger and asserts its generations, so the
    # project must start with none (VALIDATION.md §2).
    project = scaffold_project(tmp_path / "surface", seed_ledger=False)
    _register_reference(project)
    _seed_scan(project)
    _declare_feed_joint(project)
    harness = G2Harness(project, sidecar_dist, snapshot=True, sandbox=True)
    try:
        yield harness
    finally:
        harness.close()
        harness.assert_no_orphans()


def test_every_generated_tool_flows_through_the_real_bridge(surface: G2Harness) -> None:
    steps = _steps()
    assert [name for name, _ in steps] != [], "no steps"
    # The chain must cover the declared surface exactly once.
    assert sorted(name for name, _ in steps) == sorted(tools_decl.tool_names())

    chain = Chain(steps)
    surface.set_script([chain] * (len(steps) + 1))

    answered: list[dict[str, Any]] = []

    def answerer(params: dict[str, Any]) -> Any:
        answered.append(params)
        return "yes"

    session_id = surface.create_session("orchestrator", session_id="g2-surface")
    result = surface.prompt(
        session_id, "exercise the whole tool surface", answerer=answerer, timeout=1800
    )

    assert chain.failure is None, chain.failure
    assert result.status == "completed"
    assert_stream_shape(result)

    seen = chain.seen
    # Every tool produced a result the proxy accepted against its result schema.
    assert set(seen) == set(tools_decl.tool_names()), (
        f"tools without a result: {set(tools_decl.tool_names()) - set(seen)}"
    )

    # -- the public narrative lists every tool once, in order ---------------
    narrative = called_tools(result)
    assert narrative == [name for name, _ in steps]

    # -- registry: contextual content is provenance-delimited ---------------
    skills = cast("list[Any]", seen["list_skills"])
    assert {entry["name"] for entry in skills} >= {"build123d-idioms", "sheet-goods-and-joinery"}
    skill = cast("dict[str, Any]", seen["load_skill"])
    assert "BEGIN REFERENCE" in skill["content"] or "REFERENCE" in skill["content"]
    assert skill["artifact_ref"].startswith("artifact:")
    # -- references: listed and read, still provenance-delimited -------------
    references = cast("list[Any]", seen["list_references"])
    assert [entry["name"] for entry in references] == [REFERENCE_NAME]
    assert references[0]["kind"] == "document" and references[0]["pages"] == 1
    reference = cast("dict[str, Any]", seen["read_reference"])
    assert "Overall width 40.0 mm." in reference["content"]
    assert "REFERENCE" in reference["content"], "reference text is never bare instructions"
    assert reference["artifact_ref"].startswith("artifact:reference:")
    assert reference["truncated"] is False
    materials = cast("list[Any]", seen["search_materials"])
    assert any("plywood" in str(entry["id"]) for entry in materials)
    store = cast("list[Any]", seen["search_parts_store"])
    assert store and {"id", "name", "params"} <= set(store[0])
    instanced = cast("dict[str, Any]", seen["instance_store_part"])
    # With a probed sandbox the generator really runs; without one the tool is a
    # discriminated capability_error — never a quiet unsandboxed execution.
    assert "script_fragment" in instanced or instanced.get("code") == "capability_not_available"

    # -- authoring: CAS hashes chained through the real store ---------------
    assert seen["write_part"]["applied"] is True
    assert seen["edit_part"]["applied"] is True
    script_path = surface.project_root / "parts" / "widget.py"
    assert "(edited)" in script_path.read_text(encoding="utf-8")
    assert seen["edit_globals"]["status"] == "applied"
    assert "SHELF_W" in (surface.project_root / "globals.py").read_text(encoding="utf-8")

    # -- requirement ledger: immutable generations, no open assumptions ------
    recorded = cast("dict[str, Any]", seen["record_requirements"])
    assert recorded["status"] == "ok" and recorded["generation"] == 1
    assert recorded["artifact_ref"].startswith("artifact:requirements:")
    assert [entry["id"] for entry in cast("list[Any]", recorded["entries"])] == ["R1", "R2"]
    read_back = cast("dict[str, Any]", seen["read_requirements"])
    assert read_back["artifact_ref"] == recorded["artifact_ref"]
    updated = cast("dict[str, Any]", seen["update_requirement"])
    assert updated["generation"] == 2
    assert updated["artifact_ref"] != recorded["artifact_ref"]
    assert cast("list[Any]", updated["entries"])[0]["value"] == 44.0
    # Nothing here is an assumption, so the §3 gate has nothing to block on.
    assert updated["unresolved_material"] == []

    # -- parameters + geometry ---------------------------------------------
    assert seen["set_params"]["effective"]["width"] == 44.0
    build = cast("dict[str, Any]", seen["build_part"])
    assert build["status"] == "ok" and build["current"] is True
    assert build["artifact_ref"].startswith("artifact:build:")
    inspect = cast("dict[str, Any]", seen["inspect_part"])
    assert inspect["status"] == "ok" and inspect["render_artifact_refs"]
    images = events_of(result, "image")
    assert images, "inspect_part must stream at least one public image event"
    assert payload_of(images[0])["mimeType"] == "image/png"
    assert seen["measure"]["units"] == "mm"
    comparison = cast("dict[str, Any]", seen["compare_solids"])
    assert comparison["align"] == "as_posed"
    assert comparison["a"] == comparison["b"]
    assert comparison["a"]["artifact_ref"] == build["artifact_ref"]
    assert comparison["diff"]["volume"]["iou"] == pytest.approx(1.0, abs=1e-9)
    assert comparison["diff"]["surface"]["max_deviation_mm"] == pytest.approx(0.0, abs=1e-9)
    # -- the scan half: a different record type, with no iou and no chamfer
    scan = cast("dict[str, Any]", seen["compare_to_scan"])
    assert scan["scan"]["path"] == SCAN_NAME and scan["scan"]["units"] == "mm"
    assert scan["scan"]["canonical_hash"] != scan["scan"]["sha256"]
    assert scan["part"]["artifact_ref"] == build["artifact_ref"]
    distance = cast("dict[str, Any]", scan["distance"])
    assert distance["scan_to_part_min_mm"] == pytest.approx(SCAN_CLEARANCE_MM, abs=1e-9)
    assert distance["scan_to_part_max_mm"] == pytest.approx(SCAN_CLEARANCE_MM, abs=1e-9)
    assert distance["part_to_scan_method"] == "kdtree_bound_exact_triangle"
    assert "iou" not in distance and "chamfer_mm" not in distance
    # -- constraints: declared, revised, evaluated against the built artifact
    declared = cast("dict[str, Any]", seen["declare_constraint"])
    assert declared["generation"] == 1 and declared["change"]["kind"] == "declare"
    revised = cast("dict[str, Any]", seen["update_constraint"])
    assert revised["generation"] == 2 and revised["change"]["reason"]
    read = cast("dict[str, Any]", seen["read_constraints"])
    assert [entry["id"] for entry in read["entries"]] == ["c-widget-solid"]
    checked = cast("dict[str, Any]", seen["check_assembly"])
    status = cast("dict[str, Any]", checked["assembly"])
    assert checked["partial"] is False
    assert status["counts"]["unresolvable"] == 0, status["constraints"]
    assert status["blocking"] == [], status["constraints"]
    # -- joints and poses: declared, revised, evaluated (KINEMATICS.md §2/§6)
    # Generations repointed by Stage 9C: the fixture seeds j-feed (generation
    # 1) so the coupling steps have a second joint to relate — the chain's own
    # declaration is therefore generation 2.
    joint_declared = cast("dict[str, Any]", seen["declare_joint"])
    assert joint_declared["generation"] == 2 and joint_declared["change"]["kind"] == "declare"
    joint_revised = cast("dict[str, Any]", seen["update_joint"])
    assert joint_revised["generation"] == 3 and joint_revised["change"]["reason"]
    joints_read = cast("dict[str, Any]", seen["read_joints"])
    assert [entry["id"] for entry in joints_read["entries"]] == ["j-feed", "j-mount"]
    assert joints_read["motion"] is None, "reading never measures"
    pose_declared = cast("dict[str, Any]", seen["declare_pose"])
    assert pose_declared["generation"] == 1 and pose_declared["change"]["kind"] == "declare"
    poses_read = cast("dict[str, Any]", seen["read_poses"])
    assert [entry["id"] for entry in poses_read["entries"]] == ["p-zero"]
    check_declared = cast("dict[str, Any]", seen["declare_motion_check"])
    assert check_declared["generation"] == 1 and check_declared["change"]["kind"] == "declare"
    check_revised = cast("dict[str, Any]", seen["update_motion_check"])
    assert check_revised["generation"] == 2 and check_revised["change"]["reason"]
    checks_read = cast("dict[str, Any]", seen["read_motion_checks"])
    assert [entry["id"] for entry in checks_read["entries"]] == ["mc-travel"]
    assert checks_read["results"] is None, "reading never measures"
    # -- couplings: declared, revised, read (KINEMATICS.md §5, Stage 9C)
    coupling_declared = cast("dict[str, Any]", seen["declare_coupling"])
    assert coupling_declared["generation"] == 1
    assert coupling_declared["change"]["kind"] == "declare"
    coupling_revised = cast("dict[str, Any]", seen["update_coupling"])
    assert coupling_revised["generation"] == 2 and coupling_revised["change"]["reason"]
    couplings_read = cast("dict[str, Any]", seen["read_couplings"])
    [coupling_entry] = cast("list[Any]", couplings_read["entries"])
    assert coupling_entry["id"] == "cp-feed" and coupling_entry["ratio"] == 0.5
    assert couplings_read["motion"] is None, "reading never measures"
    motion_checked = cast("dict[str, Any]", seen["check_motion"])
    motion = cast("dict[str, Any]", motion_checked["motion"])
    # Both joints name parts this project does not have: real named refusals
    # through the real engine, never skipped and never a pass. (Two rows since
    # Stage 9C seeded j-feed for the coupling steps.)
    joint_rows = cast("list[Any]", motion["joints"])
    assert [row["id"] for row in joint_rows] == ["j-feed", "j-mount"]
    for joint_row in joint_rows:
        assert joint_row["state"] == "unresolvable" and joint_row["reason"] == "missing_part"
    [pose_row] = cast("list[Any]", motion["poses"])
    assert pose_row["state"] == "resolved"
    assert motion["blocking"] == ["j-feed", "j-mount"]
    assert motion_checked["artifact_ref"].startswith("artifact:motion-status:")
    # Stage 9B: the per-check §4 results ride the same result — the sweep over
    # the unresolvable joint is `unresolvable` by name, never skipped.
    assert motion_checked["partial"] is False
    [sweep_row] = cast("list[Any]", motion_checked["results"])
    assert sweep_row["id"] == "mc-travel" and sweep_row["verdict"] == "unresolvable"
    assert motion_checked["results_ref"].startswith("artifact:motion-results:")
    # Stage 13B: the placement proposer refused BY NAME with its reason, and
    # nothing was written - `read_proposals` shows an empty generation 0. A
    # refusal is not a verdict and a refused solve records no proposal, which
    # is what makes "the output is an artifact nothing applies" checkable from
    # the other side: there is no artifact at all.
    proposed = cast("dict[str, Any]", seen["propose_placement"])
    refusal = str(proposed.get("_text") or proposed)
    assert "not_an_objective_kind" in refusal, proposed
    assert "kernel_extremum" in refusal, proposed
    proposals_read = cast("dict[str, Any]", seen["read_proposals"])
    assert proposals_read["status"] == "ok"
    assert proposals_read["proposals"] == [] and proposals_read["generation"] == 0

    assert seen["run_checks"]["checks"]["wide_enough"]["pass"] is True
    assert seen["read_artifact"]["total_bytes"] > 0

    # -- export: frozen source + hashed bytes on disk -----------------------
    export = cast("dict[str, Any]", seen["export_part"])
    assert export["source_artifact_ref"] == build["artifact_ref"]
    assert export["paths"] and export["export_hashes"]
    for path in cast("list[str]", export["paths"]):
        assert (surface.project_root / path).exists() or path.startswith("/")

    # -- documents: both files exported, dimensions in the result -----------
    drawing = cast("dict[str, Any]", seen["generate_drawing"])
    assert drawing["source_artifact_ref"] == build["artifact_ref"]
    assert drawing["paths"] == [drawing["pdf"], drawing["svg"]]
    assert any(dimension["text"] for dimension in cast("list[Any]", drawing["dimensions"]))
    for path in cast("list[str]", drawing["paths"]):
        assert (surface.project_root / path).exists()
    doc = cast("dict[str, Any]", seen["generate_doc"])
    assert doc["source_artifact_ref"] == build["artifact_ref"]
    assert "Bill of materials" in doc["markdown"]
    for path in cast("list[str]", doc["paths"]):
        assert (surface.project_root / path).exists()

    # -- query_snapshot: text + refs only, never child images ---------------
    snapshot = cast("dict[str, Any]", seen["query_snapshot"])
    assert snapshot["status"] == "ok" and snapshot["answer"]
    assert snapshot["usage"]["turns"] == 1
    assert all("data" not in str(ref) for ref in snapshot["render_artifacts"])

    # -- project checks ------------------------------------------------------
    assert seen["list_project_checks"]["status"] == "ok"
    assert seen["create_project_check"]["content_hash"]
    assert seen["edit_project_check"]["status"] == "applied"

    # -- delegation: one stable child, one terminal, replayable status -------
    delegated = cast("dict[str, Any]", seen["delegate_part_agent"])
    assert delegated["status"] == "completed"
    assert delegated["child_run_id"] and delegated["delegation_ref"]
    assert delegated["result_artifact_ref"]
    status = cast("dict[str, Any]", seen["get_delegation_status"])
    assert status["child_run_id"] == delegated["child_run_id"]
    assert status["status"] == "completed"
    # Cancelling an already-terminal delegation returns the unchanged terminal.
    assert seen["cancel_delegation"]["status"] == "completed"
    assert surface.runtime.delegation_runner.children == [delegated["child_run_id"]]

    # -- ask_user: a real suspension, surfaced as question/answer events -----
    assert len(answered) == 1 and answered[0]["question"] == "Ship it?"
    questions = events_of(result, "question")
    answers = events_of(result, "answer")
    assert len(questions) == 1 and len(answers) == 1
    assert questions[0]["seq"] < answers[0]["seq"]
    assert seen["ask_user"]["selection"] == "yes"

    # -- every dispatch carried trusted invocation metadata ------------------
    records = surface.recorder.calls
    assert records, "no dispatch reached Python"
    for record in records:
        assert record.invocation.get("session_id") == session_id
        assert record.invocation.get("entry_id")
        assert record.invocation.get("provider_call_id")
    assert len({record.invocation_id for record in records}) == len(records)
