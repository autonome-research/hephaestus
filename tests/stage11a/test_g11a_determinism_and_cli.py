"""G11A clauses 23-24: determinism, and ``heph registry components``.

Clause 23 binds to §9's *bit-reproducible* list only — Merkle roots, leaf lists,
and refusal reasons and details. It never binds to anything the geometry kernel
computes: a clause that pinned a volume across processes would be measuring
OCP's build, not this stage, and §9 says so in as many words. The two processes
are real subprocesses, because in-process repetition would measure one
interpreter's caches rather than reproducibility.

Clause 24 exists because named new work item 30 shipped a verb with no gate
clause at all, and this section's own preamble treats an ungated deliverable as
a defect in itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from _g11a import (
    BASE_PARAMS,
    DATASHEET,
    LEGACY_PARTS,
    REPO,
    SHIPPED_PARTS,
    component_tree,
    motor_component,
)
from hephaestus.core.registry import merkle_digest, tree_leaves

# ==========================================================================
# clause 23 — determinism


_DIGEST_PROBE = """
import json, sys
from pathlib import Path
from hephaestus.core.registry import merkle_digest, tree_leaves

root = Path(sys.argv[1])
print(json.dumps({"digest": merkle_digest(root), "leaves": list(tree_leaves(root))}))
"""

_REFUSAL_PROBE = """
import json, sys
from pathlib import Path
from hephaestus.core.registry import PartsIndex, RegistryRefusal, load_registry

root = Path(sys.argv[1])
try:
    PartsIndex(load_registry(root))
except RegistryRefusal as exc:
    print(json.dumps({"reason": exc.reason, "message": exc.message, "detail": exc.detail}))
else:
    print(json.dumps({"reason": None}))
