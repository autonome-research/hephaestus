# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0

"""Record the inspector's fixture JSON from a **real** ``server/http`` app.

``INTERFACE.md`` §6's panels are asserted field-for-field against recorded
response documents (``web/test/inspector.test.tsx``). Recorded means exactly
that: this script scaffolds a project, builds it, runs the project checks and a
real DFM evaluation under the probed secure backend, and writes the bodies the
routes returned into ``web/test/fixtures/``. Nothing in that directory is
hand-authored, so a component test that passes is a test against the shape the
server actually serves — the whole point of §1's `data-source` discipline is
lost if the client's tests agree only with the client's own idea of the wire.

Run it from the repository root::

    uv run python scripts/record_web_fixtures.py

Re-record whenever a §2.3 read projection changes. The script is deterministic
except for content-addressed refs and the temporary project root, both of which
change per run by construction; that is why the TypeScript assertions are on
*fields and relations*, never on a literal ref.

TWO KINDS OF FIXTURE ARE NOT PURE ROUTE OUTPUT, and both are named in
``web/test/fixtures/README.md`` rather than passing quietly as recordings:

* ``checks_not_run.json`` calls :func:`hephaestus.http.projections.checks_projection`
  with its ``declared`` argument, because no engine surface enumerates
  declared-but-unrun check names today (``projections.py`` records that gap in
  full). §6.3 requires ``not_run`` to render as its own visible state, so the
  badge has to be *reachable* for the panel that renders it to be testable.
* ``provenance_*.json`` assemble §12.3's response envelope around **real**
  selection-table entries, a real minted selection bundle and a real source-map
  tag placement, because ``POST /parts/{part}/selection/resolve`` is not a served
  route yet. Every ref, index, tag and line in them came out of the engine.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "web" / "test" / "fixtures"

PROJECT_NAME = "inspector_fixture"

MANIFEST = """[project]
name = "inspector_fixture"
units = "mm"

[dfm]
auto_run = false
"""

GLOBALS_SRC = """PARAMS = {
    "wall": Param(6.0, min=3.0, max=12.0),
}
"""

#: A laser-cut vent panel with one known violation per shipped ``laser_cut``
#: rule (thickness off the stocked ladder, an undersized bore, tight internal
#: corners), a tagged face, and a metadata block that exercises BOTH metadata
#: reads: literals the AST parse can see, and an f-string it cannot.
PANEL_SRC = """PARAMS = {
    "thickness": Param(5.5, min=3.0, max=12.0),
    "width": Param(60.0, min=20.0, max=120.0),
}

panel = Box(p.width, 40.0, p.thickness)
panel = panel - Pos(10.0, 0.0, 0.0) * Cylinder(0.25, 20.0)
panel = panel - Pos(-20.0, 12.0, 0.0) * Box(16.0, 16.0, 20.0)
corners = [e for e in panel.edges().filter_by(Axis.Z) if abs(e.center().Y - 4.0) < 1e-6]
panel = fillet(corners, 0.3)
vent = [
    f
    for f in panel.faces()
    if f.geom_type == GeomType.CYLINDER
    and abs(f.center().X - 10.0) < 0.5
    and abs(f.center().Y) < 0.5
][0]
tag(vent, "vent_bore")
panel.label = "vent_panel"

# Two spacers under ONE label: a geometry entry whose `solids` is greater than
# one, so the Results panel's visibility row is exercised on a group as well as
# on a single solid.
spacer_a = Pos(p.width / 2.0 + 8.0, -10.0, 0.0) * Box(10.0, 10.0, p.thickness)
spacer_a.label = "spacer"
spacer_b = Pos(p.width / 2.0 + 8.0, 10.0, 0.0) * Box(10.0, 10.0, p.thickness)
spacer_b.label = "spacer"

part.geometry = Compound(children=[panel, spacer_a, spacer_b])

part.description = "a laser-cut vent panel"
part.process = "laser_cut"
part.material_spec = "6 mm Baltic birch plywood"
part.stock_form = "sheet"
part.general_tolerance = "+/- 0.2 mm"
part.finish = "sanded, unfinished"
part.blank_size = f"{p.width:.0f} x 40 mm"
"""

#: A second part, so the Results panel's geometry list is not a one-row list and
#: the project check set has something to fail against.
BRACKET_SRC = """bracket = Box(30.0, 12.0, hc.wall)
bracket.label = "bracket_body"
part.geometry = bracket

