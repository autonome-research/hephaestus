# HTTP workspace API

> **Verified against** `49a90c6` on 2026-09-12.
> Route table, key policy and reason map printed from the code:
> `len(ROUTE_TABLE)` = 56, `len(WEBSOCKET_ROUTES)` = 1,
> `len(UNSERVED_SPEC_ROUTES)` = 3, `len(REASON_STATUS)` = 87.

The workspace API is what `heph serve --web` serves. It is the browser
workspace's backend, and it is the only network surface the project has besides
MCP.

```console
$ uv run heph serve --web --project ~/designs/bracket
```

The framework is **Starlette**, not FastAPI — deliberately, because Starlette is
already in the graph as the transport `fastmcp` serves streamable HTTP on, so
`heph serve --mcp --web` runs one HTTP stack in one process rather than two.

## The route table is closed

Every route is under `/api/v1`. The table lives as data in
`server/src/hephaestus/http/app.py` as `ROUTE_TABLE`, and a boundary test asserts
that the served surface **is** that list, in both directions and across both
transports. A route added to the app without a row fails a test rather than
shipping quietly.

56 rows: 28 `GET`, 24 `POST`, 3 `PUT`, 1 `PATCH`. There is no `DELETE` anywhere,
no `POST /artifacts` (the workspace mints nothing), and no route that takes a raw
filesystem path in a request body.

### Project and parts — read

| Route |
| --- |
| `GET /project` |
| `GET /parts` |
| `GET /parts/{part}/script` |
| `GET /parts/{part}/build` |
| `GET /parts/{part}/properties` |
| `GET /parts/{part}/checks` |
| `GET /parts/{part}/params` |
| `GET /parts/{part}/dfm` |
| `GET /checks` |

### Artifacts

`GET /artifacts/{ref}/meta`, `/text`, `/bytes`, `/gltf`.

`/bytes` refuses an `export`-kind ref **by enumeration**, and also refuses an
export blob wearing another kind's label, checked against the store's own
publication record. Export bytes have their own route with strictly narrower
authorization.

### Egress

| Route | Note |
| --- | --- |
| `GET /parts/{part}/exports` | export history |
| `GET /exports/{export_blob}/bytes` | addressed by blob hash, not artifact ref; authorized by a `COMMITTED` `tp_exports` row |
| `POST /parts/{part}/export` | keyed mutation, returns a result document and **no bytes** |
| `POST /parts/{part}/drawing` | keyed mutation |
| `POST /parts/{part}/doc` | keyed mutation |

Production and download are two steps on purpose. Collapsing them would make a
retried *download* re-enter a keyed *mutation*, would put a multi-megabyte binary
where the refusal payload has to fit, and would make "the export failed" and "the
transfer failed" the same event.

### Inspection and measurement

`POST /parts/{part}/inspect`, `POST /measure`, `POST /context/preview`.

These are `POST` because their argument documents exceed what a query string
should carry, and they take **no idempotency key** — the key policy is per route,
not per HTTP verb. `context/preview` is the composer's "what will the agent be
told?" disclosure: it starts no run and calls no tool, which is the whole
difference between it and the prompt route it previews.

### Mutations

`PUT`/`PATCH /parts/{part}/script`, `POST /parts/{part}/params`,
`POST /parts/{part}/build`, `POST /parts/{part}/dfm`,
`POST /project/config/dfm`, `POST /git/tag`.

### Streams, history, sessions

`GET /events` (WebSocket upgrade), `GET /sessions`,
`GET /sessions/{id}/history`, `GET /sessions/{id}/thread`,
`POST /sessions`, `POST /sessions/{id}/prompt`, `POST /sessions/{id}/answer`,
`POST /runs/{run_id}/cancel`, `GET`/`PUT /sessions/{id}/model`.

### Providers

`POST /providers/attach`, `GET /providers`, `PUT /providers/specs`,
`GET /providers/catalog`, `GET /providers/models`,
`GET /providers/{id}/auth/status`, `POST /providers/{id}/auth/{key,begin,complete,cancel,signout}`,
`POST /providers/auth/unlink`, `POST /providers/discover`,
`POST /providers/adopt`.

The split is by dependency: `GET /providers` and `PUT /providers/specs` read and
write a file and stay serviceable with no sidecar; `/catalog` and every `auth/*`
row relays to the provider host and refuses `agent_unavailable` when there is no
sidecar. Every provider row carries a route-level loopback precondition.

`POST /providers/discover` is a `POST` despite being a read, so that reading the
operator's home directory can never be something a page issues incidentally.

`POST /providers/attach` is deliberately the one provider route that needs **no**
sidecar: it is the route that *creates* one, so refusing it `agent_unavailable`
would be the deadlock it exists to remove.

### Git projection — read

`GET /git/status`, `/git/log`, `/git/diff`, `/git/tags`.

### Declared but not served

Three routes the interface specification names and this application does not
serve, named in the code as `UNSERVED_SPEC_ROUTES` so the gap is a fact in the
code rather than a discrepancy only a spec reader can find:

```
POST /parts/{part}/selection/resolve
POST /parts/{part}/render/section
POST /parts/{part}/quick_edit
```

All three answer `unknown_route` today.

## Authentication

One bearer token, minted per serve into `<project>/.heph/serve.token` (mode
`0600`). No login, no cookie, no refresh, no user model — there are no
credentials to prompt for.

The token rides in the entry URL's **fragment**, never a query string, so it
never enters an access log or a `Referer`. The server only ever sees it as
`Authorization: Bearer …`, compared in constant time.

