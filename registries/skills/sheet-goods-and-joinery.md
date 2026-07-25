# Sheet goods and joinery

Reference for designing parts cut from flat stock — plywood, MDF, acrylic,
aluminium sheet — and for the joints that hold them together. The governing fact
is that **sheet thickness is a project-wide variable, not a number you type**.
Every slot width, finger length, tab depth and shoulder position derives from it.
Get that one dependency right and a thickness change re-cuts the whole design;
get it wrong and you have twenty numbers to chase.

## Thickness and kerf belong in `globals.py`

```python globals
PARAMS = {
    "sheet_t": Param(6.0, min=3.0, max=18.0, doc="nominal sheet thickness, mm"),
    "kerf": Param(0.20, min=0.0, max=0.60, doc="cutter kerf removed per side, mm"),
    "joint_clear": Param(0.05, min=0.0, max=0.30,
                         doc="extra clearance per side on a slip joint, mm"),
    "tray_w": Param(220.0, min=100.0, max=600.0, doc="internal tray width, mm"),
    "tray_d": Param(140.0, min=80.0, max=400.0, doc="internal tray depth, mm"),
    "tray_h": Param(60.0, min=30.0, max=200.0, doc="internal tray height, mm"),
}

sheet_t = p.sheet_t
kerf = p.kerf
joint_clear = p.joint_clear

tray_w = p.tray_w
tray_d = p.tray_d
tray_h = p.tray_h

# A slot that receives a sheet must be a sheet thick, plus what the cutter takes
# out of the SLOT walls, plus the fit clearance. Derived once, used everywhere.
slot_w = sheet_t + 2 * kerf + 2 * joint_clear

# Overall panel sizes, so two parts cannot disagree about the box.
panel_span_w = tray_w + 2 * sheet_t
panel_span_d = tray_d + 2 * sheet_t

# Finger geometry: fingers are one sheet thickness long so they land flush.
finger_len = sheet_t
finger_w = 12.0
```

Why `slot_w` is derived and not typed: the cutter removes material from *both*
walls of a slot, so a nominally 6 mm slot cut with a 0.2 mm kerf per side comes
out 6.4 mm wide. If you want a snug joint you must cut the slot *nominal* and let
kerf open it up, or cut it undersize deliberately. Naming the intent
(`slot_w = sheet_t + 2 * kerf + 2 * joint_clear`) makes that decision reviewable.

Kerf direction differs by process, and this is the single most common way a sheet
design comes back wrong:

```text
laser / waterjet   kerf ~0.15-0.25 mm total at 6 mm; the beam is narrow, and the
                   cut face is slightly tapered. Kerf per side ~0.08-0.12 mm.
CNC router         the tool removes its FULL diameter. A 3 mm bit cutting a slot
                   on the line gives a 3 mm-wide slot; slots narrower than the
                   tool are impossible. Compensate by offsetting the toolpath,
                   not by changing the model.
saw / blade        1.5-3 mm; only relevant for straight rips, and usually handled
                   by the cut list rather than the model.
```

And nominal sheet thickness lies. 6 mm Baltic birch is routinely 5.6-6.0 mm and
varies within one sheet. **Measure the actual stock, set `sheet_t` to what you
measured, and rebuild** before committing a whole design to material.

## Finger joints

A finger joint alternates fingers and gaps along an edge. Two mating panels share
one pitch; one panel starts on a finger, the other starts on a gap.

```python
_t = hc.sheet_t
_span = hc.panel_span_w
_depth = hc.tray_d
_finger_w = hc.finger_w
_finger_len = hc.finger_len

# Odd finger count so the joint is symmetric about the centreline.
_count = 5
_pitch = 2 * _finger_w
_row_span = _pitch * _count - _finger_w

_floor = Box(_span, _depth, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))

# Fingers stand proud of the +Y edge by exactly one sheet thickness.
_fingers = []
for _i in range(_count):
    _x = -_row_span / 2 + _i * _pitch
    _finger = Pos(_x, _depth / 2 + _finger_len / 2, _t / 2) * Box(
        _finger_w, _finger_len, _t, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    _fingers.append(_finger)

_panel = _floor + _fingers
_panel.label = "tray_floor"
part.geometry = _panel
part.description = "Tray floor with a finger row on the rear edge."
part.material_spec = "Baltic birch plywood, BB/BB"
part.process = "laser_cut"
part.stock_form = "sheet"
part.joint = "5 fingers, 12 mm wide, one sheet thickness long"

CHECKS = {
    # The fingers must add exactly one sheet thickness to the panel depth.
    "depth_with_fingers": lambda m: m.bbox("part") <= (
        hc.panel_span_w + 0.05, hc.tray_d + hc.finger_len + 0.05, hc.sheet_t + 0.05
    ),
    "all_fingers_present": lambda m: m.volume("_fingers#*")
    >= 4.5 * hc.finger_w * hc.finger_len * hc.sheet_t,
    "sealed": lambda m: m.sealed("part"),
}
```

