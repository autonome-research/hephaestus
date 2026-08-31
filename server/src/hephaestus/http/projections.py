# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The §2.3 read projections — every one a view of a shape the engine already has.

``INTERFACE.md`` §0.1 is the rule these functions follow literally: *every route
returns a shape a tool or a CLI verb already returns*. Where the browser needs
something the engine does not say, the honest answers in order are (1) the route
joins two existing documents, (2) the fact is added **in the engine**, or (3) it
is not shown. Nothing here computes a fact because the server declined to offer
one, and nothing here is a second implementation of a serializer that exists.

Four projections are deliberately **not** here, because they are shared and this
module is only the web side of a shared thing. Each lives below both callers:

* ``open_project_projection`` — :mod:`hephaestus.agent_bridge.project_projections`,
  because ``mcp/app.py``'s verb returns the same body and the dependency may
  not point from the headless surface into the web layer;
* ``list_parts_projection`` — :mod:`hephaestus.core.project_store.listing`,
  shared with ``heph part list --json`` and ``mcp/app.py``'s ``list_parts``;
* ``page_text`` — :mod:`hephaestus.core.artifacts`, shared with the
  ``read_artifact`` tool under a different principal check;
* ``report_json`` — :mod:`hephaestus.core.checks.report`, shared with
  ``heph check --json``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal

from hephaestus.core.checks.report import badge, report_json
from hephaestus.core.executor.namespace import METADATA_FIELDS
from hephaestus.core.types import BuildResult

__all__ = [
    "METADATA_FIELDS",
    "PROPERTY_SOURCES",
    "PropertySource",
    "build_projection",
    "checks_projection",
    "params_projection",
    "properties_projection",
]

#: Where a properties projection's values came from — a CLOSED two-value
#: vocabulary, served as a field so the panel and the e2e can tell the two apart
#: instead of inferring which read answered.
#:
#: ``build_record`` is :attr:`hephaestus.core.types.BuildResult.metadata`: the
#: §5.2 manufacturing metadata **as the worker evaluated it**, so an f-string
#: over ``hc``/``p`` values is carried exactly like a literal. ``script_literals``
#: is the static AST read (``cad_ops.script_metadata``), which recovers only
#: string *constants* — it is the fallback for a part with no current build, and
#: it is strictly weaker.
PROPERTY_SOURCES: Final[tuple[str, ...]] = ("build_record", "script_literals")

PropertySource = Literal["build_record", "script_literals"]


def build_projection(result: BuildResult | None) -> dict[str, Any]:
    """``GET /parts/{part}/build`` — the §2.3 BuildResult projection.

    ``geometry_count`` is served as an **explicit field** and is
    ``len(BuildResult.geometries)``: §6.1's TIGHTENING (binds G4.2), because
    three plausible numbers exist (labelled ``geometries`` entries, GLTF mesh
    nodes, ``kind="solid"`` selection-table rows) and the gate says *build-result*
    geometry count. The e2e reads this field over HTTP and compares it to the DOM
    row count; it never recounts client-side and never consults the GLTF.

    ``critique`` is present only when the record carries one. The §4 post-build
    critique is computed by ``build_part`` and returned in *its* result; it is not
    part of the persisted ``BuildResult``, so a read of the current build has none
    to report and says so by omission rather than by inventing an empty one.

    A part with no current build is ``status="not_built"`` — a named absence, not
    a 404 and not an empty success. Silence never reads as a pass (§6.3's rule,
    applied to the build axis).
    """
    if result is None:
        return {"status": "not_built", "current": False, "geometry_count": 0, "geometries": []}
    payload: dict[str, Any] = {
        "status": "ok" if result.status == "ok" else "error",
        "current": result.current,
        "artifact_ref": result.artifact_ref,
        "project_snapshot_ref": result.project_snapshot_ref,
        "effective_params": dict(result.params),
        "geometry_count": len(result.geometries),
        "geometries": [entry.to_json() for entry in result.geometries],
        "metrics": None if result.metrics is None else result.metrics.to_json(),
        "checks": {name: check.to_json() for name, check in result.checks.items()},
        "source_map_ref": result.source_map_ref,
        "warnings": [warning.to_json() for warning in result.warnings],
    }
    if result.error is not None:
        payload["error"] = result.error.to_json()
    return payload


