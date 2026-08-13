<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# G7H clauses that only CI can prove

Every clause of Gate G7H that has a local pytest equivalent lives in this
directory and is run by `uv run pytest tests/stage7h -q`. This file is the
complement: the clauses whose *evidence is a machine state* this repository
cannot create, each mapped to the workflow job that produces it.

The rule this document exists to enforce is that no clause is silently absent.
A clause is either (1) covered by a test here, or (2) listed below with the job
that covers it. It is never a local `pytest.skip` dressed up as a pass — a
skipped test reports green, and a green skip on a clean-machine matrix is the
exact failure the matrix exists to catch.

Two honesty markers are used throughout:

- **WEAKER LOCALLY** — a local test proves a related but strictly weaker claim.
  The weaker form is named so nobody mistakes it for the clause.
- **KNOWN RED** — the CI job exists, is correct, and currently fails because the
  product does not yet implement what it measures. G7H cannot be declared green
  while a KNOWN RED entry remains.

---

## 1. Lane (a) — Python-only install "on every packaging lane"

| clause | where it is proven |
|---|---|
| `pipx install` of the built wheel, macOS | `release.yml` → `lane-a` (`matrix.os: macos-latest`) |
| `pipx` as the actual installer | `release.yml` → `lane-a` → *pipx install the built wheel* |
| every Hephaestus distribution resolved from a `file://` URL, not an index | `release.yml` → `lane-a` → *every hephaestus distribution came from this build* |

**Why not local.** This box is Linux, and the local suite installs with
`uv venv` + `uv pip install <explicit wheel paths>` (`_wheel.py::install_wheel`).
That pins the same property — the Hephaestus wheels come from this build, never
from an index — but through a different installer, and G7H names `pipx`.

**WEAKER LOCALLY.** `tests/stage7h/test_packaged_sidecar.py` proves the Node-free
surface works with **Node scrubbed from `PATH`**
(`_wheel.py::node_missing_env`). The clause is a machine with *no Node
installed*; a `PATH` scrub cannot rule out a runtime that a child process
rediscovers through `$HOME`, a version manager, or an absolute path. Lane (a)
additionally asserts `command -v node` fails on the runner.

---

## 2. Lane (b) — the supported secure Linux x86_64 lane

Most of lane (b) has a local equivalent: `test_lane_b_runtime.py` (JobStore,
fake-model agent, MCP over stdio), `test_packaged_sidecar.py` (integrity,
native-addon audit) and `test_no_global_fallback.py` (hostile globals) all run
against the installed wheel here.

| clause | where it is proven |
|---|---|
| build/check through a **probed bubblewrap** sandbox with unprivileged userns unrestricted | `release.yml` → `lane-b` → *sandbox + renderer prerequisites*, *core build + check through the secure executor* |
| the secure-executor **escape suite** on the release lane | `release.yml` → `lane-b` → *secure-executor escape suite* |
| the suites run against the **downloaded artifact** rather than a rebuild | `release.yml` → `lane-b` (`HEPHAESTUS_WHEELHOUSE: ${{ github.workspace }}/dist`) |

**Why not local.** The escape suite is `core/tests/test_sandbox_*.py`; it runs in
this repository, but "on the release lane, against the published wheel" is a
property of the lane, not of the suite. `test_release_lanes.py` asserts
statically that the lane runs it; only CI proves it passed there.

The `HEPHAESTUS_WHEELHOUSE` hand-off is exercised locally in the sense that the
mechanism works (`_wheel.py::build_wheelhouse` honours it), but the *artifact*
it points at is produced by the `wheelhouse` job.

---

## 3. Lane (c) — macOS through a detected OCI backend

**KNOWN RED. This is the one G7H clause that cannot currently go green.**

| clause | where it is proven |
|---|---|
| a Docker/Podman/OrbStack-compatible backend is **detected** (never assumed) | `release.yml` → `lane-c` → *detect an OCI backend* |
| the executor profile is **capability-probed**: read-only root, no network, dropped caps, bounded memory/pids | `release.yml` → `lane-c` → *capability-probe the executor profile* |
| the **product** accepts that backend as secure | `release.yml` → `lane-c` → *hephaestus accepts the detected backend as secure* |
| fake-model + MCP smoke and the escape suite on macOS | `release.yml` → `lane-c` → *fake-model + MCP smoke*, *executor escape suite through the OCI backend* |

**Why it is red.** `hephaestus.core.executor.sandbox.probe.secure_backend()`
constructs a `BwrapBackend` and nothing else — there is no OCI backend in the
product, on any platform. On macOS it therefore raises `sandbox_unavailable`,
which is *correct fail-closed behaviour* and exactly why the lane must fail
rather than skip. `repo_conventions.md` §Naming and `architecture.md`
§Sandboxing both require the OCI backend for macOS support.

The gap is pinned in two places so it cannot rot into an omission:

