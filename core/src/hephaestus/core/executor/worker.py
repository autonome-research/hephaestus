"""The sandboxed build worker: one JSON job on stdin -> one JSON result on stdout.

Executes a part script statement by statement under the §2 injected
namespace, checkpointing after every statement (index, span, bound names;
shape refs are held eagerly, metrics are computed lazily — for the last-good
snapshot on failure and for the final compound on success, per mission
rule 4). On failure it emits the complete §8 error record (line/col, type,
message, ±2-line frame with a ``"> "`` marker, ``built_through``,
``last_good`` metrics) and writes the last-good BRep under the out dir; on
success it writes the final compound BRep plus geometry index, source map,
and tag fingerprints. Artifacts are written ONLY under the job's out dir —
the parent (runner) moves them into CAS and mints refs.

Job JSON: ``{"part", "script", "globals_source", "part_overrides",
"project_overrides", "out_dir", "origin", "mode"}``.
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

from hephaestus.core.errors import HephaestusError
from hephaestus.core.executor import fingerprint, source_map
from hephaestus.core.executor.globals_exec import (
    GlobalsResult,
    ensure_no_shadowing,
    execute_globals,
)
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    ParamState,
    PartOutput,
    build_namespace,
)
from hephaestus.core.executor.splitter import (
    GLOBALS_FILENAME,
    PART_FILENAME,
    Statement,
    compile_statement,
    frame_lines,
    parse_module,
    split_statements,
)
from hephaestus.core.executor.tags import TagRegistry, resolve_placements
from hephaestus.core.params import params_declaration_json
from opstore.types import JSONValue

FINAL_BREP = "final.brep"
LAST_GOOD_BREP = "last_good.brep"
SOURCE_MAP_FILE = "source_map.json"

#: §8 hint text, verbatim.
INSPECT_HINT = "inspect_part(name, artifact_ref=last_good_artifact_ref) renders this exact snapshot"
NO_SNAPSHOT_HINT = "no statement completed before the failure; fix the reported line and rebuild"


def _is_shapeish(value: object) -> bool:
    """Shape, or a list of shapes (the observed list-binding pattern)."""
    from build123d.topology import Shape

    if isinstance(value, Shape):
        return True
    if isinstance(value, list):
        items: list[object] = value
        return all(isinstance(item, Shape) for item in items)
    return False


def _solid_genus(solid: Any) -> int:
    """Genus via the Euler-Poincaré formula: G = S - (V - E + 2F - L)/2."""
    v = len(solid.vertices())
    e = len(solid.edges())
    f = len(solid.faces())
    loops = len(solid.wires())
    shells = len(solid.shells())
    return shells - (v - e + 2 * f - loops) // 2


def _shape_metrics(shape: Any) -> dict[str, JSONValue]:
    """Full metrics for a built shape (bbox, volume, counts, sealed, genus)."""
    solids = list(shape.solids())
    bbox = shape.bounding_box()
    size = bbox.size
    sealed = bool(solids) and all(bool(s.is_manifold) for s in solids)
    genus = sum(_solid_genus(s) for s in solids)
    return {
        "solids": len(solids),
        "faces": len(shape.faces()),
        "edges": len(shape.edges()),
        "bbox_mm": [float(size.X), float(size.Y), float(size.Z)],
        "volume_mm3": float(shape.volume),
        "area_mm2": float(shape.area),
        "sealed": sealed,
        "genus": genus,
    }


def _write_brep(shape: Any, path: Path) -> None:
    from OCP.BRepTools import BRepTools  # pyright: ignore[reportAttributeAccessIssue]

    if not BRepTools.Write_s(shape.wrapped, str(path)):
        raise OSError(f"failed to write BRep to {path}")


def _as_compound(shapes: list[Any]) -> Any:
    from build123d import Compound

    # A script may bind one shape object under several names, so the checkpoint
    # shape list can contain duplicates; anytree refuses to parent the same
    # node twice. Deduplicate by identity, preserving first-seen order.
    unique: list[Any] = []
    seen: set[int] = set()
    for shape in shapes:
        if id(shape) not in seen:
            seen.add(id(shape))
            unique.append(shape)
    if len(unique) == 1:
        return unique[0]
    return Compound(children=unique)


def _failure_location(exc: BaseException, filename: str, fallback_line: int) -> tuple[int, int]:
    """Deepest script-frame line/col of ``exc`` (0-based col per §8 example)."""
    line = fallback_line
    col = 0
    if isinstance(exc, SyntaxError) and exc.filename == filename:
        return (exc.lineno or fallback_line, max(0, (exc.offset or 1) - 1))
    te = traceback.TracebackException.from_exception(exc)
    for frame_summary in te.stack:
        if frame_summary.filename == filename:
            line = frame_summary.lineno or line
            colno = getattr(frame_summary, "colno", None)
            col = colno if isinstance(colno, int) else 0
    return (line, col)


class _LastGood:
    """Tracks the last-good geometry candidates as execution progresses."""

    def __init__(self) -> None:
        self.shapes: list[Any] = []
        self.statement: Statement | None = None

    def update(self, statement: Statement, bound_shapes: list[Any]) -> None:
        self.statement = statement
        if bound_shapes:
            self.shapes = bound_shapes


def _error_record(
    *,
    exc: BaseException,
    source: str,
    filename: str,
    fallback_line: int,
    built_through: Statement | None,
    last_good_shape: Any | None,
    out_dir: Path,
) -> tuple[dict[str, JSONValue], bool]:
    """Build the §8 error record; returns (record, wrote_last_good_brep)."""
    line, col = _failure_location(exc, filename, fallback_line)
    record: dict[str, JSONValue] = {
        "line": line,
        "col": col,
        "type": type(exc).__name__,
        "message": str(exc),
        "frame": list(frame_lines(source, line)),
        "built_through": None,
        "last_good": None,
        "last_good_artifact_ref": None,
        "hint": NO_SNAPSHOT_HINT,
    }
    if built_through is not None:
        record["built_through"] = {
            "line": built_through.lineno,
            "statement": built_through.text,
        }
    wrote = False
    if last_good_shape is not None:
        metrics = _shape_metrics(last_good_shape)
        bodies = (
            len(list(last_good_shape.children))
            if hasattr(last_good_shape, "children") and list(last_good_shape.children)
            else 1
        )
        record["last_good"] = {
            "bodies": bodies,
            "solids": metrics["solids"],
            "size_mm": metrics["bbox_mm"],
            "volume_mm3": metrics["volume_mm3"],
            "sealed": metrics["sealed"],
            "genus": metrics["genus"],
        }
        record["hint"] = INSPECT_HINT
        try:
            _write_brep(last_good_shape, out_dir / LAST_GOOD_BREP)
            wrote = True
        except OSError:
            wrote = False
    return record, wrote


def _reverse_binding_names(
    namespace: Mapping[str, object], injected: frozenset[str]
) -> list[tuple[str, Any]]:
    """Script-bound (name, shape) pairs, list elements expanded, first-bound order."""
    from build123d.topology import Shape

    out: list[tuple[str, Any]] = []
    for name, value in namespace.items():
        if name in injected or name == "PARAMS":
            continue
        if isinstance(value, Shape):
            out.append((name, value))
        elif isinstance(value, list):
            items: list[object] = value
            if items and all(isinstance(item, Shape) for item in items):
                out.extend((name, item) for item in items)
    return out


def _binding_counts(namespace: Mapping[str, object], injected: frozenset[str]) -> dict[str, int]:
    """Source-map binding name -> element count (§7 rule 4)."""
    from build123d.topology import Shape

    out: dict[str, int] = {}
    for name, value in namespace.items():
        if name in injected or name == "PARAMS":
            continue
        if isinstance(value, Shape):
            out[name] = 1
        elif isinstance(value, list):
            items: list[object] = value
            if items and all(isinstance(item, Shape) for item in items):
                out[name] = len(items)
    return out


def _fill_labels_and_rows(root: Any, bindings: list[tuple[str, Any]]) -> list[tuple[str, int]]:
    """Label-fill unlabeled children from binding names; return (label, solids) rows.

    Pre-order traversal of the geometry tree. Unlabeled direct children whose
    shape matches a script binding get that binding name as their label (§5.1
    — underscore-private names keep their prefix, e.g. ``_placed_spline``).
    Unlabeled unmatched compounds recurse; unlabeled unmatched leaves are
    skipped.
    """
    from build123d import Compound

    rows: list[tuple[str, int]] = []

    def binding_name_for(shape: Any) -> str | None:
        wrapped = getattr(shape, "wrapped", None)
        if wrapped is None:
            return None
        for name, candidate in bindings:
            candidate_wrapped = getattr(candidate, "wrapped", None)
            if candidate_wrapped is not None and wrapped.IsSame(candidate_wrapped):
                return name
        return None

    def visit(node: Any) -> None:
        children = list(node.children) if hasattr(node, "children") else []
        for child in children:
            label = child.label
            if not label:
                name = binding_name_for(child)
                if name is not None:
                    child.label = name
                    label = name
            if label:
                rows.append((label, len(child.solids())))
            if isinstance(child, Compound):
                visit(child)

    children = list(root.children) if hasattr(root, "children") else []
    if children:
        visit(root)
    else:
        if not root.label:
            name = binding_name_for(root)
            if name is not None:
                root.label = name
        if root.label:
            rows.append((root.label, len(root.solids())))
    return rows


def _globals_failure(exc: BaseException, globals_source: str) -> dict[str, JSONValue]:
    line, col = _failure_location(exc, GLOBALS_FILENAME, 1)
    return {
        "line": line,
        "col": col,
        "type": type(exc).__name__,
        "message": f"globals.py: {exc}",
        "frame": list(frame_lines(globals_source, line)),
        "built_through": None,
        "last_good": None,
        "last_good_artifact_ref": None,
        "hint": "the failure is in globals.py, not the part script; fix globals.py and rebuild",
    }


def execute_job(job: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Run one build job and return the worker result record (pure protocol)."""
    part_name = str(job.get("part", "part"))
    script = str(job.get("script", ""))
    globals_raw = job.get("globals_source")
    globals_source = str(globals_raw) if isinstance(globals_raw, str) else None
    part_overrides_raw = job.get("part_overrides") or {}
    project_overrides_raw = job.get("project_overrides") or {}
    if not isinstance(part_overrides_raw, dict) or not isinstance(project_overrides_raw, dict):
        raise ValueError("part_overrides/project_overrides must be objects")
    out_dir = Path(str(job.get("out_dir", ".")))
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, JSONValue] = {
        "part": part_name,
        "status": "failed",
        "checkpoints": [],
        "metrics": None,
        "params_declaration": {},
        "effective_params": {},
        "project_params_declaration": {},
        "project_effective_params": {},
        "consumed_hc": {},
        "hc_state": {},
        "geometry_index": {"labels": [], "bindings": {}, "tags": []},
        "geometries": [],
        "source_map": None,
        "tag_fingerprints": {},
        "check_names": [],
        "checks": {},
        "metadata": {},
        "feature_metadata": {},
        "warnings": [],
        "artifacts": {},
        "error": None,
    }

    # --- globals.py -------------------------------------------------------
    try:
        globals_result = execute_globals(
            globals_source,
            overrides={k: _override_value(v, k) for k, v in project_overrides_raw.items()},
        )
    except BaseException as exc:
        result["error"] = _globals_failure(exc, globals_source or "")
        return result
    result["project_params_declaration"] = _params_json(globals_result)
    result["project_effective_params"] = dict(globals_result.effective_project_params)
    result["hc_state"] = globals_result.hc_state_json()

    # --- part namespace ---------------------------------------------------
    param_state = ParamState(
        scope="part",
        overrides={k: _override_value(v, k) for k, v in part_overrides_raw.items()},
    )
    hc = globals_result.hc_namespace()
    part = PartOutput()
    tag_registry = TagRegistry()
    check_registry = CheckRegistry()
    namespace = build_namespace(
        param_state=param_state,
        hc=hc,
        part=part,
        tag_registry=tag_registry,
        check_registry=check_registry,
    )
    injected = frozenset(namespace)

    # --- parse ------------------------------------------------------------
    try:
        module = parse_module(script, filename=PART_FILENAME)
        statements = split_statements(script, filename=PART_FILENAME)
    except SyntaxError as exc:
        record, _ = _error_record(
            exc=exc,
            source=script,
            filename=PART_FILENAME,
            fallback_line=exc.lineno or 1,
            built_through=None,
            last_good_shape=None,
            out_dir=out_dir,
        )
        result["error"] = record
        return result

    recorder = source_map.SourceMapRecorder(
        PART_FILENAME, source_map.assigns_by_line(module), _is_shapeish
    )
    booleans = source_map.boolean_attributions(module)

    # --- statement loop ---------------------------------------------------
    checkpoints: list[JSONValue] = []
    last_good = _LastGood()
    captured = io.StringIO()
    failure: BaseException | None = None
    failed_statement: Statement | None = None

    for statement, node in zip(statements, module.body, strict=True):
        tag_registry.set_statement(statement.index, statement.lineno)
        recorder.start_statement(statement.index)
        code = compile_statement(node, filename=PART_FILENAME)
        before = {name: id(value) for name, value in namespace.items()}
        try:
            with redirect_stdout(captured):
                recorder.run(code, namespace)
                if not param_state.published and "PARAMS" in namespace:
                    param_state.publish(namespace)
                    ensure_no_shadowing(param_state.declared or {}, hc.names())
        except BaseException as exc:
            failure = exc
            failed_statement = statement
            break
        bound = [
            name
            for name, value in namespace.items()
            if name not in injected and before.get(name) != id(value)
        ]
        shape_names = [name for name in bound if _is_shapeish(namespace[name])]
        bound_shapes: list[Any] = []
        for name in shape_names:
            value = namespace[name]
            if isinstance(value, list):
                items: list[Any] = value
                bound_shapes.extend(items)
            else:
                bound_shapes.append(value)
        last_good.update(statement, bound_shapes)
        checkpoint: dict[str, JSONValue] = {
            "index": statement.index,
            "span": list(statement.span),
            "bound": list(bound),
            "shapes": list(shape_names),
        }
        checkpoints.append(checkpoint)
    result["checkpoints"] = checkpoints
    result["stdout"] = captured.getvalue()

    geometry = part.geometry_value
    if failure is None:
        try:
            param_state.finalize()
            if geometry is None:
                _raise_missing_geometry(part_name)
            if not hasattr(geometry, "wrapped"):
                _raise_bad_geometry(geometry)
        except HephaestusError as exc:
            failure = exc
            failed_statement = None

    result["params_declaration"] = params_declaration_json(param_state.declared or {})
    result["effective_params"] = dict(param_state.effective or {})
    result["consumed_hc"] = hc.consumed_projection()
    result["metadata"] = part.metadata()
    feature_metadata: dict[str, JSONValue] = dict(part.feature_metadata())
    result["feature_metadata"] = feature_metadata

    if failure is not None:
        built_through = last_good.statement
        # ``part.geometry`` may hold a non-shape when the failure IS the bad
        # assignment (§5.1 contract error) — never feed it to metrics.
        last_good_shape = geometry if hasattr(geometry, "wrapped") else None
        if last_good_shape is None and last_good.shapes:
            last_good_shape = _as_compound(last_good.shapes)
        fallback_line = (
            failed_statement.lineno
            if failed_statement is not None
            else (built_through.lineno if built_through is not None else 1)
        )
        record, wrote = _error_record(
            exc=failure,
            source=script,
            filename=PART_FILENAME,
            fallback_line=fallback_line,
            built_through=built_through,
            last_good_shape=last_good_shape,
            out_dir=out_dir,
        )
        result["error"] = record
        if wrote:
            result["artifacts"] = {"last_good": LAST_GOOD_BREP}
        return result

    # --- success: metrics, index, source map, fingerprints, artifacts -----
    assert geometry is not None
    bindings = _reverse_binding_names(namespace, injected)
    rows = _fill_labels_and_rows(geometry, bindings)
    labels: list[str] = []
    dedup_counts: dict[str, int] = {}
    geometries: list[JSONValue] = []
    for label, solids in rows:
        labels.append(label)
        count = dedup_counts.get(label, 0) + 1
        dedup_counts[label] = count
        display = label if count == 1 else f"{label}#{count}"
        geometries.append({"label": display, "solids": solids})
    result["geometries"] = geometries
    geometry_index: dict[str, JSONValue] = {
        "labels": cast("list[JSONValue]", list(labels)),
        "bindings": cast("dict[str, JSONValue]", dict(_binding_counts(namespace, injected))),
        "tags": cast("list[JSONValue]", sorted(tag_registry.names())),
    }
    result["geometry_index"] = geometry_index

    placements = resolve_placements(tag_registry, geometry)
    warnings: list[JSONValue] = []
    for name, placement in placements.items():
        if placement.solid_index is None and placement.kind in ("face", "edge", "solid"):
            warnings.append(
                {
                    "kind": "tag_unresolved",
                    "tag": name,
                    "detail": (
                        f"tag {name!r} references topology that is not part of the "
                        "final part.geometry compound"
                    ),
                }
            )
    result["warnings"] = warnings

    smap = source_map.assemble(recorder, booleans, placements)
    (out_dir / SOURCE_MAP_FILE).write_text(json.dumps(smap, indent=2), encoding="utf-8")
    result["source_map"] = smap

    descriptors = {
        name: fingerprint.descriptor_for(record.shape)
        for name, record in tag_registry.records().items()
    }
    result["tag_fingerprints"] = fingerprint.descriptors_to_json(descriptors)

    checks: dict[str, object] = dict(check_registry.collected())
    raw_checks = namespace.get("CHECKS")
    if isinstance(raw_checks, dict):
        raw_map: dict[object, object] = raw_checks
        for key, value in raw_map.items():
            if isinstance(key, str) and callable(value):
                checks[key] = value
    result["check_names"] = cast("list[JSONValue]", sorted(checks))
    result["checks"] = _run_part_checks(
        part_name, geometry, checks, namespace, injected, tag_registry
    )

    result["metrics"] = _shape_metrics(geometry)
    _write_brep(geometry, out_dir / FINAL_BREP)
    result["artifacts"] = {"build": FINAL_BREP, "source_map": SOURCE_MAP_FILE}
    result["status"] = "ok"
    return result


