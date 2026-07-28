"""Assembling the submission ZIP the leaderboard accepts (``EXTERNAL_EVAL.md`` §2).

Everything here is written against the real submission contract
(``CADGENBENCH_FACTS.md`` — "Submission contract"), because the Space rejects a
malformed upload outright rather than scoring it partially:

- **no wrapper directory**: ``meta.json`` sits at the ZIP root and every sample
  folder is a top-level entry;
- **all sample folders are present**, including the unsolved ones — the folder
  set must equal the dataset's exactly, and both missing and extra folders are
  fatal server-side. An empty folder needs an explicit ``"<sample>/"`` directory
  entry or it does not survive extraction and comes back as "missing sample";
- **``meta.json`` has all five keys**, ``agent_url`` and ``notes`` may be
  ``null`` but must exist, and ``agree_to_publish`` must be the literal boolean
  ``true`` (the check is ``is not True``, so the string ``"true"`` is rejected).
  That flag is the sole consent gate, so this module never defaults it: an
  operator publishes, a harness does not.

Packaging **fails** — no ZIP is written — when a declared sample folder is
missing, when an included candidate fails the local validity floor, or when the
benchmark's own ``sanity_check_submission.py`` rejects one. The order matters:
validate everything, report every failure, then write. A half-written ZIP that
looks submittable is worse than no ZIP.

The sanity checker is **fetched on demand into the cache, never vendored**: it
ships in the ODC-BY *data* repo rather than the Apache-2.0 code repo, so
committing a copy would be redistributing dataset content under terms we would
have to reason about (and ``EXTERNAL_EVAL.md`` §4 says no committed external
data). It also hard-imports the full ``cadgenbench`` install (build123d,
cadquery-ocp, open3d, trimesh, …), so an environment without it gets a named
``sanity_check_error``, never a silent pass.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ._fetch import ATTRIBUTION, DATASET_REPO_ID, SANITY_CHECK_FILENAME, default_cache_dir
from ._validity import ValidityFacts, step_validity

__all__ = [
    "CANDIDATE_NAMES",
    "META_FILENAME",
    "NOTES_MAX_CHARS",
    "REQUIRED_META_KEYS",
    "SUBMISSION_CANDIDATE",
    "PackageReport",
    "PackagingError",
    "SubmissionMeta",
    "package_submission",
    "resolve_sanity_check",
    "run_sanity_check",
]

#: Accepted candidate filenames, in the benchmark's own priority order (the
#: constant is duplicated identically in four places upstream).
CANDIDATE_NAMES: tuple[str, ...] = ("output.step", "output.stp")

#: What this adapter writes. Editing samples write ``output.step`` too — never a
#: renamed ``input.step``.
SUBMISSION_CANDIDATE = CANDIDATE_NAMES[0]

META_FILENAME = "meta.json"
REQUIRED_META_KEYS: tuple[str, ...] = (
    "submitter_name",
    "submission_name",
    "agent_url",
    "notes",
    "agree_to_publish",
)
#: ``notes`` is capped *after* whitespace normalization, upstream.
NOTES_MAX_CHARS = 500

_WHITESPACE = re.compile(r"\s+")


class PackagingError(ValueError):
    """Packaging refused, with every reason it refused for."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("cadgenbench packaging failed: " + "; ".join(self.reasons))


@dataclass(frozen=True)
class SubmissionMeta:
    """The root ``meta.json``, validated the way the Space validates it."""

    submitter_name: str
    submission_name: str
    agent_url: str | None = None
    notes: str | None = None
    #: Consent to publish. Never defaulted to ``True``: it is the operator's
    #: declaration, and a harness has no standing to make it.
    agree_to_publish: bool = False

    def to_json(self) -> dict[str, Any]:
        if not self.submitter_name.strip():
            raise PackagingError(["meta_submitter_name_empty"])
        if not self.submission_name.strip():
            raise PackagingError(["meta_submission_name_empty"])
        if self.agree_to_publish is not True:
            raise PackagingError(["meta_agree_to_publish_required"])
        notes = self.notes
        if notes is not None:
            notes = _WHITESPACE.sub(" ", notes).strip()
            if len(notes) > NOTES_MAX_CHARS:
                raise PackagingError([f"meta_notes_too_long:{len(notes)}>{NOTES_MAX_CHARS}"])
        return {
            "submitter_name": self.submitter_name.strip(),
            "submission_name": self.submission_name.strip(),
            "agent_url": self.agent_url,
            "notes": notes,
            "agree_to_publish": True,
        }


