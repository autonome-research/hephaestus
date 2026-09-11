// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Presentation only. Never infer effects on the design from an error envelope.
const secretKey = /^(?:api[_-]?key|access[_-]?token|token|authorization|password|secret)$/i;
function redact(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redact);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, secretKey.test(key) ? "[redacted]" : redact(item)]));
  }
  if (typeof value !== "string") return value;
  // Sanitize string envelopes BEFORE JSON serialization escapes their quotes.
  return value.replace(/(Bearer\s+)[\w.+/=-]+/gi, "$1[redacted]")
    .replace(/((?:api[_-]?key|access[_-]?token|token|authorization|password|secret)["']?\s*[:=]\s*["']?)[^\s,"'}&]+/gi, "$1[redacted]")
    .replace(/https?:\/\/[^\s"'<>]+/gi, "[address redacted]");
}
export function sanitizeDiagnostic(value: unknown): string {
  const safe = redact(value);
  return typeof safe === "string" ? safe : JSON.stringify(safe, null, 2) ?? "";
}
export function readableReason(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") {
    const doc = value as Record<string, unknown>;
    return readableReason(doc["message"] ?? doc["error"] ?? doc["reason"] ?? doc["payload"]);
  }
  if (typeof value !== "string") return null;
  const text = value.replace(/^\s*\d{3}:\s*/, "");
  try { return readableReason(JSON.parse(text)); } catch { /* Plain readable reason. */ }
  // Unparsed structured diagnostics are not primary prose.
  if (/^[{[]/.test(text.trim())) return "The request could not be completed. Inspect Details for the recorded cause.";
  // A provider's recovery/effect assurances are not execution authority. Keep
  // the leading cause here; the complete recorded envelope remains in Details.
  const cause = text.split(/(?<=[.!?])\s+/)[0] ?? text;
  if (/\bno (?:design|files?|geometry|changes?)\b.*\bchang|\b(?:nothing|no changes?) (?:was |were )?(?:changed|made)/i.test(cause)) {
    return "The request could not be completed. Review the recorded result.";
  }
  return sanitizeDiagnostic(cause).replace(/_/g, " ");
}
export function outcomeLabel(state: string): string {
  return ({ completed: "Completed", cancelled: "Cancelled", failed: "Request failed", error: "Request failed", interrupted: "Interrupted" } as Record<string, string>)[state] ?? "Checking";
}
