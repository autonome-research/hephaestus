# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""``heph render`` end-to-end and ``heph goldens`` dirty-tree refusal.

The render CLI is exercised as a real subprocess against the public assembly
fixture (build then render); the goldens generator is verified to refuse a
dirty git tree (verification.md meta-test) using a throwaway scratch repo.

B-10 adds: golden regeneration outside a Hephaestus checkout must refuse by
name instead of a raw ``FileNotFoundError``; ``heph render``'s ``--out`` must
be validated *before* the GL session opens, for both the single-part and the
posed-scene command.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hephaestus.core.render.goldens import (
    GOLDEN_SPECS,
    DirtyTreeError,
    git_is_dirty,
    script_hash,
    update_goldens,
)

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"


def _heph(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ},
    )


@pytest.fixture(scope="module")
def built_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("cli-assembly")
    for item in ASSEMBLY.iterdir():
        if item.is_dir():
            (root / item.name).mkdir(exist_ok=True)
            for sub in item.iterdir():
                (root / item.name / sub.name).write_bytes(sub.read_bytes())
        else:
            (root / item.name).write_bytes(item.read_bytes())
    build = _heph(["build", "primary", "--unsafe-local-executor"], root)
    assert build.returncode == 0, build.stderr
    return root


def test_render_writes_pngs_and_metadata(built_project: Path) -> None:
    out = built_project / "render-out"
    result = _heph(["render", "primary", "--views", "iso", "+X", "--out", str(out)], built_project)
    assert result.returncode == 0, result.stderr
    assert (out / "primary_iso_rgb.png").is_file()
    assert (out / "primary_pX_rgb.png").is_file()
    for name in ("primary_iso_rgb.png", "primary_pX_rgb.png"):
        assert (out / name).read_bytes().startswith(b"\x89PNG\r\n")
    metadata = json.loads((out / "primary_render.json").read_text())
    assert metadata["source_artifact_ref"].startswith("artifact:build:sha256:")
    assert len(metadata["images"]) == 2


def test_render_json_shape(built_project: Path) -> None:
    out = built_project / "render-json"
    result = _heph(
        ["render", "primary", "--views", "iso", "--channel", "mask", "--out", str(out), "--json"],
        built_project,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["source_artifact_ref"].startswith("artifact:build:sha256:")
    assert isinstance(payload["images"], list) and len(payload["images"]) == 1
    image = payload["images"][0]
    assert image["view"] == "iso"
    assert image["channel"] == "mask"
    assert Path(image["file"]).is_file()
    assert "mask_legend_truncated" in payload


def test_render_selection_cli(built_project: Path) -> None:
    out = built_project / "render-sel"
    result = _heph(
        [
            "render",
            "primary",
            "--views",
            "iso",
            "--channel",
            "mask",
            "--mask-mode",
            "selection",
            "--out",
            str(out),
            "--json",
        ],
        built_project,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["selection_table_ref"].startswith("artifact:selection-table:")
    assert len(payload["selection_bundles"]) == 1
    bundle = payload["selection_bundles"][0]
    assert set(bundle["pass_refs"]) == {"solid", "face", "edge"}


# -- goldens dirty-tree meta-test ------------------------------------------


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "seed"], repo)
    return repo


def test_git_is_dirty_detects_clean_and_dirty(scratch_repo: Path) -> None:
    assert git_is_dirty(scratch_repo) is False
    (scratch_repo / "new.txt").write_text("x\n", encoding="utf-8")
    assert git_is_dirty(scratch_repo) is True


def test_git_is_dirty_fails_closed_on_non_repo(tmp_path: Path) -> None:
    # A plain directory (no git) is treated as dirty (fail closed).
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_is_dirty(plain) is True


