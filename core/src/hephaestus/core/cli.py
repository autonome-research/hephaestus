"""``heph`` — engine-first CLI: build, check, lint (no server, no Node).

- ``heph build <part-or-path> [--param k=v]... [--global-param k=v]...
  [--stale] [--json] [--unsafe-local-executor]`` runs the full pipeline:
  freeze inputs under locks -> sandboxed worker build -> §6 checks (evaluated
  in-worker) -> publication (current-pointer flip on success, checkpoint
  evidence on failure). ``--json`` emits the exact §8 BuildResult JSON, one
  object per line per built part. Any ``--param``/``--global-param`` override
  makes the build a transient preview (never current, never clearing stale).
  ``--stale`` rebuilds every part marked stale by project-param/globals.py
  changes (after syncing the live ``hc`` projection).
- ``heph check [--project] [--json]`` runs the ``checks/*.py`` cross-part
  check set against each part's current published artifact; ``--project``
  additionally assembles (and requires) a coherent project snapshot.
- ``heph lint <path> [--json] [--requirements <ledger.json>]
  [--request <request.txt>]`` runs the §9 lints (plus the §4 shadowing
  error) against a part script, resolving the project's globals.py when the
  script lives inside a project. With ``--requirements`` the ledger's entry
  ids become the accepted ``CHECKS`` citations (``VALIDATION.md`` §2
  ``unsourced_constant``); adding ``--request`` also checks every
  ``source: "specified"`` entry's quote against the request text
  (``unsourced_requirement``). An entry carrying an ``INGEST.md`` §2 ``cite``
  is verified against the *project's registered references* instead — their
  extracted text is resolved automatically, so no extra flag is needed — and a
  citation of an image reference is reported ``unverifiable_citation``, which
  is the ``VALIDATION.md`` §5 reviewer's job, not lint's.
- ``heph reference add|list|remove`` registers operator-supplied reference
  documents and images (``INGEST.md`` §2); see ``hephaestus.core.cli_references``.
- ``heph import add|list`` admits a vendor STEP or scan into ``imports/``
  (path-confined copy, optional ``create_part`` seed). The kernel already
  imports; this is project ingress. A mesh ``--part`` seed is the Stage 12
  scan-to-part path (``import_mesh`` + ``mesh_to_solid``); then ``heph build``
  and ``heph scan check``. Reconstruction is deferred. Browser import stays
  deferred (``INTERFACE.md`` §15.37); see ``hephaestus.core.cli_import``.
- ``heph assembly [--json]`` / ``heph assembly check`` show and re-evaluate the
  project's declared cross-part constraints (``ASSEMBLY.md`` §3); see
  ``hephaestus.core.cli_assembly``.
- ``heph joints [--json]`` shows the declared joint and pose sets with their
  latest projected motion outcomes (``KINEMATICS.md`` §6, the Stage 9A
  subset); see ``hephaestus.core.cli_joints``.
- ``heph motion [--json]`` / ``heph motion check [IDS]`` show and re-evaluate
  the declared motion checks with their §4 sweep results (``KINEMATICS.md``
  §6, Stage 9B); see ``hephaestus.core.cli_motion``.
- ``heph cam emit <part> [--out FILE] [--kerf-mm N] [--json]`` emits a
  laser/waterjet cut-file (ordered toolpath + DXF) from the part's current
  build, using the in-tree flat-pattern and kerf path. Not an export and not
  Stage 14 milling CAM; see ``hephaestus.core.cli_cam``.
- ``heph export list [PART]`` / ``heph export unpin BLOB`` show the committed
  exports with their GC-root pins and drop one of those pins (``INTERFACE.md``
  §19.40, §22.6 — the verbs the workspace's "unpin it from the command line"
  sentence names). They ship with the server package, which owns the export
  write-ahead table, but need no Node; see ``hephaestus.agent_bridge.cli_export``.
- ``heph part list|create|show``, ``heph script show|write``, ``heph params``,
  and ``heph prompt`` are the agent-shaped authoring verbs: list parts, create
  or write a script through the same ``create_part`` / ``write_part`` store
  contract, show the last published build and ``PARAMS``, and store request
  text. They need no Node; see ``hephaestus.core.cli_authoring``.

Exit codes: 0 success, 1 failure (build failed / raced, failing checks,
sandbox unavailable), 2 usage (bad arguments, no project, unknown part).

Secure-by-default: builds run under the probed bwrap sandbox and fail closed
with ``sandbox_unavailable`` when it cannot be proven; the unsafe plain-
subprocess backend runs only behind its explicit flag and warns loudly.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from hephaestus.core.checks.report import badge, project_check_report, report_json
from hephaestus.core.cli_errors import (
    CliUsageError,
    dispatch,
    json_listing,
    project_root_or_refuse,
    require_input_file,
)
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecBackend,
    ExecOutcome,
    SandboxSpec,
)
from hephaestus.core.executor.sandbox.probe import cached_probe, secure_backend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.lint import (
    ComponentClaimFacts,
    ComponentDatum,
    lint_component_citations,
    lint_part_script,
    lint_requirements,
    requirement_entries,
)
from hephaestus.core.project_store.layout import (
    GLOBALS_FILENAME,
    PARTS_DIRNAME,
    ProjectLayout,
    find_project_root,
    load_project,
    open_store,
)
from hephaestus.core.project_store.projections import SnapshotRejectedError
from hephaestus.core.project_store.publication import PublicationKind, Publisher
from hephaestus.core.types import BuildResult, CheckResult
from hephaestus.core.version import version as _version
from opstore.types import JSONValue

from opstore import canonical_json

__all__ = ["broken_import_message", "build_parser", "main", "make_backend"]

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Minimal probe part used by ``heph build --stale`` (no named part) to
#: evaluate globals.py in the sandbox and refresh the live hc projection.
_SYNC_PART = "__hc_sync__"
_SYNC_SCRIPT = "part.geometry = Box(1.0, 1.0, 1.0)\n"


# --------------------------------------------------------------------------
# shared plumbing


class _ProbedBackend:
    """ExecBackend adapter returning an already-verified capability report.

    ``run_build`` re-probes its backend fail-closed on every call;
    ``BwrapBackend.probe`` is a full live sandbox probe. The CLI probes once
    (per-store cached) and reuses that passing report for every build of the
    invocation.
    """

    def __init__(self, inner: ExecBackend, report: CapabilityReport) -> None:
        self._inner = inner
        self._report = report

    @property
    def name(self) -> str:
        return self._inner.name

    def probe(self) -> CapabilityReport:
        return self._report

    def execute(self, spec: SandboxSpec, stdin_payload: bytes) -> ExecOutcome:
        return self._inner.execute(spec, stdin_payload)


def make_backend(layout: ProjectLayout, *, unsafe: bool) -> ExecBackend:
    """The one backend-selection helper every model-facing runtime shares.

    Public (ledger J-agent-wiring-4): ``heph build`` had this probe-and-warn
    logic and ``heph agent`` had none — it took the CAD ops' "for fast tests"
    unsafe default instead — so the engine and the agent disagreed about the
    shipped sandbox posture while both ran part scripts. Rather than copy the
    probe into a second verb, ``heph agent`` calls this: one place decides what
    ``--unsafe-local-executor`` means, one place prints the selection line, and
    one place raises ``sandbox_denied`` when the secure probe cannot be proven.
    (``heph serve --mcp`` and ``--web`` reach the same posture through
    ``serve_mode``, which has no unsafe opt-in at all and never should.)

    Raises :class:`~hephaestus.core.errors.SandboxDeniedError` when ``unsafe``
    is false and bwrap cannot be probed; the callers map that to their own
    named exit-2 refusal rather than a traceback.
    """
    if unsafe:
        # One line at SELECTION, naming the flag that was actually passed; the
        # backend itself warns again per execution and no longer names any one
        # verb's flag, because it is reached from more than one (and from tests
        # and library callers with no CLI at all).
        print(
            "heph: --unsafe-local-executor: builds run WITHOUT OS sandboxing",
            file=sys.stderr,
        )
        return UnsafeLocalBackend()
    backend = secure_backend(layout.store_root)  # sandbox_denied when unproven
    report = cached_probe(layout.store_root, backend)  # cache hit: just written
    return _ProbedBackend(backend, report)


def _parse_kv(pairs: Sequence[str], flag: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key or not value:
            raise CliUsageError(f"{flag} expects name=value, got {pair!r}")
        overrides[key] = value
    return overrides


def _resolve_build_target(target: str) -> tuple[Path, str]:
    """(project root, part name) for a part name or a parts/<name>.py path."""
    path = Path(target)
    if path.suffix == ".py" or path.is_file():
        script = path.resolve()
        if not script.is_file():
            raise CliUsageError(f"no such part script: {target}")
        root = project_root_or_refuse(script.parent)
        if script != (root / PARTS_DIRNAME / script.name).resolve():
            raise CliUsageError(f"{target} is not a part script under {root / PARTS_DIRNAME}/")
        return root, script.stem
    if not _PART_NAME_RE.match(target):
        raise CliUsageError(f"invalid part name {target!r}")
    return project_root_or_refuse(), target


def _sync_projections(publisher: Publisher, hc_state_raw: JSONValue | None) -> None:
    """Advance the audit revision to the worker-computed live hc projection.

    Marks stale exactly the consumers whose consumed names/values changed;
    a no-op when the recorded projection already matches (no revision bump).
    """
    if not isinstance(hc_state_raw, dict):
        return
    hc_state = cast("Mapping[str, JSONValue]", hc_state_raw)
    live = publisher.projections.state().hc_state
    if canonical_json(dict(live)) != canonical_json(dict(hc_state)):
        publisher.projections.apply_hc_state(
            hc_state, reason="globals.py or project parameters changed"
        )


def _sync_via_probe(publisher: Publisher, layout: ProjectLayout, backend: ExecBackend) -> None:
    """Sandbox-evaluate globals.py alone to refresh the hc projection (--stale)."""
    globals_snapshot = publisher.parts.read_globals()
    request = BuildRequest(
        part=_SYNC_PART,
        script=_SYNC_SCRIPT,
        globals_source=None if globals_snapshot is None else globals_snapshot.content,
        project_overrides=dict(layout.manifest.params),
        origin="local",
    )
    out_dir = layout.store_root / "builds" / f"hc-sync-{uuid.uuid4().hex[:12]}"
    try:
        build = run_build(request, backend=backend, out_dir=out_dir)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    if build.result.status != "ok":
        error = build.result.error
        detail = "unknown failure" if error is None else error.message
        raise ValidationError(f"--stale: globals.py evaluation failed: {detail}", kind="evaluation")
    _sync_projections(publisher, build.worker_result.get("hc_state"))


def _build_and_publish(
    publisher: Publisher,
    layout: ProjectLayout,
    backend: ExecBackend,
    part: str,
    *,
    part_overrides: Mapping[str, str],
    project_overrides: Mapping[str, str],
    preview: bool,
) -> tuple[BuildResult, PublicationKind]:
    """One part through the full pipeline: freeze -> build -> sync -> publish."""
    # INGEST.md §1: an imports/ file replaced since the last build is a changed
    # input — refresh the live import state first so its consumers are stale
    # before this build (and so an unchanged tree stays a no-op).
    publisher.sync_import_state()
    inputs = publisher.freeze_inputs(part)
    baseline = publisher.baseline_for(part)
    merged_project: dict[str, int | float | str] = dict(inputs.manifest_params)
    merged_project.update(project_overrides)
    request = BuildRequest(
        part=part,
        script=inputs.script,
        globals_source=inputs.globals_source,
        part_overrides=dict(part_overrides),
        project_overrides=merged_project,
        origin="local",
        # INGEST.md §1: the frozen bytes of every declared imports/ file travel
        # with the request; a refused import is reported at its statement.
        imports=dict(inputs.imports),
        import_errors=dict(inputs.import_errors),
    )
    out_dir = layout.store_root / "builds" / f"{part}-{uuid.uuid4().hex[:12]}"
    try:
        build = run_build(request, backend=backend, out_dir=out_dir, baseline=baseline)
        if build.result.status == "ok" and not project_overrides:
            # Persist the live hc projection this build observed (manifest
            # params + globals, no transient overrides) so consumers of
            # changed names go stale and publication revalidation sees the
            # current state. Transient --global-param builds must not touch it.
            _sync_projections(publisher, build.worker_result.get("hc_state"))
        outcome = publisher.publish_build(
            build, op_id=f"heph-build-{uuid.uuid4().hex}", preview=preview
        )
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    return outcome.result, outcome.kind


def _emit_build(result: BuildResult, kind: PublicationKind, *, json_out: bool) -> None:
    if json_out:
        print(json.dumps(result.to_json()))
        return
    if result.status == "ok":
        print(f"{result.part}: ok ({kind}) artifact={result.artifact_ref}")
        if result.checks:
            failing = sorted(n for n, c in result.checks.items() if not c.passed)
            passed = len(result.checks) - len(failing)
            line = f"  checks: {passed}/{len(result.checks)} passed"
            if failing:
                line += f"; failing: {', '.join(failing)}"
            print(line)
        for warning in result.warnings:
            print(f"  warning [{warning.kind}] {warning.detail}")
        return
    error = result.error
    if error is None:  # pragma: no cover - failed <=> error, enforced by types
        print(f"{result.part}: FAILED")
        return
    print(f"{result.part}: FAILED — {error.type} at line {error.line}, col {error.col}")
    print(f"  {error.message}")
    for frame_line in error.frame:
        print(f"  {frame_line}")
    if error.built_through is not None:
        print(f"  built through line {error.built_through.line}: {error.built_through.statement}")
    if error.last_good is not None:
        print(
            f"  last good: {error.last_good.solids} solid(s), "
            f"volume {error.last_good.volume_mm3} mm^3, sealed={error.last_good.sealed}"
        )
    if error.last_good_artifact_ref is not None:
        print(f"  last_good_artifact_ref: {error.last_good_artifact_ref}")
    print(f"  hint: {error.hint}")


# --------------------------------------------------------------------------
# commands


def _cmd_build(args: argparse.Namespace) -> int:
    part_overrides = _parse_kv(cast("Sequence[str]", args.param), "--param")
    project_overrides = _parse_kv(cast("Sequence[str]", args.global_param), "--global-param")
    # Request-local overrides are transient: the build is a preview (§8 —
    # never current, never clearing stale). Persistent overrides belong in
    # hephaestus.toml [params].
    preview = bool(part_overrides or project_overrides)
    target = cast("str | None", args.part)
    stale = bool(args.stale)
    json_out = bool(args.json)
    if target is None and not stale:
        raise CliUsageError("build: a part name or script path is required (or --stale)")
    if target is not None:
        root, part = _resolve_build_target(target)
    else:
        root, part = project_root_or_refuse(), None
    layout = load_project(root)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    backend = make_backend(layout, unsafe=bool(args.unsafe_local_executor))

    exit_code = 0
    built: set[str] = set()
    if part is not None:
        result, kind = _build_and_publish(
            publisher,
            layout,
            backend,
            part,
            part_overrides=part_overrides,
            project_overrides=project_overrides,
            preview=preview,
        )
        _emit_build(result, kind, json_out=json_out)
        built.add(part)
        if result.status != "ok" or kind == "raced":
            exit_code = 1
    if stale:
        if part is None:
            _sync_via_probe(publisher, layout, backend)
        # INGEST.md §1: a replaced imports/ file makes its importers stale, and
        # --stale must see that before it picks the rebuild set.
        publisher.sync_import_state()
        stale_parts = [
            name for name in sorted(publisher.projections.state().stale) if name not in built
        ]
        for name in stale_parts:
            result, kind = _build_and_publish(
                publisher,
                layout,
                backend,
                name,
                part_overrides=part_overrides,
                project_overrides=project_overrides,
                preview=preview,
            )
            _emit_build(result, kind, json_out=json_out)
            if result.status != "ok" or kind == "raced":
                exit_code = 1
        if not stale_parts and not json_out:
            print("no stale parts")
    return exit_code


def _check_line(outcome: CheckResult) -> str:
    """One human check row, in ``checks/report.py``'s four-value vocabulary.

    ``heph check`` rendered a two-valued verdict and dumped ``measured``
    verbatim, so a check that could not be *evaluated* was badged ``FAIL`` with
    its error object printed as prose — asserting a measurement the engine
    explicitly declined to take, and leaving ``not_run`` unrepresentable
    (ledger J-cli-robustness-15). :func:`hephaestus.core.checks.report.badge` is
    the classifier the HTTP route and the web badges already share; the CLI
    prints its state, and for ``error`` prints the reason the envelope carries
    instead of the envelope.
    """
    state = badge(outcome)
    if state != "error":
        return f"{state} (measured: {json.dumps(outcome.measured)})"
    measured = outcome.measured
    envelope = (
        measured.get("error") or measured.get("unverifiable")
        if isinstance(measured, dict)
        else None
    )
    if not isinstance(envelope, dict):  # pragma: no cover - badge() implies one of the two
        return state
    # `error` carries the engine `code` (or the exception `type` for a
    # non-Hephaestus raise); `unverifiable` carries the timeout's `reason`.
    reason = envelope.get("code") or envelope.get("reason") or envelope.get("type")
    message = envelope.get("message")
    detail = ": ".join(str(part) for part in (reason, message) if isinstance(part, str))
    return f"{state} — {detail}" if detail else state


def _cmd_check(args: argparse.Namespace) -> int:
    json_out = bool(args.json)
    root = project_root_or_refuse()
    layout = load_project(root)
    store = open_store(layout)

    # INTERFACE.md §6.3 / §19 item 5: the run and the serialization live in
    # `hephaestus.core.checks.report`, which `server/http`'s GET /checks calls
    # under its own principal check. One serializer, two callers.
    try:
        report = project_check_report(layout, store, project=bool(args.project))
    except SnapshotRejectedError as exc:
        print(f"heph: error ({exc.code}): project snapshot is incoherent", file=sys.stderr)
        for issue in exc.issues:
            names = f" ({', '.join(issue.names)})" if issue.names else ""
            print(f"  {issue.part}: {issue.kind}: {issue.detail}{names}", file=sys.stderr)
        return 1

    if json_out:
        # Byte-bound to the web client (§6.3 parity gate) — never reshaped here.
        print(json.dumps(report_json(report)))
    else:
        if not report.checks:
            print("no cross-part checks")
        for name in sorted(report.checks):
            print(f"{name}: {_check_line(report.checks[name])}")
    return 0 if all(outcome.passed for outcome in report.checks.values()) else 1


def _reference_text(root: Path | None) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """``({document: pages}, image_names)`` from the project's reference registry.

    Extraction happened at registration (``INGEST.md`` §2), so this reads stored
    text and needs no parser. A project with no store yet simply has no
    references, which is not an error.
    """
    if root is None:
        return ({}, ())
    from hephaestus.core.project_store.references import ReferenceRegistry

    layout = load_project(root)
    store = open_store(layout)
    try:
        registry = ReferenceRegistry(layout, store)
        entries = registry.list_references()
        documents = {
            entry.name: registry.pages(entry) for entry in entries if entry.kind == "document"
        }
        images = tuple(entry.name for entry in entries if entry.kind == "image")
    finally:
        store.close()
    return (documents, images)


def _reference_digests(root: Path | None) -> dict[str, str]:
    """``{reference name: sha256:…}`` — the left-hand side of §7.4's join."""
    if root is None:
        return {}
    from hephaestus.core.project_store.references import ReferenceRegistry

    layout = load_project(root)
    store = open_store(layout)
    try:
        registry = ReferenceRegistry(layout, store)
        return {entry.name: entry.sha256 for entry in registry.list_references()}
    finally:
        store.close()


