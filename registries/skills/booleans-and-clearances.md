# Booleans and clearances

Reference for combining solids and for the thing that actually decides whether a
design assembles: **clearance you declared on purpose**. Two parts that touch at
exactly nominal dimensions do not fit. The fix is not smaller numbers, it is a
named parameter with a bound, plus a check that proves the gap survived your last
edit.

## The three operators

```text
a + b     fuse      union of both solids
a - b     cut       a with b removed (b is a "cutter", need not be inside a)
a & b     intersect the shared volume — usually a diagnostic, not a feature
```

They work on single shapes, on lists (`_panel + _fingers`), and compose left to
right. Each returns a new shape; nothing mutates in place.

```python
PARAMS = {
    "wall": Param(3.0, min=1.5, max=8.0, doc="housing wall thickness, mm"),
}

_wall = p.wall
_w = 70.0
_d = 45.0
_h = 28.0

_shell = Box(_w, _d, _h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_cavity = Box(_w - 2 * _wall, _d - 2 * _wall, _h, align=(Align.CENTER, Align.CENTER, Align.MIN))
_housing = _shell - Pos(0.0, 0.0, _wall) * _cavity

# One cutter, reused: a through-bore built once and placed twice.
_bore = Cylinder(3.0, _wall + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_housing = _housing - Pos(-20.0, 0.0, _wall / 2) * _bore
_housing = _housing - Pos(20.0, 0.0, _wall / 2) * _bore

_housing.label = "housing"
part.geometry = _housing
part.description = "Open-top housing: shell minus cavity, then the floor bores."

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    "floor_left": lambda m: m.volume("part") >= 6000.0,
}
```

Two habits that pay off immediately:

- **Build a cutter once, place it many times.** `_bore` above is one solid
  multiplied by locations. When the bore diameter changes, one number changes.
- **Oversize cutters along the cut direction.** `_wall + 2.0` rather than
  `_wall`. A cutter that ends exactly on the face it is cutting through leaves a
  coincident-face boolean, which is the classic source of "sealed = False" and of
  zero-thickness slivers that later fillets choke on.

## Coincident faces are the enemy

```text
bad     _plate - Cylinder(r, plate_t, ...)        cutter ends flush with both faces
good    _plate - Cylinder(r, plate_t + 2.0, ...)  cutter overshoots by 1 mm each side

bad     _box - Pos(0, 0, wall) * Box(w - 2*wall, d - 2*wall, h - wall)
        cavity top exactly at the box top
good    _box - Pos(0, 0, wall) * Box(w - 2*wall, d - 2*wall, h)
        cavity runs past the top; the open top is intentional
```

The kernel is allowed to succeed on a coincident-face boolean and often does. The
problem is that it sometimes produces a valid-but-degenerate result — a face of
zero area, an edge of zero length — which survives `sealed` and then breaks a
fillet, a mesh export or a section render several operations later. Overshoot
costs nothing and removes the whole failure class.

## Clearance is a parameter, never a literal

Any gap between mating features has a reason and a tolerance. Give it a name, a
default, and bounds.

```python
PARAMS = {
    "shaft_d": Param(8.0, min=3.0, max=20.0, doc="nominal shaft diameter, mm"),
    "running_clear": Param(0.20, min=0.05, max=0.60,
                           doc="radial clearance for a running fit, mm"),
    "print_swell": Param(0.10, min=0.0, max=0.40,
                         doc="allowance for FDM outer-contour oversizing, mm"),
}

_shaft_d = p.shaft_d
_clear = p.running_clear
_swell = p.print_swell
_block_t = 14.0

# Total gap: the fit clearance PLUS what the process adds back.
_bore_d = _shaft_d + 2 * (_clear + _swell)

_block = Box(30.0, 24.0, _block_t, align=(Align.CENTER, Align.CENTER, Align.MIN))
_bore = Cylinder(_bore_d / 2, _block_t + 2.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_bearing_block = _block - Pos(0.0, 0.0, -1.0) * _bore

_bore_face = _bearing_block.faces().filter_by(GeomType.CYLINDER)[0]
tag(_bore_face, "shaft_bore")
part.feature("shaft_bore").general_tolerance = "H8; ream after printing if binding"

_bearing_block.label = "bearing_block"
part.geometry = _bearing_block
part.process = "fdm"

CHECKS = {
    # The bore must be the nominal shaft plus the declared gap, not "about right".
    # 8.0 + 2 * (0.20 + 0.10) = 8.60 mm, bracketed both ways.
    "bore_not_oversize": lambda m: m.bbox("shaft_bore") <= (8.65, 8.65, 15.0),
    "bore_not_undersize": lambda m: m.bbox("shaft_bore") >= (8.55, 8.55, 13.0),
    "sealed": lambda m: m.sealed("part"),
}
```

