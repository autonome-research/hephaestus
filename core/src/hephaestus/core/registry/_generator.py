"""The store-generator fragment contract: parse, check, and render an instance.

Instancing rewrites a generator body mechanically, so the source must be
unambiguous. A generator declares three marker regions (``params`` / ``bind`` /
``body``), reaches its body only through ``_name = p.name`` binds, keeps every
module-scope name underscore-prefixed, and ends with ``part.geometry = <name>``
naming the instance root. :func:`parse_generator` enforces exactly that;
:func:`render_fragment` emits the generator's own body verbatim, renamed under a
per-instance prefix and placed, so two pasted instances cannot collide.

``PARTS_STORE.md`` §2.1 adds a fourth, **optional** region after ``body``:

.. code-block:: python

    # --- hephaestus-store: interface ---
    tag(_root.faces().filter_by(GeomType.PLANE).sort_by(SortBy.AREA)[-1], "mount_face")

This is the whole of "mounting interfaces are tagged geometry". A fragment is
*pasted source*, so a ``tag()`` call inside one executes during the consumer's
build, lands in that build's ``TagRegistry`` and resolves through the same
``AnchorResolver`` every 8C constraint and Stage 9 joint already uses. No new
addressing machinery is required and none is added here — what is added is
permission to emit the tag and the discipline that makes the emitted name safe:

* **the region is emitted BELOW the placement tail**, with every whole-token
  occurrence of the renamed root rewritten to the *placed* instance name. The
  tail creates a moved copy (``{prefix} = Pos(...) * Rot(...) * {prefix}{root}``)
  and ``resolve_placements`` matches with the location-sensitive
  ``TopoDS_Shape.IsSame``, so a tag against the unplaced body local would name
  topology that is not in the consumer's compound at all — every interface of
  every instance placed away from the origin would be unaddressable. Rewriting
  only the chain root is the same bug at one remove, which is why the AST rule
  below refuses body locals in argument 1 outright;
* **the emitted literal is ``<instance>__<name>``**, so two pastes of the same
  component cannot silently overwrite each other's tags (§2.2); and
* **the region's grammar is an AST contract, not the word "nested"**. Every
  realistic selector *is* a chain of nested calls, so a rule refusing nested
  calls would refuse the mechanism's own canonical example and leave the region
  able to tag a bare solid and nothing else.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, cast

from hephaestus.core.errors import ValidationError
from opstore.types import JSONValue

from ._component import INTERFACE_NAME_RE
from ._errors import RegistryError, RegistryRefusal
from ._parts import StorePart

__all__ = [
    "BIND_MARKER",
    "BODY_MARKER",
    "INTERFACE_MARKER",
    "INTERFACE_TAG_INFIX",
    "PARAMS_MARKER",
    "GeneratorSource",
    "instance_name",
    "instance_prefix",
    "instance_prefix_for",
    "is_placed",
    "parse_generator",
    "render_fragment",
]

PARAMS_MARKER: Final[str] = "# --- hephaestus-store: params ---"
BIND_MARKER: Final[str] = "# --- hephaestus-store: bind ---"
BODY_MARKER: Final[str] = "# --- hephaestus-store: body ---"
#: ``PARTS_STORE.md`` §2.1's fourth region. Optional — a legacy store part has
#: none and behaves exactly as it did — but at most once and only after ``body``.
INTERFACE_MARKER: Final[str] = "# --- hephaestus-store: interface ---"

#: The infix that makes an emitted interface tag recognisable everywhere
#: downstream (§2.2). A declared interface name may not contain it, so
#: ``<instance>__<name>`` cannot be produced by any other route.
INTERFACE_TAG_INFIX: Final[str] = "__"

_FORBIDDEN_NAMES: Final[frozenset[str]] = frozenset({"hc", "tag", "check", "CHECKS"})

_PLACEMENT_KEYS: Final[tuple[str, ...]] = ("x", "y", "z", "rx", "ry", "rz")

#: An ``instance`` argument is a part ident, the same grammar ``_parts.py`` uses
#: for a store part id — because the value ends up inside an anchor selector a
#: model writes by hand.
_INSTANCE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: Expression nodes an interface selector may not contain, each decidable by a
#: parser (§2.1). Nothing here is a judgement call about what a selector "means":
#: a walrus assigns, a lambda/comprehension defers evaluation past the point the
#: rewrite can reason about, ``await`` has no meaning in a build script, a
#: starred expression hides the argument count, and an f-string manufactures a
#: name the static index could never have read.
_REFUSED_SELECTOR_NODES: Final[tuple[type[ast.AST], ...]] = (
    ast.NamedExpr,
    ast.Lambda,
    ast.Await,
    ast.Starred,
    ast.JoinedStr,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)

#: Which refusal a statement is reported *as* when it breaks several rules at
#: once. ``open("/etc/passwd").read()`` breaks two — ``open`` is not the root
#: name and ``open`` is not in the whitelist — and §2.1 says both fire; every
#: violated rule is listed in ``detail["reasons"]`` so a caller sees the whole
#: verdict rather than the first one found.
_REASON_PRECEDENCE: Final[tuple[str, ...]] = (
    "interface_region_violation",
    "interface_root_violation",
    "interface_body_local_reference",
)


@dataclass(frozen=True)
class GeneratorSource:
    """A parsed, contract-checked store generator.

    ``bound_names`` is every module-scope name the bind and body regions assign;
    ``root_name`` is the name the final ``part.geometry = <name>`` statement
    publishes, i.e. the instance root a fragment places.

    ``interface_region`` is §2.1's fourth region verbatim (empty when the
    generator declares none) and ``interface_names`` is the set of literal names
    it tags, extracted **statically** — ``_parts.py`` indexes and searches
    generators and never executes one, so the index has to learn which
    interfaces a part offers without running anything.
    """

    script: str
    params_region: str
    bind_region: str
    body_region: str
    param_names: tuple[str, ...]
    bound_names: tuple[str, ...] = field(default=())
    root_name: str = ""
    interface_region: str = ""
    interface_names: tuple[str, ...] = field(default=())


def _module_bound_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()

    def record(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Tuple | ast.List):
            for element in target.elts:
                record(element)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                record(target)
        elif isinstance(node, ast.AnnAssign | ast.AugAssign | ast.For):
            record(node.target)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    record(item.optional_vars)
    return names


def parse_generator(script: str, *, source: str = "generator.py") -> GeneratorSource:
    """Parse and contract-check a store generator (see the module docstring).

    Enforced, because instancing rewrites the body mechanically and must not
    guess: exactly one ``params``/``bind``/``body`` marker in that order; the
    params region declares only ``PARAMS``; the bind region is exactly one
    ``_<name> = p.<name>`` line per declared parameter; the body never touches
    ``p``, ``hc``, ``tag``, ``check`` or ``CHECKS``; every module-scope name the
    bind/body regions assign is underscore-prefixed; and the last body statement
    is ``part.geometry = <name>``.

    ``PARTS_STORE.md`` §2.1's ``interface`` region is optional and, when
    present, appears exactly once and after ``body``. It is the only region
    permitted to reference ``tag``; ``_FORBIDDEN_NAMES`` still applies unchanged
    to the body, so store generators remain pure geometry and simply now *name*
    parts of it.
    """
    for marker in (PARAMS_MARKER, BIND_MARKER, BODY_MARKER):
        if script.count(marker) != 1:
            raise ValidationError(
                f"{source}: expected exactly one {marker!r} marker", kind="contract"
            )
    if script.count(INTERFACE_MARKER) > 1:
        raise ValidationError(
            f"{source}: expected at most one {INTERFACE_MARKER!r} marker", kind="contract"
        )
    params_at = script.index(PARAMS_MARKER)
    bind_at = script.index(BIND_MARKER)
    body_at = script.index(BODY_MARKER)
    if not params_at < bind_at < body_at:
        raise ValidationError(
            f"{source}: markers must appear in params -> bind -> body order", kind="contract"
        )
    has_interface = INTERFACE_MARKER in script
    interface_at = script.index(INTERFACE_MARKER) if has_interface else len(script)
    if has_interface and interface_at < body_at:
        raise ValidationError(
            f"{source}: markers must appear in params -> bind -> body -> interface order",
            kind="contract",
        )
    params_region = script[params_at + len(PARAMS_MARKER) : bind_at].strip("\n")
    bind_region = script[bind_at + len(BIND_MARKER) : body_at].strip("\n")
    body_region = script[body_at + len(BODY_MARKER) : interface_at].strip("\n")
    interface_region = (
        script[interface_at + len(INTERFACE_MARKER) :].strip("\n") if has_interface else ""
    )

    try:
        params_tree = ast.parse(params_region)
        bind_tree = ast.parse(bind_region)
        body_tree = ast.parse(body_region)
        interface_tree = ast.parse(interface_region)
    except SyntaxError as exc:
        raise ValidationError(f"{source}: invalid Python: {exc}", kind="syntax") from exc

    param_names = _check_params_region(params_tree, source=source)
    _check_bind_region(bind_tree, param_names, source=source)
    _refuse_tag_outside_the_interface_region(params_tree, region="params", source=source)
    _refuse_tag_outside_the_interface_region(bind_tree, region="bind", source=source)
    bound = (_module_bound_names(bind_tree) | _module_bound_names(body_tree)) - {"part"}
    offending = sorted(name for name in bound if not name.startswith("_"))
    if offending:
        raise ValidationError(
            f"{source}: module-scope generator names must be underscore-prefixed; "
            f"got {', '.join(offending)}",
            kind="contract",
        )
    root_name = _check_body_region(body_tree, source=source)
    interface_names = _check_interface_region(
        interface_tree, root_name=root_name, bound=bound, source=source
    )
    return GeneratorSource(
        script=script,
        params_region=params_region,
        bind_region=bind_region,
        body_region=body_region,
        param_names=param_names,
        bound_names=tuple(sorted(bound)),
        root_name=root_name,
        interface_region=interface_region,
        interface_names=interface_names,
    )


def _refuse_tag_outside_the_interface_region(tree: ast.Module, *, region: str, source: str) -> None:
    """§2.1: the ``interface`` region is the ONLY region permitted to name ``tag``.

    The body already refuses it through ``_FORBIDDEN_NAMES``. The params and
    bind regions did not, and their own checkers skip every ``ast.Expr`` — the
    allowance that lets a region carry a docstring — so a bare ``tag(...)`` call
    in either of them sailed through the contract and then *executed*, since the
    whole generator runs as one script. That is an interface tag emitted from
    outside the region the record is compared against, i.e. exactly the
    undeclared-interface hazard item 11 exists to close, entering by a side
    door. Refused by name, which is decidable and costs nothing.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "tag":
            raise ValidationError(
                f"{source}: the {region} region must not reference 'tag'; the interface "
                "region is the only region permitted to (PARTS_STORE.md §2.1)",
                kind="contract",
            )


