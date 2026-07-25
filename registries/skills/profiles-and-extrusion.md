# Profiles and extrusion

Reference for the construction style that dominates real Hephaestus part
scripts: build a **2D profile that states the design intent**, then give it depth
with `extrude`, `revolve`, `loft` or `sweep`. Profile-then-extrude beats
boolean-stacking primitives because the profile *is* the drawing — a reviewer can
read the section, and a parameter change moves the whole silhouette coherently
instead of shifting three boxes independently.

## The four depth operations

```text
extrude(face, amount)          straight prism along the face normal
extrude(face, amount, both=True)     symmetric about the sketch plane
extrude(face, amount, taper=deg)     draft angle, for moulded/printed walls
revolve(face, axis)            body of revolution; profile must not cross the axis
loft([section, ...])           blend between parallel sections, in order
sweep(section, path=path)      drag a section along a 1D path
```

All four take a *face* (or a closed wire made into one with `make_face`) and
return a solid. All four respect the plane the sketch was placed on, so place the
sketch and the depth direction follows.

## Sketch on a plane, not in your head

A sketch lives on a plane. Multiply a plane by a sketch to place it:

```python
PARAMS = {
    "flange_t": Param(6.0, min=3.0, max=12.0, doc="flange plate thickness, mm"),
    "bore": Param(50.0, min=20.0, max=120.0, doc="duct bore diameter, mm"),
}

_t = p.flange_t
_bore = p.bore
_od = _bore + 30.0

# The flange plate: a disc on XY, extruded up.
_plate = extrude(Plane.XY * Circle(_od / 2), amount=_t)
_plate = _plate - extrude(Plane.XY * Circle(_bore / 2), amount=_t)

# The spigot: same axis, sketched on the top face's plane.
_top = _plate.faces().filter_by(Plane.XY).sort_by(Axis.Z)[-1]
_spigot = extrude(Plane(_top) * Circle(_bore / 2 + 3.0), amount=18.0)
_spigot = _spigot - extrude(Plane(_top) * Circle(_bore / 2), amount=18.0)

_flange = _plate + _spigot
_flange.label = "duct_flange"
part.geometry = _flange
part.description = "Round duct flange with an integral spigot."
part.process = "fdm"
```

Useful planes: `Plane.XY`, `Plane.XZ`, `Plane.YZ`, `Plane.XY.offset(z)` for a
parallel plane at a height, and `Plane(face)` to sketch **on a face you just
built**. `Plane(face)` is the one that keeps a feature attached to its parent
when a parameter moves that parent.

## Building an outline that reads like a drawing

`Polyline` takes points; arcs and splines join onto it with `+`; `make_face`
closes the loop into a face.

```python
PARAMS = {
    "web_t": Param(5.0, min=3.0, max=10.0, doc="web thickness (extruded both ways), mm"),
}

_t = p.web_t
_len = 40.0
_high = 20.0
_nose = 10.0

# Straight run, a radius at the loaded corner, then back to the start.
_outline = Polyline((0.0, 0.0), (_len, 0.0), (_len, _nose))
_outline = _outline + RadiusArc((_len, _nose), (_len - _nose, _high), _nose)
_outline = _outline + Polyline((_len - _nose, _high), (0.0, _high), (0.0, 0.0))
_web = extrude(make_face(_outline), amount=_t / 2, both=True)

_web.label = "gusset_web"
part.geometry = _web
part.description = "Gusset web: one profile, one symmetric extrude."
part.general_tolerance = "+/-0.2 mm on the profile"
```

Two habits worth keeping:

- **Close the loop explicitly.** `Polyline(..., close=True)` or a final segment
  back to the first point. `make_face` on an open wire is a build error, and it
  is the most common first failure in a new profile.
- **`both=True` for symmetric parts.** A web that is symmetric about its sketch
  plane should say so, so the symmetry survives a thickness change instead of
  drifting to one side.

## Revolve: profiles that must not cross the axis

```python
PARAMS = {
    "shoulder": Param(4.0, min=1.0, max=10.0, doc="shoulder height, mm"),
}

_shoulder = p.shoulder
_bore_r = 4.0
_body_r = 9.0
_flange_r = 13.0
_len = 20.0

# Section in the XZ half-plane: x is radius, z is axial. Never x < bore radius.
_section = Polyline(
    (_bore_r, 0.0),
    (_flange_r, 0.0),
    (_flange_r, _shoulder),
    (_body_r, _shoulder),
    (_body_r, _len),
    (_bore_r, _len),
    close=True,
)
_bushing = revolve(Plane.XZ * make_face(_section), Axis.Z)

_bushing.label = "shoulder_bushing"
part.geometry = _bushing
part.description = "Turned shoulder bushing, revolved from one section."

CHECKS = {
    "manifold": lambda m: m.sealed("part") and m.genus("part") == 1,
    "flange_dia": lambda m: m.bbox("part") <= (26.5, 26.5, 20.5),
}
```

Revolve failure modes, in order of frequency:

