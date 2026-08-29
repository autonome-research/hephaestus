"""G11B clauses 9, 12, 13 and 14: verification against built topology.

Everything here runs the real generator under the real probed sandbox, because
the whole claim of §2.3 is that a declared interface is checked against
geometry that actually built — at the caller's parameters *and at the caller's
placement*. A verdict computed from a synthetic in-memory shape would prove
nothing about the channel the numbers travel down: ``geom_type`` is read off the
OCP adaptor **in the worker**, rides ``tag_fingerprints`` through
``descriptors_to_json`` and the runner's parse, and is merged with the source
map's placements on the far side.

Clause 9 is the clause the placement bug would have failed. With the region
emitted above the tail, or with only the chain root rewritten, every interface
of an instance placed away from the origin resolves to ``solid_index=None``,
``PartGeometry._tag_shape`` raises ``unaddressable_anchor`` and the constraint
row is unresolvable — for a motor seated on a pad, which is the whole point of
the mechanism. The last test in that section builds exactly that fragment on
purpose, so the clause is proved to have teeth rather than assumed to.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, cast

import pytest
from _g11b import (
    _RIG_BODY,
    DRIFT_ROT,
    DRIFTING_INTERFACE,
    EQUAL_MEASURE_ROT,
    RIG_INTERFACES,
    RIG_SRC,
    SEAT_POS,
    component_tree,
    fragment_for,
    ops_for,
    requires_bwrap,
    rig,
    store_ops,
)
from hephaestus.core.addressing import Resolution
from hephaestus.core.assembly import PartGeometry, UnresolvableAnchorError
from hephaestus.core.executor.sandbox.base import ExecBackend
from hephaestus.core.registry import (
    INTERFACE_MARKER,
    INTERFACE_TOPOLOGY,
    RegistryError,
)

pytestmark = requires_bwrap

#: Rule 4 (`mission_plan.md` performance rule): the placement-verification build
#: doubles the sandbox cost of a placed instance, so the two-build path is
#: budgeted rather than merely disclosed. Generous against the pinned CI image's
#: cold cache; the clause is "the second build is bounded and named", not a
#: microbenchmark.
TWO_BUILD_BUDGET_S = 180.0


class CountingBackend:
    """The real sandbox, counting how many worker jobs cross the boundary.

    A wrapper rather than a fake: clause 12 is about how many times the *real*
    boundary is crossed, and a stub backend would count invocations of itself.
    """

    def __init__(self) -> None:
        from hephaestus.core.executor.sandbox.bwrap import BwrapBackend

        self._inner: ExecBackend = BwrapBackend()
        self.runs = 0

    @property
    def name(self) -> str:
        return self._inner.name

    def probe(self) -> Any:
        return self._inner.probe()

    def execute(self, spec: Any, stdin_payload: bytes) -> Any:
        self.runs += 1
        return self._inner.execute(spec, stdin_payload)


# ==========================================================================
# clause 9 — placement resolution at a non-trivial pos


@pytest.mark.parametrize(
    ("label", "pos"),
    [
        ("translation and rotation", {"x": 12.0, "y": -4.0, "z": 7.0, "rz": 30.0}),
        ("translation only", {"x": 12.0, "y": -4.0, "z": 7.0}),
        ("rotation only", {"rz": 30.0}),
    ],
)
def test_every_interface_tag_resolves_at_a_placement(
    label: str, pos: dict[str, float], tmp_path: Path
) -> None:
    """Placed, addressable, and reaching a shape through the 8C resolver's own path."""
    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=pos, instance="motor_a")
    emitted = cast("list[str]", result["interfaces"])
    assert emitted == [f"motor_a__{name}" for name, _k, _r in RIG_INTERFACES], label

    geometry = _consumer_geometry(tmp_path, cast("str", result["script_fragment"]))
    for name in emitted:
        placement = geometry.placements[name]
        assert placement.solid_index is not None, (label, name)
        assert placement.topo_index is not None, (label, name)
        assert geometry.shape_for(Resolution(kind="tag", name=name)) is not None, (label, name)


