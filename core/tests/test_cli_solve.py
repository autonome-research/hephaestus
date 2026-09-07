# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``heph solve pose|placement|params`` — argument-shape validation and ordering.

Ledger J-cli-robustness-17: a ``--bound`` with no ``=`` (or no ``:`` in its
window) used to be accepted as an unbounded window on a variable nobody
declared — the separator-less spec partitioned into an empty window,
partitioned that into two empty bounds, and both mapped to ``None`` with no
error at any point. And because the request was built *before* the
argument-shape checks, a pure-argument mistake was reported late or not at
all. These tests exercise the fixed shape: every argument-shape check runs
before the project is even opened, several bad flags collect into one
refusal, and a genuinely half-open window still parses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hephaestus.core.cli import main


def run(root: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.chdir(root)
    return main(list(argv))


_PLACEMENT_BASE = (
    "solve",
    "placement",
    "--tol",
    "1",
    "--weighting",
    "unit_scaled_v1",
    "--regularization",
    "min_norm_from_start",
    "--requirement",
    "REQ-1",
    "--constraint",
    "c1",
    "--free",
    "bracket",
)


def test_bound_without_a_separator_is_refused_before_the_project_is_opened(
    tmp_path: Path,
) -> None:
    """No ``hephaestus.toml`` exists here at all — the refusal must still fire,
    proving argument-shape checks run before ``project_root_or_refuse``."""
    code = main([*_PLACEMENT_BASE, "--bound", "bogus"])
    assert code == 2


def test_bound_without_a_separator_names_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bogus"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--bound" in err
    assert "bogus" in err


def test_bound_with_equals_but_no_window_colon_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``VAR=5`` has the ``=`` but no window ``:`` — still not a silent no-op."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bracket.tx=5"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--bound" in err


def test_bound_naming_a_variable_outside_the_free_set_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A well-formed ``--bound`` on a variable this solve does not move clamps
    nothing and must say so, once the free set is known."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "other.tx=0:10"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "other.tx" in err
    assert "--free" in err


def test_a_genuinely_half_open_bound_still_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the separators are compulsory — a half-open window (empty MIN or
    MAX) is the documented, legitimate form and must not be refused as
    malformed. This must get *past* argument-shape validation: it fails later,
    at project resolution (there is no project here), not as a usage error
    about ``--bound``.

    The variable is ``bracket.tx``, not ``bracket``: a placement request's free
    *variables* are ``<part>.<axis>`` over the six transform axes
    (``placement.TRANSFORM_AXES``), while ``--free`` names the parts.
    """
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bracket.tx=0:"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--bound" not in err, err
    assert "hephaestus.toml" in err, err


def test_several_bad_flags_produce_one_refusal_listing_all_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A user fixing several mistakes one run at a time pays a full solve setup
    per mistake; every pure-argument check must be collected into one refusal.

    Two independent mistakes here: no provenance at all (neither
    ``--requirement`` nor ``--assumed``), and a malformed ``--point`` spec with
    the wrong arity.
    """
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "solve",
            "pose",
            "--tol",
            "1",
            "--weighting",
            "unit_scaled_v1",
            "--regularization",
            "min_norm_from_start",
            "--point",
            "anchor,1,2",  # wrong arity: needs ANCHOR,X,Y,Z,TOL_MM
        ]
    )
    err = capsys.readouterr().err
    assert code == 2, err
    assert "provenance is compulsory" in err
    assert "--point" in err
    assert "anchor,1,2" in err


def test_a_single_bad_flag_is_not_wrapped_in_the_several_arguments_preamble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exactly one problem should read as one refusal, not a one-item list."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bogus"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "several arguments are wrong" not in err, err


# -- J-cli-robustness-17, the same defect in the sibling flag: `--start` -----


def test_start_without_a_separator_is_refused_before_the_project_is_opened(
    tmp_path: Path,
) -> None:
    """``--start nonsense`` partitioned into an id with an empty body, iterated
    no pairs, and became a second ``as_built`` start under a name the operator
    never meant — the ``--bound`` defect in the flag beside it. A declared start
    that declares nothing is not a start; the empty assignment is what the
    *default* start is, so a typo must not be able to reach it."""
    code = main([*_PLACEMENT_BASE, "--start", "nonsense"])
    assert code == 2


def test_start_refusal_quotes_the_flag_and_the_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--start", "nonsense"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--start" in err, err
    assert "nonsense" in err, err
    assert "ID=VAR:VALUE" in err, err  # the flag's own metavar, not a third spelling


def test_a_start_pair_without_a_colon_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``s=bracket.tx`` names a variable and no value. It used to reach
    ``float("")`` and be reported as a number problem, which is not what is
    wrong with it."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--start", "s=bracket.tx"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "bracket.tx" in err, err


def test_a_well_formed_start_still_parses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard against over-correcting: the refusal is about the *separators*,
    so a real start reaches the project-resolution step and fails there."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--start", "s=bracket.tx:1,bracket.ty:-2.5"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--start" not in err, err
    assert "hephaestus.toml" in err, err


def test_the_pose_verb_names_joints_in_its_start_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One parser serves three verbs whose metavars differ (``JOINT`` / ``VAR``
    / ``PARAM``); the refusal must quote the one the operator actually read in
    ``--help``."""
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "solve",
            "pose",
            "--tol",
            "1",
            "--weighting",
            "unit_scaled_v1",
            "--regularization",
            "min_norm_from_start",
            "--requirement",
            "REQ-1",
            "--constraint",
            "c1",
            "--start",
            "nonsense",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2, err
    assert "ID=JOINT:VALUE" in err, err


def test_every_bad_bound_is_named_not_only_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repeatable flag can be wrong several times in one invocation. Banking
    the first refusal per *parser* still costs one run per mistake, which is the
    cost the item is about — the ledger asks for one refusal listing all of
    them."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bogus", "--bound", "spam", "--bound", "x=1"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "several arguments are wrong" in err, err
    for spec in ("bogus", "spam", "x=1"):
        assert spec in err, err


def test_every_bad_start_is_named_not_only_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--start", "nonsense", "--start", "also_bad"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "nonsense" in err, err
    assert "also_bad" in err, err


def test_bad_specs_in_two_different_flags_join_one_flat_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Per-flag collection and per-spec collection compose: the operator gets
    one list, not a list with a list nested inside it."""
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bogus", "--bound", "spam", "--start", "nonsense"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert err.count("  - ") == 3, err


def test_every_bad_point_is_named_not_only_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--point`` is the third repeatable spec flag and had the same shape."""
    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "solve",
            "pose",
            "--tol",
            "1",
            "--weighting",
            "unit_scaled_v1",
            "--regularization",
            "min_norm_from_start",
            "--requirement",
            "REQ-1",
            "--point",
            "anchor,1,2",
            "--point",
            "anchor,a,b,c,d",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2, err
    assert "anchor,1,2" in err, err
    assert "anchor,a,b,c,d" in err, err


def test_a_bound_on_a_declared_part_but_an_unknown_axis_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``bracket.zz`` names a free *part* and a component that does not exist.

    The membership test decomposes ``<part>.<axis>``; comparing the whole
    spelling against the ``--free`` part names would refuse every legitimate
    bound there is, and comparing only the prefix would accept a bound the
    engine then rejects with ``no_free_variables`` after a full solve setup.
    """
    monkeypatch.chdir(tmp_path)
    code = main([*_PLACEMENT_BASE, "--bound", "bracket.zz=0:10"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "bracket.zz" in err
    assert "tx|ty|tz|rx|ry|rz" in err, err
