"""Parameter declaration probes, ``set_params`` and ``edit_globals``.

The scope of this module is everything that decides what a parameter override
*may* be: the sandboxed probe that recovers a scope's ``PARAMS`` declaration,
the all-or-nothing bounds validation ``set_params`` applies before the CAS write
in :class:`~._base.ParamStore`, and the opkey-first ``globals.py`` edit whose
candidate must survive the same probe against the persisted project overrides.

Project-scope writes also advance the audit revision (``apply_hc_state``), which
is what makes the reported ``stale_parts`` real dependency tracking rather than a
guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from hephaestus.core.errors import AddressingError, HephaestusError, ValidationError
from hephaestus.core.executor.runner import UnpublishedBuild
from hephaestus.core.params import Param, merge_overrides
from hephaestus.core.project_store.store import (
    artifact_ref as make_artifact_ref,
)
from opstore.types import JSONValue

from opstore import (
    Fresh,
    PendingRecovery,
    Replay,
    canonical_json,
    sha256_bytes,
    sha256_canonical_json,
)

from ._base import CadOpError, CadOpsState, json_map, numeric_map, recorded_ref

#: Minimal probe part used to evaluate ``globals.py`` alone in the sandbox.
SYNC_PART: Final[str] = "__hc_sync__"
_SYNC_SCRIPT: Final[str] = "part.geometry = Box(1.0, 1.0, 1.0)\n"


def _diff_line(old_str: str, new_str: str) -> str:
    """A minimal one-hunk diff rendering of an exact-match replacement."""
    return f"-{old_str.rstrip(chr(10))}\n+{new_str.rstrip(chr(10))}"


def _globals_failure_kind(error_type: str | None, message: str) -> str:
    """Map a sandboxed ``globals.py`` failure onto the edit_globals ``kind`` set."""
    if error_type == "ParamOutOfBoundsError":
        return "invalid_overrides"
    if error_type == "SyntaxError":
        return "syntax"
    if error_type == "ValidationError":
        lowered = message.lower()
        if "unknown parameter" in lowered or "declares no params" in lowered:
            return "invalid_overrides"
        if "sandbox" in lowered:
            return "sandbox"
        return "contract"
    if error_type == "SandboxDeniedError":
        return "sandbox"
    return "evaluation"


@dataclass(frozen=True)
class ParamProbe:
    """A sandboxed probe of one scope: the declaration, plus any failure."""

    declaration: Mapping[str, Param]
    effective: Mapping[str, int | float]
    hc_state: Mapping[str, JSONValue]
    error_type: str | None = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None


def _params_from_declaration(raw: Mapping[str, JSONValue]) -> dict[str, Param]:
    """Rebuild ``{name: Param}`` from the worker's declaration JSON."""
    out: dict[str, Param] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        decl = cast("Mapping[str, JSONValue]", entry)
        default = decl.get("default")
        minimum = decl.get("min")
        maximum = decl.get("max")
        bounds = (default, minimum, maximum)
        if any(isinstance(v, bool) or not isinstance(v, int | float) for v in bounds):
            continue
        doc = decl.get("doc")
        raw_step = decl.get("step")
        numeric_step = isinstance(raw_step, int | float) and not isinstance(raw_step, bool)
        out[name] = Param(
            default=cast("int | float", default),
            min=cast("int | float", minimum),
            max=cast("int | float", maximum),
            doc=doc if isinstance(doc, str) else "",
            step=cast("int | float", raw_step) if numeric_step else None,
        )
    return out


