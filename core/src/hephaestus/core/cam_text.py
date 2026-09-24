# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""In-memory program text: the single declarative emitter and THE parser.

CAM.md §11 items 31–32, landed **at 14C as in-memory machinery** by the dated
2026-09-02 amendment decision (mission_plan.md Stage 14, "the round-trip
landing decision"): pure functions from a :class:`~hephaestus.geom.toolpath.MoveList`
plus a post record to program bytes and back, exercised against fixture post
records. **Nothing here writes a file, opens a path, or reaches a tool
result** — the D2 mandate bans a runnable program *reaching the filesystem*,
not program bytes in memory, and Gate G14B clause 24's filesystem assertion
extends over these paths.

Two hard rules from CAM.md §5.2 shape this module:

* **One emitter.** The dialect lives in the :class:`CamPost` record as data
  (word spellings, decimals, the arc-centre form), never as a per-post code
  path — a single emitter is a testable emitter, and a round-trip against a
  per-post branch proves much less.
* **One parser.** :func:`parse_program` is the round-trip parser AND the
  simulator's parser — Gate G14C clause 4 asserts the identity (``is``, not
  two passing tests), so the text the round-trip verifies is the text the
  simulation would consume, with no second implementation to drift.

The round-trip compares **motion signatures** (kind, endpoint, arc centre,
feed — every field the program text can carry). ``op_id`` and ``feed_source``
are engine provenance that no G-code dialect transports; the record says which
projection was compared rather than quietly widening or narrowing the claim.

The ``arc_form: "r"`` dialect exists because Gate G14C clause 3 needs the
classic I/J-versus-R post bug as a *fixture*: R is ambiguous — a radius names
two centres, and the parser resolves it to the minor arc by the G-code
convention — so a major arc emitted as R round-trips to a DIFFERENT centre,
and the divergence is named move by move instead of shipped.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

# isort: off — ``hephaestus.geom`` must initialize before ``core.cutfile``:
# cutfile reaches ``dfm.types`` whose package pulls ``geom.topology``, and a
# cold interpreter that enters through cutfile first would meet its own
# partially-initialized module coming back around. Loading the geom package
# first (which every other entry point does implicitly) breaks the cycle.
from hephaestus.geom.toolpath import Move, MoveKind, MoveList
from hephaestus.core.cutfile import COORD_DECIMALS

# isort: on
from opstore.types import JSONValue

__all__ = [
    "ROUND_TRIP_VERDICTS",
    "CamPost",
    "Emitter",
    "RoundTripReport",
    "emit_program",
    "motion_signature",
    "parse_program",
    "round_trip",
]

#: The §1.1 closed round-trip vocabulary. Exactly two verdicts; no third.
ROUND_TRIP_VERDICTS: Final[tuple[str, ...]] = ("round_trip_identical", "round_trip_diverged")

#: An emitter: moves + post -> program bytes. :func:`emit_program` is the one
#: shipped implementation; the type exists so Gate G14C clause 3 can inject
#: its two fault emitters (a dropped block; I/J-for-R) at this seam.
Emitter = Callable[[MoveList, "CamPost"], bytes]


@dataclass(frozen=True)
class CamPost:
    """One post record, as data — a dialect table, not a code path (CAM.md §7).

    A 14C **fixture** shape: the ``posts`` registry kind, its digest machinery
    and its mandatory ``simplifications`` stay 14D (§11 item 30). What lives
    here is exactly what the in-memory emitter and the round-trip need.
    """

    id: str
    decimals: int = COORD_DECIMALS
    arc_form: Literal["ij", "r"] = "ij"
    rapid_word: str = "G0"
    linear_word: str = "G1"

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "decimals": self.decimals,
            "arc_form": self.arc_form,
            "rapid_word": self.rapid_word,
            "linear_word": self.linear_word,
        }


def _num(value: float, decimals: int) -> str:
    text = f"{round(value, decimals):.{decimals}f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def _arc_words(move: Move, post: CamPost) -> list[str]:
    if move.i is None or move.j is None:
        raise ValueError(f"arc move to ({move.x}, {move.y}) carries no i/j centre offsets")
    if post.arc_form == "ij":
        return [f"I{_num(move.i, post.decimals)}", f"J{_num(move.j, post.decimals)}"]
    # The R form: the radius from the true centre. Deliberately lossy for a
    # major arc — that loss IS the G14C-3 fixture (module docstring).
    radius = math.hypot(move.i, move.j)
    return [f"R{_num(radius, post.decimals)}"]


