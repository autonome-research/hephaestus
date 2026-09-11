import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("image harness network boundary (rejected before DNS/connect)", () => {
  it.each([
    ["fetch", "await fetch('https://not-allowed.invalid/')", "denied_fetch"],
    ["socket", "net.connect({ host: 'not-allowed.invalid', port: 443 })", "denied_socket"],
    ["loopback-other-port", "net.connect({ host: '127.0.0.1', port: 9 })", "denied_socket"],
    ["websocket", "new WebSocket('wss://not-allowed.invalid/')", "denied_websocket"],
    ["codex-other-path", "await fetch('https://chatgpt.com/backend-api/not-codex')", "denied_fetch"],
  ])("refuses %s without external connection", (_label, attempt, expected) => {
    const directory = mkdtempSync(path.join(tmpdir(), "heph-image-guard-"));
    const journal = path.join(directory, "network.jsonl");
    const child = spawnSync(process.execPath, ["--import", path.resolve("e2e/harness/image_loopback.mjs"), "--input-type=module", "-e", `import net from 'node:net'; try { ${attempt}; process.exitCode = 2; } catch (error) { if (!String(error).includes('image harness refused')) throw error; }`], {
      env: { HOME: directory, HEPH_TEST_ENDPOINT: "http://127.0.0.1:1", HEPH_TEST_NETWORK_JOURNAL: journal, HEPH_TEST_CODEX_REDIRECT: "1" },
      timeout: 5000, encoding: "utf8",
    });
    expect(child.status, child.stderr).toBe(0);
    expect(readFileSync(journal, "utf8").trim().split("\n").map(line => (JSON.parse(line) as { event: string }).event)).toEqual(["guard_loaded", expected]);
  });
});
