"""G11B clauses 7, 8 and 20: what the renderer emits, where, and reproducibly.

These are assertions on the fragment **text**, which is deliberate: the rewrite
that makes clause 9 possible is pinned here independently of any build, so a
regression shows up as a diff in the emitted source rather than as a mysterious
``unaddressable_anchor`` three stages downstream.

Clause 8's rooting assertion is made by **tokenising** the emitted region, not
by substring search, so ``{prefix}{root}_face`` can never be mistaken for
``{prefix}{root}``.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _g11b import RIG_INTERFACES, RIG_SRC, SEAT_POS, component_tree, index_of, tag_names
from hephaestus.core.registry import (
    RegistryError,
    instance_name,
    instance_prefix_for,
    parse_generator,
    render_fragment,
)

PARAMS = {"boss_h": 4.0}


def _rendered(
    tmp_path: Path,
    *,
    pos: dict[str, float] | None = None,
    instance: str | None = None,
    generator: str = RIG_SRC,
    root: Path | None = None,
) -> tuple[str, str]:
    """``(fragment, prefix)`` for one instance of the rig."""
    tree = root if root is not None else component_tree(tmp_path / "reg", generator=generator)
    part = index_of(tree).get("rig")
    parsed = parse_generator(part.read_script(), source=str(part.script_path))
    fragment = render_fragment(parsed, part, PARAMS, pos, instance)
    prefix = instance_prefix_for(part.id, PARAMS, pos, instance)
    return fragment, prefix


def _region_lines(fragment: str, prefix: str) -> list[str]:
    """Everything the renderer appended below the two tail lines."""
    lines = fragment.splitlines()
    label = f'{prefix}.label = "rig"'
    return lines[lines.index(label) + 1 :]


# ==========================================================================
# clause 7 — emitted names


@pytest.mark.parametrize("pos", [None, {}, dict(SEAT_POS)])
def test_the_default_instance_is_the_deterministic_prefix(
    pos: dict[str, float] | None, tmp_path: Path
) -> None:
    fragment, prefix = _rendered(tmp_path, pos=pos)
    scope = prefix.lstrip("_")
    assert tag_names(fragment) == tuple(
        f"{scope}__{name}" for name, _klass, _role in RIG_INTERFACES
    )
    assert scope == instance_name("rig", PARAMS, pos, None)


def test_a_supplied_instance_scopes_every_emitted_name(tmp_path: Path) -> None:
    fragment, _prefix = _rendered(tmp_path, pos=dict(SEAT_POS), instance="motor_a")
    assert tag_names(fragment) == tuple(
        f"motor_a__{name}" for name, _klass, _role in RIG_INTERFACES
    )


def test_the_declared_names_survive_the_scoping_unchanged(tmp_path: Path) -> None:
    """``<instance>__<name>``: the infix splits it back, because no name carries one."""
    fragment, _prefix = _rendered(tmp_path, instance="motor_a")
    assert tuple(name.split("__", 1)[1] for name in tag_names(fragment)) == tuple(
        name for name, _klass, _role in RIG_INTERFACES
    )


@pytest.mark.parametrize("bad", ["Motor", "motor a", "9motor", "motor-a", "", "m" * 65])
def test_invalid_instance_name(bad: str, tmp_path: Path) -> None:
    with pytest.raises(RegistryError) as caught:
        _rendered(tmp_path, instance=bad)
    assert caught.value.reason == "invalid_instance_name"
    assert caught.value.data["instance"] == bad


def test_an_instance_may_itself_contain_the_infix(tmp_path: Path) -> None:
    """Admitted, because §2.2 puts the instance under the *part-ident* grammar.

    It is not an ambiguity anyone has to resolve by searching for the infix: a
    fragment carries exactly one scope, so the emitted name is split against the
    scope that produced it, never by looking for the first ``__``.
    """
    fragment, _prefix = _rendered(tmp_path, instance="motor__a")
    assert tag_names(fragment)[0] == "motor__a__mount_face"
    assert tag_names(fragment)[0].removeprefix("motor__a__") == "mount_face"


def test_the_instance_grammar_is_the_part_ident_grammar() -> None:
    """One grammar, not two: the value ends up inside an anchor a model types."""
    from hephaestus.contract.tools_decl import IDENT_PATTERN
    from hephaestus.core.registry._generator import _INSTANCE_RE

    assert _INSTANCE_RE.pattern == IDENT_PATTERN


# ==========================================================================
# clause 8 — emitted position and rooting


def test_the_region_is_emitted_below_both_tail_lines(tmp_path: Path) -> None:
    fragment, prefix = _rendered(tmp_path, pos=dict(SEAT_POS))
    lines = fragment.splitlines()
    placement = next(i for i, line in enumerate(lines) if line.startswith(f"{prefix} = "))
    label = lines.index(f'{prefix}.label = "rig"')
    first_tag = next(i for i, line in enumerate(lines) if line.startswith("tag("))
    assert placement < label < first_tag


def test_every_selector_is_rooted_at_the_placed_instance(tmp_path: Path) -> None:
    fragment, prefix = _rendered(tmp_path, pos=dict(SEAT_POS))
    for node in ast.walk(ast.parse(fragment)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "tag":
            continue
        roots = {
            name.id
            for name in ast.walk(node.args[0])
            if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Load)
        }
        assert prefix in roots
        assert f"{prefix}_rig" not in roots


def test_the_renamed_body_local_appears_nowhere_in_the_emitted_region(tmp_path: Path) -> None:
    """Tokenised, not searched: ``{prefix}{root}_face`` is not ``{prefix}{root}``.

    Rewriting only the chain root would leave a second mention of the root
    pointing at the *unplaced* body local — the §2 placement bug at one remove.
    """
    fragment, prefix = _rendered(tmp_path, pos=dict(SEAT_POS))
    region = "\n".join(_region_lines(fragment, prefix))
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", region))
    assert f"{prefix}_rig" not in tokens
    assert prefix in tokens
    # And the body above the tail still names the unplaced local, which is what
    # the placement statement consumes.
    assert f"{prefix}_rig = {prefix}_plate + {prefix}_boss" in fragment


def test_the_origin_case_aliases_the_root_and_is_otherwise_identical(tmp_path: Path) -> None:
    """``_placement`` returns ``""`` for an empty pos, so ``{prefix}`` IS the root."""
    fragment, prefix = _rendered(tmp_path, pos=None)
    assert f"{prefix} = {prefix}_rig" in fragment
    region = "\n".join(_region_lines(fragment, prefix))
    assert f"{prefix}_rig" not in set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", region))


def test_a_comment_in_the_region_survives_but_is_not_a_statement(tmp_path: Path) -> None:
    commented = RIG_SRC.replace(
        'tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")',
        '# the plate bottom, "mount_face", is the unique largest planar face\n'
        'tag(_rig.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")',
    )
    fragment, prefix = _rendered(tmp_path, generator=commented, instance="motor_a")
    assert '# the plate bottom, "mount_face", is the unique largest planar face' in fragment
    # The literal rewrite splices by the constant's own offsets, so the quoted
    # name inside the comment is untouched while the tag's own is scoped.
    assert "motor_a__mount_face" in fragment
    assert '"motor_a__mount_face"' in "\n".join(_region_lines(fragment, prefix))


# ==========================================================================
# clause 20 — determinism

_PROGRAM = """
import json, sys
from pathlib import Path
from hephaestus.core.registry import PartsIndex, load_registry, parse_generator, render_fragment

