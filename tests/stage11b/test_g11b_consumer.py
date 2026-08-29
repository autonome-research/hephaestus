"""G11B clauses 10 and 15: what the CONSUMER's build does with a pasted fragment.

Two hazards, both silent before this stage and both now build failures the
operator sees.

**The moved instance.** A fragment tags the *placed* copy. If the consumer then
composes a further transformed copy, the tagged topology is not in the final
compound at all, and today's worker would say so only as a ``tag_unresolved``
warning — right for a hand-authored tag whose author is still iterating, wrong
for a store fragment, where it means every anchor the model is about to write is
already dead. For a ``__``-infix name the warning becomes an error.

**The double paste.** ``TagRegistry`` documents last-wins re-tagging, which is
reasonable and deterministic for a hand-authored script and a silent
correctness failure for pasted fragments: two motors both emitting ``shaft``
leave one ``shaft`` tag, and a constraint anchored on it is measured against
whichever fragment was pasted lower in the file. A satisfied constraint about
the wrong solid. Scoped to ``__`` so every existing script keeps last-wins
byte-for-byte, which the last test here asserts rather than assumes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from _g11b import RIG_INTERFACES, SEAT_POS, fragment_for, requires_bwrap, store_ops
from hephaestus.core.executor.runner import BuildRequest, UnpublishedBuild, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend

pytestmark = requires_bwrap

_counter = [0]


def _build(tmp_path: Path, script: str) -> UnpublishedBuild:
    _counter[0] += 1
    return run_build(
        BuildRequest(part="gantry_plate", script=script, globals_source=None, origin="local"),
        backend=UnsafeLocalBackend(),
        out_dir=tmp_path / f"out-{_counter[0]}",
    )


def _prefix_of(fragment: str) -> str:
    """The instance name the fragment's own header tells the model to compose."""
    match = re.search(r"^#   (_\S+) into part\.geometry", fragment, re.M)
    assert match is not None, fragment
    return match.group(1)


def _instance(tmp_path: Path, ops: Any, instance: str | None, pos: dict[str, float]) -> str:
    result = fragment_for(ops, params={"boss_h": 4.0}, pos=pos, instance=instance)
    return cast("str", result["script_fragment"])


def _tags(build: UnpublishedBuild) -> dict[str, dict[str, Any]]:
    return cast("dict[str, dict[str, Any]]", (build.source_map or {})["tags"])


def _warnings(build: UnpublishedBuild) -> list[tuple[str, str]]:
    return [
        (warning.kind, str(warning.to_json().get("tag", ""))) for warning in build.result.warnings
    ]


# ==========================================================================
# clause 10 — interface_not_placed fires in the consumer's build


def test_a_transformed_copy_of_the_instance_fails_the_consumers_build(tmp_path: Path) -> None:
    """The composition moves the instance AFTER the paste, so every anchor is dead."""
    ops = store_ops(tmp_path)
    fragment = _instance(tmp_path, ops, "motor_a", dict(SEAT_POS))
    prefix = _prefix_of(fragment)
    build = _build(
        tmp_path,
        f"{fragment}\n"
        "pad = Box(60.0, 40.0, 8.0)\n"
        f"plate_body = Compound(children=[pad, Pos(0.0, 0.0, 1.0) * {prefix}])\n"
        "part.geometry = plate_body\n",
    )
    assert build.result.status == "failed"
    error = build.result.error
    assert error is not None
    assert error.message.startswith("interface_not_placed:")
    for name, _klass, _role in RIG_INTERFACES:
        assert f"motor_a__{name}" in error.message


def test_the_untransformed_composition_is_green(tmp_path: Path) -> None:
    """The control: the same script, composing the instance the header names."""
    ops = store_ops(tmp_path)
    fragment = _instance(tmp_path, ops, "motor_a", dict(SEAT_POS))
    prefix = _prefix_of(fragment)
    build = _build(
        tmp_path,
        f"{fragment}\n"
        "pad = Box(60.0, 40.0, 8.0)\n"
        f"plate_body = Compound(children=[pad, {prefix}])\n"
        "part.geometry = plate_body\n",
    )
    assert build.result.status == "ok", build.result.error
    assert _warnings(build) == []


def test_a_hand_authored_tag_in_the_same_position_still_only_warns(tmp_path: Path) -> None:
    """Unchanged for every script that does not use the reserved form.

    A plain tag whose topology leaves the compound is exactly the case the
    warning was written for — an author mid-iteration — and it keeps its
    warning and its green build.
    """
    build = _build(
        tmp_path,
        "pad = Box(60.0, 40.0, 8.0)\n"
        "spare = Pos(0.0, 0.0, 40.0) * Box(4.0, 4.0, 4.0)\n"
        'tag(spare.faces().sort_by(SortBy.AREA)[-1], "spare_face")\n'
        "part.geometry = pad\n",
    )
    assert build.result.status == "ok", build.result.error
    assert _warnings(build) == [("tag_unresolved", "spare_face")]
    assert _tags(build)["spare_face"]["solid"] is None


