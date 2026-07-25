# Fillets, chamfers, and repairing a failed build

Reference for the two things that go together in practice: blending edges, and
recovering when a build stops. They belong in one document because **the fillet is
where a part script most often dies**, and because the failed-build record is
precise enough that repair is a procedure rather than a guess.

The governing idea: a failed build is not a lost build. Every statement before the
failing one already ran, its geometry was captured, and the result record tells you
the line, the exception, the statement it got through, and a snapshot you can look
at. Read all of that before editing anything.

## The failed-build record, field by field

```text
status            "failed"
error.line/col    where the exception was raised, in the part script's own
                  coordinates — not a traceback into the kernel
error.type        the exception class, e.g. ValueError, RuntimeError
error.message     the kernel's own words; fillet failures usually say the
                  radius could not be created and suggest a smaller value
error.frame       the source lines around the failure, with a > on the culprit
error.built_through  the last statement that DID succeed, with its line number
error.last_good   metrics of the geometry as of that statement: bodies, solids,
                  size_mm, volume_mm3, sealed, genus
error.last_good_artifact_ref
                  an artifact ref for that partial geometry — renderable
```

Two of those fields do the real work.

`built_through` separates "my selector was wrong" from "my radius was wrong". If
the build got through the boolean and died on the fillet, the boolean is not your
problem, however suspicious it looks.

`last_good_artifact_ref` is a real, immutable snapshot. Render it —
`inspect_part(name, artifact_ref=<that ref>)` — and you are looking at the exact
geometry the failing statement was handed. Most fillet failures are obvious in
that image: the edge you meant to blend is 2 mm long, or it was consumed by a
boolean two statements earlier, or the wall behind it is thinner than the radius.

**Do not skip the render.** Repairing from the error text alone is how a session
burns ten tool calls shrinking a radius that was never the problem.

## Why fillets fail

Nearly every failure is one of five things:

1. **Radius vs. wall.** A blend of radius `r` eats `r` of material perpendicular
   to the edge, from *both* adjacent faces. If either neighbouring wall is thinner
   than about `2r`, the kernel has nowhere to put the surface. Rule of thumb:
   `r <= 0.45 * min(adjacent wall thickness)`.
2. **Radius vs. edge length.** A fillet also runs along the edge and must
   terminate somewhere. An edge shorter than roughly `2r` leaves no room for the
   end conditions, and the neighbouring edges get dragged in.
3. **Radius vs. the next feature.** A hole 4 mm from an edge cannot survive a 5 mm
   blend on that edge; the fillet surface reaches the hole wall and the kernel is
   asked to build a surface against a hole that is about to be tangent.
4. **The edge does not exist any more.** Selectors are re-evaluated against the
   current shape. A boolean that removed the corner also removed the edge, and the
   selector now resolves to a *different* edge that happens to sort the same way.
5. **A batch failing as a batch.** `fillet(shape.edges(), radius=r)` is one
   operation over the whole set. One impossible edge fails all of them, and the
   error names the operation, not the edge.

## Fillet a named set, and fillet it at the right moment

```python
PARAMS = {
    "corner_r": Param(6.0, min=0.5, max=10.0, doc="outer corner radius, mm"),
    "hole_d": Param(5.5, min=3.0, max=10.0, doc="clearance hole diameter, mm"),
}
_w = 90.0
_d = 60.0
_t = 8.0

_plate = Box(_w, _d, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))

# Blend the four outer corners BEFORE the holes are cut. After the cut, the hole
# walls are vertical edges too, and a bare filter_by(Axis.Z) would try to blend
# them as well — which either fails or silently rounds the hole mouths.
_corners = _plate.edges().filter_by(Axis.Z)
_plate = fillet(_corners, radius=p.corner_r)

_hole = Cylinder(p.hole_d / 2, _t + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
for _x in (-30.0, 30.0):
    _plate = _plate - Pos(_x, 0.0, _t / 2) * _hole

_plate.label = "cover_plate"
part.geometry = _plate
part.description = "Cover plate: rounded corners, two clearance holes."
part.process = "cnc_router"

CHECKS = {
    "manifold": lambda m: m.sealed("part") and m.genus("part") == 2,
    # A rounded corner removes (1 - pi/4) * r^2 of area per corner. If the fillet
    # silently did not happen, the volume is the full blank and this fails.
    "corners_actually_rounded": lambda m: m.volume("part")
    <= _w * _d * _t - 0.8 * (4.0 - math.pi) * p.corner_r**2 * _t,
}
```

