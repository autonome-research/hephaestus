# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""The §2.3 read routes: every one a projection of a shape the engine already has.

``INTERFACE.md`` §2.3, §6.1, §6.2, §6.3. These are the routes G4's DOM assertions
read *over HTTP* — tree row count against ``geometry_count``, the properties
panel against the ``part.*`` projection, check badges against ``heph check
--json`` — so what each returns is a gate surface, not an implementation detail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from hephaestus.core.checks.report import project_check_report, report_json
from hephaestus.core.executor.namespace import METADATA_FIELDS
from hephaestus.testing.workspace import uuid7, workspace
from starlette.websockets import WebSocketDisconnect

#: A project ``checks/*.py`` for the fixture. The tools fixture ships an empty
#: ``checks/`` — its ``CHECKS`` live inside ``widget.py`` and are part-scope,
#: evaluated in-worker — so a test about the *project* check report has to
#: declare one, or it asserts over an empty map and proves nothing.
PROJECT_CHECK_SRC = """CHECKS = {
    "widget_is_sealed": lambda m: m.sealed("widget/part"),
    "widget_is_wide_enough": lambda m: m.bbox("widget/part")[0] >= 10.0,
}
"""


def test_project_returns_the_open_project_projection_plus_closed_capabilities(
    tmp_path: Path,
) -> None:
    """§2.3: "the ``open_project`` projection, same serializer as ``mcp/app.py``".

    Same serializer is asserted structurally — the body has exactly the MCP
    verb's keys plus ``capabilities`` — and ``capabilities`` is asserted *closed*,
    because an open map would be a surface the client learns to sniff.
    """
    from hephaestus.agent_bridge.project_projections import (
        CAPABILITY_KEYS,
        open_project_projection,
    )

    with workspace(tmp_path / "proj") as web:
        body = web.get("/project").json()
        mcp_body = open_project_projection(
            web.runtime.layout, web.runtime.project_store, serve_mode=web.runtime.serve_mode
        )
    assert set(body) == set(mcp_body) | {"capabilities"}
    for key in mcp_body:
        assert body[key] == mcp_body[key]
    assert set(body["capabilities"]) == set(CAPABILITY_KEYS)


def test_parts_projection_never_leaks_an_absolute_filesystem_path(tmp_path: Path) -> None:
    """§2.3: no route takes — or hands back — a raw filesystem path."""
    with workspace(tmp_path / "proj") as web:
        parts = web.get("/parts").json()["parts"]
    assert [p["name"] for p in parts] == ["bracket", "widget"]
    for part in parts:
        assert not Path(part["path"]).is_absolute()
        assert part["path"].startswith("parts/")
        assert part["content_hash"].startswith("sha256:")


def test_script_route_returns_read_part_verbatim_with_paging_fields(tmp_path: Path) -> None:
    """§2.3: ``read_part`` result verbatim, ``_PAGING_FIELDS`` intact.

    Asserted as equality against the same call through dispatch rather than by
    listing keys: "verbatim" is a claim about the *whole* document, and a key
    list would pass while a value drifted.

    UPDATED for J-http-envelope-20 (audit-2026-09-04): "verbatim" now means
    every dispatch-level field unchanged, **plus** a ``status`` member — the
    one 200 document on this surface that used to lack the discriminator every
    sibling route carries. Adding a field the tool result does not have is not
    a violation of "verbatim"; dropping or renaming one would be, which is why
    the assertion below is "the route's document minus ``status`` equals the
    direct dispatch call" rather than a weaker key-subset check.
    """
    with workspace(tmp_path / "proj") as web:
        route = web.get("/parts/widget/script").json()
        direct = web.dispatch("read_part", {"name": "widget"}, entry="read-parity")
    assert route["status"] == "ok"
    assert {k: v for k, v in route.items() if k != "status"} == direct
    assert "truncated" in route  # the paging contract's required member


def test_build_route_serves_geometry_count_as_an_explicit_field(tmp_path: Path) -> None:
    """§6.1 TIGHTENING (binds G4.2): ``geometry_count == len(geometries)``.

    Three plausible numbers exist and the gate says *build-result* geometry
    count, so the route serves that one explicitly. The e2e reads this field over
    HTTP and compares it to the DOM row count; it does not recount and does not
    consult the GLTF.
    """
    with workspace(tmp_path / "proj") as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        body = web.get("/parts/widget/build").json()
    assert body["status"] == "ok"
    assert body["current"] is True
    assert body["geometry_count"] == len(body["geometries"])
    assert body["geometry_count"] >= 1
    assert body["artifact_ref"].startswith("artifact:build:")