Note `_fingers#*` in the check. `_fingers` is a **list binding** accumulated in a
loop, so `_fingers#*` addresses the fused compound of every member and
`_fingers#3` the third in append order — that is how you assert "all the fingers
are there" without naming each one.

Do not reach for a `.label` here. A label addresses a node that is still in the
geometry tree, and `_floor + _fingers` fuses the fingers into one solid: the child
nodes (and their labels) stop existing at that moment. Labels survive only where
the shape survives as a tree node — a `Compound` child, a separate lamination.
After a fuse, the binding name is the handle that still works. Getting this
backwards produces `selector 'finger#*' resolves to nothing`, which is the
addressing layer telling you the truth: that node was consumed by a boolean.

Finger-joint rules worth internalising:

- **Finger length = one sheet thickness** for a flush outer face. Longer fingers
  protrude (sometimes wanted, as a design feature — then say so in `part.joint`).
- **Odd finger count** keeps the joint symmetric about the panel centreline, so a
  mirrored mating panel lines up without an offset.
- **Finger width ≥ 2× sheet thickness.** Narrow fingers in plywood snap along the
  grain; in acrylic they craze.
- **The mating panel's slots use `hc.slot_w`, not `hc.sheet_t`.** This is the
  single most common joinery bug: cutting the receiving slot at nominal thickness
  and then wondering why the joint needs a mallet.

## Slots that receive a finger row

```python
_t = hc.sheet_t
_h = hc.tray_h
_span = hc.panel_span_w

_finger_w = hc.finger_w
_finger_len = hc.finger_len
_count = 5
_pitch = 2 * _finger_w
_row_span = _pitch * _count - _finger_w

# The gap that receives a finger is the finger plus kerf and fit clearance per
# side — the same derivation hc.slot_w makes for a sheet-in-a-slot, applied to
# the finger's width instead of its thickness.
_gap_w = _finger_w + 2 * hc.kerf + 2 * hc.joint_clear

_wall = Box(_span, _h, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))

# One cutter, placed per gap: as wide as the finger plus clearance, as deep as
# the finger is long, overshooting the panel edge in -Y and the sheet in Z so
# both cuts run clean out of material.
_gap = Box(_gap_w, _finger_len + 1.0, _t + 2.0,
           align=(Align.CENTER, Align.MIN, Align.CENTER))
for _i in range(_count):
    _x = -_row_span / 2 + _i * _pitch
    _wall = _wall - Pos(_x, -_h / 2 - 1.0, _t / 2) * _gap

_wall.label = "tray_wall"
part.geometry = _wall
part.description = "Tray wall with the gap row that receives the floor fingers."
part.process = "laser_cut"
part.general_tolerance = "+/-0.25 mm cut profile; gaps kerf-compensated per side"

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    # Five gaps cut INTO the lower edge, each one a notch, so the panel stays
    # genus 0. If this reads 5 instead of 0 the cutters no longer reach the
    # edge and every notch closed into a tunnel — a mortise, not a finger gap.
    "notches_not_tunnels": lambda m: m.genus("part") == 0,
    "gap_row_removed": lambda m: m.volume("part")
    <= hc.panel_span_w * hc.tray_h * hc.sheet_t - 4.5 * 12.0 * 6.0 * 6.0,
}
```

`genus` earns its place in that check set: it is the cheapest possible witness
that a notch is still open to the edge. A through-mortise and an edge notch look
almost identical in an iso render and differ by exactly one topological hole.

The cross-part check that actually proves the joint lives in `checks/*.py`, where
the facade can address both panels:

```text
# checks/joinery.py
CHECKS = {
    "fingers_seat_in_gaps": lambda m: m.interference(
        "tray_floor/_fingers#*", "tray_wall/tray_wall") == approx(0, abs=1e-6),
    "joint_not_loose": lambda m: m.clearance(
        "tray_floor/_fingers#*", "tray_wall/tray_wall") <= approx(0.15, abs=1e-6),
}
```

Model both panels in their **assembled** positions in a project snapshot and this
pair of checks is the whole joint specification: no overlap (it goes together) and
no excessive gap (it will not rattle).

## Tabs and mortises

A tab-and-mortise joint is a finger joint with one finger. Use it where a full
finger row is overkill — a divider into a floor, a leg into a rail.