def _check_params_region(tree: ast.Module, *, source: str) -> tuple[str, ...]:
    statements = [node for node in tree.body if not isinstance(node, ast.Expr)]
    if len(statements) != 1 or not isinstance(statements[0], ast.Assign):
        raise ValidationError(
            f"{source}: the params region must contain exactly one PARAMS assignment",
            kind="contract",
        )
    assign = statements[0]
    targets = assign.targets
    if len(targets) != 1 or not isinstance(targets[0], ast.Name) or targets[0].id != "PARAMS":
        raise ValidationError(f"{source}: the params region must assign PARAMS", kind="contract")
    if not isinstance(assign.value, ast.Dict):
        raise ValidationError(f"{source}: PARAMS must be a dict literal", kind="contract")
    names: list[str] = []
    for key in assign.value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValidationError(f"{source}: PARAMS keys must be string literals", kind="contract")
        names.append(key.value)
    return tuple(names)


def _check_bind_region(tree: ast.Module, param_names: Sequence[str], *, source: str) -> None:
    seen: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr):
            continue
        bad = ValidationError(
            f"{source}: the bind region accepts only '_<name> = p.<name>' statements",
            kind="contract",
        )
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise bad
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Attribute):
            raise bad
        base = value.value
        if not isinstance(base, ast.Name) or base.id != "p":
            raise bad
        if target.id != f"_{value.attr}":
            raise ValidationError(
                f"{source}: bind '{target.id} = p.{value.attr}' must bind '_{value.attr}'",
                kind="contract",
            )
        seen.append(value.attr)
    if sorted(seen) != sorted(param_names):
        declared = ", ".join(param_names) or "(none)"
        bound = ", ".join(seen) or "(none)"
        raise ValidationError(
            f"{source}: the bind region must bind every declared parameter exactly once "
            f"(declared: {declared}; bound: {bound})",
            kind="contract",
        )


