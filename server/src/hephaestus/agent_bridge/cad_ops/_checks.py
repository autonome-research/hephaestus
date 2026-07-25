"""Project-check CRUD, the safe template, and both ``run_checks`` scopes.

Check sources under ``checks/`` are a generation-tracked
:class:`~hephaestus.core.checks.engine.CheckSet`: creation installs the safe
cross-part template no-replace, edits validate in the check sandbox and advance
the generation, and listing pages an immutable frozen bundle manifest (summaries
are first-comment lines, never source).

``run_checks`` has two scopes. Part scope re-executes the part's own ``CHECKS``
through the worker and publishes the run as a *preview*, so evidence is durable
but nothing becomes current. Project scope freezes the authorized bundle, runs it
over one coherent project snapshot, and fails closed on an invalid generation.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.checks.engine import CheckSetState, load_check_module, run_bundle
from hephaestus.core.errors import AddressingError, InvalidCheckGenerationError, ValidationError
from hephaestus.core.project_store.projections import SnapshotRejectedError
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from ._base import CadOpError, CadOpsState

#: The safe cross-part check template (``create_project_check``). The sentinel is
#: substituted, not ``str.format``-ed, because the body itself contains braces.
CHECK_DESCRIPTION_SENTINEL: Final[str] = "__DESCRIPTION__"
CHECK_TEMPLATE_HEADER: Final[str] = (
    f"# Project check{CHECK_DESCRIPTION_SENTINEL}\n"
    "#\n"
    "# Checks receive the measurement facade `m` and the pure `approx` helper\n"
    '# only. Address another part as "<part>/<selector>".\n'
    "\n"
    "CHECKS = {\n"
    '    "placeholder": lambda m: True,\n'
    "}\n"
)

#: ``summary`` cap for ``list_project_checks`` items (tool_schema: 512 UTF-8 bytes).
_SUMMARY_MAX_BYTES: Final[int] = 512


def check_template(description: str) -> str:
    """The initial script ``create_project_check`` installs (no-replace)."""
    suffix = f": {description}" if description else ""
    return CHECK_TEMPLATE_HEADER.replace(CHECK_DESCRIPTION_SENTINEL, suffix)


class CheckOps(CadOpsState):
    """Read/write the project check set and execute checks in either scope."""

    def check_state(self) -> CheckSetState:
        """The current check-set generation (after recovery/reconciliation)."""
        return self._check_set().current()

    def check_diagnostics_ref(self, state: CheckSetState) -> str | None:
        return (
            None
            if state.diagnostics is None
            else make_artifact_ref("check-diagnostics", state.diagnostics)
        )

    def read_check(self, name: str) -> tuple[str, str, str]:
        """``(script, content_hash, snapshot_ref)`` for ``checks/<name>.py``."""
        path = self._layout.checks_dir / f"{name}.py"
        if not path.is_file():
            raise AddressingError(
                f"project check {name!r} does not exist under {self._layout.checks_dir}",
                selector=name,
                candidates=self.check_names(),
            )
        raw = path.read_bytes()
        blob = self._store.blobs.put(raw)
        return raw.decode("utf-8"), blob, make_artifact_ref("part-snapshot", blob)

    def check_names(self) -> tuple[str, ...]:
        directory = self._layout.checks_dir
        if not directory.is_dir():
            return ()
        return tuple(sorted(path.stem for path in directory.glob("*.py")))

    def write_check(self, name: str, content: str, *, op_id: str) -> CheckSetState:
        """Cooperative create/edit of ``checks/<name>.py`` (generation advance)."""
        return self._check_set().write_check(f"{name}.py", content, op_id=op_id)

    def check_bundle_items(self, bundle_ref: str) -> list[dict[str, JSONValue]]:
        """The frozen lexical check index behind ``check_set_ref`` (paging source)."""
        blob = blob_hash_of_ref(bundle_ref)
        if not self._store.blobs.has(blob):
            raise CadOpError("invalid_cursor", f"check-set index {bundle_ref} is not stored")
        manifest = cast(
            "Mapping[str, JSONValue]",
            json.loads(self._store.blobs.get(blob).decode("utf-8")),
        )
        entries = manifest.get("files")
        items: list[dict[str, JSONValue]] = []
        if not isinstance(entries, list):
            return items
        for entry in cast("list[JSONValue]", entries):
            if not isinstance(entry, dict):
                continue
            record = cast("Mapping[str, JSONValue]", entry)
            path = record.get("path")
            content_hash = record.get("hash")
            if not isinstance(path, str) or not isinstance(content_hash, str):
                continue
            items.append(
                {
                    "name": Path(path).stem,
                    "content_hash": content_hash,
                    "summary": self._check_summary(content_hash),
                }
            )
        return items

    def _check_summary(self, content_hash: str) -> str:
        """First comment/docstring line of a check file, capped at 512 UTF-8 bytes."""
        if not self._store.blobs.has(content_hash):
            return ""
        try:
            text = self._store.blobs.get(content_hash).decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - checks are UTF-8 sources
            return ""
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            summary = stripped.lstrip("#").strip().strip('"').strip("'")
            if not summary:
                continue
            encoded = summary.encode("utf-8")[:_SUMMARY_MAX_BYTES]
            # Truncate at a valid code-point boundary; never embed source.
            return encoded.decode("utf-8", errors="ignore")
        return ""

    @staticmethod
    def validate_check_source(name: str, content: str) -> str | None:
        """``None`` when the candidate is valid, else the failure ``kind``."""
        try:
            load_check_module(content, filename=f"{name}.py")
        except ValidationError as exc:
            return exc.kind
        return None

    # -- run_checks --------------------------------------------------------

    def run_part_checks(self, name: str) -> dict[str, Any]:
        """Re-execute ``name``'s persistent ``CHECKS`` (published as a preview)."""
        publisher = self._publisher()
        inputs = publisher.freeze_inputs(name)
        with self._build_dir(name) as out_dir:
            build = self._run(
                name,
                inputs.script,
                inputs.globals_source,
                out_dir=out_dir,
                part_overrides=dict(self.params.read("part", name).values),
                project_overrides=self._project_overrides(),
                baseline=publisher.baseline_for(name),
            )
            # preview=True: evidence is durable (refs resolve) but nothing becomes
            # current and no stale marker is cleared — run_checks is not a mutation.
            outcome = publisher.publish_build(
                build, op_id=f"heph-run-checks-{uuid.uuid4().hex}", preview=True
            )
        result: BuildResult = outcome.result
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "scope": "part",
            "part": name,
            "checks": {check_name: check.to_json() for check_name, check in result.checks.items()},
        }
        if result.artifact_ref is not None:
            payload["artifact_ref"] = result.artifact_ref
        if result.error is not None:
            payload["error"] = result.error.to_json()
        return payload

    def run_project_checks(self, project_snapshot_ref: str | None) -> dict[str, Any]:
        """Freeze the authorized cross-part bundle and run it (fails closed)."""
        check_set = self._check_set()
        bundle = check_set.capture()
        state = bundle.state
        if state.status == "invalid":
            payload: dict[str, Any] = {
                "status": "invalid_check_generation",
                "check_set_generation": str(state.generation),
                "check_set_ref": state.bundle_ref,
            }
            diagnostics = self.check_diagnostics_ref(state)
            if diagnostics is not None:
                payload["diagnostics_ref"] = diagnostics
            return payload
        publisher = self._publisher()
        with self._scratch("heph-checks-") as scratch:
            if project_snapshot_ref is None:
                try:
                    snapshot = publisher.projections.assemble_snapshot(self._layout.part_names())
                except SnapshotRejectedError as exc:
                    raise CadOpError(
                        "incoherent_project_snapshot",
                        exc.message,
                        data={"issues": [issue.to_json() for issue in exc.issues]},
                    ) from exc
                resolved_ref = snapshot.ref
            else:
                resolved_ref = project_snapshot_ref
            sources, _refs = self._snapshot_sources(resolved_ref, Path(scratch))
            try:
                report = run_bundle(
                    bundle,
                    sources,
                    part=self._layout.manifest.name,
                    project_snapshot_ref=resolved_ref,
                )
            except InvalidCheckGenerationError as exc:  # pragma: no cover - captured above
                raise CadOpError("invalid_check_generation", exc.message) from exc
        payload = dict(report.to_json())
        payload["status"] = "ok"
        payload["scope"] = "project"
        payload["check_set_generation"] = str(state.generation)
        payload["check_set_ref"] = state.bundle_ref
        return payload