def test_build_route_reports_stale_after_a_script_edit_with_no_rebuild(tmp_path: Path) -> None:
    """B-5 regression: a script edit with no rebuild must not read as current.

    ``current`` stays publication state (it is still ``True``: this build IS
    the part's current publication), but a read-time freshness fact names the
    changed input so the header can print ``stale`` instead of "up to date".
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        before = web.get("/parts/widget/build").json()
        assert before["current"] is True
        assert before["stale"] is False
        assert before["stale_inputs"] == []
        path = root / "parts" / "widget.py"
        path.write_text(
            path.read_text(encoding="utf-8") + "# a harmless comment\n", encoding="utf-8"
        )
        body = web.get("/parts/widget/build").json()
    assert body["current"] is True
    assert body["artifact_ref"] == before["artifact_ref"]
    assert body["stale"] is True
    assert body["stale_inputs"] == ["script"]


def test_build_route_stale_is_false_when_the_script_is_rewritten_identically(
    tmp_path: Path,
) -> None:
    """The negative half of the reproduction: identical bytes, no drift."""
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        path = root / "parts" / "widget.py"
        path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        body = web.get("/parts/widget/build").json()
    assert body["current"] is True
    assert body["stale"] is False
    assert body["stale_inputs"] == []


def test_build_route_stale_inputs_names_hc_dependencies_on_a_project_param_edit(
    tmp_path: Path,
) -> None:
    """The ``hc`` leg: the read path uses the same projection ``_revalidate`` does.

    ``widget`` consumes ``hc.wall`` (``body = Box(p.width, 20.0, hc.wall)``), so
    a project-parameter edit is a changed input for it even though its own
    script text never moved.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        # `POST /parts/{part}/params` forces `name` to the path's part on every
        # call (§2.3: the path wins over the body), which the tool schema
        # refuses for `scope="project"` (`name` must be `null`). There is no
        # HTTP route for a project-scope write, so this exercises it through
        # the dispatcher directly — the same call `mcp/app.py`'s verb makes.
        state_hash = web.runtime.cad.param_state_hash("project", None)
        edit = web.dispatch(
            "set_params",
            {"scope": "project", "values": {"wall": 3.0}, "expected_state_hash": state_hash},
            entry="hc-edit",
        )
        assert edit["rejected"] == [], edit
        body = web.get("/parts/widget/build").json()
    assert body["current"] is True
    assert body["stale"] is True
    assert body["stale_inputs"] == ["hc_dependencies"]


def test_build_route_names_the_absence_rather_than_returning_an_empty_success(
    tmp_path: Path,
) -> None:
    """A part with no current build says so. Silence never reads as a pass."""
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/bracket/build").json()
    assert body["status"] == "not_built"
    assert body["geometry_count"] == 0
    assert body["checkpoints"] == []


def test_build_route_projects_executor_checkpoints(tmp_path: Path) -> None:
    """``checkpoints[]`` is the worker list, persisted on the §8 record."""
    with workspace(tmp_path / "proj") as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        body = web.get("/parts/widget/build").json()
    assert body["status"] == "ok"
    checkpoints = cast("list[dict[str, Any]]", body["checkpoints"])
    assert isinstance(checkpoints, list) and len(checkpoints) >= 1
    first = checkpoints[0]
    assert first["index"] == 0
    assert isinstance(first["line"], int) and first["line"] >= 1
    assert isinstance(first["statement"], str) and first["statement"]
    assert first["span"] == [first["line"], *first["span"][1:]]
    assert first["artifact_ref"] is None
    assert "bound" in first and "shapes" in first


def test_build_route_serves_last_failure_when_there_is_no_current(tmp_path: Path) -> None:
    """A first-fail part projects its failed record, not a ``not_built`` silence."""
    root = tmp_path / "proj"
    with workspace(root) as web:
        (root / "parts" / "bracket.py").write_text(
            "plate = Box(30, 20, 6)\n"
            "bad = fillet(plate.edges(), radius=99.0)\n"
            "part.geometry = plate\n",
            encoding="utf-8",
        )
        posted = web.post("/parts/bracket/build", json={}, key=uuid7()).json()
        assert posted["status"] == "error"
        body = web.get("/parts/bracket/build").json()
    assert body["status"] == "error"
    assert body["current"] is False
    checkpoints = cast("list[dict[str, Any]]", body["checkpoints"])
    assert len(checkpoints) >= 1
    error = cast("dict[str, Any]", body["error"])
    assert error["last_good_artifact_ref"]
    last = checkpoints[-1]
    assert last["artifact_ref"] == error["last_good_artifact_ref"]


