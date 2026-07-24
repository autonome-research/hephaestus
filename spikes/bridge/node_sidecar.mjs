#!/usr/bin/env node
// Spike E sidecar: newline-delimited JSON-RPC 2.0 over stdio.
// Protocol stdout carries only frames; all logging goes to stderr.
// Frames larger than MAX_FRAME bytes are rejected with a structured error
// (code -32001, id null) without crashing or desynchronizing the stream.

const MAX_FRAME = 1024 * 1024; // 1 MiB spike-level cap (architecture.md S5 uses 64 MiB)

// 1x1 red PNG.
const PNG_1X1 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}
function respond(id, result) {
  send({ jsonrpc: '2.0', id, result });
}
function sendError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) error.data = data;
  send({ jsonrpc: '2.0', id, error });
}
function sendEvent(params) {
  send({ jsonrpc: '2.0', method: 'event', params });
}

const inflight = new Map(); // id -> { timer } for cancellable 'slow' calls
const questions = new Map(); // question_id -> { question } for ask_user suspension

function handle(msg) {
  const { id, method } = msg;
  const params = msg.params ?? {};

  if (id === undefined || id === null) {
    // Notification.
    if (method === '$/cancel') {
      const target = params.id;
      const entry = inflight.get(target);
      if (entry) {
        clearTimeout(entry.timer);
        inflight.delete(target);
        sendError(target, -32800, 'request cancelled');
        sendEvent({ type: 'cancelled', id: target });
      } else {
        sendEvent({ type: 'cancel_noop', id: target });
      }
    }
    return;
  }

  switch (method) {
    case 'echo':
      respond(id, params);
      break;
    case 'slow': {
      const ms = Number(params.ms ?? 0);
      const timer = setTimeout(() => {
        inflight.delete(id);
        respond(id, { slept_ms: ms });
      }, ms);
      inflight.set(id, { timer });
      break;
    }
    case 'ask_user': {
      const qid = 'q' + id;
      const question = String(params.question ?? '');
      questions.set(qid, { question });
      // Suspension marker: the call "completes" at the RPC layer with a
      // suspended status; the logical operation finishes on a later 'answer'.
      respond(id, { status: 'suspended', question_id: qid, question });
      break;
    }
    case 'answer': {
      const qid = params.question_id;
      const q = questions.get(qid);
      if (!q) {
        sendError(id, -32602, `unknown question_id: ${qid}`);
        break;
      }
      questions.delete(qid);
      respond(id, {
        status: 'completed',
        question_id: qid,
        question: q.question,
        answer: params.answer,
      });
      sendEvent({ type: 'ask_user_completed', question_id: qid });
      break;
    }
    case 'image':
      respond(id, { mime: 'image/png', encoding: 'base64', data: PNG_1X1 });
      break;
    case 'big': {
      // Deliberately produce an oversized sidecar->supervisor frame so the
      // Python framer's inbound guard can be exercised.
      const bytes = Math.min(Number(params.bytes ?? 0), 8 * 1024 * 1024);
      respond(id, { data: 'x'.repeat(bytes) });
      break;
    }
    default:
      sendError(id, -32601, `method not found: ${method}`);
  }
}

function handleLine(text) {
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    sendError(null, -32700, 'parse error');
    return;
  }
  try {
    handle(msg);
  } catch (err) {
    sendError(msg.id ?? null, -32603, `internal error: ${err.message}`);
  }
}

// Incremental framer with size guard: never buffers more than MAX_FRAME
// bytes of a single frame; oversized frames are dropped through the next
// newline and reported once each with a structured -32001 error.
let acc = [];
let accLen = 0;
let discarding = false;

function rejectOversize() {
  acc = [];
  accLen = 0;
  sendError(null, -32001, `frame exceeds ${MAX_FRAME} bytes`, { max_frame_bytes: MAX_FRAME });
}

process.stdin.on('data', (chunk) => {
  let start = 0;
  for (;;) {
    const nl = chunk.indexOf(0x0a, start);
    if (nl === -1) {
      const rest = chunk.subarray(start);
      if (!discarding && rest.length > 0) {
        acc.push(rest);
        accLen += rest.length;
        if (accLen > MAX_FRAME) {
          discarding = true;
          rejectOversize();
        }
      }
      break;
    }
    const part = chunk.subarray(start, nl);
    if (discarding) {
      discarding = false; // frame boundary reached; resume normal framing
    } else {
      acc.push(part);
      accLen += part.length;
      if (accLen > MAX_FRAME) {
        rejectOversize();
      } else {
        const line = Buffer.concat(acc).toString('utf8');
        acc = [];
        accLen = 0;
        if (line.trim().length > 0) handleLine(line);
      }
      acc = [];
      accLen = 0;
    }
    start = nl + 1;
  }
});

process.stdin.on('end', () => {
  process.exit(0);
});

console.error(`[sidecar] started pid=${process.pid}`);
sendEvent({ type: 'ready', pid: process.pid });
setTimeout(() => sendEvent({ type: 'tick', note: 'spontaneous event' }), 50);
