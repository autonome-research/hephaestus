"""G11B clauses 1-5: the fourth region and its AST contract.

The grammar is stated as an AST contract and **not** as the word "nested",
because every realistic selector is a chain of nested calls: a rule refusing
nested calls would refuse §2.1's own canonical example and leave the region able
to tag a bare solid and nothing else. Clause 3 is the negative control that
keeps this suite honest — a tightening that refuses the mechanism is a defect,
not a stricter gate.

Every case below is decidable by a parser, and every one is asserted at
``parse_generator`` — hence at index time, hence at publish, since
``validate_content`` builds the index. Nothing here executes a generator.
"""

from __future__ import annotations

import ast
from typing import Any, cast

import pytest
from _g11b import _RIG_BODY, RIG_REGION, RIG_SRC
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import (
    BIND_MARKER,
    BODY_MARKER,
    INTERFACE_MARKER,
    PARAMS_MARKER,
    RegistryRefusal,
    parse_generator,
)
from hephaestus.core.registry._generator import _REFUSED_SELECTOR_NODES

# --------------------------------------------------------------------------
# helpers


def region(*statements: str) -> str:
    """The rig body plus an ``interface`` region built from ``statements``."""
    return _RIG_BODY + INTERFACE_MARKER + "\n" + "\n".join(statements) + "\n"


def refuse(*statements: str) -> RegistryRefusal:
    with pytest.raises(RegistryRefusal) as caught:
        parse_generator(region(*statements), source="fixture/generator.py")
    return caught.value


def reasons(error: RegistryRefusal) -> set[str]:
    return set(cast("list[Any]", error.detail["reasons"]))


# ==========================================================================
# clause 1 — the fourth marker, its position and its cardinality


def test_a_generator_with_an_interface_region_parses() -> None:
    parsed = parse_generator(RIG_SRC, source="fixture/generator.py")
    assert parsed.root_name == "_rig"
    assert parsed.interface_names == ("mount_face", "shaft", "shaft_ring", "rail", "envelope")
    assert parsed.interface_region.splitlines()[0].startswith("tag(_rig.faces()")
    # The body stops at the interface marker: `part.geometry = <name>` is still
    # the last BODY statement, and the region is not part of it.
    assert parsed.body_region.splitlines()[-1] == "part.geometry = _rig"
    assert INTERFACE_MARKER not in parsed.body_region


def test_a_generator_without_an_interface_region_still_parses() -> None:
    """Optional, because a legacy store part has none and must behave as today."""
    parsed = parse_generator(_RIG_BODY, source="fixture/generator.py")
    assert parsed.interface_region == ""
    assert parsed.interface_names == ()


def test_the_interface_marker_is_refused_twice_over() -> None:
    doubled = RIG_SRC + INTERFACE_MARKER + "\n"
    with pytest.raises(ValidationError) as caught:
        parse_generator(doubled, source="fixture/generator.py")
    assert "at most one" in str(caught.value)
    assert INTERFACE_MARKER in str(caught.value)


def test_interface_before_body_is_refused() -> None:
    out_of_order = "\n".join(
        [
            PARAMS_MARKER,
            "PARAMS = {}",
            BIND_MARKER,
            INTERFACE_MARKER,
            'tag(_rig.faces()[0], "mount_face")',
            BODY_MARKER,
            "_rig = Box(1.0, 1.0, 1.0)",
            "part.geometry = _rig",
            "",
        ]
    )
    with pytest.raises(ValidationError) as caught:
        parse_generator(out_of_order, source="fixture/generator.py")
    assert "params -> bind -> body -> interface order" in str(caught.value)


@pytest.mark.parametrize("marker", [PARAMS_MARKER, BIND_MARKER, BODY_MARKER])
def test_the_first_three_markers_are_still_required_exactly_once(marker: str) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_generator(RIG_SRC + marker + "\n", source="fixture/generator.py")
    assert "exactly one" in str(caught.value)


def test_body_bind_params_order_is_still_enforced() -> None:
    swapped = RIG_SRC.replace(PARAMS_MARKER, "@@PARAMS@@").replace(BIND_MARKER, PARAMS_MARKER)
    swapped = swapped.replace("@@PARAMS@@", BIND_MARKER)
    with pytest.raises(ValidationError) as caught:
        parse_generator(swapped, source="fixture/generator.py")
    assert "order" in str(caught.value)


# ==========================================================================
# clause 3 — the canonical region parses (the negative control on clause 2)

