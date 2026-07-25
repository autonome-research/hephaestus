"""Gate G1 — ``heph render`` runs with Node absent from PATH (engine-first).

Gate G1 runs ``uv run pytest tests/stage1 tests/render`` **with Node absent**;
these subprocess cases prove the render CLI needs no Node toolchain: ``node`` is
stripped from the child's ``PATH`` and the precondition (``node`` truly
unreachable) is asserted before the render is trusted. rgb, mask, and
selection modes are exercised end-to-end against the public ``assembly``
fixture, then the JSON contract is checked.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSEMBLY = REPO_ROOT / "corpus" / "public_fixtures" / "assembly"


def _node_free_env() -> dict[str, str]:
    """A process env whose PATH resolves no ``node`` binary."""
    env = dict(os.environ)
    kept = [
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry and shutil.which("node", path=entry) is None
    ]
    env["PATH"] = os.pathsep.join(kept)
    return env


def _heph(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.fixture(scope="module")
def built_project(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    root = tmp_path_factory.mktemp("cli-no-node")
    shutil.copytree(ASSEMBLY, root, dirs_exist_ok=True)
    env = _node_free_env()
    # Precondition: node is genuinely unreachable in the child PATH (engine-first).
    assert shutil.which("node", path=env["PATH"]) is None
    build = _heph(["build", "primary", "--unsafe-local-executor"], root, env)
    assert build.returncode == 0, build.stderr
    return root, env


def test_render_rgb_without_node(built_project: tuple[Path, dict[str, str]]) -> None:
    root, env = built_project
    out = root / "rgb-out"
    result = _heph(
        ["render", "primary", "--views", "iso", "+X", "--out", str(out), "--json"], root, env
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["source_artifact_ref"].startswith("artifact:build:sha256:")
    assert len(payload["images"]) == 2
    for image in payload["images"]:
        assert Path(image["file"]).is_file()
        assert Path(image["file"]).read_bytes().startswith(b"\x89PNG\r\n")


def test_render_mask_without_node(built_project: tuple[Path, dict[str, str]]) -> None:
    root, env = built_project
    out = root / "mask-out"
    result = _heph(
        ["render", "primary", "--views", "iso", "--channel", "mask", "--out", str(out), "--json"],
        root,
        env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert len(payload["images"]) == 1
    assert payload["images"][0]["channel"] == "mask"
    assert "mask_legend_truncated" in payload


def test_render_selection_without_node(built_project: tuple[Path, dict[str, str]]) -> None:
    root, env = built_project
    out = root / "sel-out"
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
        root,
        env,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["selection_table_ref"].startswith("artifact:selection-table:")
    assert len(payload["selection_bundles"]) == 1
    bundle = payload["selection_bundles"][0]
    assert bundle["view"] == "iso"
    assert set(bundle["pass_refs"]) == {"solid", "face", "edge"}
    for ref in bundle["pass_refs"].values():
        assert ref.startswith("artifact:selection-pass:")