def test_a_body_local_rooted_fragment_resolves_to_nothing(tmp_path: Path) -> None:
    """The clause has teeth: this is the fragment the renderer must never produce.

    Constructed by bypassing clause 4 — the emitted region's root is rewritten
    back to the *unplaced* body local, which is exactly what a renderer that
    appended the region above the tail would have produced. ``IsSame`` is
    location-sensitive, so every tag misses the final compound, resolves to
    ``solid_index=None`` and raises ``unaddressable_anchor`` at constraint time.

    The tag names are stripped of their ``__`` scoping here for one reason: with
    them the build does not survive to be inspected at all, which the companion
    test asserts. Under plain names the build is green and the damage is exactly
    what §2 says it is — silent until an anchor is used.
    """
    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=dict(SEAT_POS), instance="motor_a")
    fragment = cast("str", result["script_fragment"])
    sabotaged = _sabotage(fragment, _prefix_of(fragment)).replace("motor_a__", "probe_")
    geometry = _consumer_geometry(tmp_path, sabotaged)
    for name, _klass, _role in RIG_INTERFACES:
        tag = f"probe_{name}"
        assert geometry.placements[tag].solid_index is None, name
        with pytest.raises(UnresolvableAnchorError) as caught:
            geometry.shape_for(Resolution(kind="tag", name=tag))
        assert caught.value.reason == "unaddressable_anchor"


def test_the_same_sabotage_under_the_reserved_infix_fails_the_build(tmp_path: Path) -> None:
    """And this is why the warning became an error for a ``__`` name.

    The identical damage, with the emitted names left alone: the consumer's
    build stops, naming every dead tag, instead of going green and handing the
    author five anchors that resolve to nothing.
    """
    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=dict(SEAT_POS), instance="motor_a")
    fragment = cast("str", result["script_fragment"])
    error = _failed_consumer_build(tmp_path, _sabotage(fragment, _prefix_of(fragment)))
    assert error.message.startswith("interface_not_placed:")
    for name, _klass, _role in RIG_INTERFACES:
        assert f"motor_a__{name}" in error.message


# ==========================================================================
# clause 12 — the second build happens exactly when it must


@pytest.mark.parametrize(
    ("label", "pos", "builds"),
    [
        ("pos absent", None, 1),
        ("pos empty", {}, 1),
        ("pos all zero", {"x": 0.0, "y": 0.0, "z": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}, 1),
        ("pos non-zero", {"z": 7.0}, 2),
        ("rotation only", {"rz": 30.0}, 2),
    ],
)
def test_the_placement_build_runs_iff_the_placement_expression_is_non_empty(
    label: str, pos: dict[str, float] | None, builds: int, tmp_path: Path
) -> None:
    """When ``_placement`` returns ``""`` the instance aliases the root: nothing to re-verify."""
    backend = CountingBackend()
    ops = ops_for(component_tree(tmp_path / "reg"), tmp_path, backend=backend)
    fragment_for(ops, params={"boss_h": 4.0}, pos=pos)
    assert backend.runs == builds, label


def test_the_two_build_path_stays_within_its_budget(tmp_path: Path) -> None:
    ops = store_ops(tmp_path)
    started = time.monotonic()
    fragment_for(ops, params={"boss_h": 4.0}, pos=dict(SEAT_POS))
    elapsed = time.monotonic() - started
    assert elapsed < TWO_BUILD_BUDGET_S, f"two-build path took {elapsed:.1f}s"


# ==========================================================================
# clause 13 — class verification against the §2.3 table


def test_the_five_table_rows_are_each_verified_positively(tmp_path: Path) -> None:
    """Including ``("solid", "OTHER")``, which is an ADMITTING row, not a fallthrough.

    A solid has no single adaptor, so the worker writes ``OTHER`` by definition
    rather than by failure. If that row were a fallthrough, a face whose surface
    the adaptor cannot classify would be admitted as a ``solid`` — and the
    negative cases below would then pass for the wrong reason.
    """
    assert set(INTERFACE_TOPOLOGY) == {klass for _n, klass, _r in RIG_INTERFACES}
    assert INTERFACE_TOPOLOGY["solid"] == ("solid", "OTHER")
    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=dict(SEAT_POS), instance="motor_a")
    assert cast("list[str]", result["interfaces"]) == [
        f"motor_a__{name}" for name, _k, _r in RIG_INTERFACES
    ]


