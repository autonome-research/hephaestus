# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""``heph render`` end-to-end and ``heph goldens`` dirty-tree refusal.

The render CLI is exercised as a real subprocess against the public assembly
fixture (build then render); the goldens generator is verified to refuse a
dirty git tree (verification.md meta-test) using a throwaway scratch repo.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
