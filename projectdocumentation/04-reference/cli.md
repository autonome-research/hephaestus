# Command line reference

> **Verified against** `16f9613` on 2026-09-12.
> Verb list from `uv run heph --help`; behaviour claims exercised against a
> scratch project created with `heph init`.

`heph` is the one console entry point. The engine verbs need no server, no
browser and no Node.

For a worked example of the core loop, see
[Your first part](../02-tutorial/your-first-part.md). The repository's own
`docs/cli.md` carries one worked transcript per verb and is kept current by a
test that derives its coverage from the parser; this page is the map, not a
replacement for it.

## The 25 verbs

| Verb | Purpose |
| --- | --- |
| `init` | scaffold a new project directory |
| `part` | list, create or show a part |
| `script` | read or write a part script under compare-and-swap |
| `params` | show parameter declarations and effective values |
| `prompt` | store or show the operator request text |
| `build` | build a part and publish the result |
| `check` | run the cross-part check set |
| `lint` | lint a part script |
| `diff` | compare two solids |
| `render` | render views of a part |
| `goldens` | verify or update the golden images |
| `assembly` | evaluate declared constraints |
| `joints` | declare and read joints |
| `motion` | evaluate poses and motion checks |
| `solve` | propose a pose, a placement or parameters |
| `proposals` | read recorded placement proposals |
| `import` | admit a STEP, mesh or point cloud into the project |
| `scan` | compare a part against a scan |
| `reference` | register operator reference documents and images |
| `registry` | inspect, pin and verify content registries |
| `cam` | emit a 2D cut file |
| `export` | list exported files and release their retention roots |
| `agent` | run an interactive CAD agent session |
| `bench` | run and score the agent benchmark |
| `serve` | serve the project over MCP or the web workspace |

## The core loop

```console
$ heph init /tmp/gadget && cd /tmp/gadget
$ heph part create spacer --template blank --json
$ heph script write spacer --file spacer.py --expected-hash sha256:… --json
$ heph params spacer --json
$ heph build spacer
$ heph part show spacer --json
$ heph check --json
$ heph render spacer
```

`heph init` writes five files in three directories and refuses a non-empty
target. It never overwrites.

```
hephaestus.toml     project name and units
globals.py          the shared `hc` namespace
parts/example.py    a part that builds with nothing edited
checks/project.py   a cross-part check stub
.gitignore          ignores .heph/
```

## Writes are compare-and-swap

`script write` requires `--expected-hash`, which is the `content_hash` from
`part create` or `script show`. A mismatch is a conflict carrying the live hash
and the live content; nothing is written. Creating a part that already exists is
`already_exists`. This is the same contract the agent's `write_part` and
`edit_part` tools use, because it is the same code.

## Builds, previews and staleness

A build publishes as `current` only when it used the project's own declared
inputs. Passing `--param` or `--global-param` makes the build a **preview**: it
is stored, addressable and returned, but it does not become current.

```console
$ heph build example
example: ok (current) artifact=artifact:build:sha256:d266f257…

$ heph build example --param width=50
example: ok (preview) artifact=artifact:build:sha256:11a5c13b…
```

A part is stale when a recorded input no longer hashes to what the build
recorded. `heph part show <part> --json` reports it as `stale` plus
`stale_inputs` naming which:

```console
$ heph part show spacer --json | jq '{stale, stale_inputs}'
{"stale": true, "stale_inputs": ["script"]}
```

The recorded inputs are the script, the toolchain, the declared parameters, the
effective parameters, each named import, and **the projection of `hc` names the
part actually read** — not all of `globals.py`, which would make every part stale
whenever anyone touched the shared namespace.

**`--stale` is narrower than that field**, and the distinction matters. Its help
says "rebuild every stale **consumer** part": it rebuilds the parts made stale by
a change to a *shared* input — `globals.py`, a project parameter, a replaced file
under `imports/` — and prints `no stale parts` when there is none. A part whose
own script you edited is reported stale by `part show` and is **not** picked up by
`heph build --stale`; rebuild it by name.

```console
$ heph build --stale          # after editing globals.py
example: ok (current) artifact=artifact:build:sha256:bb878bf1…

$ heph build --stale          # after editing parts/spacer.py only
no stale parts
```

## `serve` has three modes

```console
$ heph serve --web --project ~/designs/bracket    # browser workspace API
$ heph serve --mcp                                # Model Context Protocol over stdio
$ heph serve --mcp --http 127.0.0.1:8765          # MCP over streamable HTTP
```

`--web` prints one line on stdout carrying the entry URL with the workspace
token in the fragment. `--mcp` and `--web` in one process are refused by name,
as is `--project` without `--web`.

Neither serve mode has an unsafe-executor opt-in. That is deliberate: serve is
the mode an operator exposes to a client.

## Optional verbs

Five entry points are registered only when their package imports: `agent`,
`export`, `bench`, `serve`, and `serve --web` one level in. The CLI
distinguishes two conditions that look alike:

- **Not installed.** The verb is absent from `heph --help`, and asking for it is
  argparse's `invalid choice`.
- **Installed but broken.** The verb stays on `heph --help` and refuses by name
  when invoked, naming the import that failed and saying that this is a broken
  installation rather than an absent one.

The second case exists because a package whose own dependency is broken used to
vanish from the help output, which told the operator to install something that
was already there.

## Startup cost

Registering the verbs imports no heavy module. The parser build does not pull
the CAD kernel, the MCP stack, the HTTP stack or the geometry package, and that
is asserted as a module-name property in a fresh subprocess rather than as a
wall-clock threshold — a clock assertion would be flaky on a loaded machine and
would not say what broke. `heph --version` answers before any subcommand module
loads.

## Output and exit codes

Every verb takes `--json` where it returns a document. Refusals always go to
stderr, so stdout stays parseable.

| Exit | Meaning |
| --- | --- |
| 0 | ran and succeeded |
| 1 | ran, and the answer was no |
| 2 | the request was malformed |

The full reason vocabulary is in
[refusals](refusal-vocabulary.md).