def _check_body_region(tree: ast.Module, *, source: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise ValidationError(
                f"{source}: the generator body must not reference {node.id!r} "
                "(store generators are pure geometry)",
                kind="contract",
            )
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id == "p":
                raise ValidationError(
                    f"{source}: the body reads p.{node.attr}; parameters reach the body "
                    "only through the bind region",
                    kind="contract",
                )
            if isinstance(base, ast.Name) and base.id == "part" and node.attr != "geometry":
                raise ValidationError(
                    f"{source}: the body must not set part.{node.attr}", kind="contract"
                )
    if not tree.body:
        raise ValidationError(f"{source}: the body region is empty", kind="contract")
    last = tree.body[-1]
    bad = ValidationError(
        f"{source}: the last body statement must be 'part.geometry = <name>'", kind="contract"
    )
    if not isinstance(last, ast.Assign) or len(last.targets) != 1:
        raise bad
    target = last.targets[0]
    if not isinstance(target, ast.Attribute) or target.attr != "geometry":
        raise bad
    base = target.value
    if not isinstance(base, ast.Name) or base.id != "part":
        raise bad
    if not isinstance(last.value, ast.Name):
        raise ValidationError(
            f"{source}: 'part.geometry' must be assigned a bare name (the instance root)",
            kind="contract",
        )
    return last.value.id


def _chain_root(node: ast.expr) -> ast.expr:
    """§2.1's chain root, computed the way the spec defines it.

    Repeatedly descend: from an ``ast.Attribute`` take ``.value``, from an
    ``ast.Subscript`` take ``.value``, from an ``ast.Call`` take ``.func``. Stop
    at the first node that is none of the three. So
    ``_root.faces().sort_by(SortBy.AREA)[-1]`` roots at the ``ast.Name``
    ``_root``, while ``Compound(children=[_root]).faces()[0]`` roots at the
    ``ast.Name`` ``Compound`` — a whitelisted callable rather than the name
    binding the body published, which is a refusal.
    """
    current = node
    while True:
        if isinstance(current, ast.Attribute | ast.Subscript):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        else:
            return current


def _check_interface_region(
    tree: ast.Module, *, root_name: str, bound: set[str], source: str
) -> tuple[str, ...]:
    """§2.1's AST contract, in full, and the static interface-name extraction.

    Mission rule 1 makes an ambiguity a defect closed by tightening, so the
    region's grammar is stated as an AST contract. Every rule below is decidable
    by a parser and none requires judgement — which matters twice: ``_parts.py``
    indexes generators without executing them, and a rule that needed the shape
    to exist could not refuse a hostile generator *before* publication.

    A statement is admissible iff it is an ``ast.Expr`` whose value is an
    ``ast.Call`` on ``ast.Name("tag")`` with exactly two positional arguments,
    no keywords; argument 2 is a single-line ``str`` constant matching the
    interface-name grammar and free of ``__``; and argument 1 is any expression
    whose chain root is ``root_name``, which contains none of
    :data:`_REFUSED_SELECTOR_NODES`, and every ``ast.Name`` of which loads
    either ``root_name`` or a member of ``SELECTOR_NAMES``.

    The last rule is the one with teeth, and its earlier draft had a hole: it
    admitted "a name in ``bound_names``". A body local such as ``_shaft_face``
    or ``_body_length`` names **pre-placement** geometry, or a coordinate in the
    pre-placement frame, and :func:`render_fragment`'s rewrite cannot retarget
    it — there is no placed counterpart to retarget it *to*. A selector mixing
    the placed root with an unplaced local measures one shape in the other's
    frame and resolves to a real face that is silently the wrong one, which is
    exactly the class of failure §2.2 exists to eliminate. So it is
    ``interface_body_local_reference``, and the authoring cost is the one §2.1
    already imposes: express the discriminator as a *measure* on the placed
    shape, not as a remembered local.
    """
    if not tree.body:
        return ()
    # Imported here, not at module scope: the derivation imports build123d, and
    # a registry with no interface region must not pay for it (namespace.py's
    # `_selector_names`). Importing a declared constant is not executing a
    # script — the property `_parts.py` preserves is the latter.
    from hephaestus.core.executor.namespace import SELECTOR_NAMES

    locals_other_than_root = bound - {root_name}
    names: list[str] = []
    for node in tree.body:
        name = _check_interface_statement(
            node,
            root_name=root_name,
            locals_other_than_root=locals_other_than_root,
            selector_names=SELECTOR_NAMES,
            source=source,
        )
        if name in names:
            raise RegistryRefusal(
                "interface_region_violation",
                f"{source}: the interface region tags {name!r} twice; an emitted "
                "'<instance>__<name>' tag must resolve to exactly one thing",
                detail={"reasons": ["interface_region_violation"], "interface": name},
            )
        names.append(name)
    return tuple(names)


def _refuse_region(source: str, reasons: Mapping[str, str], **detail: JSONValue) -> RegistryRefusal:
    """One refusal carrying *every* rule the statement broke, not just the first.

    ``tag(open("/etc/passwd").read(), "x")`` breaks two: ``open`` is not the
    generator's root name (``interface_root_violation``) and ``open`` is not in
    the selector whitelist — it is in ``DENIED_BUILTINS`` —
    (``interface_region_violation``). §2.1 says both fire, and a caller that
    could only ever see the first would have to re-run the parser to learn the
    rest.
    """
    ordered = [reason for reason in _REASON_PRECEDENCE if reason in reasons]
    primary = ordered[0]
    body = "; ".join(f"{reason}: {reasons[reason]}" for reason in ordered)
    return RegistryRefusal(
        primary,
        f"{source}: {body}",
        detail={"reasons": cast("list[JSONValue]", list(ordered)), **detail},
    )


def _check_interface_statement(
    node: ast.stmt,
    *,
    root_name: str,
    locals_other_than_root: set[str],
    selector_names: frozenset[str],
    source: str,
) -> str:
    """One interface-region statement against the §2.1 grammar; returns its name."""
    only = "interface_region_violation"
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        raise _refuse_region(
            source,
            {
                only: "every interface-region statement is a bare 'tag(<selector>, "
                f'"<name>")\' call; got {type(node).__name__} at line {node.lineno} '
                "(the region may not assign, and a tag call may not appear as a "
                "sub-expression)"
            },
            line=node.lineno,
        )
    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id != "tag":
        raise _refuse_region(
            source,
            {only: f"line {node.lineno} calls something other than the bare name 'tag'"},
            line=node.lineno,
        )
    if call.keywords or len(call.args) != 2:
        raise _refuse_region(
            source,
            {
                only: f"tag() at line {node.lineno} takes exactly two positional "
                f"arguments and no keywords; got {len(call.args)} positional and "
                f"{len(call.keywords)} keyword"
            },
            line=node.lineno,
        )
    selector, literal = call.args
    name = _interface_name(literal, source=source, line=node.lineno)
    _check_selector(
        selector,
        root_name=root_name,
        locals_other_than_root=locals_other_than_root,
        selector_names=selector_names,
        source=source,
        interface=name,
    )
    return name


def _interface_name(literal: ast.expr, *, source: str, line: int) -> str:
    """Argument 2: a ``str`` constant, on one line, matching the name grammar.

    Not a literal is a refusal rather than a deferred check because the index
    must know *statically* which interfaces a part offers — ``_parts.py``
    "indexes and searches them; it never executes anything", and that property
    is not being given up for a computed tag name.
    """
    only = "interface_region_violation"
    if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
        raise _refuse_region(
            source,
            {
                only: f"tag()'s second argument at line {line} must be a string "
                "literal; the index reads the declared interface names without "
                "executing the generator"
            },
            line=line,
        )
    if literal.end_lineno != literal.lineno:
        raise _refuse_region(
            source,
            {
                only: f"the interface name at line {line} is spelled across lines "
                "(implicit concatenation); write it as one literal"
            },
            line=line,
        )
    value = literal.value
    if not INTERFACE_NAME_RE.match(value) or INTERFACE_TAG_INFIX in value:
        raise _refuse_region(
            source,
            {
                only: f"interface name {value!r} at line {line} must match "
                f"{INTERFACE_NAME_RE.pattern} and contain no "
                f"{INTERFACE_TAG_INFIX!r} (the infix is reserved for the emitted "
                "'<instance>__<name>' form, §2.2)"
            },
            line=line,
        )
    return value


def _check_selector(
    selector: ast.expr,
    *,
    root_name: str,
    locals_other_than_root: set[str],
    selector_names: frozenset[str],
    source: str,
    interface: str,
) -> None:
    """Argument 1: rooted at the published shape, and free of unplaced references."""
    reasons: dict[str, str] = {}
    line = selector.lineno
    refused = [
        type(node).__name__
        for node in ast.walk(selector)
        if isinstance(node, _REFUSED_SELECTOR_NODES)
    ]
    if refused:
        reasons["interface_region_violation"] = (
            f"the selector for {interface!r} at line {line} contains "
            f"{', '.join(sorted(set(refused)))}, which §2.1 refuses"
        )
    root = _chain_root(selector)
    if not isinstance(root, ast.Name) or root.id != root_name:
        observed = root.id if isinstance(root, ast.Name) else type(root).__name__
        reasons["interface_root_violation"] = (
            f"the selector for {interface!r} at line {line} has chain root "
            f"{observed!r}; every interface selector is rooted at the generator's "
            f"published name {root_name!r} (an interface unreachable from "
            "part.geometry is unaddressable anyway)"
        )
    unknown: list[str] = []
    body_locals: list[str] = []
    for node in ast.walk(selector):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if node.id == root_name or node.id in selector_names:
            continue
        (body_locals if node.id in locals_other_than_root else unknown).append(node.id)
    if unknown:
        reasons["interface_region_violation"] = "; ".join(
            filter(
                None,
                [
                    reasons.get("interface_region_violation", ""),
                    f"the selector for {interface!r} at line {line} loads "
                    f"{', '.join(sorted(set(unknown)))}, which is neither {root_name!r} "
                    "nor part of the interface-selector whitelist (build123d's exports "
                    "plus math; the harness handles p/part/tag/hc/check/CHECKS/"
                    "import_step/approx are excluded by name)",
                ],
            )
        )
    if body_locals:
        reasons["interface_body_local_reference"] = (
            f"the selector for {interface!r} at line {line} loads the generator "
            f"local(s) {', '.join(sorted(set(body_locals)))}. The fragment rewrite "
            f"retargets {root_name!r} to the PLACED instance; a body or bind local "
            "still names pre-placement geometry, or a coordinate in the "
            "pre-placement frame, and has no placed counterpart to retarget to — so "
            "the selector would measure the placed shape in the unplaced frame and "
            "resolve to a real face that is the wrong one. Express the "
            "discriminator as a measure on the placed shape instead"
        )
    if reasons:
        raise _refuse_region(source, reasons, line=line, interface=interface)


def _literal(value: int | float) -> str:
    if isinstance(value, int):
        return repr(value)
    return repr(float(value))


def instance_prefix(part_id: str, params: Mapping[str, int | float], pos: object) -> str:
    """Deterministic, collision-resistant local-name prefix for one instance."""
    payload = json.dumps(
        {"id": part_id, "params": {k: params[k] for k in sorted(params)}, "pos": pos},
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    )
    suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]
    return f"_{part_id}_{suffix}"