```python
_t = hc.sheet_t
_slot_w = hc.slot_w

_divider = Box(120.0, 80.0, _t, align=(Align.CENTER, Align.CENTER, Align.MIN))

_tab_w = 20.0
_tab_len = _t
_tabs = []
for _x in (-35.0, 35.0):
    _tab = Pos(_x, -40.0 - _tab_len / 2, _t / 2) * Box(
        _tab_w, _tab_len, _t, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    _tabs.append(_tab)
_divider = _divider + _tabs

# A relief notch at each tab root: without it the inside corner is a stress
# riser and the laser's corner radius fights the mating slot's square end.
_relief = Cylinder(0.8, _t + 2.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
for _x in (-35.0 - _tab_w / 2, -35.0 + _tab_w / 2, 35.0 - _tab_w / 2, 35.0 + _tab_w / 2):
    _divider = _divider - Pos(_x, -40.0, _t / 2) * _relief

_divider.label = "divider"
part.geometry = _divider
part.description = "Tray divider with two tabs and corner relief at each tab root."
part.process = "laser_cut"
part.joint = "two 20 mm tabs, one sheet thickness long, 1.6 mm root relief"

CHECKS = {
    "sealed": lambda m: m.sealed("part"),
    "tabs_present": lambda m: m.volume("_tabs#*") >= 2 * 20.0 * 6.0 * 6.0 * 0.9,
}
```

**Corner relief is not optional.** Every real cutter has a finite corner radius,
so an internal square corner comes out rounded and the mating tab will not seat.
A small circle subtracted at each internal corner (dogbone or T-bone relief) gives
the tab somewhere to go. Size it at or just above the cutter radius.

## Laminations

Stacking sheets is how you get thickness out of thin stock. Each lamination is a
separate labelled solid so the cut list and the renders both make sense.

```python
_t = hc.sheet_t
_layers = 3

_profile = make_face(
    Polyline((0.0, 0.0), (90.0, 0.0), (90.0, 30.0), (40.0, 55.0), (0.0, 55.0), close=True)
)

_stack = []
for _i in range(_layers):
    _layer = extrude(Plane.XY.offset(_i * _t) * _profile, amount=_t)
    _layer.label = "lamination"
    _layer.color = Color(0.75 - 0.12 * _i, 0.62, 0.42)
    _stack.append(_layer)

# The middle lamination is short, leaving a pocket the outer plies close over.
_pocket = Box(40.0, 20.0, _t + 0.2, align=(Align.CENTER, Align.CENTER, Align.MIN))
_stack[1] = _stack[1] - Pos(45.0, 27.0, _t - 0.1) * _pocket

part.geometry = Compound(children=_stack)
part.description = "Three-ply lamination with a captive pocket in the middle ply."
part.material_spec = "three laminations of sheet stock"
part.stock_form = "sheet"
part.blank_size = "three 90 x 55 profiles"
part.assembly_method = "PVA each face; clamp flat until cured"

CHECKS = {
    "three_layers": lambda m: m.volume("lamination#*") >= 2.0 * 90.0 * 30.0 * 6.0,
    "stack_height": lambda m: m.bbox("part") <= (90.05, 55.05, 3 * hc.sheet_t + 0.05),
}
```

Lamination notes:

- **Colour each layer differently.** In an rgb render you can then see instantly
  whether the middle ply is where you think it is.
- **A captive pocket in a middle ply** is the sheet-goods equivalent of a
  machined cavity: cut it in one layer, and the layers above and below close it.
  It needs no undercut and no second setup.
- **Glue face-grain to face-grain.** Plywood laminations bond well flat; screwing
  into plywood end-grain splits it. Say so in `part.assembly_method` so the
  information survives to whoever builds it.
- **Watch the stack height parameter.** `_layers * sheet_t` — never a typed
  literal, or a thickness change silently breaks every mating depth.

## Nesting and the cut list

Stage 2 exports `as_built` geometry: each part comes out in its modelled
position, one DXF or SVG profile per closed outline. Automatic sheet nesting is a
later capability, so for now:

- Keep every sheet part **flat in the XY plane with its thickness in Z**. A part
  modelled standing up exports as a side view, and no amount of downstream
  processing will recover the intent.
- Record the blank in `part.blank_size` (`"two 220 x 140 profiles"`). That is the
  cut list, and it is the field a fabricator actually reads.
- Count your outlines. A panel with five slots and one outer profile is *one*
  closed outer outline plus five inner ones — knowing the number lets you assert
  the export is complete rather than hoping.
- One part per sheet thickness. Mixing 3 mm and 12 mm outlines into one part
  makes both the cut list and the DFM rules ambiguous.

## Checklist before cutting material

```text
sheet_t set from a MEASURED sample, not the label on the sheet
kerf set for the actual process and tool
every slot width derived from hc.slot_w, never typed
every finger/tab length derived from hc.sheet_t
internal corners have relief at or above the cutter radius
fingers at least 2 x sheet_t wide
cross-part interference check passes in the assembled snapshot
each panel flat in XY, thickness in Z
part.blank_size names the blank; part.process names the cutter
```
