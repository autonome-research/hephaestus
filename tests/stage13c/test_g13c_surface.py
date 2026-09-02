# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""G13C clauses 51-52: the enum extension, the tool count, and the CLI verb.

``SOLVER.md`` Gate G13C:

51. ``space: "parameters"`` accepted as an enum value on ``propose_placement``
    with its schema constraint enforced in the canonical JSON Schema, and
    asserted to have been **absent** from the 13B enum (clause 40) — so this
    clause is not vacuous; no fourth tool is added (tool count still 57);
52. ``heph solve params`` human and ``--json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

REPO = Path(__file__).resolve().parents[2]

#: The model surface after 13B, and after 13C: **unchanged**. Parameter space
#: is an enum value on an existing tool, not a fourth tool — the 8A/8B lever
#: (``SOLVER.md`` §11), on the ``layout="nested_sheet"`` precedent, because each
#: tool costs five generated drift-tested artifacts, a per-profile decision,
#: dispatch tests on both profiles and a normative heading.
TOOL_COUNT: int = 57


def _schema(name: str) -> Mapping[str, Any]:
    path = REPO / "schemas" / "tools" / f"{name}.schema.json"
    return cast("Mapping[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _params(name: str) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", _schema(name)["parameters"])


# ==========================================================================
# clause 51 — the enum value, enforced, and demonstrably new


def test_the_space_enum_admits_parameters_in_the_canonical_json_schema() -> None:
    """The generated schema is the contract; a declaration alone is not."""
    space = cast("Mapping[str, Any]", _params("propose_placement")["properties"]["space"])
    assert space["enum"] == ["transform", "parameters"]
    assert space["type"] == "string"


def test_the_enum_was_absent_from_the_13b_schema_so_this_clause_is_not_vacuous() -> None:
    """Clause 51's own precondition, asserted against 13B's landed gate text.

    G13B clause 40 asserted the enum was **one member**. A clause that says
    "the value is now admitted" proves nothing unless it was not admitted
    before, so this reads 13B's own suite for the assertion it made rather than
    taking the history on trust.
    """
    source = (REPO / "tests" / "stage13b" / "test_g13b_surface.py").read_text(encoding="utf-8")
    assert '"transform"' in source
    assert "13C" in source, (
        "13B's surface suite no longer records that the space enum was one member; "
        "without that, clause 51 asserts an addition nobody can date"
    )


def test_the_schema_constraint_is_enforced_and_not_decorative() -> None:
    """An out-of-enum space is rejected by the schema, before dispatch.

    The input schema is ``additionalProperties: false`` as well, which is the
    structural half of the writeback refusal: a ``suggested_edit`` field is not
    refused by name, it is unrepresentable.
    """
    import jsonschema

    schema = _params("propose_placement")
    assert schema["additionalProperties"] is False
    base = {
        "space": "parameters",
        "constraints": ["c-seat"],
        "free": ["post.post_h"],
        "weighting": "unit_scaled_v1",
        "regularization": "min_norm_from_start",
        "tol": 1e-3,
        "provenance": {"assumed": True, "reason": "the gate's own solve"},
    }
    jsonschema.validate(base, dict(schema))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**base, "space": "poses"}, dict(schema))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**base, "suggested_edit": "post_h = 32.0"}, dict(schema))


def test_the_parameter_variable_spelling_is_admitted_by_the_free_pattern() -> None:
    """``<part>.<param>`` and ``hc.<param>`` — the script's own spellings."""
    import jsonschema

    items = cast("Mapping[str, Any]", _params("propose_placement")["properties"]["free"]["items"])
    for name in ("post.post_h", "hc.shelf_z", "lug"):
        jsonschema.validate(name, dict(items))
    for bad in ("", ".post_h", "9post.h"):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, dict(items))


def test_the_build_budget_is_on_the_tool_and_is_optional() -> None:
    """§10's 2C budget reaches the model surface, defaulted to the constant."""
    budget = cast("Mapping[str, Any]", _params("propose_placement")["properties"]["build_budget"])
    assert budget["default"] is None
    assert {entry["type"] for entry in cast("list[Any]", budget["anyOf"])} == {
        "integer",
        "null",
    }
    required = cast("list[str]", _params("propose_placement")["required"])
    assert "build_budget" not in required


def test_no_fourth_tool_is_added_and_the_count_is_unchanged() -> None:
    """The whole reason ``space`` is an enum and not a tool."""
    from hephaestus.contract.tools_decl import TOOLS

    assert len(TOOLS) == TOOL_COUNT
    names = {tool.name for tool in TOOLS}
    assert {"solve_pose", "propose_placement", "read_proposals"} <= names
    assert not any(name.startswith("propose_param") or name == "solve_params" for name in names)
    generated = {path.stem for path in (REPO / "schemas" / "tools").glob("*.schema.json")}
    assert len(generated) == TOOL_COUNT
    mcp = cast(
        "Mapping[str, Any]",
        json.loads((REPO / "schemas" / "mcp" / "tools.json").read_text(encoding="utf-8")),
    )
    assert len(cast("Sequence[Any]", mcp["tools"])) == TOOL_COUNT