root = Path(sys.argv[1])
part = PartsIndex(load_registry(root)).get("rig")
parsed = parse_generator(part.read_script(), source=str(part.script_path))
pos = json.loads(sys.argv[2])
print(render_fragment(parsed, part, {"boss_h": 4.0}, pos or None, sys.argv[3] or None))
"""


def _in_a_fresh_process(root: Path, pos: str, instance: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _PROGRAM, str(root), pos, instance],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("instance", ["", "motor_a"])
def test_two_processes_render_byte_identical_fragments(instance: str, tmp_path: Path) -> None:
    """Below the elided digest header — which two processes over one tree share anyway."""
    root = component_tree(tmp_path / "reg")
    pos = '{"z": 7.0, "rz": 30.0}'
    first = _in_a_fresh_process(root, pos, instance)
    second = _in_a_fresh_process(root, pos, instance)
    assert first == second
    assert tag_names(first) == tag_names(second)
    assert len(tag_names(first)) == len(RIG_INTERFACES)


def test_the_emitted_tag_order_is_the_regions_order(tmp_path: Path) -> None:
    """Count AND order, so a set-valued rewrite cannot pass by accident."""
    fragment, _prefix = _rendered(tmp_path, pos=dict(SEAT_POS), instance="motor_a")
    assert tag_names(fragment) == (
        "motor_a__mount_face",
        "motor_a__shaft",
        "motor_a__shaft_ring",
        "motor_a__rail",
        "motor_a__envelope",
    )


def test_two_instances_differing_only_in_pos_get_different_scopes(tmp_path: Path) -> None:
    root = component_tree(tmp_path / "reg")
    here, _ = _rendered(tmp_path, pos=None, root=root)
    there, _ = _rendered(tmp_path, pos=dict(SEAT_POS), root=root)
    assert set(tag_names(here)).isdisjoint(tag_names(there))


def test_the_same_id_params_and_pos_are_the_same_instance(tmp_path: Path) -> None:
    """Which is exactly why pasting one twice is a collision and not two motors."""
    root = component_tree(tmp_path / "reg")
    first, _ = _rendered(tmp_path, pos=dict(SEAT_POS), root=root)
    second, _ = _rendered(tmp_path, pos=dict(SEAT_POS), root=root)
    assert first == second


def test_a_legacy_generator_renders_no_region_at_all(tmp_path: Path) -> None:
    """Nothing about a part without an interface region changed."""
    from _g11b import _RIG_BODY

    root = component_tree(tmp_path / "legacy", component=None, generator=_RIG_BODY)
    import json as _json

    meta_path = root / "rig" / "part.json"
    meta: dict[str, Any] = _json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["component"]
    meta_path.write_text(_json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    fragment, prefix = _rendered(tmp_path, pos=dict(SEAT_POS), root=root)
    assert tag_names(fragment) == ()
    assert fragment.rstrip("\n").endswith(f'{prefix}.label = "rig"')
