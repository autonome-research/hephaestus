# Spike F — secure Linux executor probes

Status: **PASS** (both bwrap and Docker lanes green).

## What runs

| File | Role |
|---|---|
| `sandbox_runner.py` | bwrap executor: `build_bwrap_argv`, `run_sandboxed`, `detect_capability` |
| `probes.py` | child-side escape/limit probes (stdlib only); runs identically under bwrap and Docker |
| `run_spike.py` | host harness: starts a loopback listener + sentinel env, runs the suite, writes `out/results.json` |
| `docker_parity.sh` | same `probes.py` inside `python:3.13-slim --network none --read-only`; writes `out/docker_results.json` |

Reproduce:

```
cd spikes/sandbox
uv venv --python 3.13 .venv           # already pinned via .python-version
.venv/bin/python run_spike.py         # bwrap lane   -> out/results.json
./docker_parity.sh                    # docker lane  -> out/docker_results.json
```

## Versions (this run)

- Host kernel: `Linux 7.0.9-arch2-1 x86_64`
- bubblewrap: `0.11.2` (`/usr/bin/bwrap`)
- Sandbox interpreter: CPython **3.13.12** (uv, relocated, bound read-only at `/opt/python`)
- Docker: `29.5.1`; image `python:3.13-slim` digest `sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91` (internal Python 3.13.14)

## Exact bwrap argv (captured verbatim in `out/bwrap_argv.txt`)

```
/usr/bin/bwrap --die-with-parent --unshare-user --unshare-ipc --unshare-uts \
  --unshare-net --unshare-pid --clearenv --setenv PATH /usr/bin:/bin \
  --setenv HOME /project --setenv TMPDIR /tmp --proc /proc --dev /dev \
  --tmpfs /tmp --tmpfs /run --ro-bind /usr /usr \
  --symlink usr/lib /lib --symlink usr/lib /lib64 --symlink usr/bin /bin --symlink usr/bin /sbin \
  --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --ro-bind <uv-cpython-3.13-root> /opt/python \
  --ro-bind <spike>/probes.py /probes.py \
  --ro-bind <project-dir> /project --chdir /project --remount-ro / \
  /opt/python/bin/python3 /probes.py probe '<json-config>'
```

Notes: `--remount-ro /` seals the base tmpfs so writes to `/` and `/etc` fail (EROFS) while the
explicit `/tmp` tmpfs stays writable. `probes.py` is bound at `/probes.py` (NOT inside the read-only
`/opt/python` mount, which bwrap cannot create a mountpoint inside).

## bwrap lane — escape probes (all 14 as expected)

Every containment probe fails inside the sandbox; both legit-compute probes succeed:

| probe | expect | result | evidence |
|---|---|---|---|
| read_etc_shadow | blocked | ENOENT (not mounted) | ✅ |
| write_into_ro_project_bind | blocked | EROFS | ✅ |
| write_fs_root `/pwned.txt` | blocked | EROFS (remount-ro /) | ✅ |
| write_etc | blocked | EROFS | ✅ |
| write_home / list_home | blocked | ENOENT (no /home) | ✅ |
| tcp 1.1.1.1:443 | blocked | ENETUNREACH (--unshare-net) | ✅ |
| tcp host-loopback listener | blocked | ECONNREFUSED (isolated netns) | ✅ |
| dotdot_traversal `/project/../../etc/passwd` | blocked | ENOENT | ✅ |
| symlink_to_home_escape | blocked | ENOENT | ✅ |
| kill_host_pid `os.kill(pid,0)` | blocked | ESRCH (--unshare-pid) | ✅ |
| host_env_leak via `/usr/bin/env` | blocked | sentinel absent (--clearenv) | ✅ |
| legit_compute + /tmp write | allowed | sha256 ok | ✅ |
| legit_read_project_file | allowed | read ok | ✅ |

## bwrap lane — resource limits

- **Wall-clock**: infinite loop (`spin`) killed via process-group SIGKILL. `timed_out=true`,
  `wall_seconds≈3.0`, `returncode=-9`. (`out/results.json` → `limits.wall_timeout`)
- **Memory**: 2 GiB allocation under a 256 MiB `RLIMIT_AS`/`RLIMIT_DATA` cap → `MemoryError`,
  reported `killed=true`. (`limits.memory_cap`)

## bwrap lane — fail-closed capability detection

- Healthy host: `detect_capability` returns `usable=true` only after a live sandboxed run confirms
  network + `/etc/shadow` actually block (defense-in-depth, not just a version string).
- Simulated absence (`PATH=/nonexistent-dir-only`): `usable=false`, reason `"bwrap not on PATH"`.
  Fails closed — the runner refuses to execute unsandboxed.

## Docker parity lane (macOS OCI-backend evidence)

`python:3.13-slim` with `--network none --read-only --tmpfs /tmp --memory 256m --memory-swap 256m`:

- **Host containment**: all host-escape probes block — writes EROFS (read-only rootfs), network
  ENETUNREACH/ECONNREFUSED (`--network none`), host pid invisible (isolated pidns), host env not
  leaked. `host_containment_ok=true`.
- **Semantic difference (documented, not a breach)**: `read_etc_shadow`, `list_home`,
  `dotdot_traversal`, `symlink_to_home` read the container's OWN ephemeral rootfs (its own
  `/etc/shadow`, empty `/home`), not host files. The bwrap lane mounts none of these; the OCI lane
  ships a throwaway rootfs. These are split out as `container_internal_reads` in
  `out/docker_results.json` and excluded from `host_containment_ok`.
- **Memory**: 2 GiB under 256m cgroup cap → exit 137 (OOM-killed).
- **Wall-clock**: infinite loop → exit 137 (killed by external 3s timeout).

## Evidence files (under `out/`, gitignored)

`results.json`, `bwrap_argv.txt`, `run_spike.console.txt`, `docker_results.json`,
`docker_probe.json`, `docker_alloc.json`, `docker_spin.stderr`, `docker_parity.console.txt`.
