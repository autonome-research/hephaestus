"""Top-level statement splitting with exact source spans (architecture §3.1).

A part script executes statement by statement; :func:`split_statements`
parses the module once and yields one :class:`Statement` per top-level
statement, carrying the exact source span (1-based lines, 0-based columns)
and the verbatim source slice. Syntax errors propagate as ``SyntaxError`` —
the worker converts them into the §8 error record.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from types import CodeType

#: Filename used when compiling part scripts (traceback frame matching).
PART_FILENAME = "<hephaestus-part>"

#: Filename used when compiling globals.py (traceback frame matching).
GLOBALS_FILENAME = "<hephaestus-globals>"


@dataclass(frozen=True)
class Statement:
    """One top-level statement: index, exact span, and verbatim source text."""

    index: int
    text: str
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int

    @property
    def span(self) -> tuple[int, int, int, int]:
        """``(lineno, col_offset, end_lineno, end_col_offset)``."""
        return (self.lineno, self.col_offset, self.end_lineno, self.end_col_offset)


def parse_module(source: str, *, filename: str = PART_FILENAME) -> ast.Module:
    """Parse ``source`` into an ``ast.Module``; raises ``SyntaxError`` as-is."""
    return ast.parse(source, filename=filename, mode="exec")


def _slice_span(
    lines: list[str], lineno: int, col_offset: int, end_lineno: int, end_col_offset: int
) -> str:
    if lineno == end_lineno:
        return lines[lineno - 1][col_offset:end_col_offset]
    parts = [lines[lineno - 1][col_offset:]]
    parts.extend(lines[i] for i in range(lineno, end_lineno - 1))
    parts.append(lines[end_lineno - 1][:end_col_offset])
    return "\n".join(parts)


def split_statements(source: str, *, filename: str = PART_FILENAME) -> tuple[Statement, ...]:
    """Split ``source`` into top-level statements with exact spans.

    Statements are returned in execution order with contiguous indices from
    0. The ``text`` of each statement is the verbatim source slice of its
    span (decorators included for decorated definitions).
    """
    module = parse_module(source, filename=filename)
    lines = source.splitlines()
    out: list[Statement] = []
    for index, node in enumerate(module.body):
        lineno = node.lineno
        col_offset = node.col_offset
        # Decorated definitions span from the first decorator line.
        decorators: list[ast.expr] = getattr(node, "decorator_list", [])
        if decorators:
            lineno = min(lineno, decorators[0].lineno)
            col_offset = 0
        end_lineno = node.end_lineno if node.end_lineno is not None else lineno
        end_col_offset = node.end_col_offset if node.end_col_offset is not None else 0
        out.append(
            Statement(
                index=index,
                text=_slice_span(lines, lineno, col_offset, end_lineno, end_col_offset),
                lineno=lineno,
                col_offset=col_offset,
                end_lineno=end_lineno,
                end_col_offset=end_col_offset,
            )
        )
    return tuple(out)


def compile_statement(node: ast.stmt, *, filename: str = PART_FILENAME) -> CodeType:
    """Compile one already-parsed top-level statement, preserving line numbers."""
    single = ast.Module(body=[node], type_ignores=[])
    return compile(single, filename=filename, mode="exec")


def frame_lines(source: str, failing_line: int, *, context: int = 2) -> tuple[str, ...]:
    """§8 ``error.frame``: ±``context`` lines with a ``"> "`` marker.

    Format per the contract example: ``"44 | text"``, empty lines render as
    ``"44 |"``, and the failing line is prefixed ``"> "``.
    """
    lines = source.splitlines()
    lo = max(1, failing_line - context)
    hi = min(len(lines), failing_line + context)
    out: list[str] = []
    for n in range(lo, hi + 1):
        text = lines[n - 1]
        marker = "> " if n == failing_line else ""
        out.append(f"{marker}{n} | {text}".rstrip())
    return tuple(out)
