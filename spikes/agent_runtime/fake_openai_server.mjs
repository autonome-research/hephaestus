// Minimal fake OpenAI-compatible chat-completions server (~40 lines of logic).
// Turn 1 (no `tool` role message in the request): streams one tool call to
// `heph_fake`. Turn 2 (a `tool` role message present): streams final text.
// Exported as startFakeServer() so the proof script owns its lifecycle.
import http from "node:http";

const chunk = (delta, finish = null) =>
  `data: ${JSON.stringify({
    id: "chatcmpl-heph-1", object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000), model: "heph-fake-model",
    choices: [{ index: 0, delta, finish_reason: finish }],
    usage: finish ? { prompt_tokens: 7, completion_tokens: 5, total_tokens: 12 } : undefined,
  })}\n\n`;

export function startFakeServer(log = () => {}) {
  const requests = [];
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (d) => (body += d));
    req.on("end", () => {
      const parsed = JSON.parse(body || "{}");
      requests.push({ method: req.method, url: req.url, toolNamesOffered: (parsed.tools ?? []).map((t) => t.function?.name), roles: (parsed.messages ?? []).map((m) => m.role) });
      log(`fake-server: ${req.method} ${req.url} roles=[${(parsed.messages ?? []).map((m) => m.role)}]`);
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      const hasToolResult = (parsed.messages ?? []).some((m) => m.role === "tool");
      const toolsOffered = (parsed.tools ?? []).length > 0;
      // Tool-less requests (e.g. compaction summarization) always get text.
      if (toolsOffered && !hasToolResult) {
        res.write(chunk({ role: "assistant", content: "" }));
        res.write(chunk({ tool_calls: [{ index: 0, id: "call_heph_1", type: "function", function: { name: "heph_fake", arguments: JSON.stringify({ ping: "from-fake-server" }) } }] }));
        res.write(chunk({}, "tool_calls"));
      } else {
        res.write(chunk({ role: "assistant", content: "" }));
        for (const word of ["HEPH_FINAL:", " tool", " roundtrip", " ok"]) res.write(chunk({ content: word }));
        res.write(chunk({}, "stop"));
      }
      res.write("data: [DONE]\n\n");
      res.end();
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve({ server, port: server.address().port, requests }));
  });
}
