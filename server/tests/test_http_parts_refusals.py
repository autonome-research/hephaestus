# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""J-http-envelope-3 — one part-scoped address space, one answer for a miss.

``INTERFACE.md`` §2.4/§2.3. Today an unknown part is answered six ways across the
part-scoped routes and three of them are 200: the script route refuses
``invalid_part``, ``params``/``properties`` refuse ``addressing_error``, the
build route answers 200 ``not_built``, ``checks`` answers 200 with the whole
project report and the caller's unknown name echoed into it, ``dfm``/``exports``
answer 200 with an empty document, and only ``POST /context/preview`` gets it
right: 404 ``unknown_part`` with the known part list. A client cannot tell "this
part is gone" from "this part has never been built", and three routes fabricate
a document about a part that does not exist.

The fix (``server/src/hephaestus/http/app.py``) is to resolve the part where it
enters the layer — a shared ``resolve_part(runtime, name)`` raising 404
``unknown_part`` with the known list — so every route below answers uniformly
**before** any engine call runs. This file is the parametrised guard: every
part-scoped route template, driven with a name absent from the project, must
answer the same way. It is written against the CORRECT target behaviour, so most
cases are red against the tree this lane found — see the module docstring's
sibling in the ledger (``docs/audit-2026-09-04-janky.md``, J-http-envelope-3) for
what each route answers today.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hephaestus.testing.workspace import uuid7, workspace

UNKNOWN_PART = "nosuchpart"

#: Every route template whose path carries ``{part}``, with the method(s) it is
#: served under, a body (``None`` for a GET) and whether the route needs an
#: ``Idempotency-Key`` to reach the part-resolution step at all. Kept as one
#: table — rather than one parametrised list per HTTP verb — so a route added to
#: ``ROUTE_TABLE`` without a row here is a glaring gap in the table below, not a
#: silent omission.
_ARTIFACT_REF = f"artifact:build:sha256:{'0' * 64}"

PART_SCOPED_ROUTES: list[tuple[str, str, dict[str, Any] | None, bool]] = [
    ("GET", "/parts/{part}/script", None, False),
    ("GET", "/parts/{part}/build", None, False),
    ("GET", "/parts/{part}/properties", None, False),
    ("GET", "/parts/{part}/checks", None, False),
    ("GET", "/parts/{part}/params", None, False),
    ("GET", "/parts/{part}/dfm", None, False),
    ("GET", "/parts/{part}/exports", None, False),
    ("POST", "/parts/{part}/inspect", {}, False),
    ("PUT", "/parts/{part}/script", {"script": "part.geometry = Box(1, 1, 1)\n"}, True),
    (
        "PATCH",
        "/parts/{part}/script",
        {"expected_hash": "sha256:0", "old_str": "1", "new_str": "2"},
        True,
    ),
    (
        "POST",
        "/parts/{part}/params",
        {"values": {"width": 45.0}, "expected_state_hash": "sha256:0"},
        True,
    ),
    ("POST", "/parts/{part}/build", {}, True),
    ("POST", "/parts/{part}/dfm", {}, True),
    ("POST", "/parts/{part}/export", {"artifact_ref": _ARTIFACT_REF, "format": "step"}, True),
    (
        "POST",
        "/parts/{part}/drawing",
        {"artifact_ref": _ARTIFACT_REF, "kind": "dimensioned"},
        True,
    ),
    ("POST", "/parts/{part}/doc", {"artifact_ref": _ARTIFACT_REF, "kind": "bom"}, True),
]


def _ids(case: tuple[str, str, dict[str, Any] | None, bool]) -> str:
    method, template, _body, _key = case
    return f"{method} {template}"


def test_every_part_scoped_route_in_the_table_is_covered_here() -> None:
    """The static guard the ledger asks for: a route template added to
    ``ROUTE_TABLE`` carrying ``{part}`` in its path must appear in
    :data:`PART_SCOPED_ROUTES` above, so a new part-scoped route cannot skip
    the resolver's guard silently — the module docstring's promise made
    executable rather than left as a comment for the next reader to honour by
    hand.
    """
    from hephaestus.http.app import ROUTE_TABLE

    part_scoped_in_table = {
        (method, template) for method, template in ROUTE_TABLE if "{part}" in template
    }
    covered = {(method, template) for method, template, _body, _key in PART_SCOPED_ROUTES}
    missing = sorted(part_scoped_in_table - covered)
    assert not missing, (
        f"ROUTE_TABLE carries part-scoped routes with no row in "
        f"PART_SCOPED_ROUTES, so a miss on them is untested: {missing}"
    )
    # And the reverse: nothing here names a route the table does not carry,
    # which would silently stop testing anything the moment a route is renamed.
    extra = sorted(covered - part_scoped_in_table)
    assert not extra, f"PART_SCOPED_ROUTES names routes not in ROUTE_TABLE: {extra}"


@pytest.mark.parametrize("case", PART_SCOPED_ROUTES, ids=_ids)
def test_a_part_no_project_has_is_404_unknown_part_everywhere(
    tmp_path: Path, case: tuple[str, str, dict[str, Any] | None, bool]
) -> None:
    """RC-4: every part-scoped route answers the SAME miss the same way.

    Not ``invalid_part`` (that names a syntactically illegal part name), not
    ``addressing_error`` (that names a selector *inside* a resolved part), not a
    200 with an empty or fabricated document — 404 ``unknown_part``, carrying
    the part the caller asked for and the project's known parts, exactly as
    ``POST /context/preview`` already answers it.
    """
    method, template, body, needs_key = case
    path = template.replace("{part}", UNKNOWN_PART)
    with workspace(tmp_path / "proj") as web:
        kwargs: dict[str, Any] = {}
        if body is not None:
            kwargs["json"] = body
        if needs_key:
            kwargs["key"] = uuid7()
        response = web.request(method, path, **kwargs)
    assert response.status_code == 404, (method, path, response.status_code, response.text)
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["reason"] == "unknown_part"
    assert payload.get("part") == UNKNOWN_PART
    assert "bracket" in payload.get("parts", []) and "widget" in payload.get("parts", [])


def test_a_real_part_with_no_build_still_answers_not_built(tmp_path: Path) -> None:
    """The positive case the fix must not over-tighten: a real, unbuilt part."""
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/bracket/build").json()
    assert body["status"] == "not_built"


def test_a_real_part_with_no_exports_still_answers_an_empty_list(tmp_path: Path) -> None:
    """The sibling positive case: a real part with nothing exported yet."""
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/widget/exports").json()
    assert body["status"] == "ok"
    assert body["exports"] == []


def test_an_unknown_part_in_the_context_preview_is_the_same_shape(tmp_path: Path) -> None:
    """The one route that already gets this right — pinned so the shared
    resolver cannot silently change *this* route's contract while fixing the
    other six.
    """
    with workspace(tmp_path / "proj") as web:
        response = web.post("/context/preview", json={"context": {"part": UNKNOWN_PART}})
    assert response.status_code == 404
    body = response.json()
    assert body["reason"] == "unknown_part"
    assert body["part"] == UNKNOWN_PART