CANONICAL = """# --- hephaestus-store: params ---
PARAMS = {}
# --- hephaestus-store: bind ---
# --- hephaestus-store: body ---
_root = Box(10.0, 10.0, 4.0) + Pos(0.0, 0.0, 4.0) * Cylinder(2.0, 6.0)
part.geometry = _root
# --- hephaestus-store: interface ---
tag(_root.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")
tag(_root.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[0], "shaft")
"""


def test_the_canonical_region_of_the_spec_parses_clean() -> None:
    """Attribute chains, method calls, filter_by/sort_by arguments, a subscript.

    §2.1's own example. If this ever fails, the tightening that broke it is the
    defect — the region exists to name *selected* topology, and every realistic
    selector is a chain of nested calls.
    """
    parsed = parse_generator(CANONICAL, source="fixture/generator.py")
    assert parsed.interface_names == ("mount_face", "shaft")
    assert parsed.root_name == "_root"


def test_a_multi_line_selector_parses() -> None:
    """The shipped inserts need one; a line-oriented rule would have refused it."""
    parsed = parse_generator(
        region(
            "tag(",
            "    _rig.faces()",
            "    .filter_by(GeomType.PLANE)",
            "    .sort_by(SortBy.AREA)[-2:]",
            "    .sort_by_distance(",
            "        _rig.faces().filter_by(GeomType.CYLINDER).sort_by(SortBy.RADIUS)[-1]",
            "    )[0],",
            '    "mount_face",',
            ")",
        ),
        source="fixture/generator.py",
    )
    assert parsed.interface_names == ("mount_face",)


# ==========================================================================
# clause 2 — interface_region_violation, enumerated against the AST contract


@pytest.mark.parametrize(
    ("case", "statement"),
    [
        ("not a tag call", "_rig.faces()"),
        ("a bare name", "_rig"),
        ("a docstring", '"""a region is statements, not prose"""'),
        ("an assignment", '_face = _rig.faces()[0]\ntag(_face, "mount_face")'),
        ("an augmented assignment", "_boss_h += 1.0"),
        ("a walrus statement", "(_face := _rig.faces()[0])"),
        ("a tag call as a sub-expression", '[tag(_rig.faces()[0], "mount_face")]'),
        ("a call on something other than the name tag", 'part.tag(_rig.faces()[0], "x")'),
        ("a computed name", 'tag(_rig.faces()[0], "mount" + "_face")'),
        ("a name that is not a string", "tag(_rig.faces()[0], 3)"),
        ("a name violating the grammar", 'tag(_rig.faces()[0], "Mount_Face")'),
        ("a name carrying the reserved infix", 'tag(_rig.faces()[0], "seat__face")'),
        ("a keyword argument", 'tag(_rig.faces()[0], name="mount_face")'),
        ("a double-starred keyword argument", 'tag(**{"shape": _rig.faces()[0]})'),
        ("one positional argument", "tag(_rig.faces()[0])"),
        ("three positional arguments", 'tag(_rig.faces()[0], "mount_face", 1)'),
        # The clause enumerates "keywords, `*args`, or other than two positional
        # arguments" — three named forms, and this is the `*args` one: a starred
        # argument to the `tag` call ITSELF, as distinct from an `ast.Starred`
        # inside argument 1 (below), which is a different node in a different
        # position. It was the one named form with no case, and it must refuse
        # for the stated reason and not incidentally: the arity of a call whose
        # arguments are spliced at runtime is not decidable by a parser, so the
        # region contract cannot admit it at all.
        ("a starred argument to the tag call itself", 'tag(*[_rig.faces()[0], "mount_face"])'),
        (
            "a starred argument beside a positional one",
            'tag(_rig.faces()[0], *["mount_face"])',
        ),
        ("a lambda in argument 1", 'tag(_rig.faces().sort_by(lambda f: f.area)[0], "mount_face")'),
        (
            "a comprehension in argument 1",
            'tag(_rig.faces().sort_by(SortBy.AREA)[[0 for _ in [0]][0]], "mount_face")',
        ),
        (
            "a starred expression in argument 1",
            'tag(_rig.faces().sort_by(*[SortBy.AREA])[0], "mount_face")',
        ),
        (
            "an f-string in argument 1",
            'tag(_rig.faces().filter_by(f"{GeomType.PLANE}")[0], "mount_face")',
        ),
        (
            "a walrus in argument 1",
            'tag(_rig.faces().sort_by(SortBy.AREA)[(_i := 0)], "mount_face")',
        ),
        (
            "a free name outside the whitelist",
            'tag(_rig.faces().filter_by(NotAName)[0], "mount_face")',
        ),
        (
            "a parameter read, which is the bind region's alone",
            'tag(_rig.faces().filter_by(Plane(origin=(0, 0, p.boss_h)))[0], "mount_face")',
        ),
    ],
)
def test_the_ast_contract_refuses_each_decidable_violation(case: str, statement: str) -> None:
    error = refuse(statement)
    assert "interface_region_violation" in reasons(error), f"{case}: {error}"