@dataclass(frozen=True)
class SampleEntry:
    """One sample's place in the submission: solved, unsolved, or refused."""

    sample_id: str
    candidate: Path | None
    validity: ValidityFacts | None
    sanity: str | None = None

    @property
    def solved(self) -> bool:
        return self.candidate is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "candidate": None if self.candidate is None else str(self.candidate),
            "validity": None if self.validity is None else self.validity.to_json(),
            "sanity": self.sanity,
        }


@dataclass(frozen=True)
class PackageReport:
    """What the written ZIP contains (and how each candidate was checked)."""

    zip_path: Path
    entries: tuple[SampleEntry, ...] = ()
    sanity_check: str = "skipped"
    details: tuple[str, ...] = ()

    @property
    def n_solved(self) -> int:
        return sum(1 for entry in self.entries if entry.solved)

    def to_json(self) -> dict[str, Any]:
        return {
            "zip_path": str(self.zip_path),
            "n_samples": len(self.entries),
            "n_solved": self.n_solved,
            "n_unsolved": len(self.entries) - self.n_solved,
            "sanity_check": self.sanity_check,
            "entries": [entry.to_json() for entry in self.entries],
            "details": list(self.details),
            "attribution": ATTRIBUTION,
        }


def _candidate(directory: Path) -> Path | None:
    for name in CANDIDATE_NAMES:
        path = directory / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def resolve_sanity_check(
    *,
    dataset_root: Path | None = None,
    cache: Path | None = None,
    download: bool = True,
) -> Path:
    """Locate ``sanity_check_submission.py``: the snapshot first, then the hub.

    Never vendored into this repository (see the module docstring); the fetched
    copy lands in the same out-of-repo cache the dataset does.
    """
    if dataset_root is not None:
        local = dataset_root / SANITY_CHECK_FILENAME
        if local.is_file():
            return local
    cache_dir = (cache or default_cache_dir()).expanduser()
    cached = cache_dir / SANITY_CHECK_FILENAME
    if cached.is_file():
        return cached
    if not download:
        raise FileNotFoundError(
            f"{SANITY_CHECK_FILENAME} is not in the snapshot or the cache "
            f"({cache_dir}); fetch the dataset first"
        )
    from huggingface_hub import (
        hf_hub_download,  # pyright: ignore[reportUnknownVariableType]
    )

    fetch_file = cast("Callable[..., str]", hf_hub_download)
    downloaded = fetch_file(
        repo_id=DATASET_REPO_ID,
        repo_type="dataset",
        filename=SANITY_CHECK_FILENAME,
        cache_dir=str(cache_dir),
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(Path(downloaded).read_bytes())
    return cached


def run_sanity_check(
    script: Path, candidate: Path, *, python: str | None = None, timeout: float = 600.0
) -> tuple[bool, str]:
    """Run the benchmark's own checker on one STEP file.

    Exit codes are the benchmark's: ``0`` pass, ``1`` invalid or unloadable,
    ``2`` file not found. Anything else (an import failure from a missing
    ``cadgenbench`` install, a crash) is reported as an *error*, not a pass —
    an unrunnable check has verified nothing.
    """
    try:
        completed = subprocess.run(
            [python or sys.executable, str(script), str(candidate), "--quiet"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"sanity_check_error:{type(exc).__name__}: {exc}"
    if completed.returncode == 0:
        return True, "pass"
    detail = (completed.stderr or completed.stdout or "").strip().splitlines()
    head = detail[0] if detail else f"exit {completed.returncode}"
    # Exit 1 is ambiguous on its own: the checker uses it for "invalid", and the
    # interpreter uses it for an uncaught exception (a missing ``cadgenbench``
    # install is exactly that). Only the checker's own verdict lines count as a
    # verdict; anything else is an unrunnable check, which has verified nothing.
    if completed.returncode in (1, 2) and (head.startswith("FAIL") or head.startswith("ERROR:")):
        return False, f"sanity_check_failed:{head}"
    return False, f"sanity_check_error:exit {completed.returncode}: {head}"


def _write_zip(zip_path: Path, entries: Sequence[SampleEntry], meta: dict[str, Any]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(META_FILENAME, json.dumps(meta, indent=2, sort_keys=True) + "\n")
        for entry in entries:
            # An explicit directory entry, so an unsolved sample's folder
            # survives extraction instead of vanishing into "missing sample".
            info = zipfile.ZipInfo(f"{entry.sample_id}/")
            info.external_attr = (0o40755 << 16) | 0x10
            archive.writestr(info, b"")
            if entry.candidate is not None:
                archive.write(entry.candidate, f"{entry.sample_id}/{SUBMISSION_CANDIDATE}")


def package_submission(
    outputs_dir: Path,
    sample_ids: Sequence[str],
    meta: SubmissionMeta,
    zip_path: Path,
    *,
    sanity_check: Path | None = None,
    allow_missing: bool = False,
    python: str | None = None,
) -> PackageReport:
    """Validate the produced outputs and write the submission ZIP.

    ``sample_ids`` is the dataset's full sample set: the ZIP carries a folder
    for every one of them. ``allow_missing`` turns "this sample has no folder"
    from a failure into a recorded unsolved entry — an explicit operator choice,
    because the default has to be that a sample the run never produced is a
    packaging failure rather than a quiet zero.
    """
    document = meta.to_json()  # validated first: a bad meta.json fails nothing else
    if not sample_ids:
        raise PackagingError(["no_samples_declared"])

    reasons: list[str] = []
    details: list[str] = []
    entries: list[SampleEntry] = []
    declared = set(sample_ids)
    if outputs_dir.is_dir():
        for extra in sorted(p.name for p in outputs_dir.iterdir() if p.is_dir()):
            if extra not in declared:
                # Fatal server-side ("unexpected folder(s)"), so fatal here.
                reasons.append(f"unexpected_folder:{extra}")

    for sample_id in sample_ids:
        directory = outputs_dir / sample_id
        if not directory.is_dir():
            if not allow_missing:
                reasons.append(f"missing_sample:{sample_id}")
                continue
            entries.append(SampleEntry(sample_id=sample_id, candidate=None, validity=None))
            continue
        candidate = _candidate(directory)
        if candidate is None:
            # A legal, scored-zero submission: the folder exists and is empty.
            entries.append(SampleEntry(sample_id=sample_id, candidate=None, validity=None))
            continue
        facts = step_validity(candidate)
        sanity_note: str | None = None
        if not facts.ok:
            reasons.append(f"invalid_step:{sample_id}:{','.join(facts.failures)}")
        elif sanity_check is not None:
            passed, note = run_sanity_check(sanity_check, candidate, python=python)
            sanity_note = note
            if not passed:
                reasons.append(f"{note.split(':', 1)[0]}:{sample_id}")
                details.append(f"{sample_id}: {note}")
        entries.append(
            SampleEntry(
                sample_id=sample_id, candidate=candidate, validity=facts, sanity=sanity_note
            )
        )

    if reasons:
        raise PackagingError(reasons)
    _write_zip(zip_path, entries, document)
    return PackageReport(
        zip_path=zip_path,
        entries=tuple(entries),
        sanity_check="skipped" if sanity_check is None else str(sanity_check),
        details=tuple(details),
    )