1. The profile **touches or crosses the axis** where it should not, producing a
   self-intersecting solid or an outright failure. Keep the inner boundary at the
   bore radius, and if you want a solid part, put the inner boundary *on* the
   axis deliberately (a single point at `x = 0`, not a negative x).
2. The profile is on the wrong plane. `Plane.XZ` with `Axis.Z` is the standard
   pairing: x reads as radius, z as axial position.
3. Partial revolves (`revolve(face, Axis.Z, revolution_arc=180.0)`) leave open
   ends. That is fine as an intermediate, but check `sealed` before you trust it.

A revolved part has an exact rotational symmetry you can assert. `m.bbox` is a
cheap proxy: for a full revolve the x and y extents must match to float noise.

## Loft: blending sections

```python
PARAMS = {
    "wall": Param(2.0, min=1.2, max=4.0, doc="duct wall thickness, mm"),
    "height": Param(40.0, min=15.0, max=80.0, doc="transition height, mm"),
}

_wall = p.wall
_h = p.height
_rect_w = 60.0
_rect_d = 30.0
_round_r = 12.0

_outer_sections = [Rectangle(_rect_w, _rect_d), Pos(0.0, 0.0, _h) * Circle(_round_r)]
_inner_sections = [
    offset(Rectangle(_rect_w, _rect_d), -_wall),
    Pos(0.0, 0.0, _h) * Circle(_round_r - _wall),
]
_duct = loft(_outer_sections) - loft(_inner_sections)

_duct.label = "transition_duct"
part.geometry = _duct
part.description = "Rectangle-to-round transition, lofted outer minus lofted inner."
part.process = "fdm"

CHECKS = {
    "open_tube": lambda m: m.genus("part") == 1,
    "wall_volume": lambda m: m.volume("part") >= 2000.0,
}
```

Loft notes:

- Sections are blended **in list order**, so order them along the axis.
- Section count controls the blend: two sections give a ruled surface, three or
  more let you shape the waist. Sections need not be the same primitive.
- The reliable way to hollow a loft is **loft the inside separately and subtract
  it**, as above. `offset(sketch, -wall)` shrinks a 2D sketch; it keeps the inner
  section's corner topology consistent with the outer one.
- A loft whose sections have wildly different corner counts can twist. If the
  result looks wrong, add an intermediate section rather than fighting the solver.

## Sweep: a section along a path

```python
_path = Polyline((0.0, 0.0, 0.0), (0.0, 0.0, 30.0), (25.0, 0.0, 45.0))
_conduit = sweep(Plane.XY * Circle(5.0), path=_path)
_bore = sweep(Plane.XY * Circle(3.5), path=_path)
_conduit = _conduit - _bore

_conduit.label = "conduit"
part.geometry = _conduit
part.description = "Swept conduit: one path, outer minus inner section."
```

Sweep is the right tool for handles, cable routes, gaskets and beads. Keep the
path's turns gentle relative to the section size — a radius smaller than the
section will self-intersect, and the failure surfaces as a boolean or offset
error several statements later. When a swept solid misbehaves, sweep the outer
form alone first and inspect it before subtracting anything.

## Symmetry with `mirror`

```python
PARAMS = {
    "arm": Param(35.0, min=20.0, max=60.0, doc="arm reach from centreline, mm"),
}

_arm = p.arm
_t = 6.0

_half = Box(_arm, 18.0, _t, align=(Align.MIN, Align.CENTER, Align.MIN))
_half = _half - Pos(_arm - 8.0, 0.0, _t / 2) * Cylinder(
    2.25, _t + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER)
)
_hub = Cylinder(11.0, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))

_yoke = _half + mirror(_half, about=Plane.YZ) + _hub
_yoke.label = "yoke"
part.geometry = _yoke
part.description = "Symmetric yoke: model one arm, mirror it, add the hub."

CHECKS = {
    # Both arms present: the full span, bracketed, so a mirror that silently
    # became a translation (or vanished) fails the report.
    "span_upper": lambda m: m.bbox("part") <= (2 * 35.0 + 0.05, 22.05, 6.05),
    "span_lower": lambda m: m.bbox("part") >= (2 * 35.0 - 0.05, 21.95, 5.95),
}
```

Model half, mirror, fuse. It halves the statements you have to keep consistent
and makes the symmetry a property of the script rather than of your arithmetic.
`mirror(shape, about=Plane.YZ)` mirrors across x; `Plane.XZ` across y;
`Plane.XY` across z.

## Ordering rules that save rebuilds

1. **Profile before depth.** Get the 2D outline right — extrude it 1 mm and look
   at it if need be — before adding features on top of it.
2. **Depth before dressing.** Booleans first, then `fillet`/`chamfer`. An edge
   you round now may not exist after the next cut.
3. **Sketch on the parent's face** when a feature must stay attached, and on an
   absolute plane when it must stay put. Choosing the wrong one is how a boss
   ends up floating 3 mm off a wall after a thickness change.
4. **One profile per statement.** When a build fails, you want the failing
   statement to name one geometric idea.
