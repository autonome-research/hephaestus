# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""G14C clauses 3-4: the §5.2 round-trip and THE parser's identity.

The emitter and the parser are the in-memory 14C machinery the dated
amendment decision landed (mission_plan.md Stage 14, "the round-trip landing
decision"): pure functions, fixture post records, fault-injected emitters —
no disk write, no CLI verb, no program text in any tool result. The two fault
emitters are the clause's own: one that drops a block, and one that swaps
I/J for R (whose loss on a MAJOR arc is exactly the classic post bug class
§5.2 exists to catch — R names two centres and the parser resolves the minor
one).
"""

from __future__ import annotations

import math
from typing import Any

from _g14c import check_kwargs
from hephaestus.core import cam_check, cam_text
from hephaestus.core.cam_check import check_setup
from hephaestus.core.cam_text import (
    CamPost,
    emit_program,
    motion_signature,
    parse_program,
    round_trip,
)
from hephaestus.geom.toolpath import Move, MoveList

POST = CamPost(id="post-fixture")

MOVES = MoveList(
    moves=(
        Move(kind="rapid", x=0.0, y=0.0, z=5.0),
        Move(kind="linear", x=0.0, y=0.0, z=-1.0, feed_mm_min=120.0),
        Move(kind="linear", x=10.0, y=0.0, z=-1.0, feed_mm_min=300.0),
        Move(kind="linear", x=10.0, y=8.0, z=-1.0, feed_mm_min=300.0),
        Move(kind="rapid", x=10.0, y=8.0, z=5.0),
    )
)

#: A MAJOR arc (sweep > 180 deg): start (0,0), end (1,0), centre (0.5, 2) —
#: i=0.5, j=2, R = sqrt(0.25 + 4). The R form names the radius only, and the
#: parser resolves R to the MINOR-arc centre (0.5, -2) by the G-code
#: convention, so the round-tripped centre flips sign: the divergence is the
#: fixture, hand-computable.
ARC_MOVES = MoveList(
    moves=(
        Move(kind="rapid", x=0.0, y=0.0, z=0.0),
        Move(kind="arc_cw", x=1.0, y=0.0, z=0.0, feed_mm_min=200.0, i=0.5, j=2.0),
    )
)


# -- clause 3: identical on the reference setup, diverged under two faults --


def test_round_trip_identical_on_the_reference_setup(ref: tuple[Any, Any]) -> None:
    layout, store = ref
    status = check_setup(layout, store, "s-op1", **check_kwargs(), simulate=False)
    assert status.round_trip is not None
    report = status.round_trip.to_json()
    assert report["verdict"] == "round_trip_identical"
    assert report["first_divergence"] is None
    assert report["moves"] == report["parsed_moves"] > 0


def test_a_dropped_block_diverges_naming_the_first_divergent_move() -> None:
    def dropping_emitter(moves: MoveList, post: CamPost) -> bytes:
        lines = emit_program(moves, post).decode("ascii").splitlines()
        # Drop the third motion block (index 3: comment line + two blocks kept).
        del lines[3]
        return ("\n".join(lines) + "\n").encode("ascii")

    report = round_trip(MOVES, POST, emitter=dropping_emitter)
    assert report.verdict == "round_trip_diverged"
    assert report.parsed_moves == report.moves - 1
    divergence = report.to_json()["first_divergence"]
    # The first divergent move, named ON BOTH SIDES (§5.2).
    assert divergence["index"] == 2
    assert divergence["internal"] == list(motion_signature(MOVES.moves[2]))
    # What parsed back is the NEXT block's endpoint — and, because the dropped
    # block also carried the modal F word, at the stale modal feed: exactly
    # the "modal feed that never got cancelled" §5.2 names as a real post bug
    # class, caught here as a named divergence rather than shipped.
    parsed = divergence["parsed"]
    assert parsed[:4] == list(motion_signature(MOVES.moves[3]))[:4]
    assert parsed[4] == 120.0


def test_ij_swapped_for_r_diverges_on_a_major_arc() -> None:
    r_post = CamPost(id="post-r", arc_form="r")
    identical = round_trip(ARC_MOVES, POST)
    assert identical.verdict == "round_trip_identical", "the I/J form is lossless"

    report = round_trip(ARC_MOVES, r_post, emitter=emit_program)
    assert report.verdict == "round_trip_diverged"
    divergence = report.to_json()["first_divergence"]
    assert divergence["index"] == 1
    internal = divergence["internal"]
    parsed = divergence["parsed"]
    # Same endpoint, DIFFERENT centre: the minor-arc centre the R word names.
    assert internal[:4] == parsed[:4]
    assert internal[5:7] == [0.5, 2.0]
    assert parsed[5] == internal[5]
    assert math.isclose(parsed[6], -2.0, abs_tol=1e-6)


# -- clause 4: THE parser, by identity --------------------------------------


def test_the_round_trip_parser_and_the_simulators_parser_are_the_same_object() -> None:
    """``is``, not two passing tests (CAM.md §5.2, §11 item 32): one parser,
    one implementation, no drift between what the round-trip verified and
    what the simulator would consume."""
    assert cam_check.PARSER is cam_text.parse_program
    assert cam_check.PARSER is parse_program


def test_the_emitted_text_parses_with_that_one_parser() -> None:
    parsed = cam_check.PARSER(emit_program(MOVES, POST))
    assert [motion_signature(m) for m in parsed.moves] == [
        motion_signature(m) for m in MOVES.moves
    ]