def test_build_route_prefers_current_over_a_later_failure(tmp_path: Path) -> None:
    """G4.2's geometry_count is a fact about the current build, not last-fail.

    The precedence is deliberate and stays: a part that has ever built
    successfully must not lose its current build to a later failed attempt.
    But ``BuildDocument.error`` on that later attempt must not become
    unreachable through this route either — it surfaces as ``last_failure``
    beside the current record, recognised because the failure's recorded script
    hash is the hash of the script AS IT STANDS NOW, which the current build's
    is not. (The audit ledger proposed "differs from the current build's"; that
    weaker rule also carries a long-since-repaired failure forever, which
    ``test_build_route_omits_last_failure_recorded_before_the_current_success``
    is the counter-case for.)
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        current = web.get("/parts/widget/build").json()
        (root / "parts" / "widget.py").write_text(
            "body = Box(10, 10, 2)\n"
            "bad = fillet(body.edges(), radius=99.0)\n"
            "part.geometry = body\n",
            encoding="utf-8",
        )
        failed = web.post("/parts/widget/build", json={}, key=uuid7()).json()
        assert failed["status"] == "error"
        body = web.get("/parts/widget/build").json()
    assert body["status"] == "ok"
    assert body["current"] is True
    assert body["artifact_ref"] == current["artifact_ref"]
    assert body["geometry_count"] == current["geometry_count"]
    last_failure = cast("dict[str, Any]", body["last_failure"])
    assert last_failure["error"]["type"] == failed["error"]["type"]
    assert last_failure["error"]["message"] == failed["error"]["message"]
    assert len(cast("list[Any]", last_failure["checkpoints"])) >= 1


def test_build_route_omits_last_failure_recorded_before_the_current_success(
    tmp_path: Path,
) -> None:
    """The other half of the precedence: a failure the current success supersedes.

    Same script both times — only the live ``hc.wall`` value differs across the
    two build attempts — so the failed record is not about the script as it
    stands now (the live text matches the CURRENT build, not the failure) and
    ``last_failure`` is absent, rather than resurfacing a problem the current
    build already fixed.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        path = root / "parts" / "widget.py"
        path.write_text(
            "PARAMS = {\n"
            '    "width": Param(40.0, min=10.0, max=80.0),\n'
            "}\n\n"
            "body = Box(p.width, 20.0, hc.wall)\n"
            "if hc.wall < 1.5:\n"
            "    body = fillet(body.edges(), radius=99.0)\n"
            "part.geometry = body\n",
            encoding="utf-8",
        )
        low_hash = web.runtime.cad.param_state_hash("project", None)
        low = web.dispatch(
            "set_params",
            {"scope": "project", "values": {"wall": 1.0}, "expected_state_hash": low_hash},
            entry="wall-low",
        )
        assert low["rejected"] == [], low
        failed = web.post("/parts/widget/build", json={}, key=uuid7()).json()
        assert failed["status"] == "error"
        high_hash = web.runtime.cad.param_state_hash("project", None)
        high = web.dispatch(
            "set_params",
            {"scope": "project", "values": {"wall": 2.0}, "expected_state_hash": high_hash},
            entry="wall-high",
        )
        assert high["rejected"] == [], high
        succeeded = web.post("/parts/widget/build", json={}, key=uuid7()).json()
        assert succeeded["status"] == "ok"
        body = web.get("/parts/widget/build").json()
    assert body["status"] == "ok"
    assert body["current"] is True
    assert "last_failure" not in body


