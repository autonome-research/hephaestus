"""Spike C: OCCT sanity checks, timed against verification.md budgets
(reference shelf full build <= 30 s).

(a) oversized fillet MUST fail -> capture exception type + message
(b) boolean union of 30 overlapping solids -> wall time
(c) STEP round-trip of a nontrivial part via OCP-backed importer ->
    solid count equal, volume within 1e-3 relative -> wall time

Exit 0 only if all three behave as required.
"""

import json
import time
import sys

from build123d import (
    Axis,
    BuildPart,
    Box,
    Cylinder,
    GridLocations,
    Hole,
    Locations,
    Mode,
    Part,
    export_step,
    fillet,
    import_step,
)

results: dict = {}
t_total = time.perf_counter()

# (a) oversized fillet must fail --------------------------------------------
t0 = time.perf_counter()
try:
    with BuildPart() as bp:
        Box(10, 10, 10)
        fillet(bp.edges().filter_by(Axis.Z), radius=1000.0)  # absurd radius
    results["fillet_fail"] = {"failed_as_required": False}
except Exception as e:  # noqa: BLE001 - we want whatever OCCT raises
    results["fillet_fail"] = {
        "failed_as_required": True,
        "exception_type": type(e).__name__,
        "exception_module": type(e).__module__,
        "message": str(e)[:300],
    }
results["fillet_fail"]["wall_s"] = round(time.perf_counter() - t0, 3)

# Same failure through raw OCP, to record the underlying OCCT exception type
try:
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopoDS import TopoDS

    shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    mk = BRepFilletAPI_MakeFillet(shape)
    ex = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_EDGE)
    while ex.More():
        mk.Add(1000.0, TopoDS.Edge_s(ex.Current()))
        ex.Next()
    mk.Build()
    raw_shape = mk.Shape()  # raises if not done
    results["fillet_fail_raw_ocp"] = {"failed_as_required": False}
except Exception as e:  # noqa: BLE001
    results["fillet_fail_raw_ocp"] = {
        "failed_as_required": True,
        "exception_type": type(e).__name__,
        "exception_module": type(e).__module__,
        "message": str(e)[:300],
    }

# (b) boolean union of 30 overlapping solids --------------------------------
t0 = time.perf_counter()
solids = []
for i in range(30):
    with BuildPart() as sp:
        with Locations((i * 3.0, (i % 5) * 2.0, (i % 3) * 1.5)):
            Box(10, 10, 10)
    solids.append(sp.part)
build_s = time.perf_counter() - t0

t0 = time.perf_counter()
fused: Part = solids[0]
for s in solids[1:]:
    fused = fused + s  # sequential OCCT BRepAlgoAPI_Fuse, worst case
fuse_s = time.perf_counter() - t0
results["boolean_30"] = {
    "n_input_solids": 30,
    "result_solids": len(fused.solids()),
    "result_volume": round(fused.volume, 6),
    "build_wall_s": round(build_s, 3),
    "fuse_wall_s": round(fuse_s, 3),
}

# (c) STEP round-trip of a nontrivial part ----------------------------------
t0 = time.perf_counter()
with BuildPart() as np_:
    Box(120, 80, 20)
    fillet(np_.edges().filter_by(Axis.Z), radius=8)
    with GridLocations(30, 25, 3, 2):
        Hole(radius=4)
    with Locations((0, 0, 10)):
        Cylinder(radius=15, height=25)
    fillet(np_.part.edges().group_by(Axis.Z)[-1], radius=2)
part = np_.part
build_s = time.perf_counter() - t0

step_path = "out/sanity_part.step"
t0 = time.perf_counter()
export_step(part, step_path)
export_s = time.perf_counter() - t0
t0 = time.perf_counter()
reimported = import_step(step_path)  # OCP STEPControl_Reader under the hood
import_s = time.perf_counter() - t0

n_out, n_in = len(part.solids()), len(reimported.solids())
v_out, v_in = part.volume, reimported.volume
rel = abs(v_in - v_out) / v_out
results["step_roundtrip"] = {
    "solids_exported": n_out,
    "solids_reimported": n_in,
    "volume_exported": round(v_out, 6),
    "volume_reimported": round(v_in, 6),
    "volume_rel_diff": rel,
    "build_wall_s": round(build_s, 3),
    "export_wall_s": round(export_s, 3),
    "import_wall_s": round(import_s, 3),
    "ok": n_out == n_in and rel < 1e-3,
}

results["total_wall_s"] = round(time.perf_counter() - t_total, 3)
print(json.dumps(results, indent=2))

ok = (
    results["fillet_fail"]["failed_as_required"]
    and results["boolean_30"]["result_solids"] == 1
    and results["step_roundtrip"]["ok"]
    and results["total_wall_s"] < 600  # 10-minute budget
)
print("OCCT_SANITY:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
