#!/usr/bin/env bash
# Spike B driver: runs the scripted client over stdio and streamable HTTP,
# capturing logs under out/. Exits non-zero if either transport fails.
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p out

echo "== versions ==" | tee out/versions.log
uv run python -c "
import sys, importlib.metadata as im
print('python', sys.version)
for pkg in ('fastmcp', 'mcp', 'pydantic', 'uvicorn', 'httpx'):
    print(pkg, im.version(pkg))
" | tee -a out/versions.log

echo "== stdio =="
uv run python scripted_client.py stdio >out/stdio.log 2>&1
STDIO_RC=$?
echo "stdio exit code: $STDIO_RC" | tee -a out/stdio.log

echo "== http =="
uv run python echo_server.py --http >out/http_server.log 2>&1 &
SERVER_PID=$!
# wait for the port
for i in $(seq 1 50); do
  if uv run python -c "import socket; socket.create_connection(('127.0.0.1',8765),0.2).close()" 2>/dev/null; then
    break
  fi
  sleep 0.2
done
uv run python scripted_client.py http http://127.0.0.1:8765/mcp >out/http.log 2>&1
HTTP_RC=$?
echo "http exit code: $HTTP_RC" | tee -a out/http.log
kill "$SERVER_PID" 2>/dev/null
wait "$SERVER_PID" 2>/dev/null

echo "---- summary ----"
echo "stdio: exit $STDIO_RC"
echo "http:  exit $HTTP_RC"
[ "$STDIO_RC" -eq 0 ] && [ "$HTTP_RC" -eq 0 ]
