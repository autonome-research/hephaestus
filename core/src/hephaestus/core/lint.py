"""§9 style lints plus the §4 PARAMS-shadowing error — AST only, never executed.

``heph lint`` nudges part scripts toward the recovered idiom (script
contract §9): geometry unreachable from ``part.geometry``, unlabeled
multi-solid compounds, params never read, tags never referenced, and missing
``description``/``process`` metadata. The one *error* severity finding is a
part ``PARAMS`` name shadowing an ``hc`` name (§4: every tunable has exactly
one home); it reuses :func:`hephaestus.core.executor.globals_exec.shadowed_params`
so lint and build agree on the rule.

Everything is derived from the AST, so findings are deterministic heuristics
(a lint, not law). Geometry-ness is a taint analysis seeded by calls to
known build123d constructors/operations and propagated through the module's
def-use graph; reachability walks the same graph backwards from the
``part.geometry`` assignment, ``tag()`` arguments, ``CHECKS``, and ``part.*``
metadata expressions.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from hephaestus.core.executor.globals_exec import shadowed_params
from hephaestus.core.executor.splitter import GLOBALS_FILENAME, PART_FILENAME
from opstore.types import JSONValue

Severity = Literal["warning", "error"]

#: build123d names whose call results seed the geometry taint analysis.
GEOMETRY_CALLS: frozenset[str] = frozenset(
    {
        "Box",
        "Cylinder",
        "Sphere",
        "Cone",
        "Torus",
        "Wedge",
        "Hole",
        "CounterBoreHole",
        "CounterSinkHole",
        "extrude",
        "revolve",
        "loft",
        "sweep",
        "make_face",
        "make_hull",
        "fillet",
        "chamfer",
        "offset",
        "mirror",
        "scale",
        "split",
        "section",
        "Compound",
        "Solid",
        "Shell",
        "Face",
        "Wire",
        "Edge",
        "Part",
        "Curve",
        "Sketch",
        "Rectangle",
        "RectangleRounded",
        "Circle",
        "Ellipse",
        "Polygon",
        "RegularPolygon",
        "Polyline",
        "Spline",
        "Bezier",
        "Helix",
        "Line",
        "Arc",
        "CenterArc",
        "ThreePointArc",
        "Text",
    }
)

#: §5.2 metadata fields whose absence lint reports (script contract §9).
REQUIRED_METADATA: tuple[str, ...] = ("description", "process")


@dataclass(frozen=True)
class LintFinding:
    """One structured lint finding.

    ``code`` is machine-stable; ``name`` carries the offending identifier
    (param/tag/binding/metadata field) when the finding is about one.
    """

    code: str
    severity: Severity
    line: int
    col: int
    message: str
    name: str | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "severity": self.severity,
            "line": self.line,
            "col": self.col,
            "message": self.message,
            "name": self.name,
        }


def hc_names_from_globals(source: str, *, filename: str = GLOBALS_FILENAME) -> tuple[str, ...]:
    """AST projection of the public ``hc`` names a globals.py source declares.

    Mirrors :func:`hephaestus.core.executor.globals_exec.execute_globals`
    without executing: project ``PARAMS`` keys plus every non-underscore
    top-level assigned/def'd name (``PARAMS`` itself excluded). Raises
    ``SyntaxError`` as-is for unparseable source.
    """
    module = ast.parse(source, filename=filename)
    names: dict[str, None] = {}
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name in _target_names(target):
                    if name == "PARAMS":
                        for key in _dict_str_keys(node.value):
                            names.setdefault(key)
                    elif _is_public(name):
                        names.setdefault(name)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            target = node.target
            if isinstance(target, ast.Name) and _is_public(target.id):
                names.setdefault(target.id)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if _is_public(node.name):
                names.setdefault(node.name)
        elif isinstance(node, ast.For):
            for name in _target_names(node.target):
                if _is_public(name):
                    names.setdefault(name)
    return tuple(names)


def lint_part_script(
    source: str,
    *,
    globals_source: str | None = None,
    filename: str = PART_FILENAME,
) -> tuple[LintFinding, ...]:
    """Convenience wrapper: lint a part script against its project globals.py."""
    hc_names: tuple[str, ...] = ()
    if globals_source is not None and globals_source.strip():
        hc_names = hc_names_from_globals(globals_source)
    return lint_script(source, hc_names=hc_names, filename=filename)


def lint_script(
    source: str,
    *,
    hc_names: Iterable[str] = (),
    filename: str = PART_FILENAME,
) -> tuple[LintFinding, ...]:
    """Run every §9 lint (plus the §4 shadowing error) over one part script.

    Returns findings sorted by (line, col, code, name). An unparseable
    script yields a single ``syntax`` error finding — lint never raises for
    bad input source.
    """
    try:
        module = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return (
            LintFinding(
                code="syntax",
                severity="error",
                line=exc.lineno or 1,
                col=max(0, (exc.offset or 1) - 1),
                message=f"syntax error: {exc.msg}",
            ),
        )
    facts = _Facts(module)
    findings: list[LintFinding] = []
    findings.extend(_shadow_findings(facts, hc_names))
    findings.extend(_unread_param_findings(facts))
    findings.extend(_unreferenced_tag_findings(facts))
    findings.extend(_missing_metadata_findings(facts))
    findings.extend(_unlabeled_compound_findings(module))
    findings.extend(_unreachable_geometry_findings(facts))
    findings.sort(key=lambda f: (f.line, f.col, f.code, f.name or ""))
    return tuple(findings)


# ---------------------------------------------------------------------------
# fact collection


@dataclass
class _Binding:
    line: int
    col: int
    uses: set[str] = field(default_factory=set[str])
    geometry_seed: bool = False


class _Facts:
    """Single-pass module facts: params, reads, tags, strings, def-use graph."""

    def __init__(self, module: ast.Module) -> None:
        self.params: dict[str, tuple[int, int]] = {}
        self.p_reads: set[str] = set()
        #: (tag name, call line, call col, location of the name argument)
        self.tag_calls: list[tuple[str, int, int, tuple[int, int]]] = []
        self.tag_arg_names: set[str] = set()
        self.string_locs: dict[str, list[tuple[int, int]]] = {}
        self.part_attrs: dict[str, tuple[int, int]] = {}
        self.geometry_roots: set[str] = set()
        self.consumed_names: set[str] = set()
        self.bindings: dict[str, _Binding] = {}
        self.has_geometry_assign = False
        self._collect_expressions(module)
        self._visit_body(module.body, in_function=False)

    # -- expression-level facts (whole module, including nested scopes) ----

    def _collect_expressions(self, module: ast.Module) -> None:
        for node in ast.walk(module):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "p"
                and isinstance(node.ctx, ast.Load)
            ):
                self.p_reads.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.string_locs.setdefault(node.value, []).append((node.lineno, node.col_offset))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "tag" and len(node.args) >= 2:
                    name_arg = node.args[1]
                    if isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str):
                        self.tag_calls.append(
                            (
                                name_arg.value,
                                node.lineno,
                                node.col_offset,
                                (name_arg.lineno, name_arg.col_offset),
                            )
                        )
                    self.tag_arg_names |= _loaded_names(node.args[0])
                elif node.func.id == "check":
                    for arg in node.args:
                        self.consumed_names |= _loaded_names(arg)

    # -- statement-level facts (module bindings + part.* assignments) ------

    def _visit_body(self, body: Iterable[ast.stmt], *, in_function: bool) -> None:
        for stmt in body:
            self._visit(stmt, in_function=in_function)

    def _visit(self, stmt: ast.stmt, *, in_function: bool) -> None:
        if isinstance(stmt, ast.Assign):
            self._visit_assign(stmt, in_function=in_function)
        elif isinstance(stmt, ast.AugAssign | ast.AnnAssign):
            value = stmt.value
            names = _loaded_names(value) if value is not None else set()
            seed = value is not None and _has_geometry_call(value)
            if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
                names.add(stmt.target.id)
            self._assign_target(stmt.target, names, seed=seed, stmt=stmt, in_function=in_function)
        elif isinstance(stmt, ast.For | ast.AsyncFor):
            names = _loaded_names(stmt.iter)
            seed = _has_geometry_call(stmt.iter)
            if not in_function:
                for name in _target_names(stmt.target):
                    self._bind(name, stmt, names, seed=seed)
            self._visit_body(stmt.body, in_function=in_function)
            self._visit_body(stmt.orelse, in_function=in_function)
        elif isinstance(stmt, ast.While | ast.If):
            self._visit_body(stmt.body, in_function=in_function)
            self._visit_body(stmt.orelse, in_function=in_function)
        elif isinstance(stmt, ast.With | ast.AsyncWith):
            for item in stmt.items:
                names = _loaded_names(item.context_expr)
                seed = _has_geometry_call(item.context_expr)
                if item.optional_vars is not None and not in_function:
                    for name in _target_names(item.optional_vars):
                        self._bind(name, stmt, names, seed=seed)
            self._visit_body(stmt.body, in_function=in_function)
        elif isinstance(stmt, ast.Try):
            self._visit_body(stmt.body, in_function=in_function)
            for handler in stmt.handlers:
                self._visit_body(handler.body, in_function=in_function)
            self._visit_body(stmt.orelse, in_function=in_function)
            self._visit_body(stmt.finalbody, in_function=in_function)
        elif isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            if not in_function:
                names: set[str] = set()
                for inner in stmt.body:
                    names |= _loaded_names(inner)
                self._bind(stmt.name, stmt, names, seed=_body_has_geometry_call(stmt))
            self._visit_body(stmt.body, in_function=True)
        elif isinstance(stmt, ast.ClassDef):
            if not in_function:
                names = set()
                for inner in stmt.body:
                    names |= _loaded_names(inner)
                self._bind(stmt.name, stmt, names, seed=False)
            self._visit_body(stmt.body, in_function=True)
        elif isinstance(stmt, ast.Expr):
            self._visit_expr_stmt(stmt, in_function=in_function)

    def _visit_assign(self, stmt: ast.Assign, *, in_function: bool) -> None:
        value_names = _loaded_names(stmt.value)
        seed = _has_geometry_call(stmt.value)
        for target in stmt.targets:
            self._assign_target(target, value_names, seed=seed, stmt=stmt, in_function=in_function)
        # PARAMS / CHECKS declarations (top level only, matching the executor)
        if not in_function:
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "PARAMS":
                    for key, loc in _dict_str_key_locs(stmt.value):
                        self.params.setdefault(key, loc)
                if isinstance(target, ast.Name) and target.id == "CHECKS":
                    self.consumed_names |= value_names

    def _assign_target(
        self,
        target: ast.expr,
        value_names: set[str],
        *,
        seed: bool,
        stmt: ast.stmt,
        in_function: bool,
    ) -> None:
        if isinstance(target, ast.Attribute):
            base = target.value
            if isinstance(base, ast.Name) and base.id == "part":
                self.part_attrs.setdefault(target.attr, (stmt.lineno, stmt.col_offset))
                if target.attr == "geometry":
                    self.has_geometry_assign = True
                    self.geometry_roots |= value_names
                else:
                    self.consumed_names |= value_names
            elif isinstance(base, ast.Name) and not in_function:
                # attribute mutation (x.label = ..., x.color = ...) feeds x
                self._bind_use(base.id, value_names, stmt=stmt)
            elif _root_is_part(base):
                # part.feature("x").attr = ... — feature metadata consumption
                self.consumed_names |= value_names
            return
        if in_function:
            return
        for name in _target_names(target):
            self._bind(name, stmt, value_names, seed=seed)

    def _visit_expr_stmt(self, stmt: ast.Expr, *, in_function: bool) -> None:
        call = stmt.value
        if not isinstance(call, ast.Call) or in_function:
            return
        func = call.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            # method mutation on a binding: posts.append(make_post(x)) etc.
            arg_names: set[str] = set()
            for arg in call.args:
                arg_names |= _loaded_names(arg)
            for kw in call.keywords:
                arg_names |= _loaded_names(kw.value)
            self._bind_use(func.value.id, arg_names, stmt=stmt)

    def _bind(self, name: str, stmt: ast.stmt, uses: set[str], *, seed: bool) -> None:
        binding = self.bindings.setdefault(name, _Binding(line=stmt.lineno, col=stmt.col_offset))
        binding.uses |= uses - {name}
        binding.geometry_seed = binding.geometry_seed or seed

    def _bind_use(self, name: str, uses: set[str], *, stmt: ast.stmt) -> None:
        binding = self.bindings.setdefault(name, _Binding(line=stmt.lineno, col=stmt.col_offset))
        binding.uses |= uses - {name}


# ---------------------------------------------------------------------------
# individual lints


def _shadow_findings(facts: _Facts, hc_names: Iterable[str]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for name in shadowed_params(facts.params, hc_names):
        line, col = facts.params[name]
        findings.append(
            LintFinding(
                code="shadowed-param",
                severity="error",
                line=line,
                col=col,
                message=(
                    f"part PARAMS name {name!r} shadows an hc name — every tunable "
                    "has exactly one home (script contract §4); rename the part "
                    "param or drop it and read hc instead"
                ),
                name=name,
            )
        )
    return findings


def _unread_param_findings(facts: _Facts) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for name, (line, col) in facts.params.items():
        if name not in facts.p_reads:
            findings.append(
                LintFinding(
                    code="unread-param",
                    severity="warning",
                    line=line,
                    col=col,
                    message=f"PARAMS declares {name!r} but the script never reads p.{name}",
                    name=name,
                )
            )
    return findings


def _unreferenced_tag_findings(facts: _Facts) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for name, line, col, name_loc in facts.tag_calls:
        locs = facts.string_locs.get(name, [])
        if not any(loc != name_loc for loc in locs):
            findings.append(
                LintFinding(
                    code="unreferenced-tag",
                    severity="warning",
                    line=line,
                    col=col,
                    message=(
                        f"tag {name!r} is never referenced (no CHECKS selector, "
                        "part.feature() metadata, or other use names it)"
                    ),
                    name=name,
                )
            )
    return findings


def _missing_metadata_findings(facts: _Facts) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for attr in REQUIRED_METADATA:
        if attr not in facts.part_attrs:
            findings.append(
                LintFinding(
                    code="missing-metadata",
                    severity="warning",
                    line=1,
                    col=0,
                    message=f"part.{attr} is never assigned (script contract §5.2/§9)",
                    name=attr,
                )
            )
    return findings


def _unlabeled_compound_findings(module: ast.Module) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for node in ast.walk(module):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Compound"
        ):
            continue
        children = _compound_children(node)
        if children is None or len(children.elts) < 2:
            continue
        for position, element in enumerate(children.elts):
            anonymous = not (
                isinstance(element, ast.Name)
                or (isinstance(element, ast.Starred) and isinstance(element.value, ast.Name))
            )
            if anonymous:
                findings.append(
                    LintFinding(
                        code="unlabeled-compound",
                        severity="warning",
                        line=element.lineno,
                        col=element.col_offset,
                        message=(
                            f"child {position + 1} of this multi-solid Compound is "
                            "anonymous — bind it to a name or set .label so it "
                            "appears in the geometry tree (§5.1)"
                        ),
                    )
                )
    return findings


def _unreachable_geometry_findings(facts: _Facts) -> list[LintFinding]:
    if not facts.has_geometry_assign:
        return []  # missing part.geometry is a build error, not lint noise
    geometryish = _propagate_geometry(facts.bindings)
    reachable = _reach(
        facts.bindings,
        facts.geometry_roots | facts.tag_arg_names | facts.consumed_names,
    )
    findings: list[LintFinding] = []
    for name, binding in facts.bindings.items():
        if name in geometryish and name not in reachable:
            findings.append(
                LintFinding(
                    code="unreachable-geometry",
                    severity="warning",
                    line=binding.line,
                    col=binding.col,
                    message=(
                        f"{name!r} looks like geometry but is unreachable from "
                        "part.geometry — include it in the compound or remove it"
                    ),
                    name=name,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# graph helpers


def _propagate_geometry(bindings: dict[str, _Binding]) -> set[str]:
    geometryish = {name for name, binding in bindings.items() if binding.geometry_seed}
    changed = True
    while changed:
        changed = False
        for name, binding in bindings.items():
            if name not in geometryish and binding.uses & geometryish:
                geometryish.add(name)
                changed = True
    return geometryish


def _reach(bindings: dict[str, _Binding], roots: set[str]) -> set[str]:
    reachable: set[str] = set()
    stack = [name for name in roots if name in bindings]
    while stack:
        name = stack.pop()
        if name in reachable:
            continue
        reachable.add(name)
        stack.extend(use for use in bindings[name].uses if use in bindings)
    return reachable


# ---------------------------------------------------------------------------
# small AST utilities


def _is_public(name: str) -> bool:
    return bool(name) and not name.startswith("_") and name != "PARAMS"


def _target_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Tuple | ast.List):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_names(element))
        return tuple(names)
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return ()


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        inner.id
        for inner in ast.walk(node)
        if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load)
    }


def _has_geometry_call(node: ast.AST) -> bool:
    return any(
        isinstance(inner, ast.Call)
        and isinstance(inner.func, ast.Name)
        and inner.func.id in GEOMETRY_CALLS
        for inner in ast.walk(node)
    )


def _body_has_geometry_call(stmt: ast.stmt) -> bool:
    return _has_geometry_call(stmt)


def _dict_str_keys(node: ast.expr) -> tuple[str, ...]:
    return tuple(key for key, _ in _dict_str_key_locs(node))


def _dict_str_key_locs(node: ast.expr) -> tuple[tuple[str, tuple[int, int]], ...]:
    if not isinstance(node, ast.Dict):
        return ()
    out: list[tuple[str, tuple[int, int]]] = []
    for key in node.keys:
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            out.append((key.value, (key.lineno, key.col_offset)))
    return tuple(out)


def _compound_children(call: ast.Call) -> ast.List | None:
    """The literal children list of a ``Compound(...)`` call, if statically visible."""
    for keyword in call.keywords:
        if keyword.arg == "children":
            return keyword.value if isinstance(keyword.value, ast.List) else None
    if call.args and isinstance(call.args[0], ast.List):
        return call.args[0]
    return None


def _root_is_part(node: ast.expr) -> bool:
    current: ast.expr = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Name):
            return current.id == "part"
        else:
            return False