def _component_facts(
    root: Path | None,
) -> tuple[tuple[ComponentDatum, ...], dict[str, ComponentClaimFacts]]:
    """The §6.3 / §7.4 join's right-hand side, read once from the pinned registries.

    ``lint.py`` imports no registry — it is AST and JSON analysis — so the
    resolution happens here and the facts are injected. A project with no
    registries, or one whose trees carry no component records, yields empty maps
    and both rules stay silent, which is the same "no data, no finding" posture
    the reference-text resolution above takes.
    """
    if root is None:
        return ((), {})
    from hephaestus.core.registry import RegistrySet

    registries = RegistrySet.open(root)
    data: list[ComponentDatum] = []
    facts: dict[str, ComponentClaimFacts] = {}
    for part_id in registries.parts.component_ids():
        component = registries.parts.get(part_id).component
        if component is None:  # pragma: no cover - component_ids filters these out
            continue
        datasheet = component.datasheet
        facts[part_id] = ComponentClaimFacts(
            claim_ids=frozenset(claim.id for claim in component.claims),
            datasheet_sha256=None if datasheet is None else datasheet.sha256,
        )
        for claim in component.claims:
            for sample in claim.samples:
                data.extend(
                    ComponentDatum(value=float(axis), component=part_id, claim=claim.id)
                    for axis in sample
                )
    return (tuple(data), facts)


