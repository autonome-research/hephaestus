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
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from hephaestus.core.checks.engine import CheckSet
from hephaestus.core.checks.facade import GeometrySource
from hephaestus.core.errors import (
    AddressingError,
    HephaestusError,
    SandboxDeniedError,
    ValidationError,
)
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.base import (
    CapabilityReport,
    ExecBackend,
    ExecOutcome,
    SandboxSpec,
)
from hephaestus.core.executor.sandbox.probe import cached_probe, secure_backend
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.lint import lint_part_script, lint_requirements, requirement_entries
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
from hephaestus.core.project_store.store import blob_hash_of_ref
from hephaestus.core.types import BuildResult
from opstore.types import JSONValue

from opstore import canonical_json

__all__ = ["build_parser", "main"]

_PART_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Minimal probe part used by ``heph build --stale`` (no named part) to
#: evaluate globals.py in the sandbox and refresh the live hc projection.
_SYNC_PART = "__hc_sync__"
_SYNC_SCRIPT = "part.geometry = Box(1.0, 1.0, 1.0)\n"


class _UsageError(Exception):
    """CLI misuse: reported on stderr with exit code 2."""


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


def _project_root_from_cwd() -> Path:
    try:
        return find_project_root(Path.cwd())
    except ValidationError as exc:
        raise _UsageError(exc.message) from exc


def _make_backend(layout: ProjectLayout, *, unsafe: bool) -> ExecBackend:
    if unsafe:
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
            raise _UsageError(f"{flag} expects name=value, got {pair!r}")
        overrides[key] = value
    return overrides


def _resolve_build_target(target: str) -> tuple[Path, str]:
    """(project root, part name) for a part name or a parts/<name>.py path."""
    path = Path(target)
    if path.suffix == ".py" or path.is_file():
        script = path.resolve()
        if not script.is_file():
            raise _UsageError(f"no such part script: {target}")
        try:
            root = find_project_root(script.parent)
        except ValidationError as exc:
            raise _UsageError(exc.message) from exc
        if script != (root / PARTS_DIRNAME / script.name).resolve():
            raise _UsageError(f"{target} is not a part script under {root / PARTS_DIRNAME}/")
        return root, script.stem
    if not _PART_NAME_RE.match(target):
        raise _UsageError(f"invalid part name {target!r}")
    return _project_root_from_cwd(), target


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
        raise _UsageError("build: a part name or script path is required (or --stale)")
    if target is not None:
        root, part = _resolve_build_target(target)
    else:
        root, part = _project_root_from_cwd(), None
    layout = load_project(root)
    store = open_store(layout)
    publisher = Publisher(layout, store)
    backend = _make_backend(layout, unsafe=bool(args.unsafe_local_executor))

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


def _cmd_check(args: argparse.Namespace) -> int:
    json_out = bool(args.json)
    root = _project_root_from_cwd()
    layout = load_project(root)
    store = open_store(layout)
    publisher = Publisher(layout, store)

    from hephaestus.core.executor.artifact_geometry import artifact_source

    layout.store_root.mkdir(parents=True, exist_ok=True)
    sources: dict[str, GeometrySource] = {}
    with tempfile.TemporaryDirectory(prefix="heph-check-", dir=layout.store_root) as scratch:
        # Lock-free reads of each part's last current artifact (§3.5).
        for part in layout.part_names():
            current = publisher.current_result(part)
            if current is None or current.artifact_ref is None:
                continue
            data = store.blobs.get(blob_hash_of_ref(current.artifact_ref))
            sources[part] = artifact_source(data, scratch_dir=Path(scratch))

        snapshot_ref: str | None = None
        if args.project:
            try:
                snapshot = publisher.projections.assemble_snapshot(layout.part_names())
            except SnapshotRejectedError as exc:
                print(
                    f"heph: error ({exc.code}): project snapshot is incoherent",
                    file=sys.stderr,
                )
                for issue in exc.issues:
                    names = f" ({', '.join(issue.names)})" if issue.names else ""
                    print(
                        f"  {issue.part}: {issue.kind}: {issue.detail}{names}",
                        file=sys.stderr,
                    )
                return 1
            snapshot_ref = snapshot.ref

        check_set = CheckSet(layout.checks_dir, store)
        report = check_set.run(
            sources, part=layout.manifest.name, project_snapshot_ref=snapshot_ref
        )

    if json_out:
        print(json.dumps(report.to_json()))
    else:
        if not report.checks:
            print("no cross-part checks")
        for name in sorted(report.checks):
            outcome = report.checks[name]
            verdict = "pass" if outcome.passed else "FAIL"
            print(f"{name}: {verdict} (measured: {json.dumps(outcome.measured)})")
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