def test_the_result_reports_which_space_answered_and_lists_nonsmooth_terms() -> None:
    """A result that did not say which space it solved in would be unreadable."""
    result = cast("Mapping[str, Any]", _schema("propose_placement")["result"])
    properties = cast("Mapping[str, Any]", result["properties"])
    assert properties["space"] == {"type": "string"}
    assert properties["nonsmooth_terms"] == {"type": "array", "items": {"type": "string"}}


def test_the_tool_document_carries_the_parameters_subsection() -> None:
    """``tool_schema.md`` gains the heading with the sub-stage that ships it.

    A normative tool document that declared the enum value without saying what
    it does would be the drift ``KINEMATICS.md:25-29`` names, from the other
    direction: a surface with no description.
    """
    document = (REPO / "tool_schema.md").read_text(encoding="utf-8")
    assert '### `space: "parameters"` (`SOLVER.md` §2C, Stage 13C)' in document
    assert 'space: "transform"|"parameters"' in document
    assert "build_budget" in document
    assert (
        '`space: "parameters"` is 13C\'s enum extension and is deliberately not listed yet'
        not in document
    ), "the 13B amendment note outlived the amendment it described"


# ==========================================================================
# clause 52 — heph solve params, human and --json


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        capture_output=True,
        text=True,
        cwd=str(root),
    )


def test_heph_solve_params_prints_the_verdict_and_every_value_beside_its_box(
    bench_copy: Any,
) -> None:
    """The human form: what was decided, what is proposed, and its declared box."""
    layout, store = bench_copy
    store.close()
    completed = _cli(
        layout.root,
        "solve",
        "params",
        "--constraint",
        "c-fit",
        "--free",
        "cap.spigot_r",
        "--tol",
        "1e-3",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
        "--assumed",
        "--reason",
        "the gate's own solve",
    )
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "verdict: converged_at_tolerance" in out
    assert "proposal: p-" in out
    assert "cap.spigot_r = " in out
    assert "[declared 6 .. 8]" in out
    assert "preview builds issued:" in out
    assert "none of them current, none persisted" in out
    assert "nothing was applied: this is a measurement" in out
    # There is no --apply, no --set and no --write on this verb, and the help
    # text is where an operator would look for one.
    help_text = _cli(layout.root, "solve", "params", "--help").stdout
    for flag in ("--apply", "--set", "--write", "--accept"):
        assert flag not in help_text


def test_heph_solve_params_json_is_the_machine_form_of_the_same_record(
    bench_copy: Any,
) -> None:
    """``--json`` prints the record, not a summary of it."""
    layout, store = bench_copy
    store.close()
    completed = _cli(
        layout.root,
        "solve",
        "params",
        "--constraint",
        "c-fit",
        "--free",
        "cap.spigot_r",
        "--tol",
        "1e-3",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
        "--assumed",
        "--reason",
        "the gate's own solve",
        "--json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = cast("Mapping[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))
    assert payload["status"] == "ok"
    assert payload["space"] == "parameters"
    assert payload["verdict"] == "converged_at_tolerance"
    core = cast("Mapping[str, Any]", payload["solver_core"])
    assert core["determinism_tier"] == "D2"
    assert cast("Mapping[str, Any]", payload["verification"])["determinism_tier"] == "D2"
    entry = cast(
        "Mapping[str, Any]",
        cast("list[Any]", cast("Mapping[str, Any]", payload["placements"][0])["parameters"])[0],
    )
    assert entry["name"] == "cap.spigot_r"
    assert entry["scope"] == "part"
    assert 6.0 <= float(cast("float", entry["value"])) <= 8.0
    assert "suggested_edit" not in json.dumps(payload)


def test_a_refused_params_solve_exits_nonzero_and_prints_the_name(bench_copy: Any) -> None:
    """A refusal is never printed as a verdict (``core/motion.py:1489-1498``)."""
    layout, store = bench_copy
    store.close()
    completed = _cli(
        layout.root,
        "solve",
        "params",
        "--constraint",
        "c-seat",
        "--free",
        "hc.plate_t",
        "--tol",
        "1e-3",
        "--weighting",
        "unit_scaled_v1",
        "--regularization",
        "min_norm_from_start",
        "--assumed",
        "--reason",
        "the gate's own solve",
        "--json",
    )
    assert completed.returncode == 1
    payload = cast("Mapping[str, Any]", json.loads(completed.stdout.strip().splitlines()[-1]))
    assert payload["reason"] == "unbounded_param"
    assert "verdict" not in payload


def test_the_verb_is_registered_and_documented(bench_copy: Any) -> None:
    """``heph solve params`` exists beside ``pose`` and ``placement``, and is in cli.md."""
    layout, store = bench_copy
    store.close()
    help_text = _cli(layout.root, "solve", "--help").stdout
    for verb in ("pose", "placement", "params"):
        assert verb in help_text
    document = (REPO / "docs" / "cli.md").read_text(encoding="utf-8")
    assert "### `heph solve params`" in document
    assert "--build-budget" in document
    assert "unbounded_param" in document
