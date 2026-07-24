"""Bubblewrap-based secure executor for Hephaestus Stage S spike F.

Public surface:
  detect_capability()    -> fail-closed probe: does a usable bwrap exist here?
  build_bwrap_argv(...)  -> the exact argv list (captured/logged verbatim)
  run_sandboxed(...)     -> launch a child python under bwrap with rlimits + wall timeout

Design:
  * read-only bind of one project dir at /project
  * tmpfs for /tmp, private /proc + /dev; everything else invisible
  * --unshare-net (no network) --unshare-pid (no host pids) + user/ipc/uts
  * --clearenv so the host environment cannot leak in
  * a relocated CPython 3.13 is ro-bound at /opt/python (host has 3.14 as system python)
  * memory cap via RLIMIT_AS + RLIMIT_DATA set with setrlimit in a preexec hook
    (inherited across bwrap's exec into the child)
  * wall-clock cap via subprocess timeout -> kill the whole process group
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


def find_bwrap() -> str | None:
    return shutil.which("bwrap")


def _python_root() -> str:
    # The interpreter running this runner is a venv on top of the relocatable uv
    # CPython 3.13. sys.base_prefix is the real install root (stdlib + libpython +
    # bin/python3); we bind the whole root read-only so the child is self-contained.
    return sys.base_prefix


def build_bwrap_argv(
    bwrap: str,
    project_dir: str,
    python_root: str,
    child_argv: list[str],
    *,
    unshare_net: bool = True,
    unshare_pid: bool = True,
) -> list[str]:
    """Return the exact bwrap argv. child_argv is relative to /opt/python, e.g.
    ['/opt/python/bin/python3', '/opt/python/probes.py', 'probe', '{...}']."""
    argv = [
        bwrap,
        "--die-with-parent",
        "--unshare-user",
        "--unshare-ipc",
        "--unshare-uts",
    ]
    if unshare_net:
        argv += ["--unshare-net"]
    if unshare_pid:
        argv += ["--unshare-pid"]
    argv += [
        "--clearenv",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "HOME", "/project",
        "--setenv", "TMPDIR", "/tmp",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        # base OS, read-only
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/bin", "/sbin",
        "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
        # relocated python 3.13, read-only, plus the probe script mounted read-only
        # (bound at /probes.py, NOT inside the read-only /opt/python mount)
        "--ro-bind", python_root, "/opt/python",
        "--ro-bind", os.path.join(HERE, "probes.py"), "/probes.py",
        # the one project dir the child may see, read-only
        "--ro-bind", project_dir, "/project",
        "--chdir", "/project",
        # seal the base tmpfs root so nothing outside the explicit writable mounts
        # (/tmp, /proc, /dev) can be created or written. Applied last; the separate
        # submounts keep their own mount flags.
        "--remount-ro", "/",
    ]
    argv += child_argv
    return argv


@dataclass
class RunResult:
    argv: list[str]
    returncode: int | None
    timed_out: bool
    wall_seconds: float
    stdout: str
    stderr: str
    parsed: dict | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "argv": self.argv,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "wall_seconds": round(self.wall_seconds, 3),
            "parsed": self.parsed,
        }
        d.update(self.extra)
        # keep raw output short in the structured record
        d["stdout_tail"] = self.stdout[-2000:]
        d["stderr_tail"] = self.stderr[-2000:]
        return d


def _preexec(mem_bytes: int | None, cpu_seconds: int | None):
    def _fn():
        os.setsid()  # own process group so we can kill the whole sandbox tree
        if mem_bytes:
            resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
            resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
        if cpu_seconds:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        # never allow core dumps
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return _fn


def run_sandboxed(
    project_dir: str,
    child_args: list[str],
    *,
    wall_timeout: float = 30.0,
    mem_bytes: int | None = None,
    cpu_seconds: int | None = None,
    unshare_net: bool = True,
    unshare_pid: bool = True,
) -> RunResult:
    bwrap = find_bwrap()
    if not bwrap:
        raise RuntimeError("bwrap not found; refuse to run unsandboxed (fail closed)")
    python_root = _python_root()
    child_argv = ["/opt/python/bin/python3", "/probes.py", *child_args]
    argv = build_bwrap_argv(
        bwrap, os.path.abspath(project_dir), python_root, child_argv,
        unshare_net=unshare_net, unshare_pid=unshare_pid,
    )
    import time
    t0 = time.monotonic()
    timed_out = False
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        preexec_fn=_preexec(mem_bytes, cpu_seconds),
    )
    try:
        out, err = proc.communicate(timeout=wall_timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
        rc = proc.returncode
    wall = time.monotonic() - t0
    parsed = None
    for line in (out or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                pass
    if parsed is None:
        # try the whole blob (indented json)
        try:
            parsed = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            parsed = None
    return RunResult(argv, rc, timed_out, wall, out or "", err or "", parsed)


def detect_capability(project_dir: str) -> dict:
    """Fail-closed probe. Returns a structured capability report. `usable` is True
    only if bwrap exists AND a trivial sandboxed command runs AND the network is
    actually blocked inside (a defense-in-depth check, not just a version string)."""
    report: dict = {"bwrap_path": None, "bwrap_version": None, "usable": False,
                    "reason": None, "checks": {}}
    bwrap = find_bwrap()
    report["bwrap_path"] = bwrap
    if not bwrap:
        report["reason"] = "bwrap not on PATH"
        return report  # fail closed
    try:
        v = subprocess.run([bwrap, "--version"], capture_output=True, text=True, timeout=5)
        report["bwrap_version"] = v.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"bwrap --version failed: {exc}"
        return report
    # trivial sandboxed run
    try:
        res = run_sandboxed(project_dir, ["probe", json.dumps({
            "expect_file": None,
        })], wall_timeout=20.0, mem_bytes=512 * 1024 * 1024)
    except Exception as exc:  # noqa: BLE001
        report["reason"] = f"sandboxed launch raised: {exc}"
        return report
    report["checks"]["returncode"] = res.returncode
    report["checks"]["ran"] = res.parsed is not None
    if res.parsed is None:
        report["reason"] = f"no structured output (rc={res.returncode}, stderr={res.stderr[-300:]!r})"
        return report
    # require the network + shadow probes to have actually blocked
    by_name = {p["name"]: p for p in res.parsed.get("probes", [])}
    net_ok = by_name.get("tcp_1.1.1.1_443", {}).get("ok") is True
    shadow_ok = by_name.get("read_etc_shadow", {}).get("ok") is True
    report["checks"]["network_blocked"] = net_ok
    report["checks"]["shadow_blocked"] = shadow_ok
    report["checks"]["all_probes_ok"] = res.parsed.get("ok")
    if net_ok and shadow_ok and res.parsed.get("ok"):
        report["usable"] = True
    else:
        report["reason"] = "sandbox ran but a containment probe did not block"
    return report


if __name__ == "__main__":
    proj = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures", "project")
    print(json.dumps(detect_capability(proj), indent=2))