@pytest.mark.parametrize(
    ("declared", "observed"),
    [
        ("cylindrical_face", ("face", "PLANE")),
        ("planar_face", ("face", "CYLINDER")),
        ("circular_edge", ("edge", "LINE")),
        ("linear_edge", ("edge", "CIRCLE")),
        ("solid", ("face", "PLANE")),
    ],
)
def test_a_declared_class_is_refused_against_the_wrong_topology(
    declared: str, observed: tuple[str, str], tmp_path: Path
) -> None:
    """Decided on the worker-computed ``geom_type``, not on the three-way ``kind``.

    ``planar_face`` against a cylindrical face is the pair the three-way
    classifier cannot see at all: both are ``kind == "face"``, which is why
    nothing before this stage could have caught it.
    """
    ops = _ops_with_one_interface(tmp_path, declared=declared, selector=_selector_for(observed))
    with pytest.raises(RegistryError) as caught:
        fragment_for(ops, params={"boss_h": 4.0})
    assert caught.value.reason == "interface_class_mismatch"
    assert caught.value.data["declared"] == declared
    assert (caught.value.data["observed_kind"], caught.value.data["observed_geom_type"]) == observed
    assert "probe" in caught.value.message


@pytest.mark.parametrize(
    ("surface", "solid", "selector"),
    [
        (
            "a cone",
            "Pos(0.0, 0.0, -3.0) * Cone(6.0, 2.0, 4.0)",
            "_rig.faces().filter_by(GeomType.CONE).sort_by(SortBy.AREA)[-1]",
        ),
        (
            "a torus",
            "Pos(0.0, 0.0, -3.0) * Torus(9.0, 1.5)",
            "_rig.faces().filter_by(GeomType.TORUS).sort_by(SortBy.AREA)[-1]",
        ),
    ],
)
def test_a_face_the_adaptor_cannot_classify_matches_no_row(
    surface: str, solid: str, selector: str, tmp_path: Path
) -> None:
    """``("face", "OTHER")`` is a refusal, not a fallthrough into the ``solid`` row.

    This stage's consumers — 8C ``coincident`` / ``concentric`` / ``fit``, Stage
    9 ``revolute`` / ``prismatic`` — accept none of them, and admitting a class
    the consumers cannot use is how ``mating_features`` happened. Admitting a
    further surface class is a contract amendment, not a bug fix.
    """
    body = _RIG_BODY.replace("_rig = _plate + _boss", f"_rig = _plate + _boss + {solid}")
    ops = _ops_with_one_interface(tmp_path, declared="planar_face", selector=selector, body=body)
    with pytest.raises(RegistryError) as caught:
        fragment_for(ops, params={"boss_h": 4.0})
    assert caught.value.reason == "interface_class_mismatch", surface
    assert caught.value.data["observed_kind"] == "face"
    assert caught.value.data["observed_geom_type"] == "OTHER"


@pytest.mark.parametrize(
    ("kind", "selector"),
    [
        ("wire", "_rig.faces().sort_by(SortBy.AREA)[-1].outer_wire()"),
        ("vertex", "_rig.vertices().sort_by(SortBy.DISTANCE)[0]"),
    ],
)
def test_a_wire_or_a_vertex_appears_in_no_row(kind: str, selector: str, tmp_path: Path) -> None:
    """Named as the class mismatch it is, not as "your anchor is not placed".

    ``resolve_placements`` only locates solids, faces and edges, so both of
    these carry ``solid_index=None`` too — and reporting them as
    ``interface_not_placed`` would send the author hunting a composition bug
    that is not there. The two refusals call for different fixes, so the class
    check runs first.
    """
    ops = _ops_with_one_interface(tmp_path, declared="solid", selector=selector)
    with pytest.raises(RegistryError) as caught:
        fragment_for(ops, params={"boss_h": 4.0})
    assert caught.value.reason == "interface_class_mismatch"
    assert caught.value.data["observed_kind"] == kind


@pytest.mark.parametrize(
    ("label", "params", "pos"),
    [
        ("default parameters", {}, None),
        ("a caller-supplied parameter set", {"boss_h": 9.0}, None),
        ("a non-zero pos", {"boss_h": 6.0}, dict(SEAT_POS)),
    ],
)
def test_class_verification_fires_at_every_call_shape(
    label: str, params: dict[str, float], pos: dict[str, float] | None, tmp_path: Path
) -> None:
    ops = _ops_with_one_interface(
        tmp_path,
        declared="planar_face",
        selector="_rig.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1]",
    )
    with pytest.raises(RegistryError) as caught:
        fragment_for(ops, params=params, pos=pos)
    assert caught.value.reason == "interface_class_mismatch", label