def test_a_name_spelled_across_lines_is_refused() -> None:
    """Implicit concatenation is a ``str`` constant the literal rewrite cannot splice."""
    error = refuse('tag(_rig.faces()[0], "mount"\n    "_face")')
    assert error.reason == "interface_region_violation"
    assert "across lines" in error.message


def test_the_same_interface_may_not_be_tagged_twice_in_one_region() -> None:
    error = refuse(
        'tag(_rig.faces().sort_by(SortBy.AREA)[-1], "mount_face")',
        'tag(_rig.faces().sort_by(SortBy.AREA)[0], "mount_face")',
    )
    assert error.reason == "interface_region_violation"
    assert "twice" in error.message


def test_await_in_a_selector_is_refused() -> None:
    """``ast.parse`` admits a top-level ``await`` node, so the contract must refuse it."""
    assert ast.Await in _REFUSED_SELECTOR_NODES
    error = refuse('tag(await _rig.faces()[0], "mount_face")')
    assert "interface_region_violation" in reasons(error)
    assert "Await" in error.message


# -- the whitelist itself, asserted rather than assumed ---------------------


def test_selector_names_equals_the_injected_set_minus_the_two_declared_exclusions() -> None:
    """§2.1's equation, so the parse rule and the runtime namespace cannot drift.

    A build123d upgrade cannot silently widen or narrow what the region may
    name, and a harness handle cannot creep back in — in either direction the
    equality fails here rather than in a generator someone publishes.
    """
    from hephaestus.core.executor.namespace import (
        _DUNDERS,
        _HANDLES,
        SELECTOR_NAMES,
        CheckRegistry,
        HcNamespace,
        ImportRegistry,
        ParamState,
        PartOutput,
        build_namespace,
        injected_names,
    )
    from hephaestus.core.executor.tags import TagRegistry

    namespace = build_namespace(
        param_state=ParamState(scope="part", overrides={}),
        hc=HcNamespace({}),
        part=PartOutput(),
        tag_registry=TagRegistry(),
        check_registry=CheckRegistry(),
        imports=ImportRegistry({}),
    )
    assert injected_names(namespace) - _DUNDERS - _HANDLES == SELECTOR_NAMES
    assert {"__builtins__", "__name__"} == _DUNDERS
    assert {"p", "part", "tag", "hc", "check", "CHECKS", "import_step", "approx"} == _HANDLES


@pytest.mark.parametrize("name", ["GeomType", "SortBy", "Axis", "math", "Plane", "Compound"])
def test_the_pure_geometry_vocabulary_is_admitted(name: str) -> None:
    from hephaestus.core.executor.namespace import SELECTOR_NAMES

    assert name in SELECTOR_NAMES


@pytest.mark.parametrize(
    "handle", ["p", "part", "tag", "hc", "check", "CHECKS", "import_step", "approx"]
)
def test_every_harness_handle_is_refused_in_the_region_by_name(handle: str) -> None:
    from hephaestus.core.executor.namespace import SELECTOR_NAMES

    assert handle not in SELECTOR_NAMES
    error = refuse(f'tag(_rig.faces().filter_by({handle})[0], "mount_face")')
    assert "interface_region_violation" in reasons(error)
    assert handle in error.message


# ==========================================================================
# clause 4 — rooting, and the body-local refusal


def test_a_chain_root_that_is_another_body_local_is_refused() -> None:
    error = refuse('tag(_plate.faces().sort_by(SortBy.AREA)[-1], "mount_face")')
    assert error.reason == "interface_root_violation"
    assert "_plate" in error.message and "_rig" in error.message


def test_a_chain_root_that_is_a_whitelisted_callable_is_refused() -> None:
    """``Compound(children=[_rig]).faces()[0]`` roots at ``Compound``, not at a binding."""
    error = refuse('tag(Compound(children=[_rig]).faces()[0], "mount_face")')
    assert error.reason == "interface_root_violation"
    assert "Compound" in error.message and "_rig" in error.message


