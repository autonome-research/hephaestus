# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""An unfinished register that cannot go stale (J-mirrors-and-dx-37).

``INTERFACE.md`` §19 is a hand-maintained list of work that does not exist yet.
Every entry in it has one failure mode: the work lands, nobody revisits the
paragraph, and the next reader plans from a register that describes a past. That
is not hypothetical — §19's item 46 named "no stylesheet at all" for the
markdown elements its renderer emits while
``web/src/components/stream/Transcript.module.css`` delivered every one of them,
including both alignment rules the entry called out by name.

The mechanism: an entry may carry ``register-check: <id>``, and this module
holds one small predicate per id. The predicate answers **"is this entry still
true?"** — so it fails when the work has LANDED and the register has not caught
up, which is the direction a normal test never checks. Deleting an entry deletes
its predicate; adding a marker with no predicate fails here, so the marker
cannot become decoration.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTERFACE = REPO / "INTERFACE.md"

_MARKER_RE = re.compile(r"register-check:\s*([a-z0-9][a-z0-9-]*)")


def _markers() -> set[str]:
    return set(_MARKER_RE.findall(INTERFACE.read_text(encoding="utf-8")))


def _markdown_presentation_still_landed() -> str | None:
    """Item 46: the transcript prose ruleset carries the full markdown grammar.

    The entry now says this work LANDED. The predicate that keeps that sentence
    honest is the same evidence the audit used: the elements and both alignment
    rules are in the stylesheet. If the ruleset is ever cut back, this fails and
    the entry has to be rewritten rather than silently becoming wrong again.
    """
    css = REPO / "web" / "src" / "components" / "stream" / "Transcript.module.css"
    if not css.is_file():
        return f"{css} is gone; §19 item 46 says its presentation work landed there"
    text = css.read_text(encoding="utf-8")
    required = {
        "list markers": "list-style",
        "quotations": "blockquote",
        "preformatted blocks": "pre",
        "tables": "table",
        "cells": ":is(th, td)",
        "right alignment": '[data-align="right"]',
        "centre alignment": '[data-align="center"]',
    }
    missing = sorted(name for name, needle in required.items() if needle not in text)
    if missing:
        return (
            f"§19 item 46 records this presentation work as landed, but "
            f"{css.relative_to(REPO)} no longer styles: {', '.join(missing)}"
        )
    return None


#: ``id -> predicate``. A predicate returns ``None`` while the entry is true and
#: a message naming what changed otherwise.
PREDICATES: dict[str, Callable[[], str | None]] = {
    "markdown-presentation": _markdown_presentation_still_landed,
}


def test_every_marked_register_entry_still_holds() -> None:
    stale = {
        marker: message
        for marker, predicate in PREDICATES.items()
        if (message := predicate()) is not None
    }
    assert not stale, "\n".join(stale.values())


def test_every_marker_has_a_predicate_and_every_predicate_a_marker() -> None:
    """A marker with no predicate is decoration; a predicate with no marker is
    a check for an entry somebody deleted."""
    markers = _markers()
    assert markers, "no §19 entry carries a register-check marker any more"
    assert markers == set(PREDICATES), (
        f"INTERFACE.md marks {sorted(markers)}; this module implements {sorted(PREDICATES)}"
    )