The principal is:

```
WorkspacePrincipal { project_root, profile="orchestrator", token_id }
```

A local operator with the project open is orchestrator-equivalent. This layer
adds no authorization of its own beyond the token; the dispatcher's object-scope
and reviewer rules apply unchanged.

`<project>/.heph/serve.json` (`0600`) is the discovery file:
`{pid, http, started_at, token_path, started_by}`. `heph agent` reads it to
decide whether a live server already owns the project's leases — one process owns
them, and a second either routes through it or refuses.

## Idempotency

Mutations carry an `Idempotency-Key`, which must be a **UUIDv7**. The key space
is `(WorkspacePrincipal token/route identity, Idempotency-Key header value)` —
the key is scoped by the *route identity*, not the concrete path, and the body is
deliberately **not** folded into the key.

### The ladder

| Situation | Response |
| --- | --- |
| absent on a key-required route | 400 `idempotency_key_required`, no execution |
| absent on a session-control route | proceed; a supplied one is ignored |
| present but not a UUIDv7 | 400 `idempotency_key_malformed`, no execution |
| first sight, timestamp outside ±300 s | 409 `key_timestamp_skew`, no execution |
| recognized inside the 30-day horizon | replay; **freshness is not re-checked** |
| same key, different payload | 409 `key_payload_mismatch` |
| presented after the 30-day horizon | 409 `key_expired`, no execution |

The freshness asymmetry is a documented trap: **replay tests must not re-assert
freshness.**

A replay returns the stored response body **byte-for-byte**, with envelope field
`"replayed": true` (normative) and header `Idempotency-Replayed: true`
(advisory). It does not degrade to the bridge's `{applied: false, conflict: …}`
shape — that shape exists because the retrying principal is a *model* being told
a live hash it does not hold, while a REST replay is the same operator client
re-sending its own committed call.

### Which routes require a key

Enumerated, never derived from the mutation-tool set:

```
PUT    /parts/{part}/script      POST /project/config/dfm
PATCH  /parts/{part}/script      POST /git/tag
POST   /parts/{part}/params      POST /parts/{part}/export
POST   /parts/{part}/build       POST /parts/{part}/drawing
POST   /parts/{part}/dfm         POST /parts/{part}/doc
PUT    /providers/specs
```

Three of these have **no tool behind them** — `POST /project/config/dfm`,
`POST /git/tag`, `PUT /providers/specs` — so the recorded-outcome ledger is
extended to cover non-tool operations under the same key space, with the route as
the operation identity and the response body as the stored value.

### Which routes ignore a key

Session control (`POST /sessions`, `/sessions/{id}/prompt`,
`/sessions/{id}/answer`, `/runs/{run_id}/cancel`, `PUT /sessions/{id}/model`)
requires no key, and a supplied one is **ignored rather than honoured**:
byte-for-byte replay is incoherent for a route whose whole meaning is a side
effect on a live run.

Credential mutations also ignore a key, and for a sharper reason: a byte-for-byte
replay of a credential change would be a silent security failure — a rotation
swallowed because the key matched.

## Errors

One envelope, always:

```json
{"status": "error", "reason": "unknown_route", "message": "…"}
```

`reason` and `message` always win over any data spread into the body. 87 reasons
map to a status; the full table is in
[the refusal vocabulary](refusal-vocabulary.md), along with the two conditions
that return 200 rather than an error and the unknown-reason shape fallback.

Request bodies are capped at `http.max_request_bytes` = 1 MiB, checked against
`Content-Length` *before any byte is read* and again mid-stream. That is
deliberately far below the bridge's 64 MiB frame cap: 64 MiB is what the bridge
transport may carry between two trusted processes, and the largest legitimate
body here is a part script.

## The event stream

`GET /events` is a WebSocket upgrade — a row of the route table like any other.
One socket per attached client, registered as a **non-durable observer**.

It emits the normalized public vocabulary only, ten kinds:

```
text_delta  thought  tool_call  tool_result  image
question    answer   audit      progress     terminal
```

Bridge frames are never surfaced, no web-specific event kind is minted, and no
field is added to the Python-side event shape — the wire shape is that shape
verbatim plus exactly one envelope field, `session_id`.

### Overflow is 4409, not shared fate

The event pump's durable-overflow policy cancels the affected *run*. A stalled
browser tab must not kill an agent's work, and making the web client droppable is
illegal — only `progress` is droppable. So an observer that overflows is
**dropped**: the socket closes with code `4409`, reason `resync_required`, and
the run continues untouched.

The client reconnects, replays whatever the live buffer still holds, and renders
anything the buffer dropped as a **labelled break**. The break is never healed
from history: the live and historical identity namespaces are disjoint, so a
dedupe across them would never match and every "refilled" event would render
twice.

The honest cost, stated as the surface actually supports it: of the ten kinds,
history can reconstruct five (`text_delta`, `thought`, `tool_call`,
`tool_result`, `audit`), `image` as **metadata only**, and `question`, `answer`,
`terminal`, `progress` **not at all**.

Client→server control frames are a closed set; a frame carrying anything else is
refused rather than ignored.

## Every tool route goes through the dispatcher

Nothing in the HTTP module computes a result. A route validates a request,
applies the key ladder, calls `ToolDispatcher.dispatch`, and maps refusals
through the error map. There is no bypass, and
`server/tests/test_http_boundary.py` asserts it mechanically rather than
trusting the docstring that says so — including that `server/http` may not import
`core.render` at all, asserted at import level.