part.description = "a mounting bracket"
part.process = "laser_cut"
"""

#: Three project checks, one per *reachable* badge state: a passing predicate, a
#: failing one, and one that raises (``measured.error`` → the ``error`` badge).
#: ``not_run`` is unreachable from a run — see the module docstring.
CHECKS_SRC = """CHECKS = {
    "panel_is_sealed": lambda m: m.sealed("panel/part"),
    "panel_is_narrow_enough": lambda m: m.bbox("panel/part")[0] <= 20.0,
    "panel_clears_the_absent_lid": lambda m: m.bbox("lid/part")[0] > 0.0,
}
"""


def uuid7() -> str:
    """A UUIDv7 idempotency key (the stdlib has no generator before 3.14)."""
    millis = int(time.time() * 1000)
    raw = bytearray(millis.to_bytes(6, "big") + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def scaffold(root: Path) -> None:
    (root / "parts").mkdir(parents=True, exist_ok=True)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "hephaestus.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "globals.py").write_text(GLOBALS_SRC, encoding="utf-8")
    (root / "parts" / "panel.py").write_text(PANEL_SRC, encoding="utf-8")
    (root / "parts" / "bracket.py").write_text(BRACKET_SRC, encoding="utf-8")
    (root / "checks" / "panel_checks.py").write_text(CHECKS_SRC, encoding="utf-8")


def write(name: str, body: Any) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"  {path.relative_to(REPO)}")


def record(root: Path) -> None:
    from hephaestus.core.render.bundle import resolve_selection
    from hephaestus.http.app import build_app
    from hephaestus.http.projections import checks_projection
    from hephaestus.http.runtime import WorkspaceRuntime
    from hephaestus.testing.ledger import seed_minimal_ledger
    from starlette.testclient import TestClient

    scaffold(root)
    runtime = WorkspaceRuntime.open(root, token="record", serve_mode=True)
    seed_minimal_ledger(runtime.cad)
    client = TestClient(build_app(runtime))
    auth = {"Authorization": "Bearer record"}

    def get(path: str) -> Any:
        response = client.get(f"/api/v1{path}", headers=auth)
        response.raise_for_status()
        return response.json()

    def post(path: str, body: Any) -> Any:
        response = client.post(
            f"/api/v1{path}", json=body, headers={**auth, "Idempotency-Key": uuid7()}
        )
        response.raise_for_status()
        return response.json()

    try:
        print("building…")
        for part in ("panel", "bracket"):
            result = post(f"/parts/{part}/build", {})
            if result.get("status") != "ok":
                raise SystemExit(f"{part} did not build: {json.dumps(result, indent=2)}")

        print("recording the read routes…")
        build = get("/parts/panel/build")
        write("project.json", get("/project"))
        write("parts.json", get("/parts"))
        write("build.json", build)
        write("properties.json", get("/parts/panel/properties"))
        write("checks.json", get("/parts/panel/checks"))

        # §6.3's fourth badge, reachable only through the projection's `declared`
        # argument — see the module docstring for why no run can produce it.
        from hephaestus.core.checks.report import project_check_report

        run = project_check_report(runtime.layout, runtime.store)
        body = checks_projection(run, declared=["panel_checks:panel_has_a_kerf_allowance"])
        body["part"] = "panel"
        write("checks_not_run.json", body)

        # Before any evaluation: `last: null`, a NAMED absence rather than an
        # empty finding list (§6.4 — silence never reads as a pass).
        write("dfm_absent.json", get("/parts/panel/dfm"))

        print("running DFM under the probed secure backend…")
        run_dfm = post("/parts/panel/dfm", {})
        if run_dfm.get("status") != "ok":
            raise SystemExit(f"run_dfm refused: {json.dumps(run_dfm, indent=2)}")
        write("dfm.json", get("/parts/panel/dfm"))

        # The same evaluation resolved through an EXPLICIT artifact ref rather
        # than through the current pointer. §6.4 requires the panel to
        # distinguish a finding on a transient preview from one on the current
        # artifact, so both dispositions are recorded.
        preview = post("/parts/panel/dfm", {"artifact_ref": build["artifact_ref"]})
        if preview.get("resolved_from") != "artifact_ref":
            raise SystemExit(f"preview run did not resolve by ref: {preview.get('resolved_from')}")
        write("dfm_preview.json", get("/parts/panel/dfm"))

        print("recording the provenance envelopes…")
        published = runtime.cad.publish_gltf(build["artifact_ref"])
        resolution = resolve_selection(runtime.store, published.bundle_ref)
        write_provenance(runtime, build, published, resolution)
    finally:
        client.close()
        runtime.close()


def write_provenance(runtime: Any, build: Any, published: Any, resolution: Any) -> None:
    """§12.3's response envelope over real entries, a real bundle, a real line.

    Not route output: ``POST /parts/{part}/selection/resolve`` is not served yet
    (§19 item 8). Everything inside the envelope is engine output — the selection
    ids and entries come from the bundle this build minted, and the tagged case's
    ``line`` is the source map's own ``TagPlacement``.
    """
    from hephaestus.core.project_store.store import blob_hash_of_ref
    from hephaestus.core.render.inspect import tag_placements_from_source_map

    source_map = json.loads(
        runtime.store.blobs.get(blob_hash_of_ref(build["source_map_ref"])).decode("utf-8")
    )
    placements = tag_placements_from_source_map(source_map)
    entries = dict(resolution.entries)

    def envelope(selection_id: int, state: str, **extra: Any) -> dict[str, Any]:
        entry = entries[selection_id]
        placement = None if entry.tag is None else placements.get(entry.tag)
        line = None if placement is None else placement.line
        provenance: dict[str, Any] = {"state": state, **extra}
        return {
            "status": "ok",
            "selection_id": selection_id,
            "kind": entry.kind,
            "solid_index": entry.solid_index,
            "topology_index": entry.topology_index,
            "tag": entry.tag,
            "label": entry.label,
            "line": line,
            "source_artifact_ref": resolution.source_artifact_ref,
            "bundle_ref": resolution.bundle_ref,
            "selection_table_ref": resolution.selection_table_ref,
            "provenance": provenance,
            # §12.5's `selection-crop` artifact kind is named new work; a crop is
            # a named absence here rather than a fabricated ref.
            "crop_artifact_ref": None,
        }

    tagged = next(i for i, e in entries.items() if e.tag is not None and e.kind == "face")
    owned = next(i for i, e in entries.items() if e.tag is None and e.kind == "face")
    solid = next(i for i, e in entries.items() if e.kind == "solid")

    write("provenance_tagged.json", envelope(tagged, "tagged"))
    write(
        "provenance_owned.json",
        envelope(owned, "owned", statement_line=None, reason="boolean_result_face"),
    )
    write("provenance_unattributed.json", envelope(solid, "unattributed"))


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="heph-web-fixture-"))
    try:
        record(root / PROJECT_NAME)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