Note the two-sided bracket. A single `<=` bound passes on a bore that came out at
zero diameter; asserting both ends is what makes the check mean "this dimension",
and `m.bbox` on a tagged cylindrical face is the cheapest way to read a bore back
out of the built geometry.

Why split `running_clear` from `print_swell`: they change for different reasons.
The fit clearance is a *design* decision (running, locating, press). The swell
allowance is a *process* decision that changes when you change printer, material
or nozzle. Collapsing them into one 0.3 mm literal means nobody can retune either
one without guessing which half they are touching.

Rules of thumb worth encoding as parameter defaults, not as literals:

```text
free running fit       0.20 - 0.40 mm radial     rotating shaft in a bore
locating / slip fit    0.05 - 0.15 mm radial     assembles by hand, no play wanted
press / interference  -0.02 - -0.05 mm radial    needs force or heat; check both parts
sheet slot into tab    0.00 - 0.10 mm per side   plus kerf; see the sheet-goods reference
FDM outer contour     +0.05 - 0.20 mm           holes come out small, posts come out big
lid onto a rim         0.15 - 0.30 mm per side   or it will not go on after a warp
```

## Prove the gap with a check, not with a render

A render shows that two solids *look* separated. `m.interference` and
`m.clearance` measure it.

```python
PARAMS = {
    "lid_clear": Param(0.25, min=0.05, max=0.60, doc="lid-to-rim clearance per side, mm"),
}

_clear = p.lid_clear
_w = 60.0
_d = 40.0
_wall = 2.4
_rim_h = 4.0

_body = Box(_w, _d, 20.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_body = _body - Pos(0.0, 0.0, _wall) * Box(
    _w - 2 * _wall, _d - 2 * _wall, 20.0, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_body.label = "body"

# The lid skirt drops inside the body's opening, one clearance short per side.
_skirt_w = _w - 2 * _wall - 2 * _clear
_skirt_d = _d - 2 * _wall - 2 * _clear
_lid_plate = Pos(0.0, 0.0, 20.0) * Box(
    _w, _d, _wall, align=(Align.CENTER, Align.CENTER, Align.MIN)
)
_lid_plate.label = "lid_plate"
_lid_skirt = Pos(0.0, 0.0, 20.0) * Box(
    _skirt_w, _skirt_d, _rim_h, align=(Align.CENTER, Align.CENTER, Align.MAX)
)
_lid_skirt.label = "lid_skirt"

part.geometry = Compound(children=[_body, _lid_plate, _lid_skirt])
part.description = "Body and lid modelled in the assembled position."
part.assembly_method = "lid skirt drops into the body opening"

CHECKS = {
    # Assembled position, zero overlap: the fit is real, not eyeballed.
    "plate_seats": lambda m: m.interference("lid_plate", "body") == approx(0, abs=1e-6),
    "skirt_clears": lambda m: m.interference("lid_skirt", "body") == approx(0, abs=1e-6),
    # And the gap is the gap we declared, not an accident.
    "skirt_gap": lambda m: m.clearance("lid_skirt", "body") >= 0.25 - 1e-6,
}
```