def properties_projection(
    metadata: Mapping[str, str],
    *,
    source: PropertySource,
    build_artifact_ref: str | None = None,
) -> dict[str, Any]:
    """``GET /parts/{part}/properties`` — the enumerated ``part.*`` projection.

    §6.2's TIGHTENING (binds G4.3). "All metadata fields" is a completeness
    assertion with no list attached, and the only closed vocabulary available is
    the ``script_contract.md`` §5.2 ``part.*`` surface — the nine names
    :data:`hephaestus.core.executor.namespace.METADATA_FIELDS` enumerates, which
    is the same constant the executor enforces assignment against. The
    projection's keys are therefore **exactly the subset of that vocabulary the
    script declares**, and ``fields`` ships the whole vocabulary beside them so
    the panel can render an undeclared field as a visible absence rather than
    silently omitting a row.

    The e2e asserts set equality between ``PropertiesPanel``'s ``data-field``
    nodes and ``properties``' keys; a server-side pytest asserts ``properties``'
    keys equal the ``part.*`` metadata the fixture's script declares. Either
    assertion alone has a hole — containment would be satisfied by rendering one
    field, and a thin projection would make the DOM assertion trivially true.

    ``source`` names WHICH read answered, and it is load-bearing rather than
    decorative. "All metadata fields **from the script**" (G4.3) is not what a
    static AST parse returns: ``script_metadata`` recovers string *constants*
    only, so a script whose ``part.blank_size`` is an f-string over ``p.width``
    declares a field the parse cannot see — the exact 2026-08-03 defect
    :attr:`hephaestus.core.types.BuildResult.metadata` was added to fix ("which
    forced every downstream reader into literal-only static script parsing — the
    nest-gusset 'missing' blank_size the model had in fact written"). The route
    therefore reads the **runtime-metadata-carrying build record** first and
    falls back to the literal parse only where there is no current build to read;
    ``build_artifact_ref`` names the artifact the runtime values were evaluated
    with, so the panel reports metadata bound to an artifact rather than floating
    free of one.
    """
    declared = {key: value for key, value in metadata.items() if key in METADATA_FIELDS}
    return {
        "status": "ok",
        "properties": declared,
        "fields": list(METADATA_FIELDS),
        "source": source,
        "build_artifact_ref": build_artifact_ref,
    }


def checks_projection(report: Any, declared: Iterable[str] | None = None) -> dict[str, Any]:
    """``GET /checks`` and ``GET /parts/{part}/checks`` — the shared serializer.

    The body is ``heph check --json``'s document verbatim (§6.3: one serializer,
    two callers, byte-parity asserted on the canonical JSON) plus a ``badges``
    map, which is a *projection of the same document*, not a second verdict: it
    names, per check, which of the four closed states (``pass``, ``fail``,
    ``error``, ``not_run``) the report already says. The web client never runs
    checks and never derives a verdict; it reads this.

    ``declared`` is the set of check names the *check set* declares, when the
    caller knows it. Any declared name the report does not carry badges
    ``not_run`` — a first-class visible state, never a silent omission, because
    §6.3's rule is that silence must not read as a pass.

    NAMED GAP, recorded rather than papered over: **no engine surface enumerates
    declared-but-unrun check names today.**
    :func:`hephaestus.core.checks.engine.run_checks` produces one
    ``CheckResult`` per check it loaded, and ``CheckReport`` records the bundle
    ref and the file hashes but not the names inside them — so a run either
    reports a check or the whole generation fails closed with
    ``invalid_check_generation``. This parameter therefore has no production
    caller yet; it exists so the ``not_run`` badge is *implementable* rather
    than structurally unreachable, and supplying it is part of the §14 fixture
    work (§19 item 16), which needs a check in each of the four states.
    """
    document = report_json(report)
    badges = {name: badge(result) for name, result in report.checks.items()}
    for name in declared or ():
        badges.setdefault(name, badge(None))
    return {
        "status": "ok",
        "report": document,
        "badges": dict(sorted(badges.items())),
    }


def params_projection(
    declaration: Any, effective: dict[str, float | int], state_hash: str, scope: str
) -> dict[str, Any]:
    """``GET /parts/{part}/params`` — ``PARAMS`` declarations + ``state_hash``.

    One row per declared parameter: ``{name, value, default, min, max, step,
    scope}``. ``value`` is the *effective* value (declaration default merged with
    the persisted overrides) — the number a slider must start on — while
    ``default`` stays the script's literal, so the UI can offer "reset" without
    computing anything. ``state_hash`` is the optimistic
    ``expected_state_hash`` a ``POST /parts/{part}/params`` must present; the
    client echoes it back and never invents one.
    """
    rows: list[dict[str, Any]] = []
    for name in sorted(declaration):
        param = declaration[name]
        rows.append(
            {
                "name": name,
                "value": effective.get(name, param.default),
                "default": param.default,
                "min": param.min,
                "max": param.max,
                "step": param.step,
                "doc": param.doc,
                "scope": scope,
            }
        )
    return {"status": "ok", "params": rows, "state_hash": state_hash}
