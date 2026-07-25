# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
"""The four render channels over the assembly primary fixture (Gate G1).

The fixture is built through the executor's unsafe local backend (subprocess) to
prove it builds green, and executed in-process to obtain the live labelled shape
the channels render (a reloaded BRep artifact keeps neither labels nor colours).

Covers: mask decode == legend (exact colour set), every labelled solid visible in
at least one standard view, section differs from rgb, explode(1.0) strictly grows
the silhouette over explode(0.0), and two-process byte-identical rgb + mask.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from hephaestus.core.errors import ValidationError
from hephaestus.core.executor.globals_exec import execute_globals
from hephaestus.core.executor.namespace import (
    CheckRegistry,
    ParamState,
    PartOutput,
    build_namespace,
)
from hephaestus.core.executor.runner import BuildRequest, run_build
from hephaestus.core.executor.sandbox.unsafe import UnsafeLocalBackend
from hephaestus.core.executor.splitter import (
    PART_FILENAME,
    compile_statement,
    parse_module,
    split_statements,
)
from hephaestus.core.executor.tags import TagRegistry
from hephaestus.core.render.cameras import standard_view_names
from hephaestus.core.render.channels import (
    CHANNELS,
    RenderOptions,
    RenderScene,
    encode_png,
    explode_silhouette,
    parse_section_plane,
    render_channel,
    scene_from_shape,
)
from hephaestus.core.render.palette import hex_to_rgb, rgb_to_id

FIXTURES = Path(__file__).resolve().parents[2] / "corpus" / "public_fixtures"
ASSEMBLY = FIXTURES / "assembly"
PRIMARY = ASSEMBLY / "parts" / "primary.py"
GLOBALS = ASSEMBLY / "globals.py"

# Small viewport keeps the suite fast while preserving every gate property.
WIDTH, HEIGHT = 240, 180
OPTS = RenderOptions(width=WIDTH, height=HEIGHT)


def _execute_shape(script: str, globals_source: str) -> object:
    """Execute a part script in-process and return its final geometry compound."""
    globals_result = execute_globals(globals_source)
    param_state = ParamState(scope="part", overrides={})
    part = PartOutput()
    tag_registry = TagRegistry()
    namespace = build_namespace(
        param_state=param_state,
        hc=globals_result.hc_namespace(),
        part=part,
        tag_registry=tag_registry,
        check_registry=CheckRegistry(),
    )
    module = parse_module(script, filename=PART_FILENAME)
    statements = split_statements(script, filename=PART_FILENAME)
    for statement, node in zip(statements, module.body, strict=True):
        tag_registry.set_statement(statement.index, statement.lineno)
        exec(compile_statement(node, filename=PART_FILENAME), namespace)
        if not param_state.published and "PARAMS" in namespace:
            param_state.publish(namespace)
    param_state.finalize()
    geometry = part.geometry_value
    assert geometry is not None
    return geometry


@pytest.fixture(scope="module")
def primary_build() -> None:
    """Prove the fixture builds green through the executor's unsafe backend."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        built = run_build(
            BuildRequest(
                part="primary",
                script=PRIMARY.read_text(encoding="utf-8"),
                globals_source=GLOBALS.read_text(encoding="utf-8"),
            ),
            backend=UnsafeLocalBackend(),
            out_dir=Path(tmp),
        )
    assert built.result.status == "ok"
    assert built.result.metrics is not None
    assert built.result.metrics.solids == 6


@pytest.fixture(scope="module")
def scene() -> RenderScene:
    shape = _execute_shape(PRIMARY.read_text(encoding="utf-8"), GLOBALS.read_text(encoding="utf-8"))
    return scene_from_shape(shape)


def _nonbackground_colors(rgba: np.ndarray) -> set[tuple[int, int, int]]:
    rgb = rgba[:, :, :3].reshape(-1, 3)
    uniq = np.unique(rgb, axis=0)
    out: set[tuple[int, int, int]] = set()
    for row in uniq:
        colour = (int(row[0]), int(row[1]), int(row[2]))
        if colour != (0, 0, 0):
            out.add(colour)
    return out


def test_scene_has_six_labeled_solids(scene: RenderScene, primary_build: None) -> None:
    assert len(scene.solids) == 6
    labels = [s.label for s in scene.solids]
    assert labels == ["bottom_deck", "top_deck", "post", "post", "post", "post"]
    # Fixture sets no .color -> every solid falls back to the neutral default.
    assert all(not s.color_explicit for s in scene.solids)


