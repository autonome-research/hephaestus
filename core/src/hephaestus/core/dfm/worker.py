"""The sandboxed DFM worker: one JSON job on stdin -> one JSON result on stdout.

Rule predicates are untrusted registry content, so this worker is deliberately
the *same* kind of process as the build worker: launched only through an
:class:`~hephaestus.core.executor.sandbox.base.ExecBackend`, reading its job from
stdin, writing artifacts nowhere but the job's out dir, and executing predicate
source under the §2 injected namespace from
:func:`~hephaestus.core.executor.namespace.build_namespace` — the same whitelist
a part script gets and not one capability more. ``open``, ``__import__``,
``exec``/``eval`` and friends are absent from the predicate's builtins, and the
OS sandbox is the real boundary behind that.

A predicate is a module that defines ``evaluate(ctx)``. It receives a
:class:`~hephaestus.core.dfm.context.DfmContext` and reports violations through
``ctx.report(...)``; the rule id, title and severity are attached *here* from
the rule declaration, so registry content can neither invent a rule id nor
understate its own severity. A predicate that raises fails its own rule
(``status: "error"``) and never the run — one broken rule must not hide the
findings of the rest.

Job JSON: ``{"mode": "dfm", "origin": "registry", "part", "process",
"source_artifact_ref", "brep", "metadata", "material", "tags", "rules",
"out_dir"}``.
"""

from __future__ import annotations

import io
import json
import sys
import traceback
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, cast

from hephaestus.core.dfm.context import DfmContext, build_context
from hephaestus.core.dfm.types import TopologyDescriptor
from hephaestus.core.executor.namespace import ParamState, build_namespace
from opstore.types import JSONValue

__all__ = ["PREDICATE_ENTRYPOINT", "evaluate_job", "main"]

#: The function name every rule predicate must define.
PREDICATE_ENTRYPOINT = "evaluate"


def _predicate_namespace() -> dict[str, object]:
    """The §2 injected namespace, minus the part-authoring objects.

    A predicate measures; it does not author geometry, so ``part``, ``tag`` and
    ``check`` are absent and ``PARAMS``/``p`` stay unpublished (reading ``p``
    raises the ordinary contract error). Everything else — build123d, ``math``,
    ``approx``, the restricted builtins — is exactly what a part script sees.
    """
    return build_namespace(param_state=ParamState(scope="dfm rule", overrides={}))


def _load_predicate(source: str, rule_id: str) -> Any:
    namespace = _predicate_namespace()
    code = compile(source, f"<dfm:{rule_id}>", "exec")
    exec(code, namespace)
    entry = namespace.get(PREDICATE_ENTRYPOINT)
    if not callable(entry):
        raise ValueError(
            f"rule {rule_id!r}: predicate must define "
            f"{PREDICATE_ENTRYPOINT}(ctx); defined names: "
            + (", ".join(sorted(n for n in namespace if not n.startswith("_"))) or "(none)")
        )
    return entry


def _descriptors(raw: JSONValue) -> dict[str, TopologyDescriptor]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, TopologyDescriptor] = {}
    for name, entry in raw.items():
        if isinstance(entry, dict):
            out[str(name)] = TopologyDescriptor.from_json(cast("Mapping[str, JSONValue]", entry))
    return out


def _string_map(raw: JSONValue) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, str)}


def _float_map(raw: JSONValue) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, int | float) and not isinstance(value, bool):
            out[str(key)] = float(value)
    return out


