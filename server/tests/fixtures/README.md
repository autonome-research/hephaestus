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
