"""Project-check CRUD, the safe template, and both ``run_checks`` scopes.

Check sources under ``checks/`` are a generation-tracked
:class:`~hephaestus.core.checks.engine.CheckSet`: creation installs the safe
cross-part template no-replace, edits validate in the check sandbox and advance
the generation, and listing pages an immutable frozen bundle manifest (summaries
are first-comment lines, never source).

``run_checks`` has two scopes. Part scope re-executes the part's own ``CHECKS``
through the worker and publishes the run as a *preview*, so evidence is durable
but nothing becomes current. Project scope freezes the authorized bundle, runs it
over one coherent project snapshot, and fails closed on an invalid generation;
its facade also carries the two ``KINEMATICS.md`` §4 motion read surfaces
(``m.at_pose`` / ``m.sweep``) through a :class:`SnapshotMotionContext` bound to
that same frozen snapshot, so a check never measures a different geometry or
motion state than the rest of its own run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.checks.engine import CheckSetState, load_check_module, run_bundle

# The safe cross-part check template (``create_project_check``) is shared with
# ``heph init`` and lives in core; re-exported here unchanged.
from hephaestus.core.checks.template import (
    CHECK_DESCRIPTION_SENTINEL,
    CHECK_TEMPLATE_HEADER,
    check_template,
)
from hephaestus.core.errors import AddressingError, InvalidCheckGenerationError, ValidationError
from hephaestus.core.motion import SnapshotMotionContext
from hephaestus.core.project_store.layout import CHECKS_DIRNAME
from hephaestus.core.project_store.projections import SnapshotRejectedError
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from hephaestus.core.project_store.store import (
    blob_hash_of_ref,
)
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from ._base import CHECK_SNAPSHOT_KIND, CadOpError, CadOpsState, attempted_snapshot

__all__ = [
    "CHECK_DESCRIPTION_SENTINEL",
    "CHECK_SNAPSHOT_KIND",
    "CHECK_TEMPLATE_HEADER",
    "CheckOps",
    "check_template",
]

#: ``summary`` cap for ``list_project_checks`` items (tool_schema: 512 UTF-8 bytes).
_SUMMARY_MAX_BYTES: Final[int] = 512


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
            # PROJECT-RELATIVE (audit-2026-09-04 J-agent-results-11): the
            # absolute directory named the operator's home in every refusal
            # that reached a model or an HTTP client, and the candidate list
            # below already carries everything a caller can act on. The
            # directory-name constant is interpolated rather than a resolved
            # path so a refactor cannot reintroduce an absolute one.
            raise AddressingError(
                f"project check {name!r} does not exist under {CHECKS_DIRNAME}/",
                selector=name,
                candidates=self.check_names(),
            )
        raw = path.read_bytes()
        blob = self._store.blobs.put(raw)
        return raw.decode("utf-8"), blob, make_artifact_ref(CHECK_SNAPSHOT_KIND, blob)

    def attempted_check_snapshot(self, base_hash: str, old_str: str, new_str: str) -> str | None:
        """The candidate an ``edit_project_check`` MEANT to write, or None.

        Delegates to the shared replay so a check conflict names the rejected
        contender rather than the live file (ledger J-agent-results-2), minting
        the check snapshot kind (J-agent-results-S5) rather than the part one.
        """
        return attempted_snapshot(
            self._store, base_hash, old_str, new_str, kind=CHECK_SNAPSHOT_KIND
        )

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

    def _import_target_shape(self, path: str) -> object:
        """Resolve an ``m.diff(..., "import:<path>")`` target (``COMPARE.md`` §2).

        Rides the Stage 8A machinery unchanged through
        :meth:`~hephaestus.core.project_compare.ProjectComparer.import_operand`:
        the same ``openat2``-class confinement walk and the same content hash,
        so a project-scoped acceptance check measures exactly the bytes the
        operator seeded. A missing file, a traversal or an unreadable STEP
        keeps its own named refusal, which the checks engine records as that
        predicate's failure — never a pass, never a crash of the run. Wired
        2026-08-25: project-scope ``run_checks`` (the bench grader's path)
        previously had no resolver, so the editing-task predicate
        ``COMPARE.md`` §2 promises failed as unresolvable at grade time.
        """
        from hephaestus.core.project_compare import ProjectComparer

        shape, _operand = ProjectComparer(self._layout, self._store).import_operand(path)
        return shape

    # -- run_checks --------------------------------------------------------

    def run_part_checks(self, name: str) -> dict[str, Any]:
        """Re-execute ``name``'s persistent ``CHECKS`` (published as a preview).

        One conservative precondition short-circuits the rebuild
        (audit-2026-09-04 J-cli-startup-9): a part whose current successful
        build still revalidates against the live script, parameters and
        dependencies **and** whose record says it declared no checks has
        nothing to re-run, and answering from the record costs a pointer read
        instead of 3.4 s of sandbox, worker interpreter, kernel import,
        script re-execution and a preview publication.

        The rebuild is intrinsic everywhere else and stays: ``CHECKS``
        predicates are script-local closures over a facade bound to the built
        geometry, so there is no way to re-run a real one without re-executing
        the script, and a check that passed on the recorded build may fail
        against an edited one. The fast path is therefore gated on *both* the
        freshness of the inputs and an explicitly recorded empty declaration —
        never on the results map alone, which is empty for a part whose checks
        failed to register (which is why the record now carries the names).
        """
        recorded = self._recorded_empty_check_run(name)
        if recorded is not None:
            return recorded
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
                imports=inputs.imports,
                import_errors=inputs.import_errors,
                baseline=publisher.baseline_for(name),
            )
            # preview=True: evidence is durable (refs resolve) but nothing becomes
            # current and no stale marker is cleared — run_checks is not a mutation.
            outcome = publisher.publish_build(
                build, op_id=f"heph-run-checks-{uuid.uuid4().hex}", preview=True
            )
        result: BuildResult = outcome.result
        payload = self._part_check_payload(result)
        if result.error is not None:
            payload["error"] = result.error.to_json()
        return payload

    def _part_check_payload(self, result: BuildResult) -> dict[str, Any]:
        """The part-scope ``run_checks`` document for one build record.

        ``project`` is stated in both scopes and ``part`` names a part in both
        (J-agent-results-9): a reader never has to know which scope it is in to
        know what the two fields mean.
        """
        payload: dict[str, Any] = {
            "status": "ok" if result.status == "ok" else "error",
            "scope": "part",
            "part": result.part,
            "project": self._layout.manifest.name,
            "checks": {check_name: check.to_json() for check_name, check in result.checks.items()},
        }
        if result.artifact_ref is not None:
            payload["artifact_ref"] = result.artifact_ref
        return payload

    def _recorded_empty_check_run(self, name: str) -> dict[str, Any] | None:
        """The recorded answer for a fresh build that declared no checks, else None.

        Three conditions, all required, none of them a heuristic: the part has
        a current **successful** build; that build's recorded inputs still
        revalidate against the live ones (the read-only predicate B-5 factored
        out of the publisher, so this and the params route share ONE answer to
        "is the current build still an answer for the live inputs"); and the
        record positively says the build registered no check names. A record
        written before ``check_names`` existed carries ``()``, which says
        nothing, so it takes the full path — silence must not read as a pass.
        """
        publisher = self._publisher()
        result = publisher.current_result(name)
        if result is None or result.status != "ok" or result.artifact_ref is None:
            return None
        if result.checks:
            return None
        # `None` is "the record does not say" — a build published before the
        # names were recorded — and takes the full path, because silence is not
        # a statement that the part declares nothing.
        declared = publisher.recorded_check_names(name)
        if declared is None or declared:
            return None
        freshness = publisher.freshness(name)
        if freshness is None or not freshness.fresh:
            return None
        return self._part_check_payload(result)

    def run_project_checks(
        self,
        project_snapshot_ref: str | None,
        *,
        parts: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Freeze the authorized cross-part bundle and run it (fails closed).

        ``parts`` scopes the assembled snapshot to those part names (the bench
        grader's declared-parts scope — an undeclared scratch part with no
        successful build must not veto the snapshot the acceptance checks run
        on). ``None`` keeps the whole-project snapshot, and it is ignored when
        an explicit ``project_snapshot_ref`` is supplied.
        """
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
                    names = list(parts) if parts is not None else self._layout.part_names()
                    snapshot = publisher.projections.assemble_snapshot(names)
                except SnapshotRejectedError as exc:
                    raise CadOpError(
                        "incoherent_project_snapshot",
                        exc.message,
                        data={"issues": [issue.to_json() for issue in exc.issues]},
                    ) from exc
                resolved_ref = snapshot.ref
            else:
                resolved_ref = project_snapshot_ref
            # Each source carries the FULL §7 namespace of the build the
            # manifest froze (audit-2026-09-04 B-1). Until then this reached an
            # empty index, so an acceptance check addressing "<part>/<label>"
            # or a tag came back ``pass: false`` with an AddressingError buried
            # in ``measured`` — a red verification signal for a correct design,
            # which is worse than a refusal because it looks like a verdict.
            sources, _refs = self._snapshot_sources(resolved_ref, Path(scratch))
            # KINEMATICS.md §2 (last bullet) / §4: the m.at_pose / m.sweep
            # read surfaces resolve against the SAME frozen snapshot the
            # run's sources came from — the context freezes the motion
            # generations and pins anchor resolution to the manifest's
            # artifact refs at construction, never CURRENT mid-run.
            motion = SnapshotMotionContext(
                self._layout, self._store, snapshot_ref=resolved_ref, scratch=Path(scratch)
            )
            try:
                report = run_bundle(
                    bundle,
                    sources,
                    part=None,
                    scope="project",
                    project=self._layout.manifest.name,
                    project_snapshot_ref=resolved_ref,
                    imports=self._import_target_shape,
                    at_pose=motion.at_pose,
                    sweep=motion.sweep,
                    motion_generations=motion.generations,
                )
            except InvalidCheckGenerationError as exc:  # pragma: no cover - captured above
                raise CadOpError("invalid_check_generation", exc.message) from exc
        # J-agent-results-9: the subject is now declared at the run
        # (``run_bundle(..., part=None, scope="project", project=…)``), so the
        # report arrives correct and there is nothing to correct afterwards. It
        # was briefly patched here with ``dataclasses.replace``; that fixed the
        # tool's copy while ``heph check --json`` and ``GET /checks`` — which
        # go through the same serializer from ``checks/report.py`` — kept
        # saying the project's name was a part.
        payload = dict(report.to_json())
        payload["status"] = "ok"
        payload["check_set_generation"] = str(state.generation)
        payload["check_set_ref"] = state.bundle_ref
        return payload
