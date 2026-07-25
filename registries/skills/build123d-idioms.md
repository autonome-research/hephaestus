# build123d idioms for Hephaestus part scripts

Reference for writing part scripts that build, stay readable, and survive edits.
Everything here is grounded in the part-script contract: a script is a Python
module executed top to bottom, **statement by statement**, in a namespace the
executor pre-populates. There are no imports. The injected namespace is the
entire API surface.

## What you get, and nothing else

- **All of build123d**, as if `from build123d import *` had run: `Box`,
  `Cylinder`, `Polyline`, `make_face`, `extrude`, `revolve`, `loft`, `sweep`,
  `fillet`, `chamfer`, `mirror`, `Pos`, `Rot`, `Plane`, `Axis`, `Align`,
  `Color`, `Compound`, `SortBy`, the location generators, and the selector
  methods (`.faces()`, `.edges()`, `.sort_by()`, `.filter_by()`, `.group_by()`).
- **`math`**.
- **`Param`, `PARAMS`, `p`** — bounded parameters.
- **`hc`** — the project-shared namespace from `globals.py`, read-only.
- **`part`** — the output object.
- **`tag`** — semantic names for topology.
- **`check`, `CHECKS`, `approx`** — persistent assertions.

`open`, `__import__`, `exec`, filesystem and network access are absent. Reaching
for them is a build error, not a warning. If a script seems to need a file, the
value belongs in `globals.py` or `PARAMS` instead.

## Algebra mode, one idea per statement

build123d has two styles. Prefer **algebra mode** — plain expressions on shapes
with `+`, `-`, `&` and `Plane`/`Pos`/`Rot` multiplication — over builder contexts.
The reason is specific to this executor: it checkpoints after *every* top-level
statement, so a failure reports the exact failing line and hands back the
last-good geometry from the statement before it. Long `with` blocks collapse many
operations into one statement and throw that resolution away.

```python
PARAMS = {
    "rail_w": Param(20.0, min=10.0, max=40.0, doc="rail width the clamp grips, mm"),
    "wall": Param(4.0, min=2.0, max=8.0, doc="clamp wall thickness, mm"),
}

_rail_w = p.rail_w
_wall = p.wall
_depth = 24.0

# One idea per statement: outer block, then the rail channel, then the relief.
_block = Box(_rail_w + 2 * _wall, _depth, _rail_w / 2 + _wall,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
_channel = Box(_rail_w, _depth + 2.0, _rail_w / 2,
               align=(Align.CENTER, Align.CENTER, Align.MIN))
_clamp = _block - Pos(0.0, 0.0, _wall) * _channel
_relief = Cylinder(1.5, _depth + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_clamp = _clamp - Pos(0.0, 0.0, _wall) * Rot(90.0, 0.0, 0.0) * _relief

_clamp.label = "rail_clamp"
part.geometry = _clamp
part.description = "Clamp block that grips a square rail from below."
part.process = "fdm"
```

Module-scope working values are prefixed `_`. That is a lint nudge, not a rule,
but it pays off: the source map uses binding names for unlabeled geometry, and a
leading underscore marks "internal" so it renders as `_name` rather than
competing with your real labels.

## Parameters: `PARAMS` before `p`

```python
PARAMS = {
    "plate_t": Param(6.0, min=3.0, max=12.0, doc="plate thickness, mm"),
    "hole_count": Param(4, min=2, max=8, doc="number of mounting holes"),
}

_plate_t = p.plate_t
_count = p.hole_count
_pitch = 18.0

_plate = Box(_pitch * _count + 20.0, 40.0, _plate_t,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
_drill = Cylinder(2.25, _plate_t + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_span = _pitch * (_count - 1)
for _i in range(_count):
    _x = -_span / 2 + _i * _pitch
    _plate = _plate - Pos(_x, 0.0, _plate_t / 2) * _drill

_plate.label = "mounting_plate"
part.geometry = _plate
```

Rules that bite:

- `Param(default, min=..., max=...)` — an **int** default declares an integer
  parameter, a **float** default declares a float. `Param(6, ...)` and
  `Param(6.0, ...)` are different declarations; write the float form unless you
  mean a count.
- `PARAMS` must appear before the first read of `p`. Reading `p.x` earlier is a
  contract error, not a `None`.
- Override values are validated against the bounds *all or nothing*: an
  out-of-range value names the offending parameter and applies nothing.