def _placement(pos: Mapping[str, Any] | None) -> tuple[str, str]:
    """``(placement expression prefix, human description)`` for a ``pos`` dict."""
    if not pos:
        return "", "at the part origin"
    unknown = sorted(key for key in pos if key not in _PLACEMENT_KEYS)
    if unknown:
        raise RegistryError(
            "invalid_params",
            f"pos accepts only {', '.join(_PLACEMENT_KEYS)}; got {', '.join(unknown)}",
        )
    values: dict[str, float] = {}
    for key in _PLACEMENT_KEYS:
        raw = pos.get(key, 0.0)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise RegistryError("invalid_params", f"pos[{key!r}] must be a number")
        if not math.isfinite(float(raw)):
            raise RegistryError("invalid_params", f"pos[{key!r}] must be finite")
        values[key] = float(raw)
    factors: list[str] = []
    if any(values[key] for key in ("x", "y", "z")):
        factors.append(
            f"Pos({_literal(values['x'])}, {_literal(values['y'])}, {_literal(values['z'])})"
        )
    if any(values[key] for key in ("rx", "ry", "rz")):
        factors.append(
            f"Rot({_literal(values['rx'])}, {_literal(values['ry'])}, {_literal(values['rz'])})"
        )
    if not factors:
        return "", "at the part origin"
    expression = " * ".join(factors) + " * "
    description = (
        f"at ({values['x']:g}, {values['y']:g}, {values['z']:g}) mm"
        f", rotated ({values['rx']:g}, {values['ry']:g}, {values['rz']:g})deg"
    )
    return expression, description