def evaluate_job(job: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Run one DFM job and return the worker result record (pure protocol).

    Importable and callable in-process for tests; production callers reach it
    only through :func:`hephaestus.core.dfm.runner.evaluate_pack`, i.e. through
    a sandbox backend.
    """
    from hephaestus.core.executor.artifact_geometry import load_brep_shape

    part = str(job.get("part", "part"))
    process = str(job.get("process", ""))
    artifact_ref = str(job.get("source_artifact_ref", ""))
    out_dir = Path(str(job.get("out_dir", ".")))
    metadata = _string_map(job.get("metadata"))
    material_raw = job.get("material")
    material = (
        cast("Mapping[str, JSONValue]", material_raw) if isinstance(material_raw, dict) else None
    )
    tags = _descriptors(job.get("tags"))

    result: dict[str, JSONValue] = {
        "status": "failed",
        "part": part,
        "process": process,
        "source_artifact_ref": artifact_ref,
        "rules": [],
        "truncated": False,
        "error": None,
    }

    brep_name = job.get("brep")
    if not isinstance(brep_name, str) or not brep_name:
        result["error"] = "job is missing the 'brep' artifact filename"
        return result
    brep_path = out_dir / brep_name
    try:
        geometry = load_brep_shape(brep_path.read_bytes(), scratch_dir=out_dir)
    except Exception as exc:
        result["error"] = f"could not load the source artifact: {type(exc).__name__}: {exc}"
        return result

    rules_raw = job.get("rules")
    if not isinstance(rules_raw, list):
        result["error"] = "job 'rules' must be a list"
        return result

    outcomes: list[JSONValue] = []
    truncated = False
    captured = io.StringIO()
    for item in cast("list[JSONValue]", rules_raw):
        if not isinstance(item, dict):
            continue
        rule = cast("Mapping[str, JSONValue]", item)
        rule_id = str(rule.get("rule_id", ""))
        title = str(rule.get("title", rule_id))
        severity = str(rule.get("severity", "error"))
        params = _float_map(rule.get("params"))
        context = build_context(
            part=part,
            process=process,
            source_artifact_ref=artifact_ref,
            geometry=geometry,
            params=params,
            metadata=metadata,
            material=material,
            tags=tags,
        )
        outcome = _run_rule(
            context,
            rule_id=rule_id,
            title=title,
            severity=severity,
            params=params,
            source=str(rule.get("source", "")),
            process=process,
            artifact_ref=artifact_ref,
            captured=captured,
        )
        truncated = truncated or context.truncated
        outcomes.append(outcome)

    result["rules"] = outcomes
    result["truncated"] = truncated
    result["stdout"] = captured.getvalue()
    result["status"] = "ok"
    return result


def _run_rule(
    context: DfmContext,
    *,
    rule_id: str,
    title: str,
    severity: str,
    params: Mapping[str, float],
    source: str,
    process: str,
    artifact_ref: str,
    captured: io.StringIO,
) -> dict[str, JSONValue]:
    """Evaluate one predicate; its failure is its own outcome, never the run's."""
    base: dict[str, JSONValue] = {
        "rule_id": rule_id,
        "title": title,
        "severity": severity,
        "params": {name: value for name, value in sorted(params.items())},
    }
    try:
        with redirect_stdout(captured):
            predicate = _load_predicate(source, rule_id)
            predicate(context)
    except BaseException as exc:
        return {
            **base,
            "status": "error",
            "findings": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
    findings: list[JSONValue] = []
    for raw in context.collected():
        findings.append(
            {
                "rule_id": rule_id,
                "severity": severity,
                "title": title,
                "process": process,
                "source_artifact_ref": artifact_ref,
                "message": raw.message,
                "tags": list(raw.tags),
                "topology": [descriptor.to_json() for descriptor in raw.topology],
                "measured": raw.measured,
                "suggested_bound": raw.suggested_bound,
                "bound_unit": "mm",
            }
        )
    return {
        **base,
        "status": "violations" if findings else "ok",
        "findings": findings,
        "error": None,
    }


def main() -> int:
    """Protocol entrypoint: JSON job on stdin, JSON result on stdout."""
    try:
        job_raw: object = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"dfm worker: invalid job JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(job_raw, dict):
        print("dfm worker: job must be a JSON object", file=sys.stderr)
        return 2
    try:
        result = evaluate_job(cast("Mapping[str, JSONValue]", job_raw))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"dfm worker: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 3
    json.dump(result, sys.stdout)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