def _cmd_lint(args: argparse.Namespace) -> int:
    json_out = bool(args.json)
    path = Path(cast("str", args.path))
    raw_requirements = cast("str | None", args.requirements)
    raw_request = cast("str | None", args.request)
    if raw_request is not None and raw_requirements is None:
        # VALIDATION.md §2 / INGEST.md §2: `unsourced_requirement` is a JOIN
        # between the ledger's entries and the request text. With no ledger the
        # rule has one operand and yields nothing by construction, so the flag
        # read as live and reported "clean" (ledger J-cli-robustness-2).
        raise CliUsageError(
            "--request needs --requirements: unsourced_requirement joins the "
            "requirement ledger against the request text (VALIDATION.md §2)"
        )
    require_input_file(path, what="part script")
    source = path.read_text(encoding="utf-8")
    resolved = path.resolve()
    globals_source: str | None = None
    try:
        root = find_project_root(resolved.parent)
    except ValidationError:
        root = None  # standalone script: lint without hc-shadowing context
    if root is not None:
        globals_path = root / GLOBALS_FILENAME
        if globals_path.is_file() and globals_path.resolve() != resolved:
            globals_source = globals_path.read_text(encoding="utf-8")
    entries: list[Mapping[str, Any]] = []
    # No --requirements: the ledger rules stay off entirely (None), rather than
    # reporting every threshold against a ledger the caller never showed us.
    ledger_ids: list[str] | None = None
    if raw_requirements is not None:
        ledger_path = require_input_file(Path(raw_requirements), what="requirements file")
        entries = requirement_entries(json.loads(ledger_path.read_text(encoding="utf-8")))
        ledger_ids = [str(entry.get("id", "")) for entry in entries]
    component_data, component_facts = _component_facts(root)
    findings = lint_part_script(
        source,
        globals_source=globals_source,
        filename=str(path),
        ledger_ids=ledger_ids,
        component_data=component_data,
    )
    if raw_requirements is not None:
        # PARTS_STORE.md §7.4. Unlike `lint_requirements`, this needs no request
        # text: the join is between the ledger, the reference registry and the
        # component record, and none of those is the prompt.
        findings = findings + lint_component_citations(
            entries,
            reference_digests=_reference_digests(root),
            components=component_facts,
        )
    if raw_request is not None:
        request_path = require_input_file(Path(raw_request), what="request file")
        # INGEST.md §2: a citation is checked against the project's own
        # registered references, so the text a lint verifies is exactly the text
        # `read_reference` showed the model. Resolved only when the script lives
        # in a project; a standalone lint has no registry to consult.
        documents, images = _reference_text(root)
        findings = findings + lint_requirements(
            entries,
            request_path.read_text(encoding="utf-8"),
            references=documents,
            image_references=images,
        )
    failed = any(finding.severity == "error" for finding in findings)
    if json_out:
        # One listing envelope, not a bare array (ledger J-cli-robustness-7):
        # `status` mirrors the exit code, so a wrapper reads one shape.
        print(
            json_listing(
                "findings",
                [finding.to_json() for finding in findings],
                status="error" if failed else "ok",
            )
        )
    else:
        for finding in findings:
            suffix = f" [{finding.name}]" if finding.name else ""
            print(
                f"{path}:{finding.line}:{finding.col}: {finding.severity} "
                f"{finding.code}: {finding.message}{suffix}"
            )
        if not findings:
            print(f"{path}: clean")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# entrypoint