def instance_prefix_for(
    part_id: str,
    effective: Mapping[str, int | float],
    pos: Mapping[str, Any] | None,
    instance: str | None = None,
) -> str:
    """The per-instance rename prefix: the caller's ``instance``, or the hash.

    ``instance`` scopes the **whole** rename pass, not only the emitted tag
    literal, and that is what makes it the escape hatch §2.2 says it is. Two
    instances with identical ``(id, params, pos)`` hash to the same
    :func:`instance_prefix` and are therefore the same instance *by
    construction* — pasting one twice rebinds every local, so the earlier
    paste's tags end up on a shape the consumer never composes and the build
    fails. Scoping only the literal would leave the escape hatch unable to
    escape anything: the two pastes would still collide on their locals.

    Absent, the prefix is exactly what it has always been, so a legacy part's
    fragment is byte-identical to what it was before this stage.
    """
    if instance is None:
        return instance_prefix(part_id, effective, dict(pos) if pos else None)
    if not _INSTANCE_RE.match(instance):
        raise RegistryError(
            "invalid_instance_name",
            f"instance {instance!r} must match {_INSTANCE_RE.pattern}; the value is "
            "spelled into an anchor selector a model writes by hand",
            data={"instance": instance, "pattern": _INSTANCE_RE.pattern},
        )
    return f"_{instance}"


