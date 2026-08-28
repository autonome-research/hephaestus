# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The two event-identity namespaces, named once (``INTERFACE.md`` §2.8).

There is no field named "event ID" and there is no *single* identity: the live
stream and the history page mint two, and this module names both rather than
asserting a shared one that does not exist.

===============  =========================================  ==================
Surface          Identity                                   Serialized as
===============  =========================================  ==================
Live stream      ``(run_id, seq)`` — run-scoped, monotonic  ``<run_id>#<seq>``
History page     ``(session_id, ordinal)`` — session-       ``<sess>@<ordinal>``
                 scoped, restarts at 0 per session
===============  =========================================  ==================

**The two are not comparable and are never merged.** The separators differ so a
DOM attribute (`data-event-id`) tells a live chip from a historical one without
a second attribute, and so a test can assert which surface a chip came from.

**Why a dedupe across them is impossible, not merely unwise.** Live events carry
the real run id and a run-monotonic seq minted by ``active.nextSeq()``
(``agent/src/session/live.ts``). Historical events do not: ``main.ts``'s
``history.page`` handler passes the **session id** into the parameter
``history.ts`` names ``runId``, and ``normalizeEntries`` restarts ``seq`` at 0
for the whole session. The same logical event therefore has two disjoint
identities on the two surfaces, so a dedupe on ``(run_id, seq)`` would never
match and a "refilled" gap would render every event twice.

That is why **history is used for pre-attach backfill only, never to close a
live gap** (§2.7): after a ``4409 resync_required`` the client replays what the
live buffer still holds and renders anything the buffer dropped as a *labelled
break* (§7.4's ``resyncing`` state). The break is never healed from history.

Nothing here rewrites either identity to look like the other, and no third one
is invented. G4.11's archive is over the **historical** pair, because those are
the identities a reopened transcript actually emits.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "HISTORICAL_SEPARATOR",
    "LIVE_SEPARATOR",
    "historical_event_id",
    "identity_surface",
    "live_event_id",
]

#: Live: ``<run_id>#<seq>``.
LIVE_SEPARATOR: Final[str] = "#"

#: Historical: ``<session_id>@<ordinal>``.
HISTORICAL_SEPARATOR: Final[str] = "@"


def live_event_id(run_id: str, seq: int) -> str:
    """Serialize a live event's run-scoped identity."""
    return f"{run_id}{LIVE_SEPARATOR}{seq}"


def historical_event_id(session_id: str, ordinal: int) -> str:
    """Serialize a history page event's session-scoped identity."""
    return f"{session_id}{HISTORICAL_SEPARATOR}{ordinal}"


def identity_surface(event_id: str) -> str:
    """``"live"`` / ``"historical"`` / ``"unknown"`` for a serialized identity.

    The separator alone decides, which is the whole point of choosing two: a
    reader never needs a second attribute, and an id carrying neither separator
    is reported ``unknown`` rather than guessed into one of the namespaces.
    """
    if LIVE_SEPARATOR in event_id:
        return "live"
    if HISTORICAL_SEPARATOR in event_id:
        return "historical"
    return "unknown"