"""


def _run_probe(source: str, argument: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", source, argument],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    return cast("dict[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("tree", [SHIPPED_PARTS, LEGACY_PARTS], ids=["shipped", "legacy"])
def test_two_processes_agree_on_the_root_and_the_leaf_list(tree: Path) -> None:
    first = _run_probe(_DIGEST_PROBE, str(tree))
    second = _run_probe(_DIGEST_PROBE, str(tree))
    assert first == second
    assert first["digest"] == merkle_digest(tree)
    assert [tuple(leaf) for leaf in first["leaves"]] == list(tree_leaves(tree))


#: A record advertising a parameter the fixture generator's ``PARAMS`` lacks —
#: clause 8's surplus direction, whose detail carries a *list* and so is exactly
#: the kind of payload a set-ordering bug would make non-reproducible.
_DRIFT_PARAMS: dict[str, Any] = {
    **BASE_PARAMS,
    "shaft_length": {"type": "float", "default": 24.0, "min": 10.0, "max": 40.0},
}

#: One case per clause-4..14 refusal, so "same input, same reason, same detail"
#: is asserted across the whole vocabulary rather than on a representative.
#: Each case is ``(reason, component, tree kwargs)`` — the third element exists
#: because two of the eleven in-range refusals are *not* reachable by editing the
#: component block alone: clause 8 (``param_schema_drift``) is a disagreement
#: between ``part.json``'s ``params`` and the generator's ``PARAMS``, and clause 9
#: (``unlicensed_registry``) is a missing line in ``registry.toml``. Both were
#: absent while the list carried only component dicts, which left 2 of the 11
#: refusals clause 23 names with no cross-process evidence at all. Their refusal
#: details are the ones most worth pinning here: ``param_schema_drift`` reports
#: sorted name lists, and ``unlicensed_registry`` is raised from
#: ``load_registry`` rather than from the index, so it also proves the probe
#: reaches refusals raised before the index is built.
_REFUSAL_CASES: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("unknown_component_kind", motor_component(**{"class": "flux_capacitor"}), {}),
    (
        "missing_required_interface",
        motor_component(
            interfaces=[{"name": "shaft", "class": "cylindrical_face", "role": "shaft"}]
        ),
        {},
    ),
    (
        "duplicate_interface_name",
        motor_component(
            interfaces=[
                {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
                {"name": "shaft", "class": "cylindrical_face", "role": "shaft"},
                {"name": "shaft", "class": "cylindrical_face", "role": "pilot"},
            ]
        ),
        {},
    ),
    (
        "duplicate_claim_id",
        motor_component(
            datasheet=DATASHEET,
            claims=[
                {
                    "id": "torque_speed",
                    "kind": "torque_speed_curve",
                    "unit_x": "rpm",
                    "unit_y": "N*m",
                    "samples": [[0, 0.44], [600, 0.28]],
                    "cite": {"page": 3, "quote": "q"},
                }
            ]
            * 2,
        ),
        {},
    ),
    (
        "unknown_interface_class",
        motor_component(
            interfaces=[
                {"name": "mount_face", "class": "planar_face", "role": "mount_face"},
                {"name": "shaft", "class": "conical_face", "role": "shaft"},
            ]
        ),
        {},
    ),
    # clause 8, both directions: a surplus parameter and a missing one.
    ("param_schema_drift", motor_component(), {"params": _DRIFT_PARAMS}),
    ("param_schema_drift", motor_component(), {"params": {}}),
    # clause 9: refused by `load_registry`, before the index exists.
    ("unlicensed_registry", motor_component(), {"license_line": None}),
    (
        "unsourced_component_datum",
        motor_component(mass={"value_g": 280.0, "source": "datasheet"}),
        {},
    ),
    (
        "mass_source_conflict",
        motor_component(
            datasheet=DATASHEET,
            mass={"value_g": 280.0, "source": "datasheet", "material": "steel_1018"},
        ),
        {},
    ),
    ("inertia_out_of_scope", motor_component(inertia=[1.0, 2.0, 3.0]), {}),
    (
        "malformed_performance_curve",
        motor_component(
            datasheet=DATASHEET,
            claims=[
                {
                    "id": "torque_speed",
                    "kind": "torque_speed_curve",
                    "unit_x": "rpm",
                    "unit_y": "N*m",
                    "samples": [[0, 0.28], [600, 0.44]],
                    "cite": {"page": 3, "quote": "q"},
                }
            ],
        ),
        {},
    ),
    (
        "malformed_datasheet_pointer",
        motor_component(datasheet={k: v for k, v in DATASHEET.items() if k != "url"}),
        {},
    ),
]

#: Clause 23 names clauses 4-14, and each of those clauses names its refusals.
#: Enumerated here so a clause that grows a refusal fails this file rather than
#: silently leaving the new one without cross-process evidence.
CLAUSE_4_TO_14_REFUSALS: frozenset[str] = frozenset(
    {
        "unknown_component_kind",
        "missing_required_interface",
        "duplicate_interface_name",
        "duplicate_claim_id",
        "unknown_interface_class",
        "param_schema_drift",
        "unlicensed_registry",
        "unsourced_component_datum",
        "mass_source_conflict",
        "inertia_out_of_scope",
        "malformed_performance_curve",
        "malformed_datasheet_pointer",
    }
)


def test_every_clause_4_to_14_refusal_has_a_determinism_case() -> None:
    """The list's own completeness, asserted rather than claimed in a comment.

    The previous form said "one case per clause-4..14 refusal" in a docstring
    while omitting two of them. A comment cannot fail; this can.
    """
    assert {case[0] for case in _REFUSAL_CASES} == CLAUSE_4_TO_14_REFUSALS


@pytest.mark.parametrize(
    ("reason", "component", "tree_kwargs"),
    _REFUSAL_CASES,
    ids=[f"{index}-{case[0]}" for index, case in enumerate(_REFUSAL_CASES)],
)
def test_two_processes_produce_the_same_refusal_reason_and_detail(
    reason: str, component: dict[str, Any], tree_kwargs: dict[str, Any], tmp_path: Path
) -> None:
    root = component_tree(tmp_path / "tree", component, **tree_kwargs)
    first = _run_probe(_REFUSAL_PROBE, str(root))
    second = _run_probe(_REFUSAL_PROBE, str(root))
    assert first["reason"] == reason
    assert first == second, "same input, same reason, same detail (§9)"


# ==========================================================================
# clause 24 — heph registry components [--json]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project pinning a two-part `parts` registry: one component, one legacy.

    Pinned under the key ``parts`` so the bundled fallback's own ``parts`` pin
    is not also resolved — two registries of a kind is ``duplicate_registry_kind``
    now, which is clause 18's whole point.
    """
    parts = component_tree(
        tmp_path / "parts",
        motor_component(datasheet=DATASHEET, mass={"value_g": 280.0, "source": "datasheet"}),
    )
    # A second, legacy part in the same tree: the verb must list it *not at all*.
    legacy_dir = parts / "legacy_spacer"
    legacy_dir.mkdir()
    for name in ("part.json", "generator.py"):
        (legacy_dir / name).write_bytes((LEGACY_PARTS / "legacy_spacer" / name).read_bytes())
    manifest = parts / "registry.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + '\n[[parts]]\nid = "legacy_spacer"\ndir = "legacy_spacer"\n',
        encoding="utf-8",
    )

    root = tmp_path / "proj"
    root.mkdir()
    (root / "parts").mkdir()
    (root / "hephaestus.toml").write_text(
        f'[project]\nname = "stage11a"\n\n[registries.parts]\npath = {json.dumps(str(parts))}\n',
        encoding="utf-8",
    )
    return root


