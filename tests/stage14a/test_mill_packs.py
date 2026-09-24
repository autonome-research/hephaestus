# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14A clauses 5 and 8: the machining packs on the existing DFM machinery.

Clause 5 — both new packs load under the existing loader invariants (every
``rule_id`` is ``<process>.<name>`` and unique, every ``reads`` name exists in
``[params]`` — ``_dfm.py:14-20``), and a deliberately broken fork of each pack
is refused. Clause 8 — the ``cnc_mill`` index inversion is paid (issue #28's
precedent inverted the ``cnc_router`` hole; this stage owes the same for
``cnc_mill``), and ``heph init``'s default process (``cli_init.py:64``) resolves
to a real pack end to end.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from _g14a import DFM_ROOT, compliant_fixture, dfm_index, mill_pack, router_pack, run_in_process
from hephaestus.core.errors import ValidationError
from hephaestus.core.registry import load_pack

# -- clause 5: both packs load under the loader invariants -------------------


def test_both_machining_packs_load_from_the_bundled_registry() -> None:
    index = dfm_index()
    assert index.has("cnc_mill") and index.has("cnc_router")
    assert mill_pack().rule_ids() == (
        "cnc_mill.min_internal_radius_vs_tool",
        "cnc_mill.pocket_depth_vs_tool_diameter",
        "cnc_mill.min_web_thickness",
        "cnc_mill.bore_aspect_ratio",
        "cnc_mill.single_axis_accessibility",
    )
    assert "kerf_mm" not in mill_pack().params, (
        "a mill bit removes its full diameter; cut-file kerf is a laser/waterjet concern"
    )


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_the_loader_invariants_hold_for_each_pack(process: str) -> None:
    """Unique ``<process>.<name>`` ids; every ``reads`` in ``[params]``."""
    pack = dfm_index().get(process)
    ids = pack.rule_ids()
    assert ids == tuple(dict.fromkeys(ids)), "rule ids must be unique"
    for rule in pack.rules:
        assert rule.rule_id.startswith(f"{process}.")
        assert rule.params, f"{rule.rule_id} declares no parameters"
        assert set(rule.params) <= set(pack.params), (
            "a predicate can therefore never read an undeclared number (_dfm.py:14-20)"
        )
        assert rule.predicate_path.is_file()


def _fork(tmp_path: Path, process: str) -> Path:
    fork = tmp_path / process
    shutil.copytree(DFM_ROOT / process, fork)
    return fork


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_a_fork_reading_an_undeclared_parameter_is_refused(tmp_path: Path, process: str) -> None:
    fork = _fork(tmp_path, process)
    manifest = fork / "pack.toml"
    text = manifest.read_text(encoding="utf-8")
    assert 'reads = ["tool_diameter_mm", "min_internal_radius_mm"]' in text
    manifest.write_text(
        text.replace(
            'reads = ["tool_diameter_mm", "min_internal_radius_mm"]',
            'reads = ["tool_diameter_mm", "min_internal_radius_mm", "kerf_mm"]',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        load_pack(fork)
    assert "kerf_mm" in caught.value.message
    assert "undeclared parameter" in caught.value.message


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_a_fork_with_a_duplicate_rule_id_is_refused(tmp_path: Path, process: str) -> None:
    fork = _fork(tmp_path, process)
    manifest = fork / "pack.toml"
    text = manifest.read_text(encoding="utf-8")
    duplicate = (
        f'\n[[rules]]\nid = "{process}.bore_aspect_ratio"\ntitle = "duplicate"\n'
        'predicate = "bore_aspect_ratio.py"\nreads = ["max_bore_aspect"]\n'
    )
    manifest.write_text(text + duplicate, encoding="utf-8")
    with pytest.raises(ValidationError, match="duplicate rule id"):
        load_pack(fork)


@pytest.mark.parametrize("process", ["cnc_mill", "cnc_router"])
def test_a_fork_whose_rule_id_leaves_its_process_is_refused(tmp_path: Path, process: str) -> None:
    fork = _fork(tmp_path, process)
    manifest = fork / "pack.toml"
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        text.replace(f'id = "{process}.bore_aspect_ratio"', 'id = "plasma.bore_aspect_ratio"', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="prefixed with the pack process"):
        load_pack(fork)


# -- clause 8: the owed inversion, and the default process end to end --------


def test_the_cnc_mill_index_inversion_is_paid() -> None:
    """`core/tests/test_dfm_packs.py` asserted ``not index.has("cnc_mill")``
    (line 217) while line 215 asserted ``has("cnc_router")`` — the hole issue
    #28's inversion left for this stage. Both are now positive assertions."""
    index = dfm_index()
    assert index.has("cnc_router"), "issue #28's inversion, still paid"
    assert index.has("cnc_mill"), "this stage's owed inversion, now paid"


def test_the_heph_init_default_process_resolves_to_a_real_pack_end_to_end(
    tmp_path: Path,
) -> None:
    """`cli_init.py:64` writes ``part.process = "cnc_router"``; that string must
    load a bundled pack and every rule must run clean against the scaffolded
    example's geometry, so the default the harness hands a model is not a lie."""
    from hephaestus.core.cli_init import EXAMPLE_PART

    assert 'part.process = "cnc_router"' in EXAMPLE_PART
    pack = router_pack()
    assert pack.process == "cnc_router"
    outcomes = run_in_process(pack, compliant_fixture(), tmp_path, part="example")
    assert set(outcomes) == set(pack.rule_ids())
    assert all(outcome.status == "ok" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error, [f.message for f in outcome.findings])
        for rule_id, outcome in outcomes.items()
    }
    assert all(not outcome.findings for outcome in outcomes.values())


def test_the_mill_pack_also_runs_clean_on_the_scaffolded_example(tmp_path: Path) -> None:
    """The same negative control for the new pack: a first `heph dfm` run on a
    plain plate that declared cnc_mill must not be a wall of findings."""
    outcomes = run_in_process(mill_pack(), compliant_fixture(), tmp_path, part="example")
    assert all(outcome.status == "ok" for outcome in outcomes.values()), {
        rule_id: (outcome.status, outcome.error) for rule_id, outcome in outcomes.items()
    }
    assert all(not outcome.findings for outcome in outcomes.values())