- `test_release_lanes.py::test_lane_c_is_documented_as_red_until_the_oci_backend_lands`
  keeps the KNOWN RED comment in `release.yml`;
- `test_lane_fail_closed.py::test_bwrap_is_still_the_only_secure_backend`
  fails the day an OCI backend lands, forcing this entry to be revisited.

There is no local equivalent and there should not be one: this machine is Linux
and has no OCI backend the product would accept.

---

## 4. Lane (d) — fail-closed with no secure backend

| clause | where it is proven |
|---|---|
| **bubblewrap is not installed on the machine** | `release.yml` → `lane-d` → *no secure backend is available* (asserts `command -v bwrap` fails) |
| `heph build` refuses by name on that machine | `release.yml` → `lane-d` → *script execution refuses by name* (greps `sandbox_unavailable`) |

**WEAKER LOCALLY.** `test_lane_fail_closed.py` reproduces the missing backend by
sanitising `PATH` so `bwrap` is unreachable. That proves the *refusal path*
end to end — the named error, the absence of a silent fallback to the unsafe
backend, and that the non-executing surface survives — but it is weaker than the
clause in two specific ways:

1. a cached probe result computed before the scrub could mask the failure;
2. an absent kernel feature (unprivileged user namespaces restricted) is a
   different cause than an absent binary, and only a real machine has it.

Lane (d) has neither weakness: bubblewrap is genuinely not installed.

---

## 5. Prior gates green on the release SHA

| clause | where it is proven |
|---|---|
| Gates GS, G0A, G0B, G1, G2, G2V, G3, G6 concluded `success` **for this exact commit** | `release.yml` → `prior-gates` |

**G6's bench clause: CLOSED (2026-08-13).** The numeric clause — "Tier 3
corpus-v1, Wilson lower-90% ≥ 0.70 on the prose split" — is satisfied by the
archived clean sweep `bench/results/gpt-5.6-sol/2026-08-13.json`
(`meets_gate: true`, Wilson 0.7396). `mission_plan.md` §"G6 status" records
it CLOSED with the audit chain; `release.yml`'s release-gate additionally
asserts an archived artifact with `meets_gate: true` exists, so the closure
is machine-checked on every release run, not just recorded in prose.

**Why not local.** This box is Linux, and the local suite installs with
`uv venv` + `uv pip install <explicit wheel paths>` (`_wheel.py::install_wheel`).
That pins the same property — the Hephaestus wheels come from this build, never
from an index — but through a different installer, and G7H names `pipx`.

**WEAKER LOCALLY.** `tests/stage7h/test_packaged_sidecar.py` proves the Node-free
surface works with **Node scrubbed from `PATH`**
(`_wheel.py::node_missing_env`). The clause is a machine with *no Node
installed*; a `PATH` scrub cannot rule out a runtime that a child process
rediscovers through `$HOME`, a version manager, or an absolute path. Lane (a)
additionally asserts `command -v node` fails on the runner.

---

## 2. Lane (b) — the supported secure Linux x86_64 lane

Most of lane (b) has a local equivalent: `test_lane_b_runtime.py` (JobStore,
fake-model agent, MCP over stdio), `test_packaged_sidecar.py` (integrity,
native-addon audit) and `test_no_global_fallback.py` (hostile globals) all run
against the installed wheel here.

| clause | where it is proven |
|---|---|
| build/check through a **probed bubblewrap** sandbox with unprivileged userns unrestricted | `release.yml` → `lane-b` → *sandbox + renderer prerequisites*, *core build + check through the secure executor* |
| the secure-executor **escape suite** on the release lane | `release.yml` → `lane-b` → *secure-executor escape suite* |
| the suites run against the **downloaded artifact** rather than a rebuild | `release.yml` → `lane-b` (`HEPHAESTUS_WHEELHOUSE: ${{ github.workspace }}/dist`) |

**Why not local.** The escape suite is `core/tests/test_sandbox_*.py`; it runs in
this repository, but "on the release lane, against the published wheel" is a
property of the lane, not of the suite. `test_release_lanes.py` asserts
statically that the lane runs it; only CI proves it passed there.

The `HEPHAESTUS_WHEELHOUSE` hand-off is exercised locally in the sense that the
mechanism works (`_wheel.py::build_wheelhouse` honours it), but the *artifact*
it points at is produced by the `wheelhouse` job.

---

## 3. Lane (c) — macOS through a detected OCI backend

**KNOWN RED. This is the one G7H clause that cannot currently go green.**

| clause | where it is proven |
|---|---|
| a Docker/Podman/OrbStack-compatible backend is **detected** (never assumed) | `release.yml` → `lane-c` → *detect an OCI backend* |
| the executor profile is **capability-probed**: read-only root, no network, dropped caps, bounded memory/pids | `release.yml` → `lane-c` → *capability-probe the executor profile* |
| the **product** accepts that backend as secure | `release.yml` → `lane-c` → *hephaestus accepts the detected backend as secure* |
| fake-model + MCP smoke and the escape suite on macOS | `release.yml` → `lane-c` → *fake-model + MCP smoke*, *executor escape suite through the OCI backend* |

