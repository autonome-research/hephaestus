# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""``GET /artifacts/{ref}/meta``'s ``part`` field (``audit-2026-09-04`` J-web-viewport-5).

§4.1 says the operator must never have to ask which build they are looking at,
and the held-pin gates are exactly the case where that matters: the stage shows
one part's artifact while the inspector shows another's. The workspace used to
*remember* which part a held pin came from, in a private field explicitly outside
§4.5's closed record — so the fact survived a click and died on a reload, and a
pasted URL could hold a reference without saying which part minted it.

The pinned reference IS an artifact reference and this route was already served
and already keyless to the workspace principal, so the fix is a field, not a
route: the part becomes a server value — attributable, reload-surviving — and the
closed record does not grow a field for a sentence.

Sibling file, and the split is ownership rather than taxonomy: the rest of the
artifact surface's tests (the kind enumeration, §19.24's relabelling refusal, the
byte-for-byte assertions) live in ``test_http_artifacts.py`` and belong there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from hephaestus.testing.workspace import uuid7, workspace


def test_artifact_meta_names_the_part_the_artifact_was_minted_for(tmp_path: Path) -> None:
    """The field, on the ref the workspace actually pins."""
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        build = web.get("/parts/widget/build").json()
        ref = cast("str", build["artifact_ref"])
        meta = web.get(f"/artifacts/{ref}/meta").json()
    assert meta["part"] == "widget"
    # The addition drops nothing the route already served.
    assert set(meta) >= {"status", "kind", "mime_type", "total_bytes", "sha256", "links"}


def test_a_superseded_builds_meta_still_names_its_part(tmp_path: Path) -> None:
    """The reload case, which is the whole reason the field exists.

    A held pin names a build the part has since moved past — that is what holding
    IS — so the answer may not come from "which build is current". This rebuilds
    the part and asks the *superseded* ref, which the remembered field could
    never answer after a reload.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        held = cast("str", web.get("/parts/widget/build").json()["artifact_ref"])
        (root / "parts" / "widget.py").write_text(
            "body = Box(11, 10, 2)\npart.geometry = body\n", encoding="utf-8"
        )
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        current = cast("str", web.get("/parts/widget/build").json()["artifact_ref"])
        assert current != held
        held_meta = web.get(f"/artifacts/{held}/meta").json()
        current_meta = web.get(f"/artifacts/{current}/meta").json()
    assert held_meta["part"] == "widget"
    assert current_meta["part"] == "widget"


def test_the_part_is_read_from_the_record_and_never_guessed(tmp_path: Path) -> None:
    """Two parts, and each artifact names its own — not the first part listed.

    The bundle pointer is keyed by part *and* artifact because two parts whose
    geometry is byte-identical share one ref; an answer derived by scanning the
    project's parts would hand the second part's pin the first part's name, which
    is the silent wrong answer §4.4 forbids.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        assert web.post("/parts/bracket/build", json={}, key=uuid7()).status_code == 200
        refs = {
            name: cast("str", web.get(f"/parts/{name}/build").json()["artifact_ref"])
            for name in ("bracket", "widget")
        }
        named = {
            name: web.get(f"/artifacts/{ref}/meta").json()["part"] for name, ref in refs.items()
        }
    assert refs["bracket"] != refs["widget"]
    assert named == {"bracket": "bracket", "widget": "widget"}


def test_an_artifact_no_publication_record_names_reports_a_null_part(tmp_path: Path) -> None:
    """``null`` is a fact, not an omission and not a guess.

    A part snapshot is a real, reachable, kind-verified artifact of this project
    that no build bundle describes. The field is present and ``null`` — the
    client's marker then says nothing rather than inventing a source part, which
    is what §4.4 requires of an answer nobody can attribute.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        listing = cast("list[dict[str, Any]]", web.get("/parts").json()["parts"])
        snapshot_ref = cast("str", listing[0]["snapshot_ref"])
        meta = web.get(f"/artifacts/{snapshot_ref}/meta").json()
    assert meta["status"] == "ok"
    assert "part" in meta
    assert meta["part"] is None
