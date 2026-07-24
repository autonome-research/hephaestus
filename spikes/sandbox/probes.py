"""Child-side escape/limit probes. Runs INSIDE the sandbox (bwrap or docker).

Stdlib only. Prints one JSON document to stdout:
  {"python": ..., "mode": ..., "probes": [{name, expect, blocked/allowed, ok, detail}], "ok": bool}

Modes (first argv token):
  probe '<json-config>'   run the escape-probe suite
  spin                    busy-loop forever (wall-clock timeout target)
  alloc <bytes>           try to allocate <bytes>; report MemoryError as structured JSON

Config keys for `probe`:
  host_pid        a PID known to exist on the HOST (must not be visible/killable here)
  sentinel_name   env var name set on the host runner (must not leak in here)
  localhost_port  a port with a live listener on the HOST's 127.0.0.1 (must be unreachable)
  project_dir     mount point of the read-only project bind (default /project)
  expect_file     relative path + expected content proving legit reads work, e.g.
                  ["data.txt", "hello from project fixture\n"]
"""

from __future__ import annotations

import errno
import json
import os
import socket
import subprocess
import sys


def _attempt(fn):
    """Run fn(); return (blocked, detail). blocked=True iff it raised."""
    try:
        result = fn()
        return False, f"succeeded: {result!r}"
    except Exception as exc:  # noqa: BLE001 - we classify every failure as 'blocked'
        eno = getattr(exc, "errno", None)
        ename = errno.errorcode.get(eno, "") if eno is not None else ""
        return True, f"{type(exc).__name__}({ename or eno}): {exc}"


def run_probe_suite(cfg: dict) -> dict:
    project = cfg.get("project_dir", "/project")
    probes: list[dict] = []

    def add(name: str, expect: str, fn):
        blocked, detail = _attempt(fn)
        ok = blocked if expect == "blocked" else not blocked
        probes.append(
            {"name": name, "expect": expect,
             "outcome": "blocked" if blocked else "allowed", "ok": ok, "detail": detail}
        )

    # 1. read /etc/shadow
    add("read_etc_shadow", "blocked", lambda: open("/etc/shadow", "rb").read(16))

    # 2. writes outside the project dir (and into the ro project bind itself)
    add("write_into_ro_project_bind", "blocked",
        lambda: open(os.path.join(project, "pwned.txt"), "w"))
    add("write_fs_root", "blocked", lambda: open("/pwned.txt", "w"))
    add("write_etc", "blocked", lambda: open("/etc/pwned.txt", "w"))
    add("write_home", "blocked", lambda: open("/home/pwned.txt", "w"))
    add("list_home", "blocked", lambda: os.listdir("/home"))

    # 3. network: public internet and host loopback
    def _connect(host: str, port: int):
        with socket.create_connection((host, port), timeout=3) as s:
            return s.getpeername()

    add("tcp_1.1.1.1_443", "blocked", lambda: _connect("1.1.1.1", 443))
    lp = int(cfg.get("localhost_port", 0))
    if lp:
        add("tcp_host_loopback_listener", "blocked", lambda: _connect("127.0.0.1", lp))

    # 4. ../ and symlink traversal out of the bind
    add("dotdot_traversal_etc_passwd", "blocked",
        lambda: open(os.path.join(project, "..", "..", "etc", "passwd"), "rb").read(16))

    def _symlink_escape():
        link = "/tmp/esc"
        try:
            os.symlink("/home", link)
        except FileExistsError:
            pass
        return os.listdir(link)

    add("symlink_to_home_escape", "blocked", _symlink_escape)

    # 5. signal a host pid
    host_pid = int(cfg.get("host_pid", 0))
    if host_pid:
        add("kill_host_pid", "blocked", lambda: os.kill(host_pid, 0))

    # 6. host environment leak via subprocess /usr/bin/env
    sentinel = cfg.get("sentinel_name", "HEPH_SANDBOX_SENTINEL")

    def _env_leak():
        out = subprocess.run(["/usr/bin/env"], capture_output=True, text=True,
                             timeout=10, check=True).stdout
        if sentinel in out or sentinel in os.environ:
            return f"SENTINEL {sentinel} LEAKED: {out!r}"
        raise RuntimeError(f"sentinel {sentinel} absent from child env ({len(out)} bytes of env)")

    add("host_env_leak_via_subprocess_env", "blocked", _env_leak)

    # 7. legit computation must still work
    def _compute():
        import hashlib
        digest = hashlib.sha256(b"hephaestus" * 100_000).hexdigest()
        with open("/tmp/scratch.txt", "w") as f:
            f.write(digest)
        readback = open("/tmp/scratch.txt").read()
        assert readback == digest
        return digest[:12]

    add("legit_compute_and_tmp_write", "allowed", _compute)

    ef = cfg.get("expect_file")
    if ef:
        rel, expected = ef

        def _read_project():
            content = open(os.path.join(project, rel)).read()
            assert content == expected, f"content mismatch: {content!r}"
            return f"read {rel} ok"

        add("legit_read_project_file", "allowed", _read_project)

    return {"python": sys.version.split()[0], "mode": "probe",
            "probes": probes, "ok": all(p["ok"] for p in probes)}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    if mode == "spin":
        while True:
            pass
    elif mode == "alloc":
        size = int(sys.argv[2])
        try:
            buf = bytearray(size)
            buf[::4096] = b"x" * len(buf[::4096])  # touch pages
            print(json.dumps({"mode": "alloc", "allocated": size, "killed": False, "ok": False}))
        except MemoryError:
            print(json.dumps({"mode": "alloc", "requested": size, "killed": True,
                              "kind": "MemoryError", "ok": True}))
        return 0
    cfg = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    report = run_probe_suite(cfg)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
