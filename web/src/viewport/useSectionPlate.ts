// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The **server-rendered** section plate (INTERFACE.md §5.3).
//
// §5.3, the sharpest render decision in the document: "Section renders that any
// gate compares against a golden are **server-rendered PNGs**, produced by the
// existing `render_channel(..., channel="section")` path with
// `section_plane="[+-]AXIS@OFFSET"` and served as artifact bytes. The viewport
// displays them as a **section plate** — a fitted image layer in the Stage —
// with the plate's `source_artifact_ref` shown in the header."
//
// Two properties of this module are the whole point:
//
// 1. **The displayed pixels are the artifact's bytes.** The result also carries
//    an inline base64 preview; it is not used. §12.2 bars every pixel assertion
//    from an inline preview, so a plate rendered from `data:` would put the
//    picture on screen out of step with the bytes G4.7's golden compares. The
//    plate is fetched from `/artifacts/{ref}/bytes` (§2.6: "exact stored bytes,
//    no transformation").
// 2. **The plate's own `source_artifact_ref` is carried through and displayed.**
//    Not the pin the request was made with — the ref the *server* resolved, which
//    is the one §12.1 and §4.4 make the answer.
//
// DEVIATION, recorded loudly rather than reinterpreted. §2.3 lists a dedicated
// `POST /parts/{part}/render/section` route for this and §5.3 names it as the
// producer. **That route does not exist in `server/http` today**: `app.py`'s
// `ROUTE_TABLE` has no row for it, and a boundary test asserts the served
// surface *is* that table, so it cannot be reached. What does exist is
// `POST /parts/{part}/inspect` — `inspect_part` verbatim, a row on the table —
// and `inspect_part(channel="section", section_plane=…, artifact_ref=…)` is
// **literally the `render_channel(..., channel="section")` path §5.3 names**,
// returning the same render artifact under the same `render` kind. So the
// viewport rides the route that exists rather than a route that does not, and
// gets identical bytes by identical machinery. When the dedicated route lands,
// only `plateRequest` below changes.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiBytes, apiJson, refSegment } from "../api/client";
import type { InspectDocument, InspectImage } from "../api/types";

/** `inspect_part`'s channel for a section render. Closed: one channel, one mode. */
const SECTION_CHANNEL = "section";

/** What the Stage needs to draw one plate. */
export interface SectionPlate {
  /** The `render`-kind artifact the plate's pixels came from. */
  readonly render_artifact_ref: string;
  /** The build the **server** resolved the render against (§4.4, §12.1). */
  readonly source_artifact_ref: string;
  /**
   * The artifact's exact stored bytes (§2.6). The **component** wraps these in
   * an object URL and revokes it on unmount: minting the URL here would tie a
   * revocable browser resource to a cache entry that outlives every component
   * holding it, and leaking one per render is how a long session ends up with a
   * few hundred pinned blobs.
   */
  readonly bytes: ArrayBuffer;
  readonly mime_type: string;
  readonly view: string;
  readonly section_plane: string;
}

export interface SectionPlateRequest {
  readonly part: string;
  /** The pin. §12.1: every inspection sends it explicitly. */
  readonly artifact_ref: string;
  readonly view: string;
  readonly section_plane: string;
}

/** A section render the server could produce but this model cannot preview. */
export class CapabilityRefusal extends Error {
  readonly code: string;
  constructor(code: string, message: string) {
    super(message);
    this.name = "CapabilityRefusal";
    this.code = code;
  }
}

export const sectionPlateKey = (request: SectionPlateRequest): readonly unknown[] => [
  "parts",
  request.part,
  "section",
  request.artifact_ref,
  request.view,
  request.section_plane,
];

function sectionImage(document: InspectDocument, view: string): InspectImage | null {
  for (const image of document.images ?? []) {
    if (image.view === view && image.channel === SECTION_CHANNEL) return image;
  }
  return null;
}

async function plateRequest(request: SectionPlateRequest): Promise<SectionPlate> {
  // A **read** route: §2.3 puts `inspect` in the "no idempotency key" table
  // ("the key policy is per route, not per HTTP verb"), so no key is sent and
  // none is expected.
  const document = await apiJson<InspectDocument>(
    `/parts/${encodeURIComponent(request.part)}/inspect`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        views: [request.view],
        channel: SECTION_CHANNEL,
        section_plane: request.section_plane,
        artifact_ref: request.artifact_ref,
      }),
    },
  );

  // §2.4's DECISION: a capability refusal arrives as a discriminated result at
  // 200, not as an exception. It is named here rather than flattened, so the
  // Stage can say *which* absence this is.
  if (document.status === "capability_error") {
    throw new CapabilityRefusal(
      document.code ?? "capability_error",
      document.message ?? "the server declined to produce a section render",
    );
  }

  const image = sectionImage(document, request.view);
  const ref = image?.render_artifact_ref ?? document.render_artifact_refs?.[0];
  if (ref === undefined) {
    throw new CapabilityRefusal(
      "section_render_absent",
      "the inspection returned no section render artifact",
    );
  }

  const { bytes } = await apiBytes(`/artifacts/${refSegment(ref)}/bytes`);
  return {
    render_artifact_ref: ref,
    source_artifact_ref: document.source_artifact_ref,
    bytes,
    mime_type: image?.mime_type ?? "image/png",
    view: request.view,
    section_plane: request.section_plane,
  };
}

/**
 * The plate for one `(part, pin, view, plane)`, fetched only once `enabled`.
 *
 * §5.3: the plate replaces the preview "when the drag settles or the user clicks
 * *Render section*" — so the request is an explicit act, not a consequence of
 * moving a slider. `enabled` is that act; the cache key is the four values that
 * identify the render, so returning to a plane already rendered shows its plate
 * without a second render.
 */
export function useSectionPlate(
  request: SectionPlateRequest | null,
  enabled: boolean,
): UseQueryResult<SectionPlate, Error> {
  const key = request === null ? ["parts", "", "section"] : sectionPlateKey(request);
  return useQuery({
    queryKey: key,
    queryFn: () => plateRequest(request as SectionPlateRequest),
    enabled: enabled && request !== null,
    // A render is expensive and its inputs are all in the key; nothing about
    // `(pin, view, plane)` can go stale while those four values hold.
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
}