def emit_program(moves: MoveList, post: CamPost) -> bytes:
    """The single declarative emitter: one block per move, in order, in memory.

    Modal feed: ``F`` is emitted only when the cutting feed changes, which is
    exactly the modality the parser tracks — a modal feed that never got
    cancelled is a §5.2 named post bug class, and the shared parser is what
    catches it.
    """
    lines: list[str] = [f"({post.id})"]
    position = (0.0, 0.0, 0.0)
    modal_feed: float | None = None
    for move in moves.moves:
        words: list[str]
        if move.kind == "rapid":
            words = [post.rapid_word]
        elif move.kind == "linear":
            words = [post.linear_word]
        elif move.kind == "arc_cw":
            words = ["G2"]
        elif move.kind == "arc_ccw":
            words = ["G3"]
        elif move.kind == "dwell":
            lines.append("G4 P0")
            continue
        elif move.kind == "tool_change":
            lines.append("M6")
            continue
        elif move.kind == "spindle":
            lines.append("M3")
            continue
        else:  # coolant — the vocabulary is closed (CAM.md §4.2)
            lines.append("M8")
            continue
        words.append(f"X{_num(move.x, post.decimals)}")
        words.append(f"Y{_num(move.y, post.decimals)}")
        words.append(f"Z{_num(move.z, post.decimals)}")
        if move.kind in ("arc_cw", "arc_ccw"):
            words.extend(_arc_words(move, post))
        if move.kind != "rapid" and move.feed_mm_min is not None:
            feed = round(move.feed_mm_min, post.decimals)
            if feed != modal_feed:
                words.append(f"F{_num(move.feed_mm_min, post.decimals)}")
                modal_feed = feed
        lines.append(" ".join(words))
        position = (move.x, move.y, move.z)
    return ("\n".join(lines) + "\n").encode("ascii")


_WORD_KINDS: Final[dict[str, MoveKind]] = {
    "G0": "rapid",
    "G00": "rapid",
    "G1": "linear",
    "G01": "linear",
    "G2": "arc_cw",
    "G02": "arc_cw",
    "G3": "arc_ccw",
    "G03": "arc_ccw",
}

_STATE_KINDS: Final[dict[str, MoveKind]] = {
    "G4": "dwell",
    "G04": "dwell",
    "M6": "tool_change",
    "M06": "tool_change",
    "M3": "spindle",
    "M03": "spindle",
    "M8": "coolant",
    "M08": "coolant",
}


def _r_centre(
    start: tuple[float, float], end: tuple[float, float], radius: float, *, clockwise: bool
) -> tuple[float, float]:
    """The centre the R word names: the minor arc, by the G-code convention.

    Of the two candidate centres, positive R selects the one giving a sweep of
    at most 180 degrees. This is exactly where a major arc emitted as R comes
    back different — the ambiguity is the fixture, not a bug here.
    """
    mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
    dx, dy = end[0] - start[0], end[1] - start[1]
    chord = math.hypot(dx, dy)
    if chord == 0.0 or chord > 2.0 * radius + 1e-9:
        raise ValueError(f"R{radius:g} cannot span a {chord:g} mm chord")
    half = math.sqrt(max(0.0, radius * radius - (chord / 2.0) ** 2))
    # Unit normal to the chord; the minor-arc centre sits on the side that
    # makes the sweep <= 180 deg for the commanded direction.
    nx, ny = -dy / chord, dx / chord
    sign = -1.0 if clockwise else 1.0
    return (mx + sign * half * nx, my + sign * half * ny)


