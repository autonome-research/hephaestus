# Recorded fixtures

`bracket_101_s2_bracket.py` / `bracket_101_s2_globals.py` are the **verbatim**
part script and `globals.py` of the recorded `bracket-101` seed-2 run
(`bench/results/Qwen3.6-27B-NVFP4/2026-07-26/bracket-101-s2/project/`), the
measured failure `VALIDATION.md` exists to catch: the wall is placed outside the
stated footprint, so the bracket measures 46 mm in Y against a request that says
40 mm — and the model's own `CHECKS` envelope encodes the misreading and passes.

They are evidence, not example code. Do not "fix" them: `test_build_critique.py`
asserts the §4 critique fires `unmatched_request_number` and
`dimension_mismatch` on exactly this geometry.

## `corpus_variants/`

Second, independent implementations of corpus tasks, laid out exactly like
`corpus/solutions/<id>/` so `grade_reference_solution(..., solutions_dir=...)`
grades them through the ordinary path.

They exist because `corpus/solutions` cannot validate a task's *checks*: those
checks were authored from that solution, so "a task no reference solution
passes is broken" passes trivially — the same self-referential trap
`VALIDATION.md` describes for model-authored `CHECKS`, one level up. A variant
is deliberately a **different correct design** (different construction order,
different in-spec dimensions, different wording), so a check that demands the
reference geometry back fails here and nowhere else.

Added by the 2026-07-26 corpus audit for the two tasks it re-authored:

- `enclosure-bosses/` — assembled shell with a 0.3 mm base chamfer, and a lid
  whose register is a peripheral rib at 0.3 mm clearance instead of a solid
  block at 0.2. ~6800 mm³ away from the reference lid; the retired
  `lid_register_clearance` check allowed ±20.
- `drawing-shelf/` — same shelf built sides-first, with every §5.2 metadata
  field worded differently. The retired drawing requirement matched the
  material line verbatim.
- `cat-step/` — the flagship prose task, whose dimensions are fully specified
  and whose *detailing* therefore carries all the freedom a correct run has:
  the tread is profiled in 2D and extruded (the reference fillets in 3D), the
  gusset is a blank cut to its hypotenuse (the reference extrudes a polygon),
  and the tread's top edges are eased by 1 mm — ~490 mm³, outside the ±400
  window the material check carried before the audit and inside the ±600 it
  carries now.

Keep them different. Converging a variant on the reference deletes the guard.