def instance_name(
    part_id: str,
    effective: Mapping[str, int | float],
    pos: Mapping[str, Any] | None,
    instance: str | None,
) -> str:
    """The ``<instance>`` half of an emitted ``<instance>__<name>`` tag (§2.2)."""
    return instance_prefix_for(part_id, effective, pos, instance)[1:]


def _rewrite_tag_literals(region: str, instance: str) -> str:
    """Rewrite each ``tag(..., "<name>")`` literal to ``"<instance>__<name>"``.

    Spliced by the constant's own ``(lineno, col_offset)`` rather than by a text
    substitution, so a name that also appears in a comment, or one that is a
    prefix of another declared name, cannot be caught by accident. The region
    has already passed :func:`_check_interface_region`, so every statement is a
    two-argument ``tag`` call whose second argument is a single-line ``str``
    constant.
    """
    lines = region.splitlines()
    edits: dict[int, list[tuple[int, int, str]]] = {}
    for node in ast.parse(region).body:
        assert isinstance(node, ast.Expr)
        call = node.value
        assert isinstance(call, ast.Call)
        literal = call.args[1]
        assert isinstance(literal, ast.Constant)
        name = cast("str", literal.value)
        assert literal.end_col_offset is not None
        edits.setdefault(literal.lineno, []).append(
            (literal.col_offset, literal.end_col_offset, f'"{instance}{INTERFACE_TAG_INFIX}{name}"')
        )
    out: list[str] = []
    for number, line in enumerate(lines, start=1):
        raw = line.encode("utf-8")
        for start, end, replacement in sorted(edits.get(number, ()), reverse=True):
            raw = raw[:start] + replacement.encode("utf-8") + raw[end:]
        out.append(raw.decode("utf-8"))
    return "\n".join(out)