def test_interface_not_placed_is_the_stores_own_guard_and_stays_reachable() -> None:
    """Unreachable through a rooted selector *by construction* — and still checked.

    §2.1 rule 1 says why: an interface that is not reachable from the published
    shape is unaddressable anyway, so requiring the chain root to be the
    published name removes the store-side case rather than hiding it. The guard
    stays because the placement build's evidence is assembled from two channels
    and a missing placement must never be read as a pass. Its *reachable* site
    is the consumer's own build, which clause 10 asserts against a real build.
    """
    from hephaestus.core.registry._component import parse_component
    from hephaestus.core.registry._ops import RegistryOps, _Evidence
    from hephaestus.core.registry._parts import StorePart

    record = parse_component(
        rig(
            **_ONE_INTERFACE, interfaces=[{"name": "probe", "class": "planar_face", "role": "bore"}]
        ),
        source="fixture",
    )
    part = StorePart(
        id="rig",
        name="rig",
        summary="",
        keywords=(),
        params={},
        preview="",
        script_path=Path("generator.py"),
        registry="fixture",
        digest="sha256:0",
        component=record,
    )
    ops = object.__new__(RegistryOps)
    with pytest.raises(RegistryError) as absent:
        ops._check_declared(part, record, {}, at="the generator's own build")
    assert absent.value.reason == "interface_not_placed"
    unplaced = {"probe": _Evidence(kind="face", geom_type="PLANE", scalar=1.0, solid_index=None)}
    with pytest.raises(RegistryError) as dead:
        ops._check_declared(part, record, unplaced, at="the caller's placement")
    assert dead.value.reason == "interface_not_placed"


# ==========================================================================
# clause 14 — interface_placement_drift, and its exact limit


def _drifting_ops(tmp_path: Path, name: str) -> Any:
    return store_ops(
        tmp_path / name,
        generator=RIG_SRC.replace(
            'tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")',
            DRIFTING_INTERFACE,
        ),
    )


def test_a_pos_dependent_selector_under_a_reordering_rotation_is_refused(
    tmp_path: Path,
) -> None:
    """``sort_by(Axis.X)[-1]``: a world axis, which the placement moves."""
    ops = _drifting_ops(tmp_path, "drift")
    with pytest.raises(RegistryError) as caught:
        fragment_for(ops, params={"boss_h": 4.0}, pos=dict(DRIFT_ROT))
    assert caught.value.reason == "interface_placement_drift"
    assert caught.value.data["interface"] == "mount_face"
    assert cast("float", caught.value.data["unplaced_scalar"]) == pytest.approx(120.0)
    assert cast("float", caught.value.data["placed_scalar"]) == pytest.approx(180.0)


def test_the_same_generator_at_the_origin_is_silent(tmp_path: Path) -> None:
    """No placement expression, no second build, nothing to disagree with."""
    ops = _drifting_ops(tmp_path, "drift-origin")
    assert "interfaces" in fragment_for(ops, params={"boss_h": 4.0})


def test_a_pos_invariant_selector_under_the_same_rotation_is_silent(tmp_path: Path) -> None:
    ops = store_ops(tmp_path)
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=dict(DRIFT_ROT), instance="motor_a")
    assert cast("list[str]", result["interfaces"])[0] == "motor_a__mount_face"


def test_two_faces_of_equal_measure_are_not_distinguished(tmp_path: Path) -> None:
    """The documented limit, named here rather than left as an unstated gap.

    Under a half turn ``sort_by(Axis.X)[-1]`` picks the *other* end face — a
    different face, the same 120 mm^2. Area, length and volume are invariant
    under rigid motion, so nothing about the two descriptors differs and the
    rule stays silent. That is why ``interface_placement_drift`` reports drift
    and never certifies invariance: it is a *necessary, not sufficient*
    condition for selector pos-invariance, and the authoring rule §2.1 states
    is the real control.
    """
    ops = _drifting_ops(tmp_path, "drift-equal")
    assert "interfaces" in fragment_for(ops, params={"boss_h": 4.0}, pos=dict(EQUAL_MEASURE_ROT))


# --------------------------------------------------------------------------
# fixtures and small builders


def _selector_for(observed: tuple[str, str]) -> str:
    return {
        ("face", "PLANE"): "_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1]",
        ("face", "CYLINDER"): (
            "_rig.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1]"
        ),
        ("edge", "CIRCLE"): "_rig.edges().filter_by(GeomType.CIRCLE).sort_by(SortBy.LENGTH)[-1]",
        ("edge", "LINE"): "_rig.edges().filter_by(GeomType.LINE).sort_by(SortBy.LENGTH)[-1]",
    }[observed]


