# Add or change an agent tool

> **Verified against** `49a90c6` on 2026-09-12.
> Generator interface read from `contract/src/hephaestus/contract/toolgen.py`
> and confirmed by running `uv run python -m hephaestus.contract.toolgen`;
> dispatch rules from `server/src/hephaestus/agent_bridge/dispatch.py`.

There are 57 tools. Changing one touches five artifacts, four of which are
generated, and CI drift-tests all of them against each other.

## The shape of the change

```
             ┌──────────────────────────────────────────┐
  YOU EDIT → │ contract/…/tools_decl.py    ToolDecl     │
             └────────────────┬─────────────────────────┘
                              │  toolgen
       ┌──────────────────────┼───────────────────────┐
       ▼                      ▼                       ▼
 schemas/tools/*.json   agent/src/tools/        schemas/mcp/tools.json
 (57 files)             schema.gen.ts
       │                      │                       │
       └──────────────────────┴───────────────────────┘
                              │  drift-tested in CI against
                              ▼
                    tool_schema.md headings
                              │
  YOU ALSO EDIT →  the implementation behind the dispatcher
```

## 1. Edit the declaration

`contract/src/hephaestus/contract/tools_decl.py`.

```python
ToolDecl(
    name="measure_thing",
    summary="…",
    params=_obj({...}, required=[...]),
    result=_obj({...}, required=[...]),
    profiles=("orchestrator", "part"),
    sequential=False,
    idempotent=False,
    max_utf8_fields={"note": PROMPT_MAX_UTF8_BYTES},
)
```

### Rules the declaration must follow

**No numeric literal for a limit.** Read it from `schemas/bridge_limits.json`
through the module's own constants (`PROMPT_MAX_UTF8_BYTES`, `DEADLINE_MIN`,
`MAX_IMAGES_PER_RESULT`, …). A duplicated literal fails the census test.

**Byte caps go in `max_utf8_fields`**, which emits the custom keyword
`x-hephaestus-maxUtf8Bytes` and is enforced by every validator **after** ordinary
JSON Schema validation — because JSON Schema's `maxLength` counts code points,
not bytes.

**`profiles` is the authorization.** A tool available to `reviewer` must also be
in `REVIEWER_TOOLS`, and the reviewer's inability to mutate is a property of this
table, not of any prompt. Orchestrator-only is the right answer for anything
spanning parts (`propose_placement`, the project-check family, `edit_globals`,
delegation).

**`sequential` and `idempotent` are different questions.** Sequential means it
blocks the turn; idempotent means the same invocation id replays. `ask_user` is
sequential and not idempotent; `solve_pose` is idempotent and not sequential.

**Additional properties are closed.** `_obj` sets `additionalProperties: false`
by default; keep it that way.

## 2. Regenerate

```console
$ uv run python -m hephaestus.contract.toolgen all
schemas/tools/….schema.json
…
agent/src/tools/schema.gen.ts
schemas/mcp/tools.json
toolgen: wrote 59 files from 57 tools
```

`all`, `json`, `ts` or `mcp`. Use `all`.

**Never hand-edit a generated file.** `schemas/tools/*.schema.json`,
`agent/src/tools/schema.gen.ts` and `schemas/mcp/tools.json` are outputs; a hand
edit fails the drift test, which is the point.

## 3. Update `tool_schema.md`

The normative prose surface. Its **headings** are drift-tested against the
declaration, with `STAGE2_EXCLUDED_TOOLS` (`run_fea`, `import_geometry`)
subtracted first.

A new tool with no heading fails the drift test, and so does a heading with no
tool.

## 4. Implement it behind the dispatcher

`server/src/hephaestus/agent_bridge/dispatch.py` routes by family:

| Family | Goes to |
| --- | --- |
| file CRUD | `ProjectStore` |
| geometric, parametric, check-, artifact-, export-related | `CadOps` (`agent_bridge/cad_ops/`) |
| delegation | `DelegationService` |
| `query_snapshot` | `QuerySnapshotService` |
| skills / parts store / materials | `RegistryOps` |

**Nothing bypasses the dispatcher.** The HTTP routes and the MCP tools both reach
it; a boundary test asserts the absence of a bypass mechanically.

### Refuse by name

Raise a `DispatchError` carrying a **stable `reason`**, or let the engine's own
`HephaestusError` code through — the dispatcher re-raises the engine's code
rather than flattening it.

Pick an existing reason if one fits. A new one must:

- be a machine token, dispatched on rather than read;
- be added to the HTTP status map if it can reach an HTTP route;
- get a client-side sentence in `web/src/components/refusalText.ts` if the
  browser can see it — there is deliberately **no raw-message fallback**, so a
  reason without a sentence renders generically;
- never be spellable as a verdict.

Two codes are special: `capability_not_available` and `image_model_required` are
turned by the sidecar proxy into **discriminated tool results at 200**, not
errors. They are answers.

## 5. Add a mutation's idempotency, if it mutates

Mutations are idempotent on the trusted invocation id through opstore opkeys: a
retry of a committed write replays the recorded outcome, and a
same-id-different-payload presentation is a hard mismatch.

If your tool has a compare-and-swap gate in front of the key, you want a
**discriminated result** instead of a replay — `conflict` carrying the live hash
the tool wrote itself. Look at `edit_part` / `write_part` and the project-check
family, and note that `edit_globals` claims its key *before* the CAS precisely so
it replays `applied` instead.

## 6. If it reaches the browser

A route may need a row in `ROUTE_TABLE`, and a key-required mutation a row in
`KEY_REQUIRED_ROUTES`. Both are enumerated, never derived — that rule was
withdrawn because it decides nothing for a route with no `ToolDecl`, and a rule
that silently exempts the routes a reader most expects it to cover is worse than
no rule.

Numbers the UI presents must render through `<Fact source="…">` naming the
response field. The lint rejects a computed source, a derived value, or
`data-source` on any other element.

## 7. Test it

```console
$ uv run pytest contract/tests -q                     # declaration + generated artifacts
$ uv run pytest tests/stage2 -q                       # the bridge gates, incl. the limits census
$ uv run pytest server/tests -q -k dispatch           # profile gate and object scope
$ (cd agent && pnpm typecheck && pnpm test)           # schema.gen.ts compiles and is used
```

Write the dispatch tests on **both** an orchestrator session and a scoped one: a
`part` session must be refused `scope_denied` when it addresses a different part
— by `name`, by `part`, or through a cross-part `"<part>/<selector>"` selector —
and a nameless `scope="project"` call must be refused too.

## Checklist

- [ ] `tools_decl.py` edited; no limit literal; `additionalProperties: false`
- [ ] `profiles` correct; `REVIEWER_TOOLS` updated if reviewer-visible
- [ ] `sequential` and `idempotent` decided separately
- [ ] `toolgen all` run; generated files committed, not hand-edited
- [ ] `tool_schema.md` heading added or updated
- [ ] implementation behind the dispatcher, refusing by name
- [ ] idempotency or a discriminated conflict result, if it mutates
- [ ] HTTP route row and key-policy row, if it has one
- [ ] client refusal sentence, if the browser can see the reason
- [ ] contract, stage2, dispatch and agent suites green

## Related

- [Agent tool catalogue](../04-reference/agent-tools.md).
- [Refusal vocabulary](../04-reference/refusal-vocabulary.md).
- [Work on the sidecar](work-on-the-sidecar.md).
