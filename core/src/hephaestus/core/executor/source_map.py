"""Source maps: provenance at the three §3.1 scopes.

1. **Bindings** — for every name bound to a shape (or a list of shapes), the
   creating statement and every rebinding, including bindings inside loops
   and function bodies, recorded per iteration with the call site.
2. **Boolean results** — a shape produced by ``+ - &`` attributes to the
   boolean *statement* with references to the operand names' provenance.
   Result faces are never attributed to operand statements (no per-face
   promise for untagged topology).
3. **Tags** — name -> (solid, topology index, tagging statement), supplied by
   :mod:`hephaestus.core.executor.tags`.

The binding recorder is a ``sys.settrace`` hook active only for frames whose
code was compiled from the script file: on each line-boundary event it
flushes the just-completed line's statically known assignment targets,
recording an event when the bound value satisfies the caller's shape
predicate. Loop iterations hit their line repeatedly, yielding one event per
iteration; function-body bindings carry the caller's line as ``call_site``.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import CodeType, FrameType
from typing import Any, Literal

from hephaestus.core.executor.tags import TagPlacement
from opstore.types import JSONValue

_BOOL_OPS: dict[type[ast.operator], str] = {ast.Add: "+", ast.Sub: "-", ast.BitAnd: "&"}


@dataclass(frozen=True)
class BindingEvent:
    """One recorded (re)binding of a name."""

    line: int
    statement_index: int
    iteration: int
    call_site: int | None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "line": self.line,
            "statement": self.statement_index,
            "iteration": self.iteration,
            "call_site": self.call_site,
        }


@dataclass(frozen=True)
class BooleanAttribution:
    """One ``+ - &`` result attributed to its statement (never per-face)."""

    target: str
    op: str
    operands: tuple[str, ...]
    line: int
    statement_index: int

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "target": self.target,
            "op": self.op,
            "operands": list(self.operands),
            "line": self.line,
            "statement": self.statement_index,
        }


def _target_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Tuple | ast.List):
        out: list[str] = []
        for element in target.elts:
            out.extend(_target_names(element))
        return tuple(out)
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return ()


def assigns_by_line(module: ast.Module) -> dict[int, tuple[str, ...]]:
    """Static map: line number -> names that line binds (loops/functions included)."""
    out: dict[int, list[str]] = {}

    def add(line: int, names: tuple[str, ...]) -> None:
        if names:
            out.setdefault(line, []).extend(n for n in names if n not in out.get(line, ()))

    for node in ast.walk(module):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                add(node.lineno, _target_names(target))
        elif isinstance(node, ast.AugAssign | ast.AnnAssign | ast.For):
            add(node.lineno, _target_names(node.target))
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars is not None:
                    add(node.lineno, _target_names(item.optional_vars))
        elif isinstance(node, ast.NamedExpr):
            add(node.lineno, (node.target.id,))
    return {line: tuple(names) for line, names in out.items()}


def boolean_attributions(module: ast.Module) -> tuple[BooleanAttribution, ...]:
    """Statically attribute ``+ - &`` assignment results to their statements.

    A boolean inside a loop or function body attributes to the enclosing
    top-level statement (statement-level, never per-face).
    """
    out: list[BooleanAttribution] = []
    for stmt_index, top in enumerate(module.body):
        for node in ast.walk(top):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if not isinstance(value, ast.BinOp):
                continue
            op = _BOOL_OPS.get(type(value.op))
            if op is None:
                continue
            operands = tuple(
                sub.id
                for sub in ast.walk(value)
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load)
            )
            for target in node.targets:
                for name in _target_names(target):
                    out.append(
                        BooleanAttribution(
                            target=name,
                            op=op,
                            operands=operands,
                            line=node.lineno,
                            statement_index=stmt_index,
                        )
                    )
    return tuple(out)


class SourceMapRecorder:
    """Trace-based per-iteration binding recorder (scope 1 of §3.1).

    Install via :meth:`trace` as the ``sys.settrace`` function around each
    top-level statement's execution (:meth:`run`); events accumulate in
    :attr:`bindings` keyed by name in first-binding order.
    """

    def __init__(
        self,
        filename: str,
        assigns: Mapping[int, tuple[str, ...]],
        is_shape: Callable[[object], bool],
    ) -> None:
        self._filename = filename
        self._assigns = dict(assigns)
        self._is_shape = is_shape
        self._statement_index = -1
        self._iterations: dict[tuple[int, int, str], int] = {}
        self._pending: dict[int, tuple[int, FrameType]] = {}
        self.bindings: dict[str, list[BindingEvent]] = {}

    def start_statement(self, index: int) -> None:
        self._statement_index = index
        self._pending.clear()

    def _flush(self, frame: FrameType, *, record: bool) -> None:
        pending = self._pending.pop(id(frame), None)
        if pending is None or not record:
            return
        line, pending_frame = pending
        names = self._assigns.get(line)
        if not names:
            return
        for name in names:
            try:
                value = pending_frame.f_locals[name]
            except KeyError:
                continue
            if not self._is_shape(value):
                continue
            key = (self._statement_index, line, name)
            iteration = self._iterations.get(key, 0) + 1
            self._iterations[key] = iteration
            call_site: int | None = None
            back = pending_frame.f_back
            if (
                pending_frame.f_code.co_name != "<module>"
                and back is not None
                and back.f_code.co_filename == self._filename
            ):
                call_site = back.f_lineno
            self.bindings.setdefault(name, []).append(
                BindingEvent(
                    line=line,
                    statement_index=self._statement_index,
                    iteration=iteration,
                    call_site=call_site,
                )
            )

    def trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        del arg
        if frame.f_code.co_filename != self._filename:
            return None
        if event == "call":
            return self.trace
        if event == "line":
            self._flush(frame, record=True)
            self._pending[id(frame)] = (frame.f_lineno, frame)
        elif event == "return":
            self._flush(frame, record=True)
        elif event == "exception":
            # The pending line raised; its assignment did not complete.
            self._flush(frame, record=False)
        return self.trace

    def run(self, code: CodeType, globals_dict: dict[str, object]) -> None:
        """Execute one compiled statement under this recorder's trace hook."""
        previous = sys.gettrace()
        sys.settrace(self.trace)
        try:
            exec(code, globals_dict)
        finally:
            sys.settrace(previous)

    def bindings_json(self) -> dict[str, JSONValue]:
        return {
            name: [event.to_json() for event in events] for name, events in self.bindings.items()
        }


def assemble(
    recorder: SourceMapRecorder,
    booleans: tuple[BooleanAttribution, ...],
    tag_placements: Mapping[str, TagPlacement],
) -> dict[str, JSONValue]:
    """Serialize the three-scope source map (stored alongside the build artifact)."""
    return {
        "version": 1,
        "bindings": recorder.bindings_json(),
        "booleans": [entry.to_json() for entry in booleans],
        "tags": {name: tag_placements[name].to_json() for name in sorted(tag_placements)},
    }


SourceMapScope = Literal["bindings", "booleans", "tags"]
