<!--
Copyright 2026 The Hephaestus Authors
SPDX-License-Identifier: Apache-2.0
-->

# macOS OCI network investigation (experimental)

## Current handoff

The [execution identity implementation](macos-execution-identity.md) now requires
**manifest 4**, retaining profile 5/protocol 3/transfer 1. Fresh image/storage and
real supervised CAD acceptance now run in the [executor CLI](macos-executor-stage.md);
its containment retains these network checks. See [progress](macos-progress.md).
The bridge negative-control results below remain historical.

The profile-v3 results below are historical network investigation evidence.
[Integrated staging](macos-staging.md) passed a complete 15-feature profile-4
containment probe retaining the same network validation. The storage-review
follow-up now requires **profile 5 / protocol 3 / manifest 3**, adding typed
no-follow proc-mask evidence; fresh results are linked there. The network-check CLI now uses the framed probe stream
and RO snapshot contract; its bridge-control code was adapted, not used to
activate a backend or counted as a new live bridge run in the staging slice.
Production discovery remains disabled.

## Historical profile-v3 result

Docker Desktop can satisfy the experimental executor's containment probe on this
Mac. Two verifier defects caused false rejection:

1. `/sys/class/net` includes `bonding_masters` (a control entry) and LinuxKit
   creates down tunnel devices inside networkless namespaces. Socket enumeration
   and `/proc/self/net/dev` agree on ten actual devices; only loopback is up,
   only loopback has addresses, and there are no non-loopback IPv4/IPv6 routes.
2. The host interpreted Linux worker errno numbers using host constants. Linux
   `ENETUNREACH` is 101; Darwin's is 51. Wire validation must use Linux values.

This is not proof that arbitrary Docker configurations are secure. Production
macOS discovery remains disabled. No Docker settings, privileges, or capability
grants were changed; no interface-name allowlist was added.

## Profile-v3 verification

`core/src/hephaestus/core/executor/sandbox/oci_network.py` collects bounded raw
observations. Host and worker use a closed schema: real interface indices/names,
flags, primary IPv4 addresses, all procfs IPv6 addresses, a matching procfs device
inventory, non-loopback routes, and independent IPv4/IPv6 connection errors.

The host requires up, correctly addressed loopback; all other devices must be
down, not running, not loopback-marked, and unaddressed. All routes must be
loopback-only. Only specified Linux unreachable errors pass; successful connects,
timeouts, connection refusals, missing fields, malformed data and inventory
mismatches refuse. Collection errors abort the probe rather than imply absence.

This check relies on the **entire** enclosing profile, notably nonroot identity,
all capability sets empty and no-new-privileges: CAD must not be able to configure
or activate down devices. The existing Docker `--network=none`, PID/UTS, read-only
root, work mount, tmpfs, rlimits and cgroup requirements are unchanged.

`OCI_PROFILE_VERSION` is now 3, changing the manifest. Old images/profile-v2
responses and the old sysfs-only observation are still rejected. Envelope protocol
and manifest schema versions stay at 2 because their structure did not change.
Images must be rebuilt for this profile; production activation is not part of this
experiment.

## Live evidence

All paths below are relative to the isolated `feat/macos-feasibility` worktree.

- `dist/macos-network-control-none-*/report.json` and
  `dist/macos-network-control-bridge-*/report.json`: initial trusted diagnostic
  comparisons; these cannot authorize a backend. Namespace IDs from sequential
  container runs can be reused and are not evidence of sharing or separation.
- `dist/macos-network-v3-live/report.json`: collected new state correctly but
  still failed before correcting the Darwin/Linux errno mismatch.
- `dist/macos-network-v3-controls/report.json`: first full corrected-image build
  hit its 360-second limit during final image copy; cleanup passed. Not a pass.
- **`dist/macos-network-v3-controls-retry/report.json`**: native image build and
  immutable digest resolution passed; all **14 ordinary containment features
  passed**. A second container running only the trusted fixed probe with bridge
  networking was rejected **specifically for `network_isolated`**. Its active
  `eth0`, `172.17.0.2`, and two routes appear in `negative-control-probe.json`.
  Owned containers and temporary image tags were confirmed absent after cleanup.

The successful image config/digest is
`sha256:4ef55983f494cd05408aa0380d91d944dc0ec21200158cfa9779e5712b5858c6`.
The report retains source/input hashes and raw command/probe logs. Subsequent
formatting does not change network semantics; hashes describe exactly the source
snapshot used for that build, not arbitrary future worktree changes.

The negative control deliberately changes **only the trusted probe's** network
mode. It never runs CAD, authorizes execution, overrides the executor entrypoint,
or changes the production runtime. Other profile checks must pass, so a probe
crash or unrelated rejection cannot make this test green.

Reproduce (new report directory required; serialize heavy operations):

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/opt/python@3.13/bin/python3.13 \
  scripts/macos_network_check.py \
  --report-dir "$PWD/dist/macos-network-new" \
  --wheelhouse "$PWD/dist/macos-report-02/download/wheels"
```

Exit zero means **only the network regression passed**, including cleanup. The
milestone report deliberately retains `accepted: false`; unimplemented acceptance
stages are not marked passed.

## Tests and next steps

155 focused host tests passed across `test_sandbox_oci_network.py`,
`test_sandbox_oci.py`, `test_sandbox_oci_launcher.py`, `test_sandbox_oci_image.py`
and `tests/test_macos_feasibility.py`. They cover version skew, missing/malformed
observations, duplicate identities, up/addressed devices, dual-stack errors,
Linux errno portability and route/parser failures. These are not CAD or browser
tests. Full suite, full type checking and independent security review remain.

Next: preserve integrated staging, wire trusted executor provenance and durable
ownership for secure CAD build/artifacts and cancellation, then separate renderer
integration for RGB, exact selection masks and kernel sections, followed by
provenance-linked GLB browser acceptance. Do not declare the feasibility milestone
complete based on containment alone.