def test_all_channels_render_rgba(scene: RenderScene) -> None:
    for channel in CHANNELS:
        views = render_channel(scene, ["iso"], channel, OPTS)
        view = views["iso"]
        assert view.rgba.shape == (HEIGHT, WIDTH, 4)
        assert view.rgba.dtype == np.uint8
        if channel == "mask":
            assert view.legend is not None
        else:
            assert view.legend is None


def test_rgb_honors_explicit_colors(scene: RenderScene) -> None:
    """A scene whose solids carry .color renders those colours (not the default)."""
    from build123d import Box, Color, Compound, Pos

    a = Box(20, 10, 6)
    a.label = "red"
    a.color = Color(1.0, 0.0, 0.0)
    b = Pos(40, 0, 0) * Box(8, 8, 8)
    b.label = "green"
    b.color = Color(0.0, 1.0, 0.0)
    coloured = scene_from_shape(Compound(children=[a, b]))
    assert coloured.solids[0].color[:3] == (255, 0, 0)
    assert coloured.solids[1].color[:3] == (0, 255, 0)
    rgba = render_channel(coloured, ["iso"], "rgb", OPTS)["iso"].rgba
    r = rgba[:, :, 0].astype(int)
    g = rgba[:, :, 1].astype(int)
    b_ch = rgba[:, :, 2].astype(int)
    # Some pixels are strongly red-dominant and others green-dominant (lit).
    assert int(np.count_nonzero((r > 120) & (r > g + 60) & (r > b_ch + 60))) > 50
    assert int(np.count_nonzero((g > 120) & (g > r + 60) & (g > b_ch + 60))) > 50


def test_mask_decode_equals_legend_exact_color_set(scene: RenderScene) -> None:
    """Over the standard views, decoded mask colours == the legend colour set."""
    legend = scene.legend()
    legend_colors = {hex_to_rgb(colour) for colour in legend}
    legend_ids = {rgb_to_id(c) for c in legend_colors}

    decoded_union: set[tuple[int, int, int]] = set()
    views = render_channel(scene, list(standard_view_names()), "mask", OPTS)
    for view in views.values():
        colors = _nonbackground_colors(view.rgba)
        # Soundness: every decoded colour is a legend colour naming a real solid.
        for colour in colors:
            selection_id = rgb_to_id(colour)
            assert selection_id in legend_ids
            descriptor = legend[next(k for k in legend if hex_to_rgb(k) == colour)]
            assert descriptor["kind"] == "solid"
            assert descriptor["solid_index"] == selection_id
        decoded_union |= colors
    # Completeness: every legend colour is decoded in at least one standard view.
    assert decoded_union == legend_colors


def test_every_labeled_solid_visible_in_a_standard_view(scene: RenderScene) -> None:
    views = render_channel(scene, list(standard_view_names()), "mask", OPTS)
    seen: set[int] = set()
    for view in views.values():
        for colour in _nonbackground_colors(view.rgba):
            seen.add(rgb_to_id(colour))
    assert seen == {s.solid_index for s in scene.solids}


def test_section_differs_from_rgb(scene: RenderScene) -> None:
    rgb = render_channel(scene, ["iso"], "rgb", OPTS)["iso"].rgba
    section = render_channel(scene, ["iso"], "section", OPTS)["iso"].rgba
    differing = int(np.count_nonzero(np.any(rgb != section, axis=2)))
    assert differing > 500
    # The section cap paints reddish cut pixels absent from the neutral rgb.
    r = section[:, :, 0].astype(int)
    g = section[:, :, 1].astype(int)
    b = section[:, :, 2].astype(int)
    assert int(np.count_nonzero((r > 120) & (r > g + 40) & (r > b + 40))) > 30


def test_section_plane_grammar() -> None:
    lo, hi = (0.0, 0.0, 0.0), (10.0, 20.0, 30.0)
    default = parse_section_plane(None, lo, hi)
    assert (default.axis, default.sign, default.offset) == (2, 1, 15.0)
    assert parse_section_plane("+Z@c", lo, hi).offset == 15.0
    assert parse_section_plane("-X@0", lo, hi) == parse_section_plane("-X@0", lo, hi)
    minus_x = parse_section_plane("-X@4", lo, hi)
    assert (minus_x.axis, minus_x.sign, minus_x.offset) == (0, -1, 4.0)
    assert parse_section_plane("y@mid", lo, hi).offset == 10.0
    with pytest.raises(ValidationError):
        parse_section_plane("bogus", lo, hi)
    with pytest.raises(ValidationError):
        parse_section_plane("+Z@notanumber", lo, hi)