def is_placed(pos: Mapping[str, Any] | None) -> bool:
    """Whether an instance carries a non-empty placement expression (§2.3).

    The gate on the placement-verification build, exported rather than
    re-derived by the caller so there is exactly one answer to "does ``{prefix}``
    alias the root?" — the condition under which the first build's tag
    placements are already the caller's.
    """
    expression, _described = _placement(pos)
    return bool(expression)


def render_fragment(
    generator: GeneratorSource,
    part: StorePart,
    effective: Mapping[str, int | float],
    pos: Mapping[str, Any] | None,
    instance: str | None = None,
) -> str:
    """Render the placed ``script_fragment`` for one generator instance.

    The fragment is the generator's own body verbatim, with (a) the bind region
    replaced by literal effective values, (b) every module-scope name renamed
    under a per-instance prefix so pasting two instances into one script cannot
    collide, and (c) the trailing ``part.geometry = <root>`` statement replaced
    by a placement binding the model composes into its own ``part.geometry``.

    §2.1's ``interface`` region is emitted **below** that placement statement,
    with (d) every whole-token occurrence of the renamed root rewritten to the
    placed instance name and (e) each tag literal rewritten to
    ``<instance>__<name>``. All three of "below the tail", "*every* root
    occurrence" and "the literal too" are load-bearing: rewriting only the
    literal leaves the selector measuring the unplaced body local, which made an
    earlier draft of §2 inoperative for any instance not at the origin;
    rewriting only the chain root is the same bug at one remove. When ``pos`` is
    empty ``_placement`` returns ``""`` and ``{prefix}`` is an alias of the root
    — the same shape object — so the origin case is unaffected.
    """
    prefix = instance_prefix_for(part.id, effective, pos, instance)
    placement, described = _placement(pos)
    scope = prefix[1:]
    rename = {name: f"{prefix}{name}" for name in generator.bound_names}

    def apply(text: str) -> str:
        out = text
        for old in sorted(rename, key=len, reverse=True):
            out = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", rename[old], out)
        return out

    binds = "\n".join(
        f"{rename['_' + name]} = {_literal(effective[name])}" for name in generator.param_names
    )
    body_lines = apply(generator.body_region).splitlines()
    # Drop the generator's own publication statement; a fragment is an instance,
    # not a part.
    root = rename[generator.root_name]
    kept = [line for line in body_lines if not line.strip().startswith("part.geometry")]
    header = [
        f"# {part.name} — parts-store instance {described}.",
        f"# registry: {part.registry} @ {part.digest}   id: {part.id}",
        "# Reference geometry from a pinned registry: review it, then compose",
        f"#   {prefix} into part.geometry (e.g. Compound(children=[..., {prefix}])).",
    ]
    tail = [
        f"{prefix} = {placement}{root}",
        f'{prefix}.label = "{part.id}"',
    ]
    interface: list[str] = []
    if generator.interface_region:
        placed = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(root)}(?![A-Za-z0-9_])",
            prefix,
            apply(generator.interface_region),
        )
        interface = _rewrite_tag_literals(placed, scope).splitlines()
    if binds:
        return "\n".join([*header, "", binds, *kept, *tail, *interface, ""])
    return "\n".join([*header, "", *kept, *tail, *interface, ""])