def _cmd_lint(args: argparse.Namespace) -> int:
    json_out = bool(args.json)
    path = Path(cast("str", args.path))
    if not path.is_file():
        raise _UsageError(f"no such file: {path}")
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
    raw_requirements = cast("str | None", args.requirements)
    if raw_requirements is not None:
        ledger_path = Path(raw_requirements)
        if not ledger_path.is_file():
            raise _UsageError(f"no such requirements file: {ledger_path}")
        entries = requirement_entries(json.loads(ledger_path.read_text(encoding="utf-8")))
        ledger_ids = [str(entry.get("id", "")) for entry in entries]
    findings = lint_part_script(
        source,
        globals_source=globals_source,
        filename=str(path),
        ledger_ids=ledger_ids,
    )
    raw_request = cast("str | None", args.request)
    if raw_request is not None:
        request_path = Path(raw_request)
        if not request_path.is_file():
            raise _UsageError(f"no such request file: {request_path}")
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
    if json_out:
        print(json.dumps([finding.to_json() for finding in findings]))
    else:
        for finding in findings:
            suffix = f" [{finding.name}]" if finding.name else ""
            print(
                f"{path}:{finding.line}:{finding.col}: {finding.severity} "
                f"{finding.code}: {finding.message}{suffix}"
            )
        if not findings:
            print(f"{path}: clean")
    return 1 if any(finding.severity == "error" for finding in findings) else 0


# --------------------------------------------------------------------------
# entrypoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heph", description="Hephaestus CAD engine CLI (engine-first: no server)"
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
        "--project",
        action="store_true",
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
        help="original request text; enables the unsourced_requirement rule",
    )
    lint.set_defaults(func=_cmd_lint)

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

    # Stage 2 agent verb (heph agent) ships with the server package; the engine
    # CLI stays Node-free and fully functional when it is not installed.
    try:
        from hephaestus.agent_bridge import cli as agent_cli
    except ImportError:
        pass
    else:
        agent_cli.add_subparsers(sub)

    # Stage 2 bench verbs (heph bench run/score) ship with the server package too;
    # the handlers import the harness lazily, so registering costs nothing.
    try:
        from hephaestus.bench import cli_bench
    except ImportError:
        pass
    else:
        cli_bench.add_subparsers(sub)

    # Stage 3 MCP verb (heph serve --mcp) ships with the server package as well;
    # the handler imports FastMCP lazily, so registering costs nothing here.
    try:
        from hephaestus.mcp import cli_serve
    except ImportError:
        pass
    else:
        cli_serve.add_subparsers(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = cast("Callable[[argparse.Namespace], int]", args.func)
    try:
        return command(args)
    except _UsageError as exc:
        print(f"heph: {exc}", file=sys.stderr)
        return 2
    except AddressingError as exc:
        detail = exc.message
        if exc.candidates:
            detail += f" (candidates: {', '.join(exc.candidates)})"
        print(f"heph: {detail}", file=sys.stderr)
        return 2
    except SandboxDeniedError as exc:
        print(f"heph: error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    except HephaestusError as exc:
        print(f"heph: error ({exc.code}): {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