Two habits in that snippet are worth stating outright:

- **Order matters as much as radius.** Blend while the edge set is small and
  unambiguous. Every boolean you perform first adds edges your selector must then
  exclude.
- **A fillet needs a check.** `sealed`/`genus` prove the part is still a solid with
  the expected number of holes; the volume bound proves the blend actually
  occurred. Without the second one, a fillet that quietly did nothing looks exactly
  like a fillet that worked.

## Ask the kernel for the largest radius it will take

`max_fillet` searches for the biggest radius the given edge set accepts. It is a
search — it rebuilds the fillet repeatedly — so it is a *design-time* instrument,
not something to leave in a hot script.

```python
PARAMS = {
    "corner_r": Param(8.0, min=0.5, max=30.0, doc="outer corner radius, mm"),
}
_w = 40.0
_d = 24.0
_t = 6.0

_blank = Box(_w, _d, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))
_edges = _blank.edges().filter_by(Axis.Z)

# What will this edge set actually accept? Then stay clear of the boundary: a
# radius exactly at the limit is one parameter nudge away from failing.
_limit = _blank.max_fillet(_edges, tolerance=0.25, max_iterations=20)
_r = min(p.corner_r, _limit - 0.2)

_rounded = fillet(_edges, radius=_r)
_rounded.label = "rounded_blank"
part.geometry = _rounded
part.description = "Blank with corners blended to a kernel-verified radius."

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    "radius_applied": lambda m: m.volume("part") < _w * _d * _t,
}
```

`max_fillet` can also fail outright with "failed to find the max value within
&lt;tolerance&gt; in &lt;n&gt;" — that is the bisection running out of iterations, not a
statement about your geometry. Loosen `tolerance`, raise `max_iterations`, and
remember that you are paying a fillet attempt per iteration.

Use it like this: run it once, read the limit out of the build, then **write the
limit into the parameter's `max=`** and drop the call. The parameter bound is the
durable artifact — it is checked on every override, it is visible to whoever tunes
the design, and it costs nothing at build time. A `min(p.r, limit - eps)` clamp
left in permanently hides the problem instead: the part silently stops honouring
the radius you asked for.

## Split a failing batch instead of shrinking everything

When a whole-set fillet fails, the useful move is not a smaller radius — it is a
smaller *set*. Blend groups separately, largest radius first, and any failure
names the group that cannot take it.

```python
PARAMS = {
    "outer_r": Param(6.0, min=0.5, max=12.0, doc="outer corner radius, mm"),
    "inner_r": Param(2.0, min=0.5, max=6.0, doc="cavity corner radius, mm"),
}
_w = 60.0
_d = 40.0
_h = 20.0
_wall = 5.0

_body = Box(_w, _d, _h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_cavity = Box(_w - 2 * _wall, _d - 2 * _wall, _h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_body = _body - Pos(0.0, 0.0, _wall) * _cavity

# Two vertical edge families with different constraints: the outer corners have
# the whole wall behind them, the cavity corners have only the wall itself.
_verticals = _body.edges().filter_by(Axis.Z)
_outer = _verticals.filter_by(lambda e: abs(e.center().X) > _w / 2 - 1.0)
_inner = _verticals.filter_by(lambda e: abs(e.center().X) < _w / 2 - _wall + 1.0)

# Largest first: the big blend needs the most untouched material around it.
_body = fillet(_outer, radius=p.outer_r)
_body = fillet(_inner, radius=p.inner_r)

_body.label = "tray_body"
part.geometry = _body
part.description = "Open tray: outer corners and cavity corners blended separately."
part.process = "cnc_router"

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    "wall_survived": lambda m: m.volume("part") >= 0.5 * _w * _d * _wall,
}
```

If that build fails, the error names one `fillet` statement, so you know
immediately whether the outer or the inner family is impossible — and the inner
one is bounded by `_wall`, which tells you the fix is `inner_r <= 0.45 * _wall`,
not "try 1.9".

## Chamfer when a fillet will not go

A chamfer of length `L` removes strictly less material than a fillet of radius `L`
and imposes no tangency condition. Where a small fillet keeps failing — thin
walls, a bore mouth, an edge between two curved faces — a chamfer usually
succeeds, and for a deburring or lead-in feature it is what a machinist would cut
anyway.