def _components(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Through the real ``heph`` parser, not the module's standalone entry point:
    # a verb registered only on the latter would pass a test and fail a user.
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", "registry", "components", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_verb_lists_every_component_record_with_its_facts(project: Path) -> None:
    completed = _components(project, "--json")
    assert completed.returncode == 0, completed.stderr[-3000:]
    records = cast("list[dict[str, Any]]", json.loads(completed.stdout))
    assert [record["id"] for record in records] == ["stepper_nema17_frame"]
    record = records[0]
    assert record["class"] == "motor"
    assert cast("dict[str, Any]", record["series"])["family"] == "nema"
    assert record["interfaces"] == ["mount_face", "shaft"]
    assert record["has_datasheet"] is True
    assert str(record["registry_digest"]).startswith("sha256:")


def test_the_verb_lists_legacy_parts_not_at_all(project: Path) -> None:
    """A part with no record is not a component, and padding the listing with
    one would answer a different question than the verb asks."""
    records = cast("list[dict[str, Any]]", json.loads(_components(project, "--json").stdout))
    assert all(record["id"] != "legacy_spacer" for record in records)


def test_the_json_output_is_byte_identical_across_two_processes(project: Path) -> None:
    first = _components(project, "--json")
    second = _components(project, "--json")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert first.stdout.count("{") >= 1


def test_the_json_key_order_is_stable(project: Path) -> None:
    """Byte identity across two runs is not enough on its own: it would hold for
    a key order that happened to be stable *today*. The order is pinned."""
    line = _components(project, "--json").stdout
    record = cast("list[dict[str, Any]]", json.loads(line))[0]
    assert list(record) == [
        "id",
        "name",
        "class",
        "series",
        "interfaces",
        "has_datasheet",
        "registry",
        "registry_digest",
    ]


def test_the_human_listing_names_class_series_interfaces_and_datasheet(project: Path) -> None:
    completed = _components(project)
    assert completed.returncode == 0, completed.stderr[-3000:]
    out = completed.stdout
    assert "stepper_nema17_frame: motor (nema 17)" in out
    assert "interfaces: mount_face, shaft" in out
    assert "datasheet:  yes" in out
    assert "legacy_spacer" not in out


def test_a_project_with_no_component_records_says_so(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hephaestus.toml").write_text(
        '[project]\nname = "empty"\n\n'
        f"[registries.parts]\npath = {json.dumps(str(LEGACY_PARTS))}\n",
        encoding="utf-8",
    )
    completed = _components(root)
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert "no component records" in completed.stdout


def test_the_verb_is_registered_on_the_real_parser() -> None:
    """Registered on ``build_parser()``, not only on the standalone entry point:
    the docs-set gate keys on the real parser and so does the user."""
    from hephaestus.core.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit) as exit_code:
        parser.parse_args(["registry", "components", "--nonsense"])
    assert exit_code.value.code == 2
    args = parser.parse_args(["registry", "components", "--json"])
    assert args.json is True
