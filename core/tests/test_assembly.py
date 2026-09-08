"""J-mirrors-and-dx-11 (second half): the anchor decoder, promoted and tested.

``AnchorRef.from_json`` used to exist twice, byte-identical apart from its
name: once in ``core/assembly.py`` beside the type it decodes, and once as a
free function ``_anchor_ref_from_json`` copied verbatim into ``core/motion.py``
when that module needed to read the same persisted rows. Two docstrings had
already begun to diverge — the second's ended by naming the first as the
authority, the classic first stage of a real behavioural split. The fix moves
the one definition onto ``AnchorRef`` itself as a classmethod (beside the type
it constructs, not beside each reader) and has ``core/motion.py`` import it.

Before this, the decoder had only INDIRECT coverage — through whatever test
exercised a ``JointOutcome``/``ConstraintOutcome``/``SweepResult`` round trip.
This gives it a test of its own, over the fields both call sites relied on.
"""

from __future__ import annotations

from typing import Any

from hephaestus.core.assembly import AnchorRef


def test_a_full_anchor_row_round_trips_every_field() -> None:
    row = {
        "anchor": "bracket:hole_a",
        "part": "bracket",
        "selector": "hole_a",
        "rule": "tag",
        "artifact_ref": "sha256:" + "ab" * 32,
    }

    ref = AnchorRef.from_json(row)

    assert ref.anchor == "bracket:hole_a"
    assert ref.part == "bracket"
    assert ref.selector == "hole_a"
    assert ref.rule == "tag"
    assert ref.artifact_ref == "sha256:" + "ab" * 32
    assert ref.to_json() == row


def test_a_row_with_no_rule_or_artifact_ref_decodes_both_as_none() -> None:
    """The unresolved-so-far shape both ``core/motion.py`` and
    ``core/assembly.py`` readers rely on: a row recorded before resolution
    reached a rule or read an artifact."""
    ref = AnchorRef.from_json({"anchor": "cuff:pin", "part": "cuff", "selector": "pin"})

    assert ref.rule is None
    assert ref.artifact_ref is None


def test_a_non_mapping_row_decodes_to_the_empty_ref_rather_than_raising() -> None:
    """§ persisted-row rule: a projection that cannot be read reports as
    unresolved, never as a crash of the reader — the type's own general
    tolerance, which the decoder must not narrow."""
    for bogus in (None, "not a mapping", 12, [1, 2, 3]):
        ref = AnchorRef.from_json(bogus)
        assert ref == AnchorRef(anchor="", part="", selector="")


def test_a_non_string_rule_or_artifact_ref_is_dropped_rather_than_kept_wrong_typed() -> None:
    row: dict[str, Any] = {
        "anchor": "a:b",
        "part": "a",
        "selector": "b",
        "rule": 7,  # wrong type — must not be trusted through
        "artifact_ref": ["not", "a", "string"],
    }

    ref = AnchorRef.from_json(row)

    assert ref.rule is None
    assert ref.artifact_ref is None


def test_motion_reads_the_same_decoder_assembly_owns_not_a_second_copy() -> None:
    """The structural half of the fix: ``core/motion.py`` must call
    ``AnchorRef.from_json`` rather than carrying its own copy under a
    different name. A private ``_anchor_ref_from_json`` reappearing in
    ``core/motion.py`` is exactly the duplicate this item removes."""
    import inspect

    import hephaestus.core.motion as motion

    assert not hasattr(motion, "_anchor_ref_from_json"), (
        "core/motion.py must not carry its own copy of the anchor decoder"
    )
    source = inspect.getsource(motion)
    assert "AnchorRef.from_json" in source, (
        "core/motion.py must decode anchors through AnchorRef.from_json, "
        "the one definition assembly.py owns"
    )