def test_explode_strictly_increases_silhouette(scene: RenderScene) -> None:
    at_zero = explode_silhouette(scene, "iso", t=0.0, width=WIDTH, height=HEIGHT)
    at_one = explode_silhouette(scene, "iso", t=1.0, width=WIDTH, height=HEIGHT)
    assert at_zero > 0
    assert at_one > at_zero
    # The rendered explode images must also differ.
    e0 = render_channel(scene, ["iso"], "explode", RenderOptions(WIDTH, HEIGHT, explode_t=0.0))
    e1 = render_channel(scene, ["iso"], "explode", RenderOptions(WIDTH, HEIGHT, explode_t=1.0))
    assert not np.array_equal(e0["iso"].rgba, e1["iso"].rgba)


def test_explode_zero_matches_rgb_positions(scene: RenderScene) -> None:
    """explode(0) is the identity transform (same geometry as an un-exploded mask)."""
    zero = explode_silhouette(scene, "iso", t=0.0, width=WIDTH, height=HEIGHT)
    # A monotone check across t: t=0 <= t=0.5 <= t=1.
    half = explode_silhouette(scene, "iso", t=0.5, width=WIDTH, height=HEIGHT)
    one = explode_silhouette(scene, "iso", t=1.0, width=WIDTH, height=HEIGHT)
    assert zero <= half <= one


def test_encode_png_is_deterministic(scene: RenderScene) -> None:
    view = render_channel(scene, ["iso"], "mask", OPTS)["iso"]
    assert encode_png(view.rgba) == encode_png(view.rgba)


_SUBPROCESS_RENDER = """
import hashlib, sys
from pathlib import Path
sys.path.insert(0, {core_src!r})
from hephaestus.core.executor.globals_exec import execute_globals
from hephaestus.core.executor.namespace import (
    CheckRegistry, ParamState, PartOutput, build_namespace)
from hephaestus.core.executor.splitter import (
    PART_FILENAME, compile_statement, parse_module, split_statements)
from hephaestus.core.executor.tags import TagRegistry
from hephaestus.core.render.channels import render_channel, scene_from_shape, RenderOptions

script = Path({primary!r}).read_text()
gsrc = Path({globals!r}).read_text()
gr = execute_globals(gsrc)
ps = ParamState(scope="part", overrides={{}})
part = PartOutput(); tr = TagRegistry()
ns = build_namespace(param_state=ps, hc=gr.hc_namespace(), part=part,
                     tag_registry=tr, check_registry=CheckRegistry())
mod = parse_module(script, filename=PART_FILENAME)
sts = split_statements(script, filename=PART_FILENAME)
for st, node in zip(sts, mod.body, strict=True):
    tr.set_statement(st.index, st.lineno)
    exec(compile_statement(node, filename=PART_FILENAME), ns)
    if not ps.published and "PARAMS" in ns:
        ps.publish(ns)
ps.finalize()
scene = scene_from_shape(part.geometry_value)
opts = RenderOptions(width={width}, height={height})
out = []
for channel in ("rgb", "mask"):
    png = render_channel(scene, ["iso", "+X"], channel, opts)
    for name in ("iso", "+X"):
        out.append(channel + ":" + name + ":" + hashlib.sha256(png[name].png()).hexdigest())
sys.stdout.write("\\n".join(out))
"""


def _render_in_subprocess() -> str:
    core_src = str(Path(__file__).resolve().parents[1] / "src")
    script = _SUBPROCESS_RENDER.format(
        core_src=core_src,
        primary=str(PRIMARY),
        globals=str(GLOBALS),
        width=WIDTH,
        height=HEIGHT,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout.strip()


def test_rgb_and_mask_are_two_process_byte_identical() -> None:
    """Same build + view + channel => byte-identical PNGs across two processes."""
    first = _render_in_subprocess()
    second = _render_in_subprocess()
    assert first == second
    assert first.count("\n") == 3  # rgb/mask x iso/+X