Each mating solid is labelled separately. That is what makes the checks
addressable: `interference("lid_plate", "body")` is zero because the plate *seats*
on the rim (touching is not interference), and `clearance("lid_skirt", "body")` is
the lateral gap you asked for. Had the two been fused into one `lid` solid, the
touching plate would drive `clearance` to zero and the gap assertion would be
meaningless.

The discipline: **model mating parts in their assembled position** and let
`interference` be zero by construction. Then the check is a one-liner and it
catches every future edit that eats the gap — a wall thickness change, a mirror
that became a translation, a parameter retune that overshot its bound.

For cross-part checks, the same predicates live in `checks/*.py` with a facade
that can address any part:

```text
# checks/fit.py
CHECKS = {
    "lid_clears_body": lambda m: m.interference("lid_part/lid", "body_part/shell")
        == approx(0, abs=1e-6),
    "rail_gap": lambda m: m.clearance("carriage/shoe", "rail/web") >= approx(0.3, abs=0.02),
}
```

## Intersection as a diagnostic

`&` is rarely a feature and often the fastest way to see *where* two solids
collide.

```python
_a = Box(40.0, 40.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_b = Pos(15.0, 0.0, 4.0) * Box(40.0, 20.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))
_overlap = _a & _b
_overlap.label = "overlap_volume"
_overlap.color = Color(0.85, 0.25, 0.25)

_a.label = "part_a"
_b.label = "part_b"
part.geometry = Compound(children=[_a, _b, _overlap])
part.description = "Interference made visible: the intersection as its own labelled solid."

CHECKS = {
    # A deliberately failing-style assertion inverted: there IS overlap here.
    "overlap_present": lambda m: m.volume("overlap_volume") >= 1.0,
}
```

Label the intersection, render it in a loud colour, and it shows up in the mask
render and in the geometry tree. Once the collision is fixed the intersection is
empty and the labelled solid disappears — which is itself a signal, so prefer a
`CHECK` on `interference` for the permanent record and keep the `&` trick for the
five minutes you are debugging.

## Boolean ordering

1. **Everything additive that defines the body.** Fuse the shell, bosses, ribs
   and lugs into one solid first.
2. **Everything subtractive.** Cavities, bores, slots, reliefs — largest first if
   any of them overlap, because overlapping cutters fused into one cutter behave
   better than a chain of individual cuts.
3. **Dressing last.** `fillet` and `chamfer` operate on edges that must still
   exist afterwards.
4. **Assembly compound last of all.** Label each solid, then
   `Compound(children=[...])`.

When step 2 produces something odd, fuse the cutters into one solid and subtract
once:

```python
_plate = Box(80.0, 40.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MIN))

_slot = Box(50.0, 8.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
_cross = Box(8.0, 30.0, 12.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
# Fuse the overlapping cutters, then cut once: one boolean instead of two.
_cutter = Pos(0.0, 0.0, 5.0) * (_slot + _cross)
_plate = _plate - _cutter

_plate.label = "cross_slot_plate"
part.geometry = _plate

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    # The fused cutter goes right through the plate, so the cross is ONE tunnel:
    # genus 1, not genus 0. Assert what the topology actually is.
    "one_tunnel": lambda m: m.genus("part") == 1,
}
```

## Failure signatures and what they mean

```text
sealed = False after a cut
    coincident faces, or a cutter that ended exactly on a surface. Overshoot it.

genus higher than expected
    a cut punched through where you meant a pocket, or two cutters merged into a
    tunnel. Render a section on the axis you cut along.

volume unchanged after a subtraction
    the cutter missed. Check the placement, and remember Align: a Box aligned
    MIN in Z starts at z = 0 and goes up, not centred.

a later fillet fails on an edge you can see
    the boolean left a sliver face there. Look for a dimension that came out as
    exactly 0 mm, and give the cutter a real overshoot.

interference check fails by a tiny amount
    two solids share a face in the assembled position. That is not interference
    in the manufacturing sense; use approx(0, abs=1e-6) rather than == 0.
```