```python
PARAMS = {
    "bore_d": Param(10.0, min=4.0, max=20.0, doc="bore diameter, mm"),
    "lead_in": Param(0.6, min=0.2, max=2.0, doc="bore mouth chamfer, mm"),
}
_od = 24.0
_h = 10.0

_hub = Cylinder(_od / 2, _h, align=(Align.CENTER, Align.CENTER, Align.MIN))

# The bore cutter is centred on the hub's mid-height, not on the origin, and
# overshoots by 1 mm at each end so the bore is genuinely through.
_bore = Cylinder(p.bore_d / 2, _h + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_hub = _hub - Pos(0.0, 0.0, _h / 2) * _bore

# Break the top bore mouth: circular edges, then the one highest in Z whose
# radius is the bore's, selected by position rather than by list order.
_circles = _hub.edges().filter_by(GeomType.CIRCLE)
_mouth = _circles.filter_by(lambda e: e.radius < _od / 2 - 0.5).sort_by(Axis.Z)[-1]
_hub = chamfer(_mouth, length=p.lead_in)

_hub.label = "bearing_hub"
part.geometry = _hub
part.description = "Hub with a chamfered bore mouth as an assembly lead-in."
part.process = "cnc_router"
part.finish = "deburr all edges; bore mouth chamfered as modelled"

CHECKS = {
    "one_bore": lambda m: m.sealed("part") and m.genus("part") == 1,
    "lead_in_cut": lambda m: m.volume("part")
    < math.pi * (_od / 2) ** 2 * _h - math.pi * (p.bore_d / 2) ** 2 * _h,
}
```

Note the selector: `filter_by(lambda e: e.radius < _od / 2 - 0.5)` keeps the bore
circles and drops the outside-diameter ones, and `sort_by(Axis.Z)[-1]` then takes
the top one. Filtering by a property first and ordering second survives edits that
change how many edges exist; a bare `edges()[3]` does not.

## The repair procedure

When a build fails, work this list in order. Each step is one tool call, and each
one either fixes the build or eliminates a cause.

1. **Read `error.type`, `error.line`, and `built_through`.** Decide whether the
   failing statement is really the guilty one.
2. **Render `last_good_artifact_ref`.** Look at the geometry the statement was
   handed. Very often the repair is now obvious and steps 3-5 are unnecessary.
3. **Halve the radius and rebuild.** Not a small decrement — a halving. If it
   still fails, the radius is not the constraint and you have learned that in one
   call rather than five.
4. **Shrink the edge set, not the radius.** Blend one edge, or one family. A
   success here localises the failure to the edges you dropped.
5. **Ask why that edge is impossible.** Measure the wall behind it and the
   distance to the nearest feature. The answer is a number, and that number is the
   real bound on the radius.
6. **Fix the cause, not the symptom.** Thicken the wall, move the hole, shorten the
   feature — or accept a smaller blend *and write it into the parameter bounds*.
   A radius pushed to 0.1 mm to make an error disappear is a part that cannot be
   machined and a failure that will return on the next edit.
7. **Lock the result in.** Set the parameter `max=` to what actually works and add
   a check that proves the blend happened. The next agent to touch this part —
   including you, later — then cannot silently undo it.

Repairs that make things worse, for reference:

```text
change several things at once     you no longer know which one mattered
delete the fillet                 the error goes away and so does the feature
raise the parameter max           bounds exist to stop exactly this
switch to edges()[k] indexing     works once, then silently selects elsewhere
rebuild without reading the error the same failure, one tool call later
```

## Selectors that survive the next edit

A fillet that works today and blends the wrong edge tomorrow is worse than one
that fails, because nothing reports it. The build does emit a
`tag_descriptor_changed` warning when a tagged face or edge moves further than the
default thresholds (1.0 mm of centroid displacement, 5 degrees of normal rotation,
2% of area) — but that is a heuristic prompting inspection, never a guarantee of
identity. Write selectors that do not need it:

```text
weak     _body.edges()[7]                          index into an unordered set
weak     _body.edges().sort_by(Axis.Z)[-1]         "highest" changes as you edit
better   _body.edges().filter_by(Axis.Z)           a family defined by direction
better   ....filter_by(lambda e: e.center().Z > 10.0)   a family plus a window
best     ....sort_by_distance((x, y, z))[0]        nearest to a point you can name
```

The strongest pattern is a **property filter plus a position window**: the filter
says what kind of edge it is, the window says which region of the part it is in.
Both survive an edit that adds features elsewhere, and both read as design intent
to the next person.

Then `tag` the result and check it. A tagged edge or face with a persistent check
against it is the only construction here that actually *proves* the right topology
was selected, on this build and on every build after it.