#: The one option string allowed to be zero-arity on one verb and value-taking
#: on another: ``heph check --project``, kept only as the retiring alias of
#: ``--snapshot`` (ledger J-cli-robustness-4). This set must shrink, never grow
#: — a second entry means the collision it exists to catch was waved through.
_ARITY_COLLISION_ALLOWED = frozenset({"--project"})


def _walk_parsers(parser: argparse.ArgumentParser) -> Iterator[argparse.ArgumentParser]:
    """``parser`` and every subparser reachable from it, depth-first."""
    yield parser
    # argparse exposes no public walk over a built parser tree.
    for action in parser._actions:  # pyright: ignore[reportPrivateUsage]
        if isinstance(action, argparse._SubParsersAction):  # pyright: ignore[reportPrivateUsage]
            children = cast(
                "Mapping[str, argparse.ArgumentParser]",
                action.choices,  # pyright: ignore[reportUnknownMemberType]
            )
            for child in children.values():
                yield from _walk_parsers(child)


def _assert_no_arity_collisions(parser: argparse.ArgumentParser) -> None:
    """One option string may not be a flag on one verb and take a value on another.

    ``--project`` was a ``store_true`` on ``heph check`` and a ``DIR`` on
    ``heph agent`` / ``heph serve --web``, so the directory became an unmatched
    positional and argparse reported "unrecognized arguments" with no hint that
    this verb's ``--project`` takes nothing (ledger J-cli-robustness-4). This is
    the parser-construction counterpart of the HTTP layer's route-table drift
    check: a build-time assertion, so the next engine verb that wants a
    directory named by an existing flag fails here rather than at a user.
    """
    zero_arity: dict[str, str] = {}
    valued: dict[str, str] = {}
    for sub_parser in _walk_parsers(parser):
        for action in sub_parser._actions:  # pyright: ignore[reportPrivateUsage]
            if not action.option_strings:
                continue
            seen = zero_arity if action.nargs == 0 else valued
            for option in action.option_strings:
                seen.setdefault(option, sub_parser.prog)
    collisions = sorted(
        (zero_arity.keys() & valued.keys()) - _ARITY_COLLISION_ALLOWED,
    )
    if collisions:  # pragma: no cover - a construction bug, asserted by test
        detail = ", ".join(
            f"{option} (flag on {zero_arity[option]!r}, takes a value on {valued[option]!r})"
            for option in collisions
        )
        raise AssertionError(f"option arity collision across heph verbs: {detail}")