def test_update_goldens_refuses_dirty_tree(scratch_repo: Path) -> None:
    (scratch_repo / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    with pytest.raises(DirtyTreeError):
        update_goldens(out_dir=scratch_repo / "goldens", repo_root=scratch_repo)
    # Nothing was written before the refusal.
    assert not (scratch_repo / "goldens").exists()


def test_script_hash_and_specs_are_well_formed() -> None:
    assert script_hash().startswith("sha256:")
    assert len(GOLDEN_SPECS) >= 1
    channels = {spec.channel for spec in GOLDEN_SPECS}
    assert {"rgb", "mask", "section"} <= channels


# -- B-10: golden regeneration outside a checkout must refuse by name -------


def test_update_goldens_refuses_outside_a_checkout(scratch_repo: Path) -> None:
    """``scratch_repo`` is a clean git repository with no ``corpus/`` at all —
    exactly "a clean git-backed project" from the ledger's reproduction.
    Today this raises a raw ``FileNotFoundError`` from ``shutil.copytree``
    reaching for a fixture path that only exists inside the Hephaestus clone.
    """
    from hephaestus.core.render import goldens as goldens_mod

    error_cls = getattr(goldens_mod, "GoldenCorpusUnavailableError", None)
    assert error_cls is not None, (
        "B-10 fix step 6: hephaestus.core.render.goldens must define "
        "GoldenCorpusUnavailableError, raised before the golden loop when the "
        "fixtures root is not a directory (docs/audit-2026-09-04-broken.md B-10)"
    )
    with pytest.raises(error_cls):
        update_goldens(out_dir=scratch_repo / "goldens", repo_root=scratch_repo)
    assert not (scratch_repo / "goldens").exists()


def test_goldens_cli_refuses_outside_checkout_without_traceback(scratch_repo: Path) -> None:
    """The CLI-level case: exit 2, a named message, and — unlike today — no
    Python traceback on stderr."""
    result = _heph(["goldens", "--update"], scratch_repo)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "Traceback" not in result.stderr
    assert "heph:" in result.stderr


def test_goldens_fixtures_dir_overrides_the_default_corpus(tmp_path: Path) -> None:
    """``--fixtures-dir`` (ledger fix step 7) lets a fork with its own corpus
    use the verb; regenerating from a copied single-spec corpus must still
    work from outside the Hephaestus checkout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "seed"], repo)

    spec = GOLDEN_SPECS[0]
    fixtures_dir = tmp_path / "my_fixtures"
    fixtures_dir.mkdir()
    shutil.copytree(FIXTURES / spec.fixture, fixtures_dir / spec.fixture)

    out = repo / "golden-out"
    result = _heph(
        ["goldens", "--update", "--dir", str(out), "--fixtures-dir", str(fixtures_dir)],
        repo,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    pngs = list(out.glob("*.png"))
    assert pngs, "expected at least one golden PNG regenerated under the overridden fixtures dir"


# -- B-10: `heph render`'s --out must be validated before the GL session ----


@pytest.fixture()
def unwritable_dir(tmp_path: Path) -> Iterator[Path]:
    """A directory with no write bit — ``mkdir`` beneath it raises PermissionError."""
    denied = tmp_path / "denied"
    denied.mkdir()
    denied.chmod(0o555)
    try:
        yield denied
    finally:
        denied.chmod(0o755)


def test_render_out_precondition_runs_before_the_gl_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unwritable_dir: Path,
) -> None:
    """Today ``out_dir.mkdir`` runs *after* every requested view has already
    been rendered (B-10 root cause): the images exist in memory and are
    discarded, and the raw ``PermissionError`` reaches the interpreter. Patch
    ``inspect_part`` to blow up if it is ever reached, proving the fixed CLI
    validates ``--out`` first and never opens a GL session at all."""
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("inspect_part must not run before --out is validated")

    monkeypatch.setattr("hephaestus.core.render.inspect.inspect_part", _must_not_be_called)

    out = unwritable_dir / "sub" / "render-out"
    code = cli_render.main(["render", "example", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--out" in err


def test_render_pose_out_precondition_runs_before_the_gl_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unwritable_dir: Path,
) -> None:
    """Same precondition, the posed-render command — B-10 notes this ``mkdir``
    was copied verbatim from the single-part command, "evidence on its own
    that a shared helper is the right shape"."""
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    def _must_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("render_posed_scene must not run before --out is validated")

    monkeypatch.setattr("hephaestus.core.render.posed.render_posed_scene", _must_not_be_called)

    out = unwritable_dir / "sub" / "render-out"
    code = cli_render.main(["render", "--pose", "p1", "--out", str(out)])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "--out" in err


# -- J-cli-robustness-10: a part that does not exist is told so, not told it
# -- "has no current successful build" (that sentence is true only of a part
# -- that exists and was never built) --------------------------------------


def test_render_of_a_nonexistent_part_says_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph render nosuch`` must not send the operator to build a part that
    is not there. ``core/src/hephaestus/core/render/inspect.py`` tests
    ``current is None or current.artifact_ref is None`` and raises one message
    for two distinct conditions without first asking whether the part exists —
    with the part list right there, already passed as ``candidates``
    (ledger J-cli-robustness-10). The correct wording already exists in the
    tree, at ``ProjectStore.read_part`` — what ``heph part show nosuch``
    prints.
    """
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    code = cli_render.main(["render", "nosuch"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "does not exist" in err, err
    assert "example" in err  # the candidate list, not a guess
    assert "has no current successful build" not in err, err


def test_render_of_an_unbuilt_but_real_part_still_says_no_current_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard against over-correcting J-cli-robustness-10: a part that
    genuinely exists and was never built keeps its own, different, message."""
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    code = cli_render.main(["render", "example"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "has no current successful build" in err, err
    assert "does not exist" not in err, err


def test_the_unbuilt_part_is_not_offered_as_a_candidate_for_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other half of not conflating the two states.

    Candidates answer "which name did you mean instead?". Attaching the whole
    part list to a refusal about a part that *resolved* offers the part as an
    alternative to itself, and re-blurs at the reporting layer exactly the
    distinction J-cli-robustness-10 draws at the raise site: the operator reads
    "primary ... (candidates: ..., primary)" and cannot tell which of the two
    states they are in.
    """
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    code = cli_render.main(["render", "example"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "candidates" not in err, err


def test_a_nonexistent_part_keeps_its_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard on the guard: suppressing a self-referential candidate list
    must not suppress a genuine one, which is the actionable half of an
    addressing refusal (``core/DESIGN.md`` §7)."""
    from hephaestus.core import cli_init, cli_render

    target = tmp_path / "proj"
    cli_init.scaffold(target)
    monkeypatch.chdir(target)

    code = cli_render.main(["render", "nosuch"])
    err = capsys.readouterr().err
    assert code == 2, err
    assert "candidates: " in err, err
    assert "example" in err, err


# -- J-cli-robustness-13: `heph goldens` with no flag verifies, not refuses --


@pytest.fixture()
def single_spec_fixtures(tmp_path: Path) -> Path:
    """A copy of one golden spec's fixture, so regeneration is cheap and does
    not touch the real Hephaestus checkout (whose tree is not guaranteed clean
    while other lanes are editing it)."""
    spec = GOLDEN_SPECS[0]
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    shutil.copytree(FIXTURES / spec.fixture, fixtures_dir / spec.fixture)
    return fixtures_dir


def test_goldens_bare_verb_verifies_instead_of_refusing(
    tmp_path: Path, single_spec_fixtures: Path
) -> None:
    """A bare verb with exactly one useful mode should do it or show help, not
    refuse (ledger J-cli-robustness-13). Today ``heph goldens`` with no
    ``--update`` prints "nothing to do" and exits 2 regardless of whether the
    corpus matches — asking for nothing is not "you asked for something
    impossible". Regenerate once into ``out``, then run the bare verb against
    that same, matching corpus: it must not refuse, and it must not say
    "nothing to do"."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "seed"], repo)

    out = repo / "golden-out"
    generate = _heph(
        ["goldens", "--update", "--dir", str(out), "--fixtures-dir", str(single_spec_fixtures)],
        repo,
    )
    assert generate.returncode == 0, (generate.stdout, generate.stderr)

    verify = _heph(
        ["goldens", "--dir", str(out), "--fixtures-dir", str(single_spec_fixtures)], repo
    )
    assert verify.returncode == 0, (verify.returncode, verify.stdout, verify.stderr)
    assert "nothing to do" not in verify.stderr


def test_goldens_bare_verb_reports_drift_by_name(
    tmp_path: Path, single_spec_fixtures: Path
) -> None:
    """A corrupted golden sidecar must be reported by name with a nonzero exit
    — the verify mode has to actually check something, not just succeed
    unconditionally once it no longer refuses."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.com"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "seed"], repo)

    out = repo / "golden-out"
    generate = _heph(
        ["goldens", "--update", "--dir", str(out), "--fixtures-dir", str(single_spec_fixtures)],
        repo,
    )
    assert generate.returncode == 0, (generate.stdout, generate.stderr)

    spec = GOLDEN_SPECS[0]
    sidecars = list(out.glob("*.json"))
    assert sidecars, sorted(p.name for p in out.iterdir())
    sidecar = sidecars[0]
    sidecar.write_text(
        sidecar.read_text(encoding="utf-8").replace(script_hash(), "sha256:" + "0" * 64),
        encoding="utf-8",
    )

    verify = _heph(
        ["goldens", "--dir", str(out), "--fixtures-dir", str(single_spec_fixtures)], repo
    )
    assert verify.returncode == 1, (verify.returncode, verify.stdout, verify.stderr)
    assert spec.name in verify.stdout + verify.stderr