# ==========================================================================
# clause 15 — the overwrite hazard


def test_pasting_one_instance_twice_fails_with_duplicate_tag(tmp_path: Path) -> None:
    """Two pastes of one instance ARE one instance: same id, same params, same pos."""
    ops = store_ops(tmp_path)
    fragment = _instance(tmp_path, ops, "motor_a", dict(SEAT_POS))
    prefix = _prefix_of(fragment)
    build = _build(
        tmp_path,
        f"{fragment}\n{fragment}\n"
        "pad = Box(60.0, 40.0, 8.0)\n"
        f"plate_body = Compound(children=[pad, {prefix}])\n"
        "part.geometry = plate_body\n",
    )
    assert build.result.status == "failed"
    error = build.result.error
    assert error is not None
    assert error.message.startswith("duplicate_tag:")
    assert "motor_a__mount_face" in error.message
    # Both tagging statements are named, not just the survivor: an operator
    # needs to know which two pastes collided.
    statements = re.findall(r"statement (\d+) at line (\d+)", error.message)
    assert len(statements) == 2
    assert statements[0] != statements[1]


def test_two_instances_differing_only_by_instance_build_cleanly(tmp_path: Path) -> None:
    """Which is what ``instance`` is FOR — and why it scopes the locals too.

    The two fragments carry the same part, parameters and placement. Only the
    caller's ``instance`` differs, and that is enough to make them two pasteable
    copies with two disjoint tag sets.
    """
    ops = store_ops(tmp_path)
    left = _instance(tmp_path, ops, "motor_left", dict(SEAT_POS))
    right = _instance(tmp_path, ops, "motor_right", dict(SEAT_POS))
    assert _prefix_of(left) != _prefix_of(right)
    build = _build(
        tmp_path,
        f"{left}\n{right}\n"
        "pad = Box(60.0, 40.0, 8.0)\n"
        f"plate_body = Compound(children=[pad, {_prefix_of(left)}, {_prefix_of(right)}])\n"
        "part.geometry = plate_body\n",
    )
    assert build.result.status == "ok", build.result.error
    tags = _tags(build)
    left_tags = {name for name in tags if name.startswith("motor_left__")}
    right_tags = {name for name in tags if name.startswith("motor_right__")}
    assert len(left_tags) == len(right_tags) == len(RIG_INTERFACES)
    assert left_tags.isdisjoint(right_tags)
    for name in left_tags | right_tags:
        assert tags[name]["solid"] is not None, name


def test_a_hand_authored_script_still_re_tags_last_wins(tmp_path: Path) -> None:
    """Byte-for-byte as today, because the rule is scoped to the reserved infix.

    ``TagRegistry.tag`` documents last-wins for a re-tagged name, and a
    ``script_contract.md`` §5.3 amendment that broke a script not using the
    reserved form would be a regression, not a tightening.
    """
    build = _build(
        tmp_path,
        "pad = Box(60.0, 40.0, 8.0)\n"
        'tag(pad.faces().sort_by(SortBy.AREA)[-1], "seat")\n'
        'tag(pad.faces().sort_by(SortBy.AREA)[0], "seat")\n'
        "part.geometry = pad\n",
    )
    assert build.result.status == "ok", build.result.error
    entry = _tags(build)["seat"]
    # The LAST tagging statement won: line 3, the third statement (index 2).
    assert entry["line"] == 3
    assert entry["statement"] == 2
    assert build.result.warnings == ()


def test_the_duplicate_rule_is_scoped_to_the_reserved_infix(tmp_path: Path) -> None:
    """One character apart: ``a__b`` refuses, ``a_b`` overwrites."""
    from hephaestus.core.errors import ValidationError
    from hephaestus.core.executor.tags import INTERFACE_TAG_INFIX, TagRegistry

    assert INTERFACE_TAG_INFIX == "__"

    class _Shape:
        wrapped = object()

    plain = TagRegistry()
    plain.set_statement(1, 1)
    plain.tag(_Shape(), "motor_a_shaft")
    plain.set_statement(2, 2)
    plain.tag(_Shape(), "motor_a_shaft")
    assert plain.records()["motor_a_shaft"].line == 2

    scoped = TagRegistry()
    scoped.set_statement(1, 1)
    scoped.tag(_Shape(), "motor_a__shaft")
    scoped.set_statement(2, 2)
    with pytest.raises(ValidationError) as caught:
        scoped.tag(_Shape(), "motor_a__shaft")
    assert str(caught.value).startswith("duplicate_tag:")
