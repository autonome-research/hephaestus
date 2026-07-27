# 07 — Ingest (Stage 8A)

Normative. Amends `mission_plan.md` (Stage 8), `script_contract.md` (one new
injected name), `tool_schema.md` (reference tools), and `VALIDATION.md` §2
(document-cited requirements). Design premise, from the maintainer: the goal
is a frontier CAD harness — real work starts from something that already
exists (a vendor STEP, a drawing, a datasheet), so ingest is core capability,
not an adapter.

## 1. STEP import: a term in the expression, never a mode

```python
base = import_step("bracket.step")          # a statement like any other
part.geometry = base - Cylinder(3, 20) + rib
```

The part script REMAINS the single source of truth: "take this file, apply
these operations" is reproducible, versionable, checkable. The imported solid
is a constant in the expression — the same shape-as-value pattern the parts
store already uses. **Feature recognition is explicitly out of scope**: no
inference of parameters or design intent from B-rep. The docs say so plainly.

Mechanics (all rule-enforced):

- **Files live under `imports/`** in the project root. `import_step` accepts a
  path relative to `imports/` only; absolute paths, traversal, and symlink
  escapes are rejected with the standard path-confinement machinery
  (`openat2`-class recheck; never preflight-trusted).
- **Harness-resolved, never script I/O.** The injected namespace still forbids
  `open`/filesystem. The executor resolves each declared import BEFORE the
  worker runs: it reads and hashes the file outside the sandbox, converts to
  BRep once, and stages the BRep read-only in the worker's input area. The
  worker's `import_step` merely deserializes the staged shape. A missing or
  unparseable file is a §8 build error at the `import_step` statement.
- **Content-addressed build input.** The build freeze records
  `input_hashes.imports = {"bracket.step": "sha256:…"}` alongside script/
  params/toolchain — a changed file is a changed input: current-pointer
  revalidation fails, staleness propagates, and a lost-response retry replays
  against the ORIGINAL bytes exactly as for scripts. Identical bytes ⇒
  identical geometry (STEP parsing is deterministic for a pinned OCCT).
- **Provenance honesty.** The source map attributes each imported solid to its
  `import_step` statement (binding scope). Imported faces have NO per-face
  creating statement — the same honesty rule as boolean results. `tag()` works
  on imported topology by selector; §5.3 drift fingerprints apply across
  re-imports and are the ONLY warning when a replaced file moves a tagged
  face, so they are load-bearing here, not optional.
- **Formats**: STEP (AP203/AP214 read) in 8A. IGES/BREP may follow; each is an
  explicit contract amendment.

## 2. Reference documents and images

A project may carry `references/` — drawings, datasheets, photos, PDFs.
They are **operator-supplied context**, not model-writable artifacts.

- **Registration is operator-side** (`heph reference add <file>`, or seeded by
  a bench task). The model cannot add references; it can only read them. Each
  is content-addressed at registration; the registry is part of project state.
- **Model surface** (canonical pipeline, both profiles):
  - `list_references() -> [{name, kind: document|image, pages?, sha256}]`
  - `read_reference(name, page?, offset_bytes?)` — documents return extracted
    text inside provenance delimiters under the standard 50 KiB/2000-line dual
    cap with byte-cursor paging; images return inline image content within the
    existing §5 image budgets plus the artifact ref. Reference content is
    REFERENCE MATERIAL under the provenance-delimiter instruction — never
    instructions.
- **Requirement ledger integration** (`VALIDATION.md` §2 extension): a
  `specified` entry may cite a reference instead of a prompt phrase:
  `{"source": "specified", "cite": {"reference": "sheet2.pdf", "page": 2,
  "quote": "Ø6.0 ±0.1"}}`. `heph lint`'s `unsourced_requirement` verifies a
  document citation against the extracted text; an IMAGE citation (a callout
  on a drawing) is lint-`unverifiable` and MUST be verified by the §5
  termination reviewer through the vision channel — recorded per finding, so
  §8's channel split now measures document-grounded work too.
- **Bench**: task fixtures may seed `references/` (generation-from-drawing
  tasks) and `imports/` (editing tasks). This is the substrate for external
  benchmarks: CADGenBench generation = image references; editing = seeded
  imports.

## 3. What deliberately does NOT change

No new persistence machinery (imports and references ride opstore CAS).
No script-side file access of any kind. No feature recognition. No new
session profile. The engine-first rule holds: everything in §1 lives in
core; §2's tool surface lives in the contract + server layers.

## Gate G8A

`uv run pytest tests/stage8a -q` exits 0, covering: import resolution +
staging (happy path; missing file, corrupt STEP, traversal/symlink escape all
refused with named errors at the right layer); the worker cannot open import
paths directly (sandbox denial proven); determinism (same bytes ⇒ identical
metrics twice); input-hash invalidation (replaced file ⇒ stale, revalidation
refuses current-flip, retry replays original bytes); source-map attribution of
imported solids + the no-per-face-statement rule; tag + drift fingerprint
across a re-import that moves a tagged face (warns with baseline ref, no-op
re-import silent); mixed imported+native geometry builds, measures, exports;
reference registration/read (text paging + caps, image budgets, provenance
delimiters); ledger document citations verified by lint, image citations
routed to the reviewer with channel recorded; a seeded bench task exercising
each of imports/ and references/ end to end with the FakeModel. Existing
suites stay green; boundary tests keep geom/contract/core clean.
