"""Statement splitting: exact spans, verbatim text, frame rendering."""

from __future__ import annotations

import pytest
from hephaestus.core.executor.splitter import (
    frame_lines,
    split_statements,
)

SOURCE = """\
_t = 6.0
base = Box(10, 10, _t)

result = (
    base
    - Box(2, 2, _t)
)
part.geometry = result
"""


class TestSplit:
    def test_indices_and_order(self) -> None:
        statements = split_statements(SOURCE)
        assert [s.index for s in statements] == [0, 1, 2, 3]

    def test_exact_spans(self) -> None:
        statements = split_statements(SOURCE)
        assert statements[0].span == (1, 0, 1, 8)
        assert statements[1].lineno == 2
        multiline = statements[2]
        assert multiline.lineno == 4
        assert multiline.end_lineno == 7

    def test_verbatim_text(self) -> None:
        statements = split_statements(SOURCE)
        assert statements[0].text == "_t = 6.0"
        assert statements[2].text == "result = (\n    base\n    - Box(2, 2, _t)\n)"
        assert statements[3].text == "part.geometry = result"

    def test_empty_source(self) -> None:
        assert split_statements("") == ()

    def test_syntax_error_propagates(self) -> None:
        with pytest.raises(SyntaxError):
            split_statements("def broken(:\n    pass")

    def test_decorated_definition_spans_decorator(self) -> None:
        source = "@property\ndef f(self):\n    return 1\n"
        statements = split_statements(source)
        assert statements[0].lineno == 1
        assert statements[0].text.startswith("@property")


class TestFrameLines:
    def test_contract_example_format(self) -> None:
        source = "a = 1\n\nb = fail()\nc = 3\nd = 4\n"
        frame = frame_lines(source, 3)
        assert frame == (
            "1 | a = 1",
            "2 |",
            "> 3 | b = fail()",
            "4 | c = 3",
            "5 | d = 4",
        )

    def test_clipped_at_file_start(self) -> None:
        frame = frame_lines("x = boom()\ny = 2\n", 1)
        assert frame[0].startswith("> 1 | ")
        assert len(frame) == 2

    def test_clipped_at_file_end(self) -> None:
        frame = frame_lines("a = 1\nb = 2\nc = boom()\n", 3)
        assert frame[-1].startswith("> 3 | ")