- Bounds are a design statement. `min`/`max` are what you are willing to have a
  slider or an agent sweep, so make them honest rather than infinite.

Read each parameter once into a `_local` at the top. It keeps the geometry
statements readable and makes the parameter dependency of each line obvious.

## Project-shared values: `globals.py` and `hc`

Interface dimensions two parts must agree on do not belong in either part. They
belong in `globals.py`, and every part reads them through `hc`.

```python globals
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=18.0, doc="sheet stock thickness, mm"),
    "tray_w": Param(180.0, min=80.0, max=400.0, doc="internal tray width, mm"),
}

sheet_t = p.sheet_t
tray_w = p.tray_w
# Derived constants are plain assignments computed from the project params.
slot_w = sheet_t
wall_span = tray_w + 2 * sheet_t
```

```python
_t = hc.sheet_t
_span = hc.wall_span

_floor = Box(_span, 120.0, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))
_slot = Box(hc.slot_w, 30.0, _t + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_floor = _floor - Pos(0.0, 0.0, _t / 2) * _slot

_floor.label = "tray_floor"
part.geometry = _floor
```

`globals.py` holds two kinds of name: its own `PARAMS` (tunable, bounds-checked,
slider-generating) and derived constants (plain assignments computed from them).
Parts see both as `hc.<name>` and cannot write them.

The executor records **which `hc` names each part read**. Changing a project
parameter or editing `globals.py` marks exactly the consuming parts stale — so
put a shared number in `hc` and the parts that depend on it rebuild themselves.
A part must not shadow an `hc` name in its own `PARAMS`; that is a lint error, so
every tunable has exactly one home.

## The output object

```text
part.geometry           required: one shape or a Compound
part.description        free text: what this is, in manufacturing terms
part.material_spec      "12 mm Baltic birch plywood, BB/BB grade"
part.process            "laser_cut" | "cnc_router" | "fdm" | ...
part.stock_form         "sheet" | "plate" | "bar" | ...
part.blank_size         "two 220 x 140 x 12 mm profiles"
part.general_tolerance  "+/-0.25 mm cut profile"
part.finish             "sand to 180 grit; clear water-based poly"
part.assembly_method    "dry-fit, then PVA the tabs"
part.joint              "12 mm finger joints, kerf-compensated per side"
```

Child `.label` strings become the geometry-tree row names and the addressing
namespace. Label every solid you will later want to measure, render or check by
name. Unlabeled children fall back to their binding name from the source map.

```python
_body = Box(60.0, 40.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_body.label = "body"
_body.color = Color(0.30, 0.42, 0.55)

_lug = Cylinder(6.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_lug = Pos(38.0, 0.0, 0.0) * _lug
_lug.label = "pivot_lug"
_lug.color = Color(0.70, 0.55, 0.25)

part.geometry = Compound(children=[_body, _lug])
part.description = "Hinge body with a pivot lug, labelled per solid."
```

## Tags: semantic names for topology

`tag(topology, name)` attaches a name to a face, edge or solid. Tags are the join
key for per-feature metadata, the `measure` tool, selection bundles, and checks.

```python
_plate = Box(80.0, 50.0, 8.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_pocket = Box(50.0, 30.0, 4.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_plate = _plate - Pos(0.0, 0.0, 4.0) * _pocket

# Filter by orientation and position, not by bare sort order.
_pocket_floor = _plate.faces().filter_by(Plane.XY).filter_by(
    lambda f: 3.9 < f.center().Z < 4.1
)[0]
tag(_pocket_floor, "pocket_floor")
part.feature("pocket_floor").finish = "flat to 0.1 mm; no tool witness marks"

_plate.label = "pocket_plate"
part.geometry = _plate
```

Tags are **recomputed by re-running the tagging selector on every build**, not
stored by topological id. That avoids dangling references but inherits a softer
failure: after an edit, `.faces().sort_by(Axis.Z)[-1]` still resolves, and may
now resolve to a *different* face. The executor fingerprints every tagged
topology and warns `tag_descriptor_changed` when a centroid, normal, area,
length or volume moved past its threshold. That warning is a heuristic, not an
identity claim — it has false positives (an intended edit to the same face) and
false negatives (a swap to a symmetric twin).

So write selectors that mean what you want:

```text
weak    _plate.faces().sort_by(Axis.Z)[-1]
        "whichever face happens to be highest" — any edit can change it

strong  _plate.faces().filter_by(Plane.XY).filter_by(lambda f: f.center().Z > 7.0)[0]
        "a horizontal face above z = 7" — states the intent, survives edits
        elsewhere, and fails loudly if the feature really moved

strong  _plate.edges().filter_by(Axis.Z).group_by(SortBy.LENGTH)[-1]
        "the longest vertical edges" — a property, not a position in a list
```

When a tag genuinely must track a moving feature, back it with a `CHECK` that
asserts the property you care about. A check is evidence; a selector is a guess.

## Persistent checks

```python
PARAMS = {
    "bore": Param(8.0, min=4.0, max=20.0, doc="through-bore diameter, mm"),
}

_bore = p.bore
_body = Cylinder(14.0, 30.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_hole = Cylinder(_bore / 2, 40.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_bushing = _body - Pos(0.0, 0.0, -5.0) * _hole

_bushing.label = "bushing"
part.geometry = _bushing

CHECKS = {
    "manifold": lambda m: m.sealed("part") and m.genus("part") == 1,
    "envelope": lambda m: m.bbox("part") <= (28.5, 28.5, 30.5),
    "wall_left": lambda m: m.volume("part") >= 4000.0,
}
```

`CHECKS` maps names to predicates over the measurement facade `m`, bound to the
built geometry. They run on **every** build and their results are part of the
build artifact — a failing check fails the report without aborting the build.
Available on `m`: `interference(a, b)`, `clearance(a, b)`, `distance(a, b)`,
`bbox(sel)`, `volume(sel)`, `mass(sel, density=None)`, `sealed(sel)`,
`genus(sel)`.

Comparison forms that actually work inside a **part script**:

```text
m.interference("lid", "body") == approx(0, abs=1e-6)   scalar equality, toleranced
m.bbox("part") <= (120.5, 80.5, 40.5)                  elementwise, per axis
m.bbox("part") >= (119.5, 79.5, 39.5)                  bracket it from both sides
m.clearance("shaft", "bore") >= 0.20 - 1e-6            plain arithmetic tolerance
m.sealed("part") and m.genus("part") == 0
```

The `approx` injected into part scripts is **scalar and `==`-only**. Do not write
`approx((x, y, z), ...)` or `value >= approx(...)` in a part script — those
silently record a `TypeError` as a failed check. `m.bbox(...)` returns a triple
whose `<=`, `>=`, `<`, `>` are elementwise against a plain 3-tuple, which covers
every envelope assertion; bracket a dimension with two bounds rather than testing
tuple equality, because exact tuple `==` will trip on float noise. The richer
comparator (tuples, `<=`/`>=` against `approx`) is available in cross-part
`checks/*.py`, which run under the check engine rather than the part namespace.

`check("name", predicate)` registers the same thing imperatively when the
predicate is easier to build in a loop.

## Addressing: one grammar everywhere

Any string that names geometry — in `CHECKS`, `measure`, `inspect_part(focus=…)`,
cross-part checks — resolves in this order inside a part:

1. `"part"` — the whole `part.geometry` compound.
2. a **tag** name.
3. a **geometry label**. Duplicates get `#2`, `#3`, … in tree order; `name`
   addresses the first, `name#k` the k-th, `name#*` the fused compound of all.
4. a **binding name** from the source map. For a list binding accumulated in a
   loop, the bare name is the fused compound and `name#k` the k-th element in
   append order.

Cross-part addressing prefixes the part: `"tray_floor/slot_wall"`. A name that
matches nothing, or matches two things at the same level, is an addressing error
listing the candidates — never a silent guess. The build result's `geometries`
array is exactly the resolvable label set, so what you can see is what you can
measure.

## Mistakes worth naming

- **Assigning geometry that is unreachable from `part.geometry`.** It builds, it
  lints, and it renders nothing. If it should exist, put it in the compound.
- **Reading `p` before declaring `PARAMS`.** Contract error.
- **Integer parameter by accident.** `Param(3, min=1, max=10)` cannot take 3.5.
- **Multi-solid compounds with no labels.** The Results tree and every check
  selector go blind.
- **One giant statement.** Failure resolution and last-good recovery both work
  per statement; a 40-line expression gives the repair loop nothing to stand on.
- **Fillet before boolean.** See the fillet reference: filleting an edge that a
  later cut removes either fails or silently rounds the wrong thing.