def _import_is_of(module_path: str, exc: ImportError) -> bool:
    """Is *exc* the report that ``module_path`` itself is not installed?

    ``ImportError`` carries the module that could not be found in ``exc.name``,
    and that one field is the whole difference between the two conditions an
    optional verb has to tell apart (ledger J-cli-robustness-21):

    * ``exc.name`` **is** ``module_path`` or a package above it — the optional
      package is genuinely absent, which is the supported core-only install
      ``PACKAGING.md`` governs: the engine CLI is Node-free and fully
      functional without the server package, and the verb is simply not there.
    * anything else, ``None`` included — the package the user asked for exists
      and something *it* imports does not. That is broken, not absent, and
      swallowing it shows the operator ``invalid choice: 'serve'``, which reads
      exactly like an uninstalled package and names nothing.

    ``None`` counts as broken deliberately: an ``ImportError`` that declines to
    say what was missing is not evidence that this module is the missing one.
    """
    name = exc.name
    if name is None:
        return False
    return module_path == name or module_path.startswith(f"{name}.")


def broken_import_message(what: str, module_path: str, exc: ImportError) -> str:
    """The refusal an optional verb prints when its package is installed but broken.

    Two facts, because two different things are wrong-able: the exception the
    import actually raised, and the fact that this is *not* the "package not
    installed" condition it would otherwise be mistaken for. ``docs/install.md``
    carries the same pair so the two shapes can be told apart from the docs.

    Public, and deliberately the ONLY definition of this sentence: the same
    condition can now surface at two different times. Registration meets it
    here; the ``serve`` handlers meet it when their lazily imported halves
    (``hephaestus.mcp.app``, ``hephaestus.http.serve``) fail, because
    J-cli-startup-3 and -4 moved those imports off the registration path. Both
    import this rather than writing the sentence twice.
    """
    missing = f" (missing module: {exc.name})" if exc.name is not None else ""
    return (
        f"heph: the {what!r} verb is installed but could not load: {exc}{missing}\n"
        f"heph: {module_path} is present and one of its imports is not; this is a "
        f"broken installation, not an absent one (a package that is simply not "
        f"installed leaves the verb off 'heph --help' entirely)"
    )