_counter = [0]

#: A one-interface probe record is a ``gear``, whose §1 required-interface table
#: asks for a single ``bore`` role — so the fixture can declare exactly one
#: interface and the class verdict below is unambiguous. A ``motor`` would need
#: both ``shaft`` and ``mount_face``, and the second one would decide nothing.
_ONE_INTERFACE: dict[str, Any] = {"class": "gear"}


def _ops_with_one_interface(
    tmp_path: Path, *, declared: str, selector: str, body: str = _RIG_BODY
) -> Any:
    """A component declaring exactly one interface, so the verdict is unambiguous."""
    _counter[0] += 1
    root = component_tree(
        tmp_path / f"one-{_counter[0]}",
        component=rig(
            **_ONE_INTERFACE, interfaces=[{"name": "probe", "class": declared, "role": "bore"}]
        ),
        generator=body + INTERFACE_MARKER + "\n" + f'tag({selector}, "probe")\n',
    )
    return ops_for(root, tmp_path)


def _prefix_of(fragment: str) -> str:
    """The instance name the fragment's own header tells the model to compose."""
    match = re.search(r"^#   (_\S+) into part\.geometry", fragment, re.M)
    assert match is not None, fragment
    return match.group(1)


def _sabotage(fragment: str, prefix: str) -> str:
    """Rewrite the emitted region's root back to the UNPLACED body local."""
    marker = f'{prefix}.label = "rig"\n'
    head, _, region = fragment.partition(marker)
    return (
        head
        + marker
        + re.sub(rf"(?<![A-Za-z0-9_]){re.escape(prefix)}(?![A-Za-z0-9_])", f"{prefix}_rig", region)
    )


def _consumer_script(fragment: str) -> str:
    prefix = _prefix_of(fragment)
    return (
        f"{fragment}\n"
        "pad = Box(60.0, 40.0, 8.0)\n"
        f"plate_body = Compound(children=[pad, {prefix}])\n"
        "part.geometry = plate_body\n"
    )


def _run_consumer(tmp_path: Path, script: str) -> Any:
    from hephaestus.core.executor.runner import BuildRequest, run_build
    from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

    _counter[0] += 1
    out = tmp_path / f"consumer-{_counter[0]}"
    return run_build(
        BuildRequest(part="gantry_plate", script=script, globals_source=None, origin="local"),
        backend=UnsafeLocalBackend(),
        out_dir=out,
    ), out


def _failed_consumer_build(tmp_path: Path, fragment: str) -> Any:
    build, _out = _run_consumer(tmp_path, _consumer_script(fragment))
    assert build.result.status == "failed", build.result
    error = build.result.error
    assert error is not None
    return error


def _consumer_geometry(tmp_path: Path, fragment: str) -> PartGeometry:
    """Build a consumer script that composes the instance, as a ``PartGeometry``.

    Assembled from the build's own artifacts — the BRep reloaded through the
    same ``load_brep_shape`` publication uses, and the source map's placements —
    so what resolves here resolves the way ``ASSEMBLY.md`` §2 requires: against
    a reloaded artifact that carries topology and nothing else.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape
    from hephaestus.core.executor.tags import TagPlacement
    from hephaestus.core.executor.worker import FINAL_BREP

    build, out = _run_consumer(tmp_path, _consumer_script(fragment))
    assert build.result.status == "ok", build.result.error
    raw = cast("dict[str, Any]", (build.source_map or {})["tags"])
    placements = {
        name: TagPlacement(
            kind=str(entry["kind"]),
            solid_index=entry["solid"],
            topo_index=entry["topo_index"],
            statement_index=int(entry["statement"]),
            line=int(entry["line"]),
        )
        for name, entry in cast("dict[str, dict[str, Any]]", raw).items()
    }
    shape = load_brep_shape((out / FINAL_BREP).read_bytes(), scratch_dir=out)
    solids = tuple(cast("Any", shape).solids())
    return PartGeometry(
        part="gantry_plate",
        artifact_ref="artifact:build:fixture",
        shape=shape,
        index=build.geometry_index(),
        solids=solids,
        runs=(),
        placements=placements,
        runs_partition=False,
    )
