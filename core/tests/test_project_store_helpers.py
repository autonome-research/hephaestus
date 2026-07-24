"""Shared builders for the project_store tests (not a test module).

Importable by test_project_store_*.py and by subprocess crash runners (which
insert this directory on ``sys.path``). Builds a minimal real project tree
and a deterministic synthetic :class:`UnpublishedBuild` whose input hashes
are internally consistent, so publication revalidation passes against the
live tree it was derived from.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.hashing import (
    consumed_hc_hash,
    effective_params_hash,
    hash_text,
    sha256_bytes,
    sha256_canonical_json,
    toolchain_hash,
)
from hephaestus.core.project_store.layout import ProjectLayout, load_project
from hephaestus.core.types import AuditHashes, BuildResult, ErrorRecord, InputHashes
from opstore.types import JSONValue

DEFAULT_SCRIPT = "part.geometry = None  # synthetic\n"


def make_project(
    root: Path,
    *,
    name: str = "proj",
    parts: Mapping[str, str] | None = None,
    globals_source: str | None = None,
    manifest_extra: str = "",
) -> ProjectLayout:
    """Write a minimal project tree under ``root`` and load its layout."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(
        f'name = "{name}"\nunits = "mm"\n{manifest_extra}', encoding="utf-8"
    )
    parts_dir = root / "parts"
    parts_dir.mkdir(exist_ok=True)
    for part, script in (parts or {"widget": DEFAULT_SCRIPT}).items():
        (parts_dir / f"{part}.py").write_text(script, encoding="utf-8")
    if globals_source is not None:
        (root / "globals.py").write_text(globals_source, encoding="utf-8")
    return load_project(root)


def make_unpublished(
    part: str,
    script: str,
    out_dir: Path,
    *,
    consumed: Mapping[str, JSONValue] | None = None,
    declaration: Mapping[str, JSONValue] | None = None,
    effective: Mapping[str, int | float] | None = None,
    globals_source: str | None = None,
    status: Literal["ok", "failed"] = "ok",
) -> UnpublishedBuild:
    """A deterministic synthetic build result over real artifact files."""
    consumed_map: dict[str, JSONValue] = dict(consumed or {})
    declaration_map: dict[str, JSONValue] = dict(declaration or {})
    effective_map: dict[str, int | float] = dict(effective or {})
    out_dir.mkdir(parents=True, exist_ok=True)
    input_hashes = InputHashes(
        script=hash_text(script),
        hc_dependencies=consumed_hc_hash(consumed_map),
        part_params=sha256_canonical_json(declaration_map),
        effective_params=effective_params_hash(effective_map),
        toolchain=toolchain_hash(),
    )
    audit_hashes = AuditHashes(
        globals_source=hash_text(globals_source or ""),
        project_param_state=effective_params_hash({}),
    )
    artifact_files: dict[str, Path] = {}
    artifact_ref: str | None = None
    error: ErrorRecord | None = None
    if status == "ok":
        stamp = ",".join(f"{k}={v!r}" for k, v in sorted(effective_map.items()))
        data = f"brep::{part}::{script}::{stamp}".encode()
        artifact_ref = f"artifact:build:{sha256_bytes(data)}"
        path = out_dir / "final.brep"
        path.write_bytes(data)
        artifact_files[artifact_ref] = path
    else:
        last_good = f"lastgood::{part}".encode()
        last_good_ref = f"artifact:build-checkpoint:{sha256_bytes(last_good)}"
        path = out_dir / "last_good.brep"
        path.write_bytes(last_good)
        artifact_files[last_good_ref] = path
        error = ErrorRecord(
            line=3,
            col=0,
            type="ValueError",
            message="synthetic failure",
            frame=("> 3 | boom",),
            built_through=None,
            last_good=None,
            last_good_artifact_ref=last_good_ref,
            hint="synthetic",
        )
    result = BuildResult(
        part=part,
        status=status,
        current=False,
        artifact_ref=artifact_ref,
        project_snapshot_ref=None,
        input_hashes=input_hashes,
        audit_hashes=audit_hashes,
        metrics=None,
        checks={},
        geometries=(),
        params=effective_map,
        source_map_ref=None,
        warnings=(),
        error=error,
    )
    return UnpublishedBuild(
        result=result,
        out_dir=out_dir,
        artifact_files=artifact_files,
        consumed_hc=consumed_map,
        worker_result={"params_declaration": declaration_map},
    )


def build_for_crash(layout: ProjectLayout, out_dir: Path) -> UnpublishedBuild:
    """The exact build the crash-recovery runner and its retry both construct."""
    script = layout.part_path("widget").read_text(encoding="utf-8")
    return make_unpublished("widget", script, out_dir)
