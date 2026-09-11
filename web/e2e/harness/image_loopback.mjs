// Test-only socket boundary. Used by an owned HEPHAESTUS_NODE launcher, never
// installed in product code. No payload/serializer/model substitution.
import fs from 'node:fs';
import net from 'node:net';
import process from 'node:process';
import { URL } from 'node:url';
const endpoint = new URL(process.env.HEPH_TEST_ENDPOINT);
const endpoints = [endpoint, new URL(process.env.HEPH_TEST_EXTRA_ENDPOINT ?? endpoint.href)];
for (const allowed of endpoints) if (allowed.protocol !== 'http:' || allowed.hostname !== '127.0.0.1') throw Error('loopback endpoint required');
const journal = process.env.HEPH_TEST_NETWORK_JOURNAL;
function record(event) { fs.appendFileSync(journal, JSON.stringify(event) + '\n'); }
record({ event: 'guard_loaded', pid: process.pid });
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const options = typeof first === 'object' ? first : { port: first, host: args[1] };
  const host = options.host ?? options.hostname ?? 'localhost';
  if (!endpoints.some(allowed => host === allowed.hostname && String(options.port) === allowed.port)) {
    record({ event: 'denied_socket' });
    throw Error('image harness refused non-fixture socket');
  }
  return connect.apply(this, args);
};
function target(input, websocket = false) {
  const url = new URL(input);
  const codex = websocket ? 'wss://chatgpt.com/backend-api/codex/responses' : 'https://chatgpt.com/backend-api/codex/responses';
  if (process.env.HEPH_TEST_CODEX_REDIRECT === '1' && url.href === codex) {
    record({ event: websocket ? 'codex_ws_redirect' : 'codex_http_redirect' });
    return `${websocket ? endpoint.origin.replace('http:', 'ws:') : endpoint.origin}${url.pathname}`;
  }
  return url.href;
}
const WebSocket = globalThis.WebSocket;
if (WebSocket) globalThis.WebSocket = class extends WebSocket {
  constructor(url, options) {
    const redirected = target(String(url), true);
    if (new URL(redirected).origin !== endpoint.origin.replace('http:', 'ws:')) {
      record({ event: 'denied_websocket' });
      throw Error('image harness refused non-fixture WebSocket');
    }
    super(redirected, options);
  }
};
const fetch = globalThis.fetch;
globalThis.fetch = function (input, init) {
  const original = input instanceof globalThis.Request ? input.url : String(input);
  const url = new URL(target(original));
  if (!endpoints.some(allowed => url.origin === allowed.origin)) {
    record({ event: 'denied_fetch' });
    throw Error('image harness refused non-fixture HTTP');
  }
  // Endpoint-only redirection: pass the SDK-produced body/headers unchanged.
  const redirected = input instanceof globalThis.Request ? new globalThis.Request(url, input) : url;
  return fetch(redirected, { ...init, redirect: 'error' });
};
