"""G8D: the fetch surface, without the network (``EXTERNAL_EVAL.md`` §2).

Gate clause: *fetch is NOT exercised against the network in tests (the CLI
surface is covered by a cache-layout test)*.

So the hub call is faked and what is asserted is everything around it: that the
cache lands **outside** the repository, that a destination inside the repository
is refused outright rather than warned about (§4 — no committed external data),
and that the resolved revision is recorded. The last one is not bookkeeping: a
benchmark number without the dataset revision it was measured on is not a
measurement.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from _g8d import DATASET
from hephaestus.bench.cadgenbench import (
    CACHE_ENV_VAR,
    DATASET_REPO_ID,
    FETCH_RECORD_FILENAME,
    default_cache_dir,
    fetch_dataset,
    read_fetch_record,
    resolve_dataset_root,
)
from hephaestus.core.cli import main as heph_main

REVISION = "f76f965585817c621d6ea0d150d745adf670e66e"


def fake_hub(root: Path) -> Any:
    """Stand-in for ``snapshot_download``: lays the snapshot down where the hub would."""
    calls: list[dict[str, Any]] = []

    def download(**kwargs: Any) -> str:
        calls.append(dict(kwargs))
        cache = Path(str(kwargs["cache_dir"]))
        repo = str(kwargs["repo_id"]).replace("/", "--")
        snapshot = cache / f"datasets--{repo}" / "snapshots" / REVISION
        shutil.copytree(DATASET, snapshot, dirs_exist_ok=True)
        return str(snapshot)

    download.calls = calls  # pyright: ignore[reportFunctionMemberAccess]
    return download


def test_fetch_caches_outside_the_repo_and_records_the_revision(tmp_path: Path) -> None:
    download = fake_hub(tmp_path)
    cache = tmp_path / "cache"

    record = fetch_dataset(cache, downloader=download)

    assert record.repo_id == DATASET_REPO_ID
    assert record.revision == REVISION
    assert record.sample_ids == ("101", "102", "201", "301", "302")
    assert "Mecado" in record.attribution  # ODC-BY attribution travels with it
    # The hub was asked for a dataset repo, into our cache, and nowhere else.
    call = download.calls[0]  # pyright: ignore[reportFunctionMemberAccess]
    assert call["repo_type"] == "dataset"
    assert Path(call["cache_dir"]) == cache

    document = json.loads((cache / FETCH_RECORD_FILENAME).read_text(encoding="utf-8"))
    assert document["revision"] == REVISION
    assert document["n_samples"] == 5
    assert read_fetch_record(cache) == record
    # …and the recorded snapshot is what later verbs read.
    assert resolve_dataset_root(cache=cache) == record.snapshot_root


def test_a_destination_inside_the_repository_is_refused(tmp_path: Path) -> None:
    from hephaestus.agent_bridge.app import repo_root

    with pytest.raises(ValueError, match="refusing to cache"):
        fetch_dataset(repo_root() / "bench" / "cadgenbench-cache", downloader=fake_hub(tmp_path))


def test_the_default_cache_is_under_the_users_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(CACHE_ENV_VAR, raising=False)
    assert default_cache_dir() == Path.home() / ".cache" / "hephaestus" / "cadgenbench"

    monkeypatch.setenv(CACHE_ENV_VAR, str(tmp_path / "elsewhere"))
    assert default_cache_dir() == tmp_path / "elsewhere"


def test_the_cli_surface_is_registered_under_heph_bench(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``heph bench cadgenbench …`` exists, and its verbs are wired to the adapter."""
    monkeypatch.chdir(tmp_path)

    # No cached snapshot and no --source: a named refusal, not a network call.
    assert heph_main(["bench", "cadgenbench", "convert", "--source", str(tmp_path / "nope")]) == 1
    assert "cadgenbench" in capsys.readouterr().err

    assert heph_main(["bench", "cadgenbench", "convert", "--source", str(DATASET), "--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["tasks"] == ["cadgenbench-101", "cadgenbench-102", "cadgenbench-201"]
    # The exit code is non-zero *because* two samples were refused by name.
    assert [row["reason"] for row in document["refusals"]] == [
        "missing_input_file",
        "unknown_task_type",
    ]


def test_packaging_requires_the_operators_consent_at_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``agree_to_publish`` is the leaderboard's only consent gate; the CLI cannot assume it."""
    code = heph_main(
        [
            "bench",
            "cadgenbench",
            "package",
            "--outputs",
            str(tmp_path / "outputs"),
            "--out",
            str(tmp_path / "submission.zip"),
            "--submitter",
            "Somebody",
            "--submission",
            "Something",
            "--samples",
            "101",
        ]
    )

    assert code == 2
    assert "--agree-to-publish is required" in capsys.readouterr().err
    assert not (tmp_path / "submission.zip").exists()
