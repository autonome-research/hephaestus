// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Every human-facing string in the workspace, in one module.
//
// INTERFACE.md §3, clean-room hygiene, inherited verbatim: "All workspace copy
// is invented and lives in one module (`web/src/copy.ts`) so a reviewer can
// audit it in one file." No identifier, filename, or string here names another
// product, and no test asserts any of these strings — assertions are on fields
// and information content (§3), never on wording.
//
// Two vocabulary rules are load-bearing rather than stylistic:
//
// * §13.2: the bare word "publish" never appears in UI text. Two different
//   operations are called "publish" inside G5 itself — a build becoming
//   `current`, and a git tag — and the workspace names both: **"Make current" /
//   "current build"** for the artifact axis, **"Tag release"** for the git axis.
// * §4.4 / §6.3: a weak or absent answer says *why* it is weak. Silence never
//   reads as a pass, and a blank field never stands in for "not known".

export const copy = {
  app: {
    /** The product name. Used in the document title and the header. */
    name: "Hephaestus",
    tagline: "workspace",
  },

  /** §2.2: with no token the app renders one non-interactive panel. */
  noToken: {
    title: "No workspace token",
    body:
      "This page was opened without a token, so it cannot talk to the workspace API. " +
      "Start the server in the project directory and open the address it prints — " +
      "the token travels in the URL fragment and is never sent to any other host.",
    command: "heph serve --web",
    hint: "The printed address looks like http://127.0.0.1:8760/#t=…",
  },

  header: {
    project: "Project",
    branch: "Branch",
    head: "HEAD",
    pin: "Artifact pin",
    buildState: "Build",
    token: "Token",
    followCurrent: "Follow current",
    /** §4.5: the action states what it will discard before it does it. */
    followCurrentExplain:
      "Stop holding this artifact and show the current build instead. " +
      "The selection, crop, and measurement taken against the held artifact are discarded.",
    pinnedBanner:
      "Showing a held artifact, not the current build. Every panel below reports against this artifact.",
    unpinned: "Following the current build",
  },

  /** §4.5 `pin_mode`, and the §4.1 build-state chip. */
  pinMode: {
    current: "current",
    pinned: "held",
  },
  buildState: {
    current: "current",
    preview: "preview",
    stale: "stale",
    failed: "failed",
    not_built: "not built",
  },

  rail: {
    title: "Project",
    partsHeading: "Parts",
    /** §13.1: the rail shows the git axis; the header shows the artifact axis. */
    gitHeading: "Working tree",
    versionsHeading: "Versions",
    partsEmpty: "This project declares no parts.",
    versionsEmpty: "No commits touch this part yet.",
    versionsNoPart: "Select a part to see its history.",
    cleanTree: "Working tree clean",
    dirtyCount: (n: number): string => (n === 1 ? "1 changed path" : `${n} changed paths`),
    dirtyMarkerLabel: "changed in the working tree",
    dirtyOutsideParts: "Changed paths outside parts/",
    /** §13.2: the read-only list of tags that exist on this repository. */
    tagsHeading: "Tags",
    /**
     * §13.2's other sense of "publish": creating an annotated git tag. Reserved
     * here so the wording lives in one file; the action itself is a keyed
     * mutation (`POST /git/tag`) and is not part of the read-only half.
     */
    tagRelease: "Tag release…",
    geometryCount: "geometries",
    notBuilt: "not built",
    buildFailed: "build failed",
  },

  /** §13.1: dirtiness is a `git status` fact, and it says which side is dirty. */
  gitStatus: {
    index: "staged",
    worktree: "unstaged",
    untracked: "untracked",
    both: "staged and unstaged",
  },

  stage: {
    tabs: {
      viewport: "Viewport",
      script: "Script",
      diff: "Diff",
    },
    diffPending: "Per-part diff lands with the versions panel's compare action.",
    selectPart: "Select a part in the rail.",
  },

  /** §5. The viewport, its two overlays, and every named absence it can reach. */
  viewport: {
    label: "Geometry",
    loading: "Loading geometry…",
    noPin: "No artifact is pinned, so there is no geometry to show.",
    /**
     * §5.5: "During a rebuild the viewport keeps the **last completed**
     * artifact… It never blanks." This is the word for that state, and the
     * canvas underneath still holds the previous artifact's geometry.
     */
    stale:
      "Loading the newly pinned artifact. Until it arrives this is the last artifact that finished loading, not the one named in the header.",
    /** §5.1: the route never serves an unlinked GLB, so a refusal is an answer. */
    refused: "The server did not serve geometry for this artifact.",
    /**
     * WebGL is the one capability this client cannot substitute for. Saying so
     * beats a black rectangle: §4.4's rule is that a weak state says why it is
     * weak, and that rule is not only about provenance.
     */
    noWebgl:
      "This browser did not give the page a WebGL context, so the geometry cannot be drawn here. " +
      "Rendered images from the server are still available through the inspector.",
    empty: "This build has no solids to draw.",
    /** §5.5: a screen-space readout, never a measurement, never a <Fact>. */
    readout: {
      view: "View",
      scale: "Scale",
      /** The camera's half-height in model units per the axis label beside it. */
      units: "mm",
      hidden: (n: number): string => (n === 1 ? "1 solid hidden" : `${n} solids hidden`),
    },
    viewCube: {
      label: "Standard views",
      free: "Free orbit",
      /** §5.5: an orbited camera is still nameable, and the name is shown. */
      freeExplain:
        "Orbiting snapshots the nearest azimuth/elevation, so every camera this viewport reaches has a name the renderer can reproduce.",
    },
    explode: {
      label: "Explode",
      /** §1: the displacement is the server's; the client scales it and stops. */
      explain:
        "Each solid moves along the displacement the server published for it. The slider scales that displacement; nothing here computes a distance.",
      reset: "Collapse",
    },
    section: {
      label: "Section",
      enable: "Cut a section",
      disable: "Clear the section",
      axis: "Axis",
      side: "Remove",
      offset: "Position",
      render: "Render section",
      rendering: "Rendering…",
      /** §5.3, said in the interface and not only in the spec. */
      previewLabel: "Live preview — not an evidentiary render",
      previewExplain:
        "The live cut is drawn by this browser while you drag. It is a working view: the rendered plate below is produced by the server's renderer, and that is the image any comparison uses.",
      plateLabel: "Server-rendered plate",
      plateFrom: "Rendered from",
      plateAbsent: "No plate has been rendered for this plane yet.",
      plateRefused: "The server did not produce a section render for this plane.",
    },
  },

  script: {
    readOnly: "Read only",
    readOnlyWhy:
      "The script viewer is read only in this build. Editing is a store mutation, not a file write.",
    lines: "lines",
    loading: "Loading script…",
    /** The §2.6 pager, surfaced as a user-visible fact rather than a silent cut. */
    paged: (shown: number, total: number): string =>
      `Showing ${shown} of ${total} bytes of this snapshot.`,
    more: "Load the next page",
    complete: "Whole snapshot loaded.",
    oversizedLine:
      "One line of this snapshot is larger than a page on its own; the page ends inside it and the next page continues from the exact byte.",
    contentHash: "Content hash",
    snapshot: "Snapshot",
  },

  inspector: {
    tabs: {
      results: "Results",
      properties: "Properties",
      provenance: "Provenance",
      checks: "Checks",
      dfm: "DFM",
    },
    pending: "This panel is not part of this build of the workspace yet.",
    selectPart: "Select a part in the rail to inspect it.",
  },

  /** §6.1 and §5.4: the build result's geometry list, and what may be hidden. */
  results: {
    heading: "Geometry",
    count: "geometries",
    solids: "solids",
    notBuilt:
      "This part has no current build, so there is no build result to report. Nothing is being hidden.",
    failed: "The last build of this part failed. The geometry list below is empty for that reason.",
    metricsHeading: "Metrics",
    /** §5.4: a scene-graph property, never geometry. The words say so. */
    show: "Show in the viewport",
    hide: "Hide in the viewport",
    hidden: "hidden",
    hiddenNote:
      "Hiding removes the entry's meshes from the viewport scene graph. It changes nothing about the build result, and the numbers below are unaffected.",
    groupNote:
      "This entry covers more than one solid; the toggle covers the group, which is the only namespace the build result gives.",
    /**
     * Was "there is no viewport yet, so hiding is recorded and has nothing to
     * apply to". The viewport landed (§5), so the sentence became false and was
     * replaced rather than left standing: the toggle now hides the entry's
     * meshes in the Stage's scene graph, on the Viewport tab.
     */
    appliesToViewport:
      "Hiding applies on the Viewport tab, to the geometry of the artifact currently pinned.",
  },

  /** §6.2: "all metadata fields" resolved to the closed `part.*` vocabulary. */
  properties: {
    heading: "Manufacturing metadata",
    undeclared: "not declared",
    undeclaredNote:
      "Fields this part does not declare are listed so the absence is visible; the panel reports only what the script sets.",
    sourceHeading: "Read from",
    source: {
      build_record:
        "the build record — the values as the worker evaluated them, so a computed field reads like a literal one",
      script_literals:
        "the script's string literals — this part has no current build to read runtime values from, so a computed field cannot be reported",
    },
    boundTo: "Evaluated with artifact",
    unbound: "No current build; these values were parsed from the script text.",
    empty: "This part declares none of the manufacturing metadata fields.",
  },

  /** §6.3: the client never runs checks; it renders the report's own verdicts. */
  checks: {
    heading: "Project checks",
    measured: "measured",
    bundle: "Check bundle",
    generation: "Generation",
    empty: "This project's check set declares no checks.",
    badge: {
      pass: "pass",
      fail: "fail",
      error: "error",
      /** §6.3: rendered as its own visible state, in words. */
      not_run: "not run",
    },
    badgeExplain: {
      pass: "The predicate ran and held.",
      fail: "The predicate ran and did not hold.",
      error:
        "The predicate could not be evaluated, so it has no verdict. This is not a pass and it is not a failure.",
      not_run: "This check was declared and the run did not reach it. Nothing about it is known.",
    },
    scope:
      "These are the project's checks, measured across every part with a current build. A part-scope check inside a script is reported with its build.",
  },

  /** §6.4: findings, descriptors, and the two DFM controls kept apart. */
  dfm: {
    heading: "Manufacturability findings",
    absent:
      "No design-for-manufacture evaluation has been recorded for this part. That is not a clean result — it is the absence of one.",
    autoRun: "Automatic evaluation after each build",
    autoRunOn: "on",
    autoRunOff: "off",
    autoRunNote:
      "This is a project setting in the manifest, not a per-message flag, and it is read-only here.",
    process: "Process",
    pack: "Rule pack",
    registry: "Registry",
    material: "Material",
    resolvedFrom: "Measured against",
    resolved: {
      current: "the current artifact",
      artifact_ref: "a named artifact — a preview, not the current build",
      project_snapshot: "a project snapshot — not the current build",
    },
    severity: "Findings by severity",
    clean: "The rule pack ran and reported no findings.",
    errored: "Rules that could not be evaluated",
    erroredNote: "A rule that raised has no verdict. It is neither a finding nor a clean result.",
    truncated:
      "The finding list was cut short by the evaluation's own bound; what is shown is a prefix, not the whole.",
    measured: "measured",
    suggested: "suggested bound",
    tags: "tags",
    topology: "Topology",
    descriptorTitle: "Resolve this topology against the artifact it was measured on",
    descriptorPending:
      "Resolving a finding's topology is a server operation and the route that performs it is not served by this build. The descriptor below is the artifact-bound address the finding carries.",
    capabilityRefused:
      "This server has no secure executor, so design-for-manufacture rules cannot run at all. Nothing has been evaluated, and nothing about this part's manufacturability is known.",
  },

  /** §4.3's spine and §4.4's three shapes, each a designed state. */
  provenance: {
    heading: "Selection provenance",
    absent:
      "Nothing is selected. Provenance answers are produced by the server from a selection; the workspace never infers one.",
    unreachable:
      "Selection resolution is a server operation and its route is not served by this build, so a selection cannot be made here yet.",
    pinned: "Pinned artifact",
    kind: "Topology",
    tag: "Tag",
    source: "Resolved against",
    bundle: "Selection bundle",
    table: "Selection table",
    crop: "Crop",
    noCrop: "No crop artifact was minted for this selection.",
    selectionId: "Selection",
    solid: "Solid",
    topology: "Topology index",
    line: "Creating line",
    noLine: "This topology carries no tag, so there is no creating statement to name.",
    state: {
      tagged: "Tagged topology",
      owned: "Owned by a solid",
      unattributed: "No statement attribution",
    },
    /** §4.4: the italic sentences are the design point — a weak answer says why. */
    why: {
      tagged: "",
      owned:
        "This face was produced by a boolean, and Hephaestus does not attribute a boolean result face to an operand statement.",
      unattributed: "No statement attribution is available for this topology.",
    },
    /**
     * The closed reason vocabulary. §4.4: "the attribution existed and was not
     * retained" is a different fact from "the machinery cannot attribute this
     * face", and a panel that renders them identically claims the first while
     * the second is true.
     */
    reason: {
      source_map_not_stored:
        "This topology is tagged, but the pinned build's source map is no longer stored, so the creating statement cannot be recovered. This is a retention fact, not a limit of the attribution machinery.",
      boolean_result_face:
        "This face was produced by a boolean, and Hephaestus does not attribute a boolean result face to an operand statement.",
    },
    origin: {
      dfm_finding: "Reached from a manufacturability finding.",
      viewport: "Reached from a viewport selection.",
    },
  },

  stream: {
    title: "Agent",
    collapse: "Collapse the agent column",
    expand: "Expand the agent column",

    /** §7.4's closed vocabulary on the Stream header, each with its reason. */
    state: {
      live: "live",
      reconnecting: "reconnecting",
      resyncing: "resyncing",
      historical: "historical",
      detached: "detached",
    },
    stateWhy: {
      live: "Attached to this session's event stream.",
      reconnecting: "The event stream closed. Reopening it.",
      resyncing:
        "The server dropped this page from the stream to protect the run, and the page is reattaching. Events sent while it was gone may be missing, and any that are appear below as a labelled break.",
      historical: "Showing the recorded transcript. This page is not attached to a live stream.",
      detached: "Not attached to an event stream.",
    },

    /** §2.4's `agent_unavailable`, said in words rather than as an empty panel. */
    noAgent:
      "This server has no agent runtime attached, so it has no sessions to show. Start it with a provider configuration to create or attach one.",
    noSessions: "No sessions are attached to this server.",
    sessionsHeading: "Sessions",
    selectSession: "Select a session to see its transcript.",

    /** §7.1's tab list; the profile and edge words are the server's own. */
    profile: {
      orchestrator: "orchestrator",
      part: "part",
      quick_edit: "quick edit",
    },
    edgeKind: {
      quick_edit: "quick edit of",
      delegation: "delegated by",
    },
    threadState: {
      linked: "threaded",
      unlinked: "no recorded parent",
    },
    unlinkedWhy:
      "No parent edge is recorded for this session. It is either a root, or a transcript older than the threading table — in which case its parent cannot be recovered and is not guessed at.",
    threadBounded:
      "The walk up this thread hit its depth bound before reaching a root, so the tabs above may not be the whole tree.",

    /** §8: history is the prefix, the live stream is the suffix, the join is seen. */
    seam: "End of the recorded transcript. Everything below arrived live.",
    historyLoading: "Loading the recorded transcript…",
    historyPages: (pages: number): string =>
      pages === 1 ? "1 page of recorded transcript" : `${pages} pages of recorded transcript`,
    historyTruncated:
      "Stopped after the page limit for one reopen. This transcript is longer than what is shown.",
    historyFailed: "The recorded transcript could not be read.",

    /** §8's named absences: what a reopened transcript cannot contain. */
    absence: {
      user_prompt:
        "Prompts are not part of the recorded event vocabulary, so this transcript shows the agent's side only.",
      terminal:
        "Run outcomes are recorded live and are not part of a reopened transcript, so no run-end band is shown here. Nothing below implies a run is still open.",
    },

    /** §7.4 / §2.7: a resync is labelled, and never healed from history. */
    resync: {
      title: "Stream break",
      pending: "The stream was dropped and is reattaching. What was missed is not yet known.",
      contiguous:
        "The stream was dropped and resumed at the next event, so nothing between them was lost.",
      gap: "The stream was dropped and resumed past the last event this page saw. The events in between are gone from the live buffer and are not recovered from the recorded transcript, because the two do not share an identity.",
      unknown:
        "The stream was dropped and reattached, and nothing has arrived for that run since, so whether anything was missed is not known.",
      after: "Last event before the break",
    },

    /** §7.2's chip. `unknown` is the section's own named fallback. */
    chip: {
      status: {
        running: "running",
        ok: "ok",
        error: "error",
        unknown: "unknown",
      },
      unknownWhy: "This transcript does not record whether the call failed.",
      runningWhy: "No result for this call is recorded here.",
      callMissing: "The call this result belongs to is not on this page.",
      arguments: "Arguments",
      fields: "Result",
      unparsed: {
        empty: "This call recorded no result document.",
        not_json: "This result is not a JSON document, so its fields cannot be named.",
        not_an_object: "This result is not a JSON object, so it has no fields to name.",
      },
      unparsedNote:
        "No result fields are shown, and none are invented. The raw result is below as it was recorded.",
      raw: "Recorded result",
      reference: "reference",
    },

    /** §7.3's kinds. */
    thought: "Reasoning",
    thoughtParts: (n: number): string => (n === 1 ? "1 part" : `${n} parts`),
    audit: "Audit",
    unknownKind: "This event is outside the published event vocabulary and is shown unread.",
    image: {
      alt: "Image produced by the agent",
      /** §7.3: history keeps `{mimeType}`; the bytes are not retained. */
      historicalPlaceholder:
        "An image was produced here. A reopened transcript keeps its type only — the bytes are not retained — so the image itself cannot be shown.",
      undecodable:
        "This image could not be decoded and is described rather than shown, so the transcript does not read as though no image was produced.",
      mimeType: "Type",
      bytes: "Bytes",
    },
    terminal: {
      title: "Run ended",
      state: "Outcome",
      id: "Terminal",
      /** §7.3: "the model stopped" and "the plumbing gave up" are different facts. */
      backpressure:
        "This run was stopped because a client attached to it could not keep up with its events, not because the model or a tool failed.",
    },

    /** §7.3's AskUserWidget. Answering is not part of this build (see below). */
    ask: {
      title: "Question for you",
      question: "Question",
      options: "Options",
      noOptions: "This question recorded no options.",
      consequenceMissing: "No consequence was recorded for this option.",
      /**
       * §7.3 has the widget post `POST /sessions/{id}/answer`, first answer
       * wins. That path is Stage 5 work here, so the widget renders the question
       * and disables its controls **and says which of the two it is**: an
       * unanswerable question with no explanation reads as a broken control.
       */
      disabled: "Answering from this page is not part of this build of the workspace.",
      answeredSelf: "Answered from this page.",
      answeredOther: "Answered from another client first.",
      answer: "Answer",
      pending: "Waiting for an answer.",
      /** §7.3: a reopened widget is rebuilt from the call and result, not the events. */
      fromToolResult:
        "Rebuilt from the recorded ask_user call and its result. The live question and answer events are not part of a reopened transcript.",
    },
  },

  /** Named absences. A missing answer says which kind of missing it is. */
  absent: {
    unavailable: "unavailable",
    noGit: "This project is not inside a git work tree, so there is no history to show.",
    gitUnavailable: "git is not available to the server, so the working tree cannot be read.",
    loading: "Loading…",
  },

  errors: {
    title: "The server refused this request",
    unauthorized: "The token this page holds was not accepted. Restart the server and reopen its address.",
    retry: "Try again",
    reason: "Reason",
  },
} as const;

export type Copy = typeof copy;