**Why it is red.** `hephaestus.core.executor.sandbox.probe.secure_backend()`
constructs a `BwrapBackend` and nothing else — there is no OCI backend in the
product, on any platform. On macOS it therefore raises `sandbox_unavailable`,
which is *correct fail-closed behaviour* and exactly why the lane must fail
rather than skip. `repo_conventions.md` §Naming and `architecture.md`
§Sandboxing both require the OCI backend for macOS support.

The gap is pinned in two places so it cannot rot into an omission:

- `test_release_lanes.py::test_lane_c_is_documented_as_red_until_the_oci_backend_lands`
  keeps the KNOWN RED comment in `release.yml`;
- `test_lane_fail_closed.py::test_bwrap_is_still_the_only_secure_backend`
  fails the day an OCI backend lands, forcing this entry to be revisited.

There is no local equivalent and there should not be one: this machine is Linux
and has no OCI backend the product would accept.

---

## 4. Lane (d) — fail-closed with no secure backend

| clause | where it is proven |
|---|---|
| **bubblewrap is not installed on the machine** | `release.yml` → `lane-d` → *no secure backend is available* (asserts `command -v bwrap` fails) |
| `heph build` refuses by name on that machine | `release.yml` → `lane-d` → *script execution refuses by name* (greps `sandbox_unavailable`) |

**WEAKER LOCALLY.** `test_lane_fail_closed.py` reproduces the missing backend by
sanitising `PATH` so `bwrap` is unreachable. That proves the *refusal path*
end to end — the named error, the absence of a silent fallback to the unsafe
backend, and that the non-executing surface survives — but it is weaker than the
clause in two specific ways:

1. a cached probe result computed before the scrub could mask the failure;
2. an absent kernel feature (unprivileged user namespaces restricted) is a
   different cause than an absent binary, and only a real machine has it.

Lane (d) has neither weakness: bubblewrap is genuinely not installed.

---

## 5. Prior gates green on the release SHA

| clause | where it is proven |
|---|---|
| Gates GS, G0A, G0B, G1, G2, G2V, G3, G6 concluded `success` **for this exact commit** | `release.yml` → `prior-gates` |

**G6's bench clause: CLOSED (2026-08-13).** The numeric clause — "Tier 3
corpus-v1, Wilson lower-90% ≥ 0.70 on the prose split" — is satisfied by the
archived clean sweep `bench/results/gpt-5.6-sol/2026-08-13.json`
(`meets_gate: true`, Wilson 0.7396); `mission_plan.md` §"G6 status" records
it CLOSED with the audit chain. The closure stays machine-checked, not
prose: `release.yml`'s release-gate asserts an archived scoring artifact
with `meets_gate: true` exists on every release run.

**Why not local.** It reads the GitHub check-runs API for a real SHA. There is no
local analogue of "a check run concluded". What *is* local:
`test_release_lanes.py::test_the_prior_gate_check_names_every_ci_job` asserts the
required-name list equals the set of `ci.yml` job display names, so a new CI job
cannot be added without entering the required list, and a renamed job cannot
silently become unrequired.

---

## 6. `bench.yml` publishes the leaderboard artifact

| clause | where it is proven |
|---|---|
| the regenerated page is uploaded as an artifact with `if-no-files-found: error` | `bench.yml` → `leaderboard` → `actions/upload-artifact` |
| the page is published into the run summary | `bench.yml` → `leaderboard` → *publish the page into the run summary* |
| the Tier 3 corpus job runs only on opted-in dispatch with a named model | `bench.yml` → `corpus` (`if:` guard) |

**Why not local.** Artifact upload is a platform action; there is nothing to
execute here. Locally proven instead: the generator is deterministic and the
committed page matches the committed artifacts
(`test_leaderboard.py`), and the workflow contains those steps
(`test_release_lanes.py`).

---

## 7. Tag `v0.1.0-headless`

| clause | where it is proven |
|---|---|
| the pushed tag agrees with the version the built wheels declare | `release.yml` → `release-gate` → *the tag agrees with the built version* |

**Why not local.** Cutting the tag is a maintainer action and this workflow holds
no write permission — it verifies, it does not create. Locally proven instead:
every distribution and the sidecar manifest declare the same version
(`test_version_coherence.py`), which is the fact the tag check compares against.

---

## Maintenance

When a clause moves from CI-only to locally provable, delete its row here in the
same change that adds the test. An entry that stays after its test exists is
worse than no document: it invites the next reader to assume the clause is still
untestable and skip writing the test that already passed.
