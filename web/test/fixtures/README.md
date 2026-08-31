# Recorded response fixtures

Every `.json` file in this directory was **recorded**, not written by hand, and
each has a recorder that says how. The inspector fixtures listed below come from
a real `server/http` app: `scripts/record_web_fixtures.py` scaffolds a project,
builds it, runs the project check set and a real DFM evaluation under the probed
secure backend, and writes the bodies the routes returned:

```sh
uv run python scripts/record_web_fixtures.py
```

`normalized-events.json` is the stream suite's fixture and has its own recorder,
`record-normalized-events.mjs`, in this directory. It records a different
substrate for a different reason: the stream's claims are about what the
**sidecar's normalizers** emit — that a historical `tool_result` carries
`isError` (section 7.2's engine change), that a historical `image` payload is
`{mimeType}` with no bytes, that a historical identity is `(session_id, ordinal)`
while a live one is `(run_id, seq)`, and that a >250-event transcript really does
page — so it runs `normalizeEntries`, `pageHistory`, `normalizeLiveEvent` and
`wireEvent` out of `agent/dist` and writes down what they produced. That is why
it is a node script rather than part of the Python recorder above: those four
functions are TypeScript and nothing outside the sidecar reproduces them.

```sh
pnpm --dir agent build
node web/test/fixtures/record-normalized-events.mjs
```

Re-record whenever a section 2.3 read projection changes. The recorder is
deterministic except for content-addressed refs, which change with the geometry
they address — which is why every assertion in `../inspector.test.tsx` is on
fields and relations and never on a literal ref.

The point of recording rather than authoring is that `INTERFACE.md` section 1
makes the client's `data-source` attributions checkable *against the wire*. A
component test that agreed only with a hand-written idea of the wire would
assert that the client is self-consistent, which is not the property under test.

| File | Route |
|---|---|
| `project.json` | `GET /api/v1/project` |
| `parts.json` | `GET /api/v1/parts` |
| `build.json` | `GET /api/v1/parts/panel/build` |
| `properties.json` | `GET /api/v1/parts/panel/properties` |
| `checks.json` | `GET /api/v1/parts/panel/checks` |
| `dfm_absent.json` | `GET /api/v1/parts/panel/dfm`, before any evaluation |
| `dfm.json` | `GET /api/v1/parts/panel/dfm`, after a run against the current artifact |
| `dfm_preview.json` | the same, after a run resolved through an explicit `artifact_ref` |

**`build_failed.json`** is the Timeline's failed-build document. It is assembled
around the §8 error shape (line/col/type/frame/built_through/last_good) plus
the worker `checkpoints[]` `GET /parts/{part}/build` now projects. The
checkpoint refs are illustrative (a last-good `build-checkpoint` hash); the
fields and the last-good join are what the marks helper asserts.

## The three fixtures that are not pure route output

Each says so here rather than passing quietly as a recording.

**`checks_not_run.json`** calls `hephaestus.http.projections.checks_projection`
with its `declared` argument. Section 6.3 requires the `not_run` badge to render
as its own visible state, and **no engine surface enumerates declared-but-unrun
check names today**: `run_bundle` loads every check in the frozen bundle and runs
all of them, so a run either reports a check or fails the whole generation
closed. The parameter exists so the badge is implementable rather than
structurally unreachable (`http/projections.py` records the gap in full), and
this fixture is the only way to exercise the panel's fourth state until the
public fixture project of section 14 lands. The report inside it is the same
report the route serialized.

**`provenance_tagged.json` / `provenance_owned.json` /
`provenance_unattributed.json`** assemble section 12.3's response envelope
around real engine output, because `POST /parts/{part}/selection/resolve` is not
a served route yet (section 19 item 8). Every value inside them came out of the
engine: the `selection_id`, `kind`, `solid_index`, `topology_index`, `tag` and
`label` are entries of the selection bundle the build minted, the three refs are
that bundle's own, and the tagged case's `line` is the source map's
`TagPlacement`. What the recorder supplied is the envelope around them and the
`provenance` record — `{state, reason?}` — which section 12.3 names without
giving a shape and section 4.4 requires to distinguish two answers that would
otherwise look identical. `web/src/components/inspector/ProvenancePanel.tsx`
closes that reason vocabulary at two values and says why.