def _register_broken_verb(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    verb: str,
    module_path: str,
    exc: ImportError,
) -> None:
    """Register *verb* as a stub whose handler names the import that failed."""
    if verb in cast("Mapping[str, argparse.ArgumentParser]", sub.choices):
        # `register` added the parser and then failed; the half-built verb is
        # more informative than a stub we cannot put in its place, and argparse
        # refuses a second parser under the same name.
        return  # pragma: no cover - registration imports before it adds a parser
    parser = sub.add_parser(
        verb,
        help=f"unavailable: {module_path} is installed but could not be imported",
        # Accept whatever the operator typed, flags included. They are
        # reproducing the invocation that used to work, and answering a broken
        # install with "unrecognized arguments" would hide the one message that
        # explains it. `prefix_chars` is what buys that: with no prefix
        # character in play argparse reads `--resume` as a positional rather
        # than an unknown option, which `nargs=REMAINDER` does NOT do for a
        # leading flag. `add_help=False` for the same reason — `heph agent
        # --help` on a broken install should say why the verb is broken.
        add_help=False,
        prefix_chars="\0",
    )
    parser.add_argument("args", nargs="*", help=argparse.SUPPRESS)

    def command(_args: argparse.Namespace) -> int:
        print(broken_import_message(verb, module_path, exc), file=sys.stderr)
        return 2

    parser.set_defaults(func=command)


def _register_broken_serve_web(serve_parser: argparse.ArgumentParser, exc: ImportError) -> None:
    """Keep ``serve --web`` on the help output when its half could not import.

    The web half of ``serve`` is an *extension* of a parser the MCP half
    created, so a stub verb is not available to it the way it is to the other
    four: the verb exists and works. What must not happen is the pre-fix
    behaviour, where a broken ``hephaestus.http.cli_web`` silently removed
    ``--web`` from a verb that still advertised ``serve`` — and, before that,
    took ``--mcp`` down with it. So ``--web`` is registered here as a flag that
    refuses by name, and every other invocation of ``serve`` is untouched.

    Only ``--web`` itself: ``--web-address`` and ``--project`` are declared by
    the half that failed to import (``cli_web.extend_serve``), and restating
    them here would fork their declarations to describe a surface that cannot
    run; with them absent, argparse rejects them as unrecognised, which is the
    honest answer for a flag whose implementation is not loadable.
    """
    inner = cast("Callable[[argparse.Namespace], int]", serve_parser.get_default("func"))
    serve_parser.add_argument(
        "--web",
        action="store_true",
        help="unavailable: hephaestus.http.cli_web is installed but could not be imported",
    )

    def command(args: argparse.Namespace) -> int:
        if not bool(getattr(args, "web", False)):
            return inner(args)
        print(
            broken_import_message("serve --web", "hephaestus.http.cli_web", exc),
            file=sys.stderr,
        )
        return 2

    serve_parser.set_defaults(func=command)