def test_properties_projection_keys_are_exactly_the_declared_part_metadata(
    tmp_path: Path,
) -> None:
    """§6.2 TIGHTENING (binds G4.3), assertion 2: projection ↔ contract.

    The DOM ↔ projection half is the e2e's. This is the half that stops a *thin*
    projection from making the e2e's set equality trivially true: the projection
    must carry exactly the ``part.*`` metadata the script declares, and every key
    must be in the closed ``script_contract.md`` §5.2 vocabulary.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        script = (root / "parts" / "widget.py").read_text(encoding="utf-8")
        declared = {field for field in METADATA_FIELDS if f"part.{field}" in script}
        body = web.get("/parts/widget/properties").json()
    assert set(body["properties"]) == declared
    assert set(body["properties"]) <= set(METADATA_FIELDS)
    assert body["fields"] == list(METADATA_FIELDS)


def test_properties_projection_carries_every_declared_field(tmp_path: Path) -> None:
    """The same assertion with metadata actually present — the non-vacuous case."""
    root = tmp_path / "proj"
    with workspace(root) as web:
        path = root / "parts" / "widget.py"
        path.write_text(
            path.read_text(encoding="utf-8")
            + '\npart.description = "a widget"\npart.process = "laser_cut"\n',
            encoding="utf-8",
        )
        body = web.get("/parts/widget/properties").json()
    assert body["properties"] == {"description": "a widget", "process": "laser_cut"}
    # No current build carries metadata here, so the weaker read answered — and
    # says so rather than letting the panel assume a runtime evaluation.
    assert body["source"] == "script_literals"
    assert body["build_artifact_ref"] is None


def test_properties_carry_computed_metadata_the_static_parse_cannot_see(
    tmp_path: Path,
) -> None:
    """§6.2 / G4.3: the projection reads the runtime-metadata-carrying build record.

    "All metadata fields **from the script**" is not what an AST parse returns.
    ``cad_ops.script_metadata`` recovers string *constants* only, so a
    ``part.blank_size`` written as an f-string over a bounded parameter is a
    field the script declares and the parse cannot see — the 2026-08-03 defect
    ``BuildResult.metadata`` exists to fix. This test asserts both halves: the
    static read genuinely misses the field, and the route genuinely reports it.
    """
    from hephaestus.agent_bridge.cad_ops import script_metadata

    root = tmp_path / "proj"
    with workspace(root) as web:
        path = root / "parts" / "widget.py"
        script = (
            path.read_text(encoding="utf-8")
            + '\npart.description = "a widget"\n'
            + 'part.blank_size = f"{p.width:.0f} x 20 mm"\n'
        )
        path.write_text(script, encoding="utf-8")
        assert "blank_size" not in script_metadata(script), "the static read must be the weak one"
        build = web.post("/parts/widget/build", json={}, key=uuid7()).json()
        assert build["status"] == "ok", build
        body = web.get("/parts/widget/properties").json()

    assert body["source"] == "build_record"
    assert body["build_artifact_ref"] == build["artifact_ref"]
    assert body["properties"] == {"description": "a widget", "blank_size": "40 x 20 mm"}
    assert set(body["properties"]) <= set(METADATA_FIELDS)


def test_checks_route_is_byte_identical_to_heph_check_json(tmp_path: Path) -> None:
    """§6.3 TIGHTENING (binds G4.4): one serializer, two callers, byte-parity.

    The e2e compares browser DOM badges against a **subprocess** ``heph check
    --json``; this is the server-side half of that claim, and it runs the real
    subprocess rather than trusting that the function it calls is the one the CLI
    calls.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        (root / "checks" / "widget_checks.py").write_text(PROJECT_CHECK_SRC, encoding="utf-8")
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        route = web.get("/checks").json()
        assert route["badges"], "the check fixture must not be empty"

    completed = subprocess.run(
        [sys.executable, "-m", "hephaestus.core.cli", "check", "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode in (0, 1), completed.stderr
    cli_document = json.loads(completed.stdout.strip().splitlines()[-1])
    assert route["report"] == cli_document


def test_check_badges_are_the_closed_four_value_vocabulary(tmp_path: Path) -> None:
    """§6.3: ``pass``, ``fail``, ``error``, ``not_run`` — and nothing else.

    ``not_run`` renders as its own visible state; the rule that silence never
    reads as a pass is a UI obligation the server has to make possible by never
    collapsing a state into ``pass``.
    """
    from hephaestus.core.checks.report import BADGES

    root = tmp_path / "proj"
    with workspace(root) as web:
        (root / "checks" / "widget_checks.py").write_text(PROJECT_CHECK_SRC, encoding="utf-8")
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        badges = web.get("/checks").json()["badges"]
    assert set(badges) == {
        "widget_checks:widget_is_sealed",
        "widget_checks:widget_is_wide_enough",
    }
    assert set(badges.values()) <= set(BADGES)


def test_the_check_serializer_is_the_one_function_both_callers_use(tmp_path: Path) -> None:
    """§19 item 5, directly: the route's document *is* ``report_json``'s."""
    with workspace(tmp_path / "proj") as web:
        route = web.get("/checks").json()["report"]
        direct = report_json(project_check_report(web.runtime.layout, web.runtime.store))
    assert route == direct


def test_params_route_returns_declarations_and_the_state_hash_to_echo(
    tmp_path: Path,
) -> None:
    """§2.3: ``PARAMS`` declarations ``{name, value, default, min, max, step, scope}``.

    ``state_hash`` is the optimistic ``expected_state_hash`` a ``POST`` must
    present. The client echoes it and never invents one — which is why the route
    has to hand it over in the same response as the declarations.
    """
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/widget/params").json()
        expected = web.runtime.cad.param_state_hash("part", "widget")
    assert body["state_hash"] == expected
    rows = {row["name"]: row for row in body["params"]}
    assert rows["width"]["default"] == 40.0
    assert rows["width"]["min"] == 10.0
    assert rows["width"]["max"] == 80.0
    assert rows["width"]["scope"] == "part"


def test_params_route_does_not_probe_the_sandbox_for_a_fresh_current_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """J-cli-startup-7: the regression guard is an INVOCATION COUNT, not a
    timing — spy the sandboxed probe and assert it is called **zero** times
    for a part with a current build and an unmodified script (tier 1,
    ``build_record``). Before the fix every read of this route cost 2.8-3.4 s
    because it called the sandboxed probe unconditionally.
    """
    calls: list[str] = []
    with workspace(tmp_path / "proj") as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        real_probe = web.runtime.cad.probe_part_params

        def spy(name: str) -> Any:
            calls.append(name)
            return real_probe(name)

        monkeypatch.setattr(web.runtime.cad, "probe_part_params", spy)
        body = web.get("/parts/widget/params").json()
    assert calls == [], f"the sandboxed probe was invoked for a current, unmodified build: {calls}"
    assert body["source"] == "build_record"


def test_params_route_source_falls_through_to_the_probe_for_a_computed_default(
    tmp_path: Path,
) -> None:
    """Tier 3 (``sandbox_probe``) still answers — and is attributed as such —
    for a script whose declaration the literal pass cannot resolve.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        path = root / "parts" / "widget.py"
        path.write_text(
            "PARAMS = {\n"
            '    "width": Param(20.0 + 20.0, min=10.0, max=80.0),\n'
            "}\n\n"
            "body = Box(p.width, 20.0, 5.0)\n"
            "part.geometry = body\n",
            encoding="utf-8",
        )
        body = web.get("/parts/widget/params").json()
    assert body["source"] == "sandbox_probe"
    assert body["params"][0]["name"] == "width"


def test_params_route_source_is_script_literals_with_no_build_at_all(tmp_path: Path) -> None:
    """Tier 2: a fully-literal declaration with no build yet still answers
    cheaply, attributed honestly as the static reading it is.
    """
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/bracket/params").json()
    assert body["source"] == "script_literals"


def test_params_route_never_serves_a_recorded_declaration_for_an_edited_script(
    tmp_path: Path,
) -> None:
    """THE SAFETY ARGUMENT of J-cli-startup-7's ladder (audit-2026-09-04).

    Build a part, change a **bound** in its script, and read the params route
    without rebuilding. Tier 1 (``build_record``) must not answer: its whole
    licence is that the build's recorded input hashes still match the live
    ones, and they no longer do. The reading that comes back has to be of the
    script **as it stands now** — the new bound, not the built one — because a
    slider whose maximum came from a superseded build is exactly the lie the
    three-tier ladder was allowed to exist only by ruling out.

    Shares its reasoning with B-5 (a build's currency recomputed against the
    current inputs); the two are the same invariant read from two routes.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        built = web.get("/parts/widget/params").json()
        assert built["source"] == "build_record"
        assert _row(built, "width")["max"] == 80.0

        path = root / "parts" / "widget.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace("max=80.0", "max=55.0"), encoding="utf-8"
        )
        after = web.get("/parts/widget/params").json()

    assert after["source"] != "build_record", (
        "an edited script must not be answered from the superseded build's declaration"
    )
    assert _row(after, "width")["max"] == 55.0


def _row(body: dict[str, Any], name: str) -> dict[str, Any]:
    """One params row by name, so the assertions above read as facts."""
    rows = {str(row["name"]): row for row in body["params"]}
    return cast("dict[str, Any]", rows[name])


def test_dfm_route_reports_auto_run_and_a_named_absence_before_any_run(
    tmp_path: Path,
) -> None:
    """§6.4: the setting and the last evaluation are two different facts.

    Before any evaluation the route says ``last: null`` rather than an empty
    finding list. An empty list would read as "no DFM problems", which is exactly
    the silence-as-pass §6.4 forbids.
    """
    with workspace(tmp_path / "proj") as web:
        body = web.get("/parts/widget/dfm").json()
    assert body["auto_run"] is False
    assert body["last"] is None
    assert body["resolved_from"] is None


def test_every_read_route_refuses_a_missing_bearer_with_401_unauthorized(
    tmp_path: Path,
) -> None:
    """§2.4: missing or invalid bearer is 401 ``unauthorized`` — on every route.

    Enumerated over the whole read surface rather than spot-checked, because an
    unauthenticated route is not a bug that shows up in the route you happened to
    test.

    AMENDMENT (§2.2, "including the WS upgrade"; §2.7). The read surface now spans
    two transports, and 401 is an *HTTP* answer. A WebSocket row is refused at the
    **handshake** instead — the client sees the upgrade rejected, and the socket is
    never accepted, which is stronger than accepting it and closing. The coverage
    obligation is unchanged and is discharged in full here: every GET row is still
    enumerated, and each is asserted against the refusal its own transport has.
    """
    from hephaestus.http.app import ROUTE_TABLE, WEBSOCKET_ROUTES

    reads = [(m, t) for m, t in ROUTE_TABLE if m == "GET"]
    assert {t for _, t in reads} >= set(WEBSOCKET_ROUTES), "a socket row left the read surface"
    with workspace(tmp_path / "proj") as web:
        for method, template in reads:
            path = template.replace("{part}", "widget").replace("{ref}", "artifact:build:sha256:00")
            if template in WEBSOCKET_ROUTES:
                for bearer in (None, "wrong"):
                    with (
                        pytest.raises(WebSocketDisconnect),
                        web.events(token=bearer) as socket,
                    ):
                        socket.receive_json()
                continue
            response = web.request(method, path, token=None)
            assert response.status_code == 401, f"{method} {path}"
            assert response.json()["reason"] == "unauthorized"
            bad = web.request(method, path, token="wrong")
            assert bad.status_code == 401, f"{method} {path}"


def test_the_dfm_project_setting_round_trips_and_takes_effect_now(tmp_path: Path) -> None:
    """§6.4: ``[dfm] auto_run`` is a **project setting**, not a per-message flag.

    Two controls, not one: a **Run DFM** action (``POST /parts/{part}/dfm``) and
    this project-settings toggle. Collapsing them into one composer switch would
    imply a tool argument that does not exist.

    The toggle has to take effect *in this process*, because ``CadOps`` reads the
    flag off the ``ProjectLayout`` it captured — a setting that waited for a
    restart would not be a setting.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.get("/parts/widget/dfm").json()["auto_run"] is False

        response = web.post("/project/config/dfm", json={"auto_run": True}, key=uuid7())
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "ok", "auto_run": True}

        assert web.get("/parts/widget/dfm").json()["auto_run"] is True
        assert web.runtime.layout.manifest.dfm_auto_run is True
        assert 'name = "tools"' in (root / "hephaestus.toml").read_text(encoding="utf-8")

        back = web.post("/project/config/dfm", json={"auto_run": False}, key=uuid7())
        assert back.json()["auto_run"] is False
        assert web.get("/parts/widget/dfm").json()["auto_run"] is False


def test_the_dfm_config_route_refuses_a_non_boolean(tmp_path: Path) -> None:
    """A checkbox has two values; anything else is ``invalid_params``."""
    with workspace(tmp_path / "proj") as web:
        response = web.post("/project/config/dfm", json={"auto_run": "yes"}, key=uuid7())
    assert response.status_code == 400
    assert response.json()["reason"] == "invalid_params"


def test_a_declared_but_unrun_check_badges_not_run(tmp_path: Path) -> None:
    """§6.3: ``not_run`` is a first-class state, never a silent omission.

    The projection can emit it, which is what makes the UI obligation
    implementable. No engine surface enumerates declared-but-unrun check names
    today (``CheckReport`` records the bundle ref and file hashes, not the names
    inside them), so this asserts the projection's contract directly rather than
    through a route that has nothing to pass it yet — the §14 fixture work is
    what will supply the fourth state.
    """
    from hephaestus.http.projections import checks_projection

    with workspace(tmp_path / "proj") as web:
        report = project_check_report(web.runtime.layout, web.runtime.store)
        badges = checks_projection(report, declared=["never_reached:a_check"])["badges"]
    assert badges["never_reached:a_check"] == "not_run"


def test_an_unevaluable_check_badges_error_and_never_fail(tmp_path: Path) -> None:
    """§6.3: a check that could not be *evaluated* has no verdict to report.

    ``run_checks`` records a raised predicate as ``measured.error``. Badging that
    ``fail`` would assert a verdict the engine explicitly declined to give, and
    badging it ``pass`` would be the silence the section forbids.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        (root / "checks" / "broken.py").write_text(
            'CHECKS = {"measures_a_missing_part": lambda m: m.volume("nosuchpart/part") > 0.0}\n',
            encoding="utf-8",
        )
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        body = web.get("/checks").json()
    assert body["badges"]["broken:measures_a_missing_part"] == "error"
    measured = body["report"]["checks"]["broken:measures_a_missing_part"]["measured"]
    assert "error" in measured


# -- the parts listing's build axis (audit-2026-09-04 J-web-viewport-7) --------


def test_the_parts_listing_carries_each_parts_build_status(tmp_path: Path) -> None:
    """§4.5's landing default needs a build state per row, and here it is.

    The workspace opened on the alphabetically first part with no regard for
    build state — in the shipped fixture the one part that has never been built,
    so the first screen was the not-built absence and every panel below it an
    empty state. The client-side alternative (read each part's build route and
    pick) would make the landing part depend on request timing; the field makes
    the pick a stable read of a document the client already has.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        before = web.get("/parts").json()["parts"]
        assert [(p["name"], p["build_status"]) for p in before] == [
            ("bracket", "not_built"),
            ("widget", "not_built"),
        ]
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        after = web.get("/parts").json()["parts"]
    assert [(p["name"], p["build_status"]) for p in after] == [
        ("bracket", "not_built"),
        ("widget", "ok"),
    ]
    # The addition drops nothing: the four keys the projection already served
    # are still every other key it serves.
    for part in after:
        assert set(part) == {"name", "path", "content_hash", "snapshot_ref", "build_status"}


def test_the_listings_build_status_is_the_build_routes_own_word_part_by_part(
    tmp_path: Path,
) -> None:
    """The anti-drift assertion: two routes, one vocabulary, asserted equal.

    A part that built, a part that failed, and — after the fixture's two are
    spent — the ``not_built`` row the first assertion already covered. For each,
    the listing's ``build_status`` is compared against ``GET
    /parts/{part}/build``'s own ``status``, so the two cannot come to mean
    different things by the same word. Both are computed by
    :func:`hephaestus.core.project_store.listing.part_build_status`; this is what
    proves the reuse rather than asserting it in a comment.
    """
    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        (root / "parts" / "bracket.py").write_text(
            "plate = Box(30, 20, 6)\n"
            "bad = fillet(plate.edges(), radius=99.0)\n"
            "part.geometry = plate\n",
            encoding="utf-8",
        )
        assert web.post("/parts/bracket/build", json={}, key=uuid7()).json()["status"] == "error"
        listing = web.get("/parts").json()["parts"]
        per_route = {
            part["name"]: web.get(f"/parts/{part['name']}/build").json()["status"]
            for part in listing
        }
    assert {part["name"]: part["build_status"] for part in listing} == per_route
    # Non-vacuous: the comparison would pass on two constant maps, so the three
    # states have to be genuinely present between them.
    assert set(per_route.values()) == {"ok", "error"}


def test_the_listings_build_status_never_leaves_the_closed_vocabulary(tmp_path: Path) -> None:
    """§2.3's build axis is a closed three-value set, and the listing stays inside it."""
    from hephaestus.core.project_store.listing import BUILD_STATUS_VALUES

    root = tmp_path / "proj"
    with workspace(root) as web:
        assert web.post("/parts/widget/build", json={}, key=uuid7()).status_code == 200
        parts = web.get("/parts").json()["parts"]
    assert BUILD_STATUS_VALUES == ("ok", "error", "not_built")
    for part in parts:
        assert part["build_status"] in BUILD_STATUS_VALUES
