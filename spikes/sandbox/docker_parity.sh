#!/usr/bin/env bash
# Docker parity lane for Spike F: run the SAME probes.py inside python:3.13-slim
# with --network none --read-only (the macOS OCI-backend equivalent of the bwrap
# lane). Writes structured JSON to out/docker_results.json.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/out"
mkdir -p "$OUT"

IMG="python:3.13-slim"
echo "== docker parity: pulling $IMG =="
docker pull "$IMG" 2>&1 | tail -2

# A host pid that exists but must be invisible/unkillable inside the container.
HOST_PID=$$
# A host sentinel env var that must NOT leak into the container.
export HEPH_SANDBOX_SENTINEL="leaked-secret-value-should-never-reach-child"
# A live host loopback listener (started in background) the container must not reach.
python3 - "$OUT/port.txt" <<'PY' &
import socket, sys, time
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
s.bind(("127.0.0.1",0)); s.listen(8)
open(sys.argv[1],"w").write(str(s.getsockname()[1]))
while True:
    try: c,_=s.accept(); c.close()
    except OSError: break
PY
LISTENER=$!
sleep 1
PORT="$(cat "$OUT/port.txt" 2>/dev/null || echo 0)"

CFG=$(python3 -c "import json,sys;print(json.dumps({
  'host_pid': int(sys.argv[1]),
  'sentinel_name': 'HEPH_SANDBOX_SENTINEL',
  'localhost_port': int(sys.argv[2]),
  'project_dir': '/project',
  'expect_file': ['data.txt', 'hello from project fixture\n'],
}))" "$HOST_PID" "$PORT")

echo "== docker run: --network none --read-only --pid host? NO (default isolated pidns) =="
# --read-only makes the container rootfs read-only; --tmpfs /tmp gives scratch;
# probes.py + the project dir are bind-mounted read-only; env is NOT forwarded.
docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,size=64m \
  --memory 256m --memory-swap 256m \
  --pids-limit 128 \
  -v "$HERE/probes.py:/probes.py:ro" \
  -v "$HERE/fixtures/project:/project:ro" \
  -w /project \
  "$IMG" python /probes.py probe "$CFG" \
  > "$OUT/docker_probe.json" 2>"$OUT/docker_probe.stderr"
RC=$?
echo "docker probe rc=$RC"

echo "== docker memory-cap test: allocate 2 GiB under 256m cap =="
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m \
  --memory 256m --memory-swap 256m \
  -v "$HERE/probes.py:/probes.py:ro" \
  "$IMG" python /probes.py alloc 2147483648 \
  > "$OUT/docker_alloc.json" 2>"$OUT/docker_alloc.stderr"
ARC=$?
echo "docker alloc rc=$ARC (137=OOM-killed by cgroup)"

echo "== docker wall-timeout test: infinite loop with 3s docker-side timeout =="
timeout --signal=KILL 3 docker run --rm --network none --read-only \
  --tmpfs /tmp:rw,size=64m --memory 256m \
  -v "$HERE/probes.py:/probes.py:ro" \
  "$IMG" python /probes.py spin \
  > "$OUT/docker_spin.stdout" 2>"$OUT/docker_spin.stderr"
TRC=$?
echo "docker spin timeout rc=$TRC (137=killed by timeout)"

# roll everything into one structured record
python3 - "$OUT" "$RC" "$ARC" "$TRC" > "$OUT/docker_results.json" <<'PY'
import json, os, sys
out, rc, arc, trc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
def load(p):
    try: return json.load(open(os.path.join(out,p)))
    except Exception as e: return {"_error": str(e)}
probe = load("docker_probe.json")
alloc = load("docker_alloc.json")
# In the OCI lane the container ships its OWN throwaway rootfs, so reading its
# internal /etc/shadow, /home, or /project/../../etc/passwd exposes container
# files, NOT host files. Those probes are expected to differ from the bwrap lane
# (where nothing is mounted). Split host-escape (must block) from container-internal.
CONTAINER_INTERNAL = {"read_etc_shadow","list_home","dotdot_traversal_etc_passwd",
                      "symlink_to_home_escape"}
probes = probe.get("probes") or []
host_escape = [p for p in probes if p["name"] not in CONTAINER_INTERNAL]
internal = [p for p in probes if p["name"] in CONTAINER_INTERNAL]
host_containment_ok = all(p["ok"] for p in host_escape)
rec = {
  "image": "python:3.13-slim",
  "flags": ["--network none","--read-only","--tmpfs /tmp","--memory 256m","--memory-swap 256m","--pids-limit 128"],
  "probe": {"returncode": rc,
            "host_containment_ok": host_containment_ok,
            "all_ok_note": "raw ok=%s; container-internal reads expose the container's own ephemeral rootfs, not the host" % bool(probe.get("ok")),
            "host_escape_probes": host_escape,
            "container_internal_reads": [{"name":p["name"],"outcome":p["outcome"],"detail":p["detail"][:80]} for p in internal],
            "python": probe.get("python")},
  "memory_cap": {"returncode": arc, "oom_killed": arc == 137,
                 "parsed": alloc if "_error" not in alloc else None,
                 "ok": arc == 137 or bool(alloc.get("killed"))},
  "wall_timeout": {"returncode": trc, "killed": trc == 137 or trc == 124, "ok": trc in (124,137)},
}
rec["overall_ok"] = host_containment_ok and rec["memory_cap"]["ok"] and rec["wall_timeout"]["ok"]
json.dump(rec, sys.stdout, indent=2)
PY

kill "$LISTENER" 2>/dev/null
echo
echo "== docker parity summary =="
python3 -c "import json;d=json.load(open('$OUT/docker_results.json'));print(json.dumps({'host_containment_ok':d['probe']['host_containment_ok'],'memory_cap_ok':d['memory_cap']['ok'],'wall_timeout_ok':d['wall_timeout']['ok'],'overall_ok':d['overall_ok']},indent=2))"