def parse_program(text: bytes | str) -> MoveList:
    """THE parser: program text back to a :class:`MoveList` (CAM.md §5.2).

    The round-trip's parser and the simulator's parser by identity — Gate
    G14C clause 4. Tracks position (for R-form arc centres) and the modal
    feed; comments in parentheses are skipped. Engine provenance the text
    cannot carry (``op_id``, ``feed_source``) comes back ``None``, which is
    why the round-trip compares :func:`motion_signature` projections.
    """
    raw = text.decode("ascii") if isinstance(text, bytes) else text
    moves: list[Move] = []
    position = (0.0, 0.0, 0.0)
    modal_feed: float | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("("):
            continue
        words = stripped.split()
        command = words[0].upper()
        state_kind = _STATE_KINDS.get(command)
        if state_kind is not None:
            moves.append(Move(kind=state_kind, x=position[0], y=position[1], z=position[2]))
            continue
        kind = _WORD_KINDS.get(command)
        if kind is None:
            raise ValueError(f"unparseable block {stripped!r}")
        x, y, z = position
        i = j = r = None
        feed: float | None = None
        for word in words[1:]:
            letter, value = word[0].upper(), float(word[1:])
            if letter == "X":
                x = value
            elif letter == "Y":
                y = value
            elif letter == "Z":
                z = value
            elif letter == "I":
                i = value
            elif letter == "J":
                j = value
            elif letter == "R":
                r = value
            elif letter == "F":
                feed = value
            else:
                raise ValueError(f"unknown word {word!r} in block {stripped!r}")
        if kind in ("arc_cw", "arc_ccw"):
            if r is not None:
                cx, cy = _r_centre(
                    (position[0], position[1]), (x, y), r, clockwise=kind == "arc_cw"
                )
                i, j = cx - position[0], cy - position[1]
            if i is None or j is None:
                raise ValueError(f"arc block {stripped!r} names no centre")
        if kind != "rapid":
            if feed is not None:
                modal_feed = feed
            feed = modal_feed
        else:
            feed = None
        moves.append(Move(kind=kind, x=x, y=y, z=z, feed_mm_min=feed, i=i, j=j))
        position = (x, y, z)
    return MoveList(moves=tuple(moves))


def motion_signature(move: Move) -> tuple[JSONValue, ...]:
    """The projection of one move the program text carries, rounded once."""
    return (
        move.kind,
        round(move.x, COORD_DECIMALS),
        round(move.y, COORD_DECIMALS),
        round(move.z, COORD_DECIMALS),
        None if move.feed_mm_min is None else round(move.feed_mm_min, COORD_DECIMALS),
        None if move.i is None else round(move.i, COORD_DECIMALS),
        None if move.j is None else round(move.j, COORD_DECIMALS),
    )


@dataclass(frozen=True)
class RoundTripReport:
    """One §5.2 round-trip: the verdict and, on divergence, the first split.

    ``first_divergence`` names the first divergent move ON BOTH SIDES (the
    internal move and what parsed back — or ``None`` for a side that ran out),
    exactly as the gate clause words it.
    """

    verdict: str
    post_id: str
    moves: int
    parsed_moves: int
    first_divergence: dict[str, JSONValue] | None = None

    def to_json(self) -> dict[str, JSONValue]:
        return {
            "verdict": self.verdict,
            "post": self.post_id,
            "moves": self.moves,
            "parsed_moves": self.parsed_moves,
            "first_divergence": self.first_divergence,
        }


def _signature_json(signature: Sequence[JSONValue] | None) -> JSONValue:
    return None if signature is None else list(signature)


def round_trip(moves: MoveList, post: CamPost, *, emitter: Emitter | None = None) -> RoundTripReport:
    """Emit, parse back with THE parser, compare exactly (CAM.md §5.2).

    ``emitter`` defaults to the one shipped :func:`emit_program`; the
    parameter is the Gate G14C clause 3 fault-injection seam and nothing else
    ships through it.
    """
    emit = emitter if emitter is not None else emit_program
    parsed = parse_program(emit(moves, post))
    ours = [motion_signature(move) for move in moves.moves]
    theirs = [motion_signature(move) for move in parsed.moves]
    limit = max(len(ours), len(theirs))
    for index in range(limit):
        expected = ours[index] if index < len(ours) else None
        got = theirs[index] if index < len(theirs) else None
        if expected != got:
            return RoundTripReport(
                verdict="round_trip_diverged",
                post_id=post.id,
                moves=len(ours),
                parsed_moves=len(theirs),
                first_divergence={
                    "index": index,
                    "internal": _signature_json(expected),
                    "parsed": _signature_json(got),
                },
            )
    return RoundTripReport(
        verdict="round_trip_identical",
        post_id=post.id,
        moves=len(ours),
        parsed_moves=len(theirs),
    )
