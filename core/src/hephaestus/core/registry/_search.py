"""The term-match score shared by the parts-store and materials searches.

Both content searches rank by the same rule — how many whitespace-separated
query terms appear anywhere in a record's searchable text — so the two tools
behave identically and neither drifts from the other.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

__all__ = ["score"]

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


def score(query: str, haystacks: Sequence[str]) -> int:
    """Matched-term count for a whitespace query over lowercased haystacks."""
    terms = _WORD_RE.findall(query.lower())
    if not terms:
        return 0
    blob = " ".join(haystacks).lower()
    return sum(1 for term in terms if term in blob)