class ParamOps(CadOpsState):
    """``set_params`` / ``edit_globals`` and the sandboxed probes they stand on."""

    # -- parameter probes --------------------------------------------------

    def probe_part_params(self, name: str) -> ParamProbe:
        """Sandbox-evaluate ``name`` to recover its ``PARAMS`` declaration."""
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
            )
            return self._probe_from(build, declaration_key="params_declaration")

    def probe_globals(
        self,
        *,
        source: str | None = None,
        overrides: Mapping[str, int | float | str] | None = None,
    ) -> ParamProbe:
        """Sandbox-evaluate ``globals.py`` alone (candidate source optional)."""
        publisher = self._publisher()
        if source is None:
            snapshot = publisher.parts.read_globals()
            source = None if snapshot is None else snapshot.content
        merged: dict[str, int | float | str] = dict(self._layout.manifest.params)
        merged.update(self.params.read("project", None).values if overrides is None else overrides)
        with self._build_dir(SYNC_PART) as out_dir:
            build = self._run(
                SYNC_PART,
                _SYNC_SCRIPT,
                source,
                out_dir=out_dir,
                part_overrides={},
                project_overrides=merged,
            )
            return self._probe_from(build, declaration_key="project_params_declaration")

    @staticmethod
    def _probe_from(build: UnpublishedBuild, *, declaration_key: str) -> ParamProbe:
        worker = build.worker_result
        declaration = _params_from_declaration(json_map(worker.get(declaration_key)))
        part_scope = declaration_key == "params_declaration"
        effective_key = "effective_params" if part_scope else "project_effective_params"

        error = build.result.error
        return ParamProbe(
            declaration=declaration,
            effective=numeric_map(worker.get(effective_key)),
            hc_state=json_map(worker.get("hc_state")),
            error_type=None if error is None else error.type,
            error_message="" if error is None else error.message,
        )

    # -- set_params --------------------------------------------------------

    def set_params(
        self,
        scope: str,
        name: str | None,
        values: Mapping[str, Any],
        *,
        expected_state_hash: str,
        op_id: str,
    ) -> dict[str, Any]:
        """Persist bounds-validated overrides for one scope, all-or-nothing."""
        probe = (
            self.probe_globals()
            if scope == "project"
            else self.probe_part_params(cast("str", name))
        )
        declaration = probe.declaration
        current = self.params.read(scope, name)
        rejected: list[dict[str, Any]] = []
        merged: dict[str, int | float] = dict(current.values)
        for key, raw in values.items():
            param = declaration.get(key)
            if param is None:
                rejected.append(
                    {
                        "name": key,
                        "reason": "unknown_parameter",
                        "declared": sorted(declaration),
                    }
                )
                continue
            if raw is None:
                merged.pop(key, None)
                continue
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                rejected.append({"name": key, "reason": "not_a_number", "value": repr(raw)})
                continue
            try:
                coerced = param.coerce(raw, name=key)
            except ValidationError as exc:
                rejected.append({"name": key, "reason": "wrong_type", "detail": exc.message})
                continue
            if not param.in_bounds(coerced):
                rejected.append(
                    {
                        "name": key,
                        "reason": "out_of_bounds",
                        "value": coerced,
                        "min": param.min,
                        "max": param.max,
                    }
                )
                continue
            merged[key] = coerced
        if rejected:
            # All-or-nothing: nothing is persisted and no state hash moves.
            return {
                "effective": self._effective(declaration, current.values),
                "rejected": rejected,
                "stale_parts": [],
                "state_hash": current.state_hash,
            }
        new_state, journal_ref = self.params.write(
            scope, name, merged, expected_state_hash=expected_state_hash, op_id=op_id
        )
        stale_parts: list[str] = []
        if scope == "project":
            after = self.probe_globals(overrides=merged)
            if after.ok:
                publisher = self._publisher()
                before = publisher.projections.state().hc_state
                if canonical_json(dict(before)) != canonical_json(dict(after.hc_state)):
                    report = publisher.projections.apply_hc_state(
                        after.hc_state, reason="project parameters changed"
                    )
                    stale_parts = list(report.stale)
                else:
                    stale_parts = sorted(publisher.projections.state().stale)
        return {
            "effective": self._effective(declaration, new_state.values),
            "rejected": [],
            "stale_parts": stale_parts,
            "state_hash": new_state.state_hash,
            "journal_ref": journal_ref,
        }

    @staticmethod
    def _effective(
        declaration: Mapping[str, Param], values: Mapping[str, int | float]
    ) -> dict[str, int | float]:
        try:
            return merge_overrides(declaration, values)
        except HephaestusError:  # pragma: no cover - validated above
            return dict(values)

    def param_state_hash(self, scope: str, name: str | None) -> str:
        """The optimistic ``expected_state_hash`` a client must present."""
        return self.params.read(scope, name).state_hash

    # -- globals -----------------------------------------------------------

    def edit_globals(
        self, *, expected_hash: str, old_str: str, new_str: str, op_id: str
    ) -> dict[str, Any]:
        """``edit_globals``: opkey-first CAS write of ``globals.py`` (tool_schema).

        The idempotency payload is the *request* (presented base hash + the exact
        old/new strings), and the opkey is claimed **before** the live hash is
        read: a lost-response retry therefore replays ``applied`` instead of
        reporting the conflict its own committed write created. The candidate must
        parse/evaluate in the **secure globals sandbox** against the persisted
        project overrides — a removed parameter or a bound tightened around a live
        override is the discriminated ``invalid_overrides`` failure and commits
        nothing (distinct from ``conflict(kind="stale_hash")``).
        """
        path = self._layout.globals_path
        payload: JSONValue = {
            "kind": "globals_edit",
            "base": expected_hash,
            "old": old_str,
            "new": new_str,
        }
        payload_hash = sha256_canonical_json(payload)
        outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, PendingRecovery):
            self._store.wal.recover(outcome.op_key)
            outcome = self._store.opkeys.begin(op_id, payload_hash)
        if isinstance(outcome, Replay):
            after = recorded_ref(outcome.response, "globals", "")
            return {
                "status": "applied",
                "diff": _diff_line(old_str, new_str),
                "content_hash": after,
                "snapshot_ref": make_artifact_ref("part-snapshot", after),
                "journal_ref": recorded_ref(outcome.response, "journal", after),
                "replayed": True,
            }
        if not isinstance(outcome, Fresh):
            raise CadOpError(
                "conflict", f"globals edit {op_id!r} cannot proceed: prior state {outcome!r}"
            )
        abort = outcome.op_key
        live = path.read_bytes() if path.is_file() else None
        if live is None:
            self._store.wal.recover(abort)
            raise AddressingError(
                "project has no globals.py to edit",
                selector="globals",
                candidates=self._layout.part_names(),
            )
        live_hash = sha256_bytes(live)
        script = live.decode("utf-8")
        if live_hash != expected_hash:
            self._store.wal.recover(abort)
            snapshot_ref = make_artifact_ref("part-snapshot", self._store.blobs.put(live))
            return {
                "status": "conflict",
                "kind": "stale_hash",
                "current_hash": live_hash,
                "current_script": script,
                "current_truncated": False,
                "current_oversized_line": False,
                "current_snapshot_ref": snapshot_ref,
                "base_snapshot_ref": make_artifact_ref("part-snapshot", expected_hash),
                "attempted_snapshot_ref": snapshot_ref,
            }
        occurrences = script.count(old_str)
        if occurrences != 1:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": "contract",
                "diagnostics": (
                    f"old_str occurs {occurrences} times in globals.py; it must be unique"
                ),
            }
        candidate = script.replace(old_str, new_str, 1)
        probe = self.probe_globals(source=candidate)
        if not probe.ok:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": _globals_failure_kind(probe.error_type, probe.error_message),
                "diagnostics": f"{probe.error_type}: {probe.error_message}",
            }
        overrides = self.params.read("project", None).values
        missing = sorted(key for key in overrides if key not in probe.declaration)
        if missing:
            self._store.wal.recover(abort)
            return {
                "status": "validation_error",
                "kind": "invalid_overrides",
                "diagnostics": (
                    "persisted project overrides are no longer declared: " + ", ".join(missing)
                ),
                "invalid_overrides": missing,
            }
        raw = candidate.encode("utf-8")
        after_hash = sha256_bytes(raw)
        journal_ref = self._journal_globals(op_id, path, live_hash, live, after_hash)
        self._store.wal.execute(
            outcome,
            path,
            raw,
            intended_outcome=canonical_json({"globals": after_hash, "journal": journal_ref}),
        )
        self._store.blobs.put(raw)
        # The audit revision advances to the projection the candidate evaluates to,
        # so exactly the consumers of changed hc names go stale.
        self.sync_globals_projection(probe.hc_state)
        return {
            "status": "applied",
            "diff": _diff_line(old_str, new_str),
            "content_hash": after_hash,
            "snapshot_ref": make_artifact_ref("part-snapshot", after_hash),
            "journal_ref": journal_ref,
        }

    def _journal_globals(
        self, op_id: str, path: Path, before_hash: str, preimage: bytes, after_hash: str
    ) -> str:
        """Durable preimage journal entry for a ``globals.py`` overwrite."""
        entry: JSONValue = {
            "kind": "globals_write",
            "op_id": op_id,
            "target": str(path),
            "before_hash": before_hash,
            "preimage_blob": self._store.blobs.put(preimage),
            "after_hash": after_hash,
        }
        payload = canonical_json(entry).encode("utf-8")
        blob = self._store.blobs.put(payload)
        self._layout.journal_dir.mkdir(parents=True, exist_ok=True)
        (
            self._layout.journal_dir / f"globals-{blob.removeprefix('sha256:')[:32]}.json"
        ).write_bytes(payload)
        return make_artifact_ref("globals-journal", blob)

    def sync_globals_projection(self, hc_state: Mapping[str, JSONValue]) -> list[str]:
        """Advance the audit revision after a globals edit; return newly stale parts."""
        publisher = self._publisher()
        before = publisher.projections.state().hc_state
        if canonical_json(dict(before)) == canonical_json(dict(hc_state)):
            return sorted(publisher.projections.state().stale)
        report = publisher.projections.apply_hc_state(hc_state, reason="globals.py changed")
        return list(report.stale)