def _run_part_checks(
    part_name: str,
    geometry: Any,
    checks: Mapping[str, object],
    namespace: Mapping[str, object],
    injected: frozenset[str],
    tag_registry: TagRegistry,
) -> dict[str, JSONValue]:
    """Evaluate part-scope CHECKS inside the sandbox (§6: run on every build).

    The predicates only exist in this worker's namespace, so they must run
    here; the measurement facade resolves selectors against the live built
    geometry. A failing/crashing check fails its report entry, never the
    build (``run_checks`` guarantees it).
    """
    if not checks:
        return {}
    try:
        from hephaestus.core.addressing import Resolution
        from hephaestus.core.checks.engine import CheckPredicate, run_checks
        from hephaestus.core.checks.facade import MappedGeometry, part_measurement
        from hephaestus.core.kernel import geometry_index, labeled_nodes

        nodes = labeled_nodes(geometry)
        index = geometry_index(
            geometry,
            bindings=_binding_counts(namespace, injected),
            tags=tag_registry.names(),
        )
        records = tag_registry.records()

        def _fuse(picked: list[Any]) -> Any:
            fused = picked[0]
            for extra in picked[1:]:
                fused = fused + extra
            return fused

        def resolver(resolution: Resolution) -> object:
            if resolution.kind == "part":
                return geometry
            if resolution.kind == "tag":
                return records[resolution.name].shape
            if resolution.kind == "label":
                picked = [nodes[i][1] for i in resolution.occurrences]
            else:  # binding: occurrences index append-order list elements
                value = namespace[resolution.name]
                items: list[Any] = value if isinstance(value, list) else [value]
                picked = [items[i] for i in resolution.occurrences]
            if len(picked) == 1 and not resolution.fused:
                return picked[0]
            return _fuse(picked)

        source = MappedGeometry(index=index, resolver=resolver)
        predicates = cast("dict[str, CheckPredicate]", dict(checks))
        results = run_checks(predicates, lambda: part_measurement(part_name, source))
        return {name: outcome.to_json() for name, outcome in results.items()}
    except Exception as exc:  # facade wiring failure: fail every check, not the build
        failure: JSONValue = {"error": {"type": type(exc).__name__, "message": str(exc)}}
        return {name: {"pass": False, "measured": failure} for name in checks}


def _override_value(value: JSONValue, name: str) -> int | float | str:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"override {name!r}: expected number or string")
    return value


def _params_json(globals_result: GlobalsResult) -> dict[str, JSONValue]:
    return params_declaration_json(dict(globals_result.project_params))


def _raise_missing_geometry(part_name: str) -> None:
    from hephaestus.core.errors import ValidationError

    raise ValidationError(
        f"part {part_name!r} did not assign part.geometry (script contract §5.1)",
        kind="contract",
    )


def _raise_bad_geometry(value: object) -> None:
    from hephaestus.core.errors import ValidationError

    raise ValidationError(
        f"part.geometry must be a build123d shape or Compound, got {type(value).__name__}",
        kind="contract",
    )


def main() -> int:
    """Protocol entrypoint: JSON job on stdin, JSON result on stdout."""
    try:
        job_raw: object = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"worker: invalid job JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(job_raw, dict):
        print("worker: job must be a JSON object", file=sys.stderr)
        return 2
    try:
        result = execute_job(job_raw)
    except Exception as exc:
        print(f"worker: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 3
    json.dump(result, sys.stdout)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
