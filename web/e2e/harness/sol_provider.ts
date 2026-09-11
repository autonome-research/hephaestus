// A strict loopback Codex Responses endpoint. It proves transport, not vision.
import { createServer } from "node:http";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { zstdDecompressSync } from "node:zlib";
import { expect } from "@playwright/test";
import { decodePng } from "../helpers/png";

export interface SolImageProof {
  part: string; view: string; channel: string; source_artifact_ref: string;
  render_artifact_ref: string; sha256: string; bytes: number; width: number; height: number;
}
export interface SolRequestProof {
  index: number; model: string; path: string; encoding: string;
  call_id: string | null; images: SolImageProof[]; output_text: string | null;
}

export async function startSolProvider(directory: string, missingBuild = false) {
  const limits = JSON.parse(readFileSync(new URL("../../../schemas/bridge_limits.json", import.meta.url), "utf8")) as { wire: { max_frame_bytes: number }; binary: { max_binary_bytes: number }; image: { max_images_per_result: number; max_image_bytes: number; max_width: number; max_height: number; max_total_pixels: number } };
  const requests: SolRequestProof[] = [];
  const failures: string[] = [];
  let upgrades = 0;
  const server = createServer((req, res) => {
    void (async () => {
      expect(req.method).toBe("POST");
      expect(req.url).toBe("/backend-api/codex/responses");
      expect(requests.length).toBeLessThan(2); // one call + one continuation, no retries
      const chunks: Buffer[] = [];
      let length = 0;
      for await (const chunk of req) {
        length += (chunk as Buffer).length;
        expect(length).toBeLessThanOrEqual(limits.wire.max_frame_bytes);
        chunks.push(chunk as Buffer);
      }
      const wire = Buffer.concat(chunks);
      const encoding = String(req.headers["content-encoding"] ?? "identity");
      expect(["identity", "zstd"]).toContain(encoding);
      const raw = encoding === "zstd" ? zstdDecompressSync(wire, { maxOutputLength: limits.wire.max_frame_bytes }) : wire;
      const body = JSON.parse(raw.toString("utf8")) as { model: string; input: Record<string, unknown>[]; tools: { name: string }[] };
      expect(body.model).toBe("gpt-5.6-sol");
      expect(body.tools.some(tool => tool.name === "inspect_part")).toBe(true);
      const outputs = body.input.filter(item => item["type"] === "function_call_output");
      const proofs: SolImageProof[] = [];
      let outputText: string | null = null;
      if (requests.length === 0) expect(outputs).toHaveLength(0);
      else {
        expect(outputs).toHaveLength(1);
        expect(outputs[0]!["call_id"]).toBe("sol_image_call");
        if (missingBuild) {
          outputText = outputs[0]!["output"] as string;
          expect(typeof outputText).toBe("string");
          expect(outputText).toMatch(/build|artifact|not_found/);
          expect(outputText).not.toContain("data:image");
        } else {
          const content = outputs[0]!["output"] as { type: string; text?: string; image_url?: string }[];
          expect(content.map(block => block.type)).toEqual(["input_text", "input_image", "input_image"]);
          const descriptor = JSON.parse(content[0]!.text!) as { images: (SolImageProof & { mime_type: string })[]; render_artifact_refs: string[]; source_artifact_ref: string };
          expect(descriptor.images).toHaveLength(2);
          expect(descriptor.images.length).toBeLessThanOrEqual(limits.image.max_images_per_result);
          let totalBytes = 0; let totalPixels = 0;
          for (const [index, desc] of descriptor.images.entries()) {
            const uri = content[index + 1]!.image_url!;
            expect(uri).toMatch(/^data:image\/png;base64,/);
            const encoded = uri.split(",")[1]!;
            const bytes = Buffer.from(encoded, "base64");
            expect(bytes.toString("base64")).toBe(encoded);
            expect(bytes.length).toBeLessThanOrEqual(limits.image.max_image_bytes);
            expect(bytes.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
            const width = bytes.readUInt32BE(16); const height = bytes.readUInt32BE(20);
            expect(width).toBeGreaterThan(0); expect(height).toBeGreaterThan(0);
            expect(width).toBeLessThanOrEqual(limits.image.max_width); expect(height).toBeLessThanOrEqual(limits.image.max_height);
            const decoded = decodePng(bytes);
            expect([decoded.width, decoded.height]).toEqual([width, height]);
            expect([width, height]).toEqual([960, 720]);
            const sha256 = createHash("sha256").update(bytes).digest("hex");
            expect(desc).toMatchObject({ part: "tread", view: ["iso", "+X"][index], channel: "rgb", mime_type: "image/png", bytes: bytes.length, width, height, source_artifact_ref: descriptor.source_artifact_ref, render_artifact_ref: `artifact:render:sha256:${sha256}` });
            expect(descriptor.render_artifact_refs[index]).toBe(desc.render_artifact_ref);
            totalBytes += bytes.length; totalPixels += width * height;
            proofs.push({ ...desc, sha256 });
          }
          expect(new Set(proofs.map(proof => proof.sha256)).size).toBe(2);
          expect(totalBytes).toBeLessThanOrEqual(limits.binary.max_binary_bytes);
          expect(totalPixels).toBeLessThanOrEqual(limits.image.max_total_pixels);
        }
      }
      requests.push({ index: requests.length, model: body.model, path: req.url!, encoding, call_id: outputs.length ? "sol_image_call" : null, images: proofs, output_text: outputText });
      writeFileSync(`${directory}/sol-requests.json`, JSON.stringify(requests, null, 2));
      const item = requests.length === 1
        ? { type: "function_call", id: "fc_sol_image", call_id: "sol_image_call", name: "inspect_part", arguments: JSON.stringify({ name: missingBuild ? "riser" : "tread", views: ["iso", "+X"] }), status: "completed" }
        : { type: "message", id: "msg_sol", role: "assistant", status: "completed", content: [{ type: "output_text", text: "SOL_TRANSPORT_ONLY_DONE (not a visual assessment)", annotations: [] }] };
      const events = [
        { type: "response.created", response: { id: `resp_${requests.length}` } },
        { type: "response.output_item.added", output_index: 0, item },
        { type: "response.output_item.done", output_index: 0, item },
        { type: "response.completed", response: { id: `resp_${requests.length}`, status: "completed", output: [item], usage: { input_tokens: 8, output_tokens: 4, total_tokens: 12 } } },
      ];
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.end(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(""));
    })().catch(error => {
      failures.push(String(error));
      writeFileSync(`${directory}/sol-failures.json`, JSON.stringify(failures));
      res.writeHead(400); res.end("strict Sol fixture assertion failed");
    });
  });
  // The pinned default is auto (WebSocket then SSE). Refuse the owned upgrade
  // explicitly so the SDK's unmodified fallback issues real HTTP input_image.
  server.on("upgrade", (req, socket) => {
    if (req.url !== "/backend-api/codex/responses") failures.push("unexpected websocket path");
    upgrades++;
    socket.end("HTTP/1.1 426 Upgrade Required\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw Error("missing loopback address");
  return {
    endpoint: `http://127.0.0.1:${address.port}`,
    requests, failures,
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
      writeFileSync(`${directory}/sol-cleanup.json`, JSON.stringify({ endpoint_closed: true, upgrades, failures }));
      expect(failures).toEqual([]);
    },
  };
}
