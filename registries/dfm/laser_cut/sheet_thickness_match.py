# laser_cut.sheet_thickness_match — the design must be cut from stock that exists.
#
# Sheet-goods designs encode their thickness everywhere: tab lengths, slot
# widths, lamination counts. If the modelled thickness is not a size the named
# material is sold in, every one of those dimensions is wrong by the difference
# — and the error only surfaces at assembly. This rule joins the measured
# thickness (the part's smallest bounding-box extent) to the materials-registry
# record that part.material_spec resolves to.
#
# Reads: thickness_tolerance_mm.


def evaluate(ctx):
    tolerance = ctx.param("thickness_tolerance_mm")
    measured = ctx.sheet_thickness()
    solids = ctx.solids()
    refs = [solids[0]] if solids else []
    spec = ctx.metadata.get("material_spec", "")
    material = ctx.material

    if material is None:
        named = spec if spec else "(unset)"
        ctx.report(
            f"part.material_spec {named!r} does not resolve to any materials-registry "
            f"record, so the {measured:.3f} mm modelled sheet thickness cannot be "
            "checked against a stock size",
            refs=refs,
            measured={"thickness_mm": measured, "material_spec": spec},
        )
        return

    name = material.get("name", material.get("id", "the material"))
    thicknesses = []
    for value in material.get("thicknesses", []):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        thicknesses.append(float(value))

    if not thicknesses:
        ctx.report(
            f"{name} carries no stock thicknesses in the materials registry, so the "
            f"{measured:.3f} mm modelled sheet cannot be matched to stock",
            refs=refs,
            measured={"thickness_mm": measured, "material": name},
        )
    else:
        nearest = min(thicknesses, key=lambda t: abs(t - measured))
        if abs(nearest - measured) > tolerance:
            offered = ", ".join(f"{t:g}" for t in sorted(thicknesses))
            ctx.report(
                f"modelled sheet thickness {measured:.3f} mm is not a stock size for "
                f"{name} (available: {offered} mm, tolerance {tolerance:g} mm); the "
                f"nearest is {nearest:g} mm",
                refs=refs,
                measured={
                    "thickness_mm": measured,
                    "nearest_stock_mm": nearest,
                    "stock_thicknesses_mm": sorted(thicknesses),
                    "material": name,
                },
                suggested_bound=nearest,
            )

    stock_form = ctx.metadata.get("stock_form", "")
    forms = []
    for value in material.get("forms", []):
        if isinstance(value, str):
            forms.append(value)
    if stock_form and forms and stock_form not in forms:
        ctx.report(
            f"part.stock_form {stock_form!r} is not a form {name} is supplied in "
            f"({', '.join(sorted(forms))})",
            refs=refs,
            measured={"stock_form": stock_form, "forms": sorted(forms)},
        )
