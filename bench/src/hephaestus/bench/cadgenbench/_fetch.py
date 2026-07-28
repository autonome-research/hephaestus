"""Fetching the public CADGenBench inputs into a cache **outside the repo**.

``EXTERNAL_EVAL.md`` §4: *no committed external data*. The dataset is ODC-BY
with geometry from Mecado — redistributing it inside this repository would be
both a licensing question we have no need to answer and a way to smuggle
benchmark inputs into the evidence tree. So the cache defaults to
``~/.cache/hephaestus/cadgenbench``, the destination is *refused* if it resolves
inside the repository, and the only thing this stage commits is the synthetic
mini-fixtures the tests author themselves.

What the fetch records is as important as what it downloads: a benchmark number
without the dataset revision it was measured on is not a measurement. Every
fetch writes ``fetch.json`` with the repo id, the resolved revision, the
snapshot root and the enumerated sample ids.

The hub call is injectable (``downloader=``) for exactly one reason: the gate
forbids network access in tests, and a cache-layout claim that could only be
checked by downloading 218 MB would not be checked at all.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from ._samples import discover_samples

__all__ = [
    "ATTRIBUTION",
    "CACHE_ENV_VAR",
    "DATASET_REPO_ID",
    "FETCH_RECORD_FILENAME",
    "SANITY_CHECK_FILENAME",
    "FetchRecord",
    "SnapshotDownloader",
    "default_cache_dir",
    "fetch_dataset",
    "read_fetch_record",
    "resolve_dataset_root",
]

#: The public inputs dataset (ground truth is a separate, private repo — see
#: ``CADGENBENCH_FACTS.md``; local scoring can never produce a ``cad_score``).
DATASET_REPO_ID = "HuggingAI4Engineering/cadgenbench-data"

#: The benchmark's own single-STEP validity checker, which lives in the dataset
#: root rather than in the code repo.
SANITY_CHECK_FILENAME = "sanity_check_submission.py"

CACHE_ENV_VAR = "HEPHAESTUS_CADGENBENCH_CACHE"
FETCH_RECORD_FILENAME = "fetch.json"

ATTRIBUTION = (
    "CADGenBench inputs (c) HuggingAI4Engineering, licensed ODC-BY; "
    "CAD geometry courtesy of Mecado (https://www.mecado.com)."
)

#: ``huggingface_hub.snapshot_download``'s shape, as this module uses it.
SnapshotDownloader = Callable[..., str]


def default_cache_dir() -> Path:
    """``$HEPHAESTUS_CADGENBENCH_CACHE`` or ``~/.cache/hephaestus/cadgenbench``."""
    override = os.environ.get(CACHE_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "hephaestus" / "cadgenbench"


def _refuse_inside_repo(dest: Path) -> None:
    """A dataset cache inside the working tree is refused, not warned about."""
    from hephaestus.agent_bridge.app import repo_root

    try:
        root = repo_root().resolve()
    except Exception:  # pragma: no cover - repo_root is total in a checkout
        return
    resolved = dest.expanduser().resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError(
            f"refusing to cache CADGenBench data inside the repository ({resolved}): "
            "the dataset is external, ODC-BY licensed content and is never committed "
            f"(EXTERNAL_EVAL.md §4). Pass a --dest outside {root}, or set {CACHE_ENV_VAR}."
        )


@dataclass(frozen=True)
class FetchRecord:
    """The provenance of one fetched snapshot (written as ``fetch.json``)."""

    repo_id: str
    revision: str
    snapshot_root: Path
    sample_ids: tuple[str, ...]
    fetched_at: str
    attribution: str = ATTRIBUTION

    def to_json(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "revision": self.revision,
            "snapshot_root": str(self.snapshot_root),
            "sample_ids": list(self.sample_ids),
            "n_samples": len(self.sample_ids),
            "fetched_at": self.fetched_at,
            "attribution": self.attribution,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FetchRecord:
        return cls(
            repo_id=str(data["repo_id"]),
            revision=str(data["revision"]),
            snapshot_root=Path(str(data["snapshot_root"])),
            sample_ids=tuple(str(s) for s in list(data.get("sample_ids", []))),
            fetched_at=str(data.get("fetched_at", "")),
            attribution=str(data.get("attribution", ATTRIBUTION)),
        )


def _resolve_revision(snapshot_root: Path, requested: str | None) -> str:
    """The commit the snapshot really is.

    ``snapshot_download`` lays a snapshot down at
    ``<cache>/datasets--<org>--<name>/snapshots/<sha>``, so the directory name
    *is* the resolved commit. A pinned ``revision`` that is already a sha agrees
    with it; a branch name does not, and the sha is the honest record.
    """
    if snapshot_root.parent.name == "snapshots" and snapshot_root.name:
        return snapshot_root.name
    return requested or "unknown"


def _hub_downloader() -> SnapshotDownloader:
    try:
        from huggingface_hub import (
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]
        )
    except ImportError as exc:  # pragma: no cover - dependency of the bench package
        raise RuntimeError(
            "huggingface_hub is required to fetch the CADGenBench dataset "
            "(declared by bench/pyproject.toml)"
        ) from exc
    # The hub's overloads are partially unknown to pyright under strict; the
    # contract this module uses is the documented one.
    return cast("SnapshotDownloader", snapshot_download)


def fetch_dataset(
    dest: Path | None = None,
    *,
    repo_id: str = DATASET_REPO_ID,
    revision: str | None = None,
    downloader: SnapshotDownloader | None = None,
) -> FetchRecord:
    """Download the public dataset into ``dest`` and record what was fetched."""
    cache = (dest or default_cache_dir()).expanduser()
    _refuse_inside_repo(cache)
    cache.mkdir(parents=True, exist_ok=True)
    download = downloader or _hub_downloader()
    snapshot = Path(
        download(repo_id=repo_id, repo_type="dataset", revision=revision, cache_dir=str(cache))
    )
    record = FetchRecord(
        repo_id=repo_id,
        revision=_resolve_revision(snapshot, revision),
        snapshot_root=snapshot,
        sample_ids=discover_samples(snapshot),
        fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    (cache / FETCH_RECORD_FILENAME).write_text(
        json.dumps(record.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def read_fetch_record(cache: Path | None = None) -> FetchRecord | None:
    """The last fetch's record, or ``None`` when nothing has been fetched."""
    path = (cache or default_cache_dir()).expanduser() / FETCH_RECORD_FILENAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: fetch record must be a JSON object")
    return FetchRecord.from_json(dict(data))  # pyright: ignore[reportUnknownArgumentType]


def resolve_dataset_root(source: Path | None = None, *, cache: Path | None = None) -> Path:
    """The samples root to read: an explicit ``--source``, else the last fetch.

    ``source`` may name either the snapshot root itself or a directory holding
    one, so an operator who unpacked the dataset by hand is not fought with.
    """
    if source is not None:
        root = source.expanduser()
        if not root.is_dir():
            raise FileNotFoundError(f"cadgenbench source {root} does not exist")
        if discover_samples(root):
            return root
        raise FileNotFoundError(f"no CADGenBench samples under {root}")
    record = read_fetch_record(cache)
    if record is None:
        raise FileNotFoundError(
            "no CADGenBench snapshot cached: run `heph bench cadgenbench fetch` "
            "first, or pass --source"
        )
    if not record.snapshot_root.is_dir():
        raise FileNotFoundError(
            f"the recorded snapshot {record.snapshot_root} is gone; re-run "
            "`heph bench cadgenbench fetch`"
        )
    return record.snapshot_root