@pytest.mark.parametrize(
    ("shape", "statement"),
    [
        (
            "geometric",
            'tag(_rig.faces().sort_by(SortBy.DISTANCE, _boss.center())[0], "mount_face")',
        ),
        (
            "scalar",
            'tag(_rig.faces().filter_by(Plane(origin=(0, 0, _boss_h)))[0], "mount_face")',
        ),
    ],
)
def test_a_selector_rooted_correctly_may_still_not_load_a_local(shape: str, statement: str) -> None:
    """The clause with the sharpest teeth in the sub-gate.

    The rewrite retargets the ROOT to the placed instance. A body or bind local
    still names pre-placement geometry, or a coordinate in the pre-placement
    frame, and there is no placed counterpart to retarget it to — so the
    selector measures the placed shape in the unplaced frame and resolves to a
    real face that is the wrong one. Silently.
    """
    error = refuse(statement)
    assert error.reason == "interface_body_local_reference", shape
    assert "_boss" in error.message


def test_the_root_itself_is_of_course_loadable() -> None:
    parsed = parse_generator(
        region('tag(_rig.faces().sort_by(SortBy.AREA)[-1], "mount_face")'),
        source="fixture/generator.py",
    )
    assert parsed.interface_names == ("mount_face",)


# ==========================================================================
# clause 11 — file IO in the region is refused BEFORE publication


def test_a_denied_builtin_in_the_region_fires_both_rules_at_parse_time() -> None:
    """``open`` is neither the root name nor in the whitelist, so both fire.

    Both are decidable by a parser, so both fire at index time and therefore at
    publish — which is why the *runtime* sandbox-denial form of this clause
    lives at G11A clause 22, against the body region, where it is reachable at
    all. A tree like this can never be published or pinned.
    """
    from hephaestus.core.executor.namespace import DENIED_BUILTINS

    assert "open" in DENIED_BUILTINS
    error = refuse('tag(open("/etc/passwd").read(), "mount_face")')
    assert reasons(error) == {"interface_region_violation", "interface_root_violation"}
    assert "open" in error.message


@pytest.mark.parametrize("denied", ["open", "exec", "eval", "__import__"])
def test_every_denied_builtin_is_refused_in_the_region(denied: str) -> None:
    error = refuse(f'tag(_rig.faces().filter_by({denied})[0], "mount_face")')
    assert "interface_region_violation" in reasons(error)


def test_such_a_tree_cannot_be_indexed_or_published(tmp_path: Any) -> None:
    from _g11b import component_tree, index_of
    from hephaestus.core.registry import publish_registry

    root = component_tree(
        tmp_path / "hostile",
        generator=region('tag(open("/etc/passwd").read(), "mount_face")'),
    )
    with pytest.raises(RegistryRefusal):
        index_of(root)
    with pytest.raises(RegistryRefusal):
        publish_registry(root)


# ==========================================================================
# clause 5 — tag stays forbidden everywhere else


def test_tag_in_the_body_region_is_refused_with_its_existing_message() -> None:
    with_tag = _RIG_BODY.replace(
        "part.geometry = _rig",
        'tag(_rig.faces()[0], "mount_face")\npart.geometry = _rig',
    )
    with pytest.raises(ValidationError) as caught:
        parse_generator(with_tag + RIG_REGION, source="fixture/generator.py")
    assert str(caught.value) == (
        "fixture/generator.py: the generator body must not reference 'tag' "
        "(store generators are pure geometry)"
    )


@pytest.mark.parametrize(("marker", "label"), [(PARAMS_MARKER, "params"), (BIND_MARKER, "bind")])
def test_tag_in_the_params_or_bind_region_is_refused(marker: str, label: str) -> None:
    """Neither region refused it before: both skip every ``ast.Expr`` statement.

    So a bare ``tag(...)`` call in either sailed through the contract and then
    executed, since the whole generator runs as one script — an interface tag
    emitted from outside the region the record is compared against.
    """
    poisoned = RIG_SRC.replace(marker, marker + '\ntag(_rig.faces()[0], "mount_face")', 1)
    with pytest.raises(ValidationError) as caught:
        parse_generator(poisoned, source="fixture/generator.py")
    assert str(caught.value) == (
        f"fixture/generator.py: the {label} region must not reference 'tag'; the "
        "interface region is the only region permitted to (PARTS_STORE.md §2.1)"
    )


@pytest.mark.parametrize("forbidden", ["hc", "check", "CHECKS"])
def test_the_other_forbidden_names_stay_forbidden_in_the_body(forbidden: str) -> None:
    poisoned = _RIG_BODY.replace("part.geometry = _rig", f"_x = {forbidden}\npart.geometry = _rig")
    with pytest.raises(ValidationError) as caught:
        parse_generator(poisoned + RIG_REGION, source="fixture/generator.py")
    assert forbidden in str(caught.value)