def _optional_verb(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],  # pyright: ignore[reportPrivateUsage]
    verb: str,
    module_path: str,
    register: Callable[[], None],
) -> None:
    """Run *register* (which imports *module_path* and adds *verb*), tolerating absence.

    The four optional verbs — and the web half of ``serve``, one level in —
    ship with packages the engine CLI does not require, and each used to be
    registered inside a bare ``try: ... except ImportError: pass``. That net
    swallows a broken dependency anywhere in the module's transitive closure
    and deletes the verb, so a broken fastmcp and an uninstalled server
    package produce the same ``invalid choice: 'serve'``
    (ledger J-cli-robustness-21). :func:`_import_is_of` splits the two, and a
    broken one is registered as a self-diagnosing stub instead of vanishing.

    ``register`` is called inside the ``try`` on purpose: an ``add_subparsers``
    that imports lazily (several do) fails the same way and means the same
    thing.
    """
    try:
        register()
    except ImportError as exc:
        if _import_is_of(module_path, exc):
            return
        _register_broken_verb(sub, verb, module_path, exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heph", description="Hephaestus CAD engine CLI (engine-first: no server)"
    )
    # Answers before any subcommand is required, and without importing anything
    # that could need Node — G7H lane (a) runs `heph --version` on a machine
    # with no Node at all, as the first proof that the wheel installed cleanly.
    parser.add_argument(
        "--version",
        action="version",
        version=f"heph {_version()}",
        help="print the installed Hephaestus version and exit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build a part and publish the result")
    build.add_argument("part", nargs="?", default=None, help="part name or path to parts/<name>.py")
    build.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="transient part-parameter override (makes the build a preview)",
    )
    build.add_argument(
        "--global-param",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        dest="global_param",
        help="transient project-parameter override (makes the build a preview)",
    )
    build.add_argument("--stale", action="store_true", help="rebuild every stale consumer part")
    build.add_argument("--json", action="store_true", help="emit the exact BuildResult JSON")
    build.add_argument(
        "--unsafe-local-executor",
        action="store_true",
        dest="unsafe_local_executor",
        help="run the worker WITHOUT OS sandboxing (local debugging only)",
    )
    build.set_defaults(func=_cmd_build)

    check = sub.add_parser("check", help="run the cross-part check set")
    check.add_argument(
        # `--project` means a directory on `heph agent` and `heph serve --web`,
        # so the boolean spelling made one name mean two things and turned
        # `heph check --project ./demo` into a bare "unrecognized arguments"
        # (ledger J-cli-robustness-4). `--snapshot` says what the flag does;
        # `--project` stays as a retiring alias so no script breaks, and is the
        # single exemption `_assert_no_arity_collisions` carries.
        "--snapshot",
        "--project",
        action="store_true",
        dest="project",
        help="require and record a coherent project snapshot",
    )
    check.add_argument("--json", action="store_true", help="emit the CheckReport JSON")
    check.set_defaults(func=_cmd_check)

    lint = sub.add_parser("lint", help="lint a part script (§9 + hc shadowing)")
    lint.add_argument("path", help="path to the part script")
    lint.add_argument("--json", action="store_true", help="emit findings as JSON")
    lint.add_argument(
        "--requirements",
        default=None,
        help="requirement-ledger JSON (entry array or generation document)",
    )
    lint.add_argument(
        "--request",
        default=None,
        help=(
            "original request text; with --requirements this enables the "
            "unsourced_requirement rule (the rule joins the two, so --request "
            "alone is refused rather than reporting a clean run)"
        ),
    )
    lint.set_defaults(func=_cmd_lint)

    # The scaffolding verb (heph init) lives in its own module; it needs no CAD
    # stack at all — it only writes the four-file project convention.
    from hephaestus.core import cli_init

    cli_init.add_subparsers(sub)

    # Agent-shaped authoring verbs (heph part / script / params / prompt): the
    # same create_part / write_part store contract the tool surface uses, plus
    # the list_parts / BuildResult / PARAMS reads. No Node, no server.
    from hephaestus.core import cli_authoring

    cli_authoring.add_subparsers(sub)

    # Stage 1 render verbs (heph render / heph goldens) live in a separate module
    # so the render stack is imported only when those verbs run; every verb above
    # is untouched. See hephaestus.core.cli_render.
    from hephaestus.core import cli_render

    cli_render.add_subparsers(sub)

    # Stage 2 registry verbs (heph registry pin/update/verify/list) likewise live
    # in their own module; pinning needs no CAD stack at all.
    from hephaestus.core import cli_registry

    cli_registry.add_subparsers(sub)

    # Stage 8A reference verbs (heph reference add/list/remove) likewise: the
    # operator-side half of INGEST.md §2. There is deliberately no model-facing
    # counterpart — a reference enters a project through this verb or a bench
    # fixture, never through a tool call.
    from hephaestus.core import cli_references

    cli_references.add_subparsers(sub)

    # Project ingress (heph import add/list): the geometry counterpart of
    # heph reference add. Kernel import already exists (import_step /
    # import_mesh); this verb copies a vendor file into imports/ so a script
    # can name it. Browser import stays deferred (INTERFACE.md §15.37).
    from hephaestus.core import cli_import

    cli_import.add_subparsers(sub)

    # Stage 8B comparison verb (heph diff): the operator's view of exactly the
    # facts the compare_solids tool returns (COMPARE.md §2).
    from hephaestus.core import cli_diff

    cli_diff.add_subparsers(sub)

    # Stage 12A ingest verb (heph scan): the facts of a mesh or point cloud
    # under imports/, through the same admission and canonicalization a build
    # uses (MESH_INGEST.md §7.3). Facts are not a tool — they ride the build
    # record and this command — so nothing on the tool surface moves for it.
    from hephaestus.core import cli_scan

    cli_scan.add_subparsers(sub)

    # Stage 8C assembly verbs (heph assembly / heph assembly check): the
    # operator's view of the declared constraint set and its latest residuals
    # (ASSEMBLY.md §3). Evaluation loads the geometry kernel, so the module is
    # imported only when one of its verbs runs.
    from hephaestus.core import cli_assembly

    cli_assembly.add_subparsers(sub)

    # Stage 9A kinematics verb (heph joints): the operator's view of the
    # declared joint and pose sets with their latest projected motion outcomes
    # (KINEMATICS.md §6). Read-only — re-evaluation is the check_motion tool
    # and 'heph motion check'. The module binds the geometry kernel through
    # the motion evaluator, so it is imported only when the verb runs, like
    # the assembly verbs.
    from hephaestus.core import cli_joints

    cli_joints.add_subparsers(sub)

    # Stage 9B kinematics verbs (heph motion / heph motion check): the
    # operator's view of the declared motion checks with their latest §4
    # sweep results, and the operator-side evaluate verb (KINEMATICS.md §6).
    # Same lazy-kernel rule as the joints verb.
    from hephaestus.core import cli_motion

    cli_motion.add_subparsers(sub)

    # 2D CAM emit (heph cam emit): laser_cut / waterjet toolpath + DXF from a
    # published build. Reuses geom.kerf + geom.nesting; loads the kernel only
    # when the verb runs, like the assembly and motion verbs.
    from hephaestus.core import cli_cam

    cli_cam.add_subparsers(sub)

    # Stage 13A pose-solving verb (heph solve pose): the operator's half of
    # SOLVER.md §2A. It PROPOSES and writes nothing - no pose declaration, no
    # artifact, no generation - so there is no --apply here and never will be
    # under this stage's mandate. Same lazy-kernel rule as the motion verbs:
    # the solver's independent verification pass binds the geometry kernel.
    from hephaestus.core import cli_solve

    cli_solve.add_subparsers(sub)
    cli_solve.add_proposal_subparser(sub)

    # The four optional verbs below ship with packages the engine CLI does not
    # require: `heph agent`, `heph export`, `heph bench` and `heph serve` all
    # live in the server package, and the engine CLI stays Node-free and fully
    # functional without it (PACKAGING.md). `_optional_verb` is what makes that
    # tolerance narrow instead of total — an absent package omits the verb, a
    # broken one registers a stub that names the failing import (ledger
    # J-cli-robustness-21).
    #
    # THE REGISTRATION INVARIANT, stated once for all of them: registering a
    # verb may import only modules whose closure EXCLUDES build123d, fastmcp,
    # starlette and `hephaestus.geom`. Three comments here used to assert that
    # these registrations were free; they were not, and the measurement said
    # 2.9 s for `heph --version` (ledger J-cli-startup-1 through -5, root cause
    # RC-2). What made them false was never the leaf modules — every one of
    # them defers its real work — but their package `__init__` files and one
    # constant read out of the geometry package; those are fixed at the source,
    # and `core/tests/test_cli_startup.py` asserts the closure after
    # `build_parser()` rather than trusting a comment again.

    def _register_agent() -> None:
        from hephaestus.agent_bridge import cli as agent_cli

        agent_cli.add_subparsers(sub)

    _optional_verb(sub, "agent", "hephaestus.agent_bridge.cli", _register_agent)

    # Stage 10A export verbs (heph export list / unpin) ship with the server
    # package because the export write-ahead table is written there
    # (`agent_bridge/cad_ops`). They need no Node and no network, and `list`
    # imports no geometry kernel — true as of J-cli-startup-2, which made the
    # `cad_ops` aggregate lazy; before that this comment was false by 3.5 s
    # (INTERFACE.md §19.40, §22.6).
    def _register_export() -> None:
        from hephaestus.agent_bridge import cli_export

        cli_export.add_subparsers(sub)

    _optional_verb(sub, "export", "hephaestus.agent_bridge.cli_export", _register_export)

    # Stage 2 bench verbs (heph bench run/score) ship with the server package too;
    # the handlers import the harness lazily, so registering costs nothing.
    def _register_bench() -> None:
        from hephaestus.bench import cli_bench

        cli_bench.add_subparsers(sub)

    _optional_verb(sub, "bench", "hephaestus.bench.cli_bench", _register_bench)

    # Stage 3 MCP verb (heph serve --mcp) ships with the server package as well;
    # the handler imports FastMCP lazily, and since J-cli-startup-3 so does the
    # `hephaestus.mcp` package init, so registering really does cost nothing.
    #
    # The `serve` verb is assembled from two halves on purpose (INTERFACE.md §2.1
    # and the 2026-07-26 ordering amendment): `hephaestus.mcp.cli_serve` owns
    # `--mcp` and creates the parser, and `hephaestus.http.cli_web` extends it
    # with `--web`. `server/http` is a web client API and NOT part of the
    # headless surface, so the MCP module may not import it — the assembly
    # happens here, where neither surface is.
    #
    # The two halves are therefore reported SEPARATELY: a broken `http.cli_web`
    # used to take `--mcp` down with it, which is the same swallowed-failure bug
    # one level in (J-cli-robustness-21). `--web` becomes a flag that refuses by
    # name; `--mcp` keeps working.
    #
    # The split is one-directional and that is a deliberate limit, not an
    # oversight: `_register_serve` is itself wrapped, so a break in
    # `hephaestus.mcp.cli_serve` — the half that CREATES the parser — stubs the
    # whole verb and takes `--web` with it. There is no parser to hang `--web`
    # on until that import returns. It is not reachable through a real
    # dependency break, because `cli_serve` imports argparse, sys and typing and
    # nothing else (0.014 s, no heavy closure) — every dependency that can
    # actually break is behind `.app`, which `serve()` imports at invocation and
    # refuses by name there. Making the two symmetric would mean moving the
    # serve parser's skeleton up into this file, which would move `serve --help`
    # away from the module that owns the verb.
    def _register_serve() -> None:
        from hephaestus.mcp import cli_serve

        serve_parser = cli_serve.add_subparsers(sub)
        try:
            from hephaestus.http import cli_web
        except ImportError as exc:
            if not _import_is_of("hephaestus.http.cli_web", exc):
                _register_broken_serve_web(serve_parser, exc)
        else:
            cli_web.extend_serve(serve_parser)

    _optional_verb(sub, "serve", "hephaestus.mcp.cli_serve", _register_serve)

    _assert_no_arity_collisions(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = cast("Callable[[argparse.Namespace], int]", args.func)
    # The taxonomy lives in `cli_errors.dispatch`, not here, so a verb group's
    # `guard()` and a module `main()` map exactly what `heph` maps
    # (ledger J-cli-robustness-5, -6, -20).
    return dispatch(command, args)


if __name__ == "__main__":
    sys.exit(main())
