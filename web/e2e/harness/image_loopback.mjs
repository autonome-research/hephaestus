// Test-only socket boundary. Used by an owned HEPHAESTUS_NODE launcher, never
// installed in product code. No payload/serializer/model substitution.
import fs from 'node:fs';
import net from 'node:net';
import process from 'node:process';
import { URL } from 'node:url';
const endpoint = new URL(process.env.HEPH_TEST_ENDPOINT);
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1') throw Error('loopback endpoint required');
const journal = process.env.HEPH_TEST_NETWORK_JOURNAL;
function record(event) { fs.appendFileSync(journal, JSON.stringify(event) + '\n'); }
record({ event: 'guard_loaded', pid: process.pid });
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  const options = typeof first === 'object' ? first : { port: first, host: args[1] };
  const host = options.host ?? options.hostname ?? 'localhost';
  if (host !== endpoint.hostname || String(options.port) !== endpoint.port) {
    record({ event: 'denied_socket' });
    throw Error('image harness refused non-fixture socket');
  }
  return connect.apply(this, args);
};
const fetch = globalThis.fetch;
globalThis.fetch = function (input, init) {
  const url = new URL(input instanceof globalThis.Request ? input.url : String(input));
  if (url.origin !== endpoint.origin) {
    record({ event: 'denied_fetch' });
    throw Error('image harness refused non-fixture HTTP');
  }
  return fetch(input, { ...init, redirect: 'error' });
};
