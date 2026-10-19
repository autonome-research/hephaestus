# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Trusted read-only namespace investigation, NOT an executor capability probe.

Uses the pinned preparation Python base, never overrides the executor entrypoint
or sends code through its worker protocol. No inputs, mounts, network mutations,
CAD or capability verdict. A sibling namespace is evidence, not authorization.
"""

from __future__ import annotations

import json
import os
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from macos_milestone_smoke import Smoke

# Fixed reviewed stdlib-only program. SIOCGIFFLAGS is a read-only ioctl; no
# CAP_NET_ADMIN, setns, unshare, external connection, or interface changes.
OBSERVE = r"""
import fcntl, json, os, pathlib, resource, socket, struct
for kind, limit in ((resource.RLIMIT_CPU, 10),
                    (resource.RLIMIT_AS, 536870912),
                    (resource.RLIMIT_DATA, 536870912),
                    (resource.RLIMIT_NPROC, 64),
                    (resource.RLIMIT_CORE, 0),
                    (resource.RLIMIT_FSIZE, 1048576)):
    resource.setrlimit(kind, (limit, limit))
def text(path):
    with open(path) as stream:
        value = stream.read(65537)
    if len(value) > 65536:
        raise RuntimeError('diagnostic file exceeds bound')
    return value
interfaces = socket.if_nameindex()
if len(interfaces) > 64:
    raise RuntimeError('diagnostic interface count exceeds bound')
rows = []
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    for index, name in interfaces:
        value = fcntl.ioctl(sock.fileno(), 0x8913,
                            struct.pack('256s', name.encode('ascii')))
        flags = struct.unpack_from('H', value, 16)[0]
        try:
            address = fcntl.ioctl(sock.fileno(), 0x8915,
                                 struct.pack('256s', name.encode('ascii')))
            primary_ipv4 = socket.inet_ntoa(address[20:24])
        except OSError as exc:
            if exc.errno != 99:  # Linux EADDRNOTAVAIL, not a silent inspection failure
                raise
            primary_ipv4 = None
        rows.append({'index': index, 'name': name, 'flags': flags,
                     'primary_ipv4': primary_ipv4,
                     'up': bool(flags & 1), 'loopback': bool(flags & 8)})
connect_errnos = {}
for family, target in ((socket.AF_INET, ('198.51.100.1', 9)),
                       (socket.AF_INET6, ('2001:db8::1', 9))):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as test:
            test.settimeout(0.25)
            test.connect(target)
        error = 0
    except OSError as exc:
        error = exc.errno if exc.errno is not None else -1
    connect_errnos[str(family)] = error
print(json.dumps({
    'connect_errnos': connect_errnos,
    'ipv6_addresses': text('/proc/self/net/if_inet6'),
    'kind': 'namespace_diagnostic_not_capability',
    'uid': os.geteuid(), 'gid': os.getegid(), 'pid': os.getpid(),
    'namespaces': {name: os.readlink('/proc/self/ns/' + name)
                   for name in ('net', 'mnt', 'pid', 'user', 'uts')},
    'sysfs_entries': sorted(p.name for p in pathlib.Path('/sys/class/net').iterdir()),
    'socket_interfaces': rows,
    'proc_net_dev': text('/proc/self/net/dev'),
    'ipv4_routes': text('/proc/self/net/route'),
    'ipv6_routes': text('/proc/self/net/ipv6_route'),
    'status': text('/proc/self/status'),
    'sysfs_mounts': [line for line in text('/proc/self/mountinfo').splitlines()
                     if ' - sysfs ' in line],
}, sort_keys=True))
"""


def diagnose(smoke: Smoke, *, network: str = "none") -> None:
    from macos_milestone_smoke import BASE, StageFailure

    if network not in {"none", "bridge"}:
        raise ValueError("diagnostic network must be none or bridge")
    name = "heph-macos-network-" + secrets.token_hex(16)
    smoke.owned.append(name)
    smoke.report["network_diagnostic"] = {
        "status": "started",
        "authorizes_execution": False,
        "network_mode": network,
        "scope": "separate namespace; pinned preparation base; not executor probe",
        "container_name": name,
    }
    smoke.save()
    _, container_id = smoke.command(
        (
            *smoke.docker,
            "create",
            "--name",
            name,
            "--platform",
            "linux/arm64",
            "--pull=never",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--network",
            network,
            "--ipc",
            "none",
            "--hostname",
            "hephaestus-executor",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--memory",
            "512m",
            "--memory-swap",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "64",
            "--ulimit",
            "cpu=10:10",
            "--ulimit",
            "fsize=1048576:1048576",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=16777216",
            BASE,
            "/usr/bin/env",
            "-i",
            "/usr/local/bin/python",
            "-I",
            "-c",
            OBSERVE,
        )
    )
    smoke.report["network_diagnostic"]["container_id"] = container_id.strip()
    _, raw = smoke.command((*smoke.docker, "start", "--attach", name), timeout=20)
    _, state_raw = smoke.command((*smoke.docker, "inspect", "--format", "{{json .State}}", name))
    state = json.loads(state_raw)
    if state["Running"] or state["ExitCode"] != 0 or state.get("OOMKilled"):
        raise StageFailure("namespace diagnostic failed; no inference permitted")
    observation = json.loads(raw)
    target = smoke.directory / "network-diagnostic.json"
    target.write_text(json.dumps(observation, indent=2) + "\n")
    smoke.report["network_diagnostic"].update(status="observed", evidence=target.name, state=state)
    smoke.save()
