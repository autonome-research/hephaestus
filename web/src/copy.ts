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
    /**
     * `branch` and `head` used to live here. §13.1 puts the git axis on the rail
     * and the artifact axis in the header, and the header was reporting both —
     * so the two words moved to `rail.branch` / `rail.head` with the working
     * tree they belong to.
     */
    pin: "Artifact pin",
    buildState: "Build",
    /**
     * The hold control's label is a VERB. It used to be `pinMode.pinned`
     * ("held"), so the bar printed a state word on a button beside two other
     * state words — four labels for one fact on an unbuilt part (§4.1's
     * 2026-09-01 amendment).
     */
    hold: "Hold",
    followCurrent: "Follow current",
    /** §4.5: the action states what it will discard before it does it. */
    followCurrentExplain:
      "Stop holding this artifact and show the current build instead. " +
      "The selection, crop, and measurement taken against the held artifact are discarded.",
    pinnedBanner:
      "Showing a held artifact, not the current build. Every panel below reports against this artifact.",
    unpinned: "Following the current build",
    /**
     * §4.7: "Disabled requires a `reason` prop… a disabled control in this app
     * must always be able to say why." There is nothing to hold until a build
     * has named an artifact, and the control says that rather than sitting inert.
     */
    holdUnavailable:
      "There is no artifact to hold: this part has no build whose artifact the workspace could pin.",
  },

  /**
   * Header chrome next to the pin (issue #12). Export and BOM are simple
   * controls bound to the on-screen artifact, not only inspector tabs.
   */
  chrome: {
    export: "Export",
    exportTitle: "Export the pinned artifact",
    bom: "BOM",
    bomTitle: "Sourcing from this part's declared manufacturing fields",
    more: "Drawings, documents, and export history",
  },

  /**
   * BOM / sourcing inspector. Only manufacturing identity the part already
   * declares — process, stock, material spec. No vendor catalog.
   */
  sourcing: {
    heading: "Sourcing",
    subjectHeading: "This artifact",
    pin: "Pinned artifact",
    noPin: "No artifact is pinned.",
    boundTo: "Evaluated with artifact",
    unbound: "No current build; these values were parsed from the script text.",
    emptyTitle: "No sourcing fields declared",
    empty:
      "This part does not declare a process, stock form, blank size, or material spec, so there is nothing to source from.",
    undeclared: "not declared",
    undeclaredHeading: "Not declared",
    undeclaredNote:
      "Only manufacturing fields this part declares are used for sourcing. Nothing is looked up from a catalog.",
    catalogNote:
      "Sourcing is the process, stock, and material spec the part already declares. This workspace does not query a vendor catalog.",
    sourceHeading: "Read from",
    sourceLabel: "Source",
    source: {
      build_record:
        "the build record — the values as the worker evaluated them, so a computed field reads like a literal one",
      script_literals:
        "the script's string literals — this part has no current build to read runtime values from, so a computed field cannot be reported",
    },
    fields: {
      process: "process",
      stock_form: "stock form",
      blank_size: "blank size",
      material_spec: "material spec",
    },
  },

  /** §4.5 `pin_mode`, and the §4.1 build-state chip. */
  pinMode: {
    current: "current",
    pinned: "held",
  },
  /**
   * §4.1's COPY DEFECT, fixed. `pinMode.current` and `buildState.current` were
   * two different closed vocabularies that both spelled "current", rendered in
   * two chip styles ~600px apart on two different axes — pin freshness versus
   * build state. The build-state vocabulary now says "up to date"; the pin
   * vocabulary keeps "current". Two axes, two words.
   */
  buildState: {
    current: "up to date",
    preview: "preview",
    stale: "stale",
    failed: "failed",
    not_built: "not built",
  },

  rail: {
    title: "Project",
    /** §4.1(b): the rail overlay's toggle and its close control. */
    open: "Show the project rail",
    close: "Hide the project rail",
    partsHeading: "Parts",
    /**
     * Closed project-tree sections. Always listed, even when the engine has
     * projected no rows. The names are the inventory; emptiness is a fact.
     */
    sections: {
      analyses: "Analyses",
      docs: "Docs",
      globals: "Globals",
      imports: "Imports",
      materials: "Materials",
    },
    sectionEmptyTitle: "No facts",
    sectionEmpty: "The engine has not projected any items for this section.",
    /** §13.1: the rail shows the git axis; the header shows the artifact axis. */
    gitHeading: "Working tree",
    versionsHeading: "Versions",
    /**
     * §4.7's EmptyState: a heading and prose, not a lone grey sentence. Every
     * absence in this workspace is a composed state with a shape.
     */
    partsEmptyTitle: "No parts",
    partsEmpty: "This project declares no parts.",
    versionsEmptyTitle: "No history",
    versionsEmpty: "No commits touch this part yet.",
    versionsNoPartTitle: "No part selected",
    versionsNoPart: "Select a part to see its history.",
    /**
     * §4.7's second EmptyState rule: a shared cause is detected once. This
     * heading covers BOTH rail sections, which is why it names the pair rather
     * than the section it happens to be printed in.
     */
    gitAbsentTitle: "No working tree or history",
    cleanTree: "Working tree clean",
    dirtyCount: (n: number): string => (n === 1 ? "1 changed path" : `${n} changed paths`),
    dirtyMarkerLabel: "changed in the working tree",
    /** §13.1's Script-tab marker, as a word beside the icon (§3.13.2). */
    dirtyShort: "changed",
    dirtyOutsideParts: "Changed paths outside parts/",
    /**
     * §13.1 reports a dirty tree and never hides one, but `.heph/` is the
     * workspace's OWN store — blobs, the state db, the serve token, agent logs —
     * and on the fixture it was 30-odd untracked rows drowning the part tree in
     * the 280px rail. One row, a count, and one click to the same facts.
     */
    generated: (n: number): string =>
      n === 1 ? "1 generated .heph path" : `${n} generated .heph paths`,
    generatedWhy:
      "Paths the workspace writes under .heph/ — the object store, the state database, and the agent's own files. They are reported because git reports them; none of them is part source.",
    /** §13.1's git identity: which repository this is, on the git axis. */
    branch: "Branch",
    head: "HEAD",
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
    tabsLabel: "Stage view",
    tabs: {
      viewport: "Viewport",
      script: "Script",
      timeline: "Timeline",
      /* Inspector tab stays "Results" (§4.1, §6). This stage tab mounts the
         same ResultsPanel (heading: Geometry). Two visible tabs with the same
         word is the operator confusion #17's hide-when-stage-is-Results path
         does not cover: Viewport + inspector Results still showed both labels. */
      results: "Geometry",
      diff: "Diff",
    },
    diffPendingTitle: "Diff is not in this build",
    diffPending: "Per-part diff lands with the versions panel's compare action.",
    selectPartTitle: "No part selected",
    selectPart: "Select a part in the rail.",
  },

  /**
   * Statement Timeline. Marks come from `GET /parts/{part}/build` only —
   * projected `checkpoints[]`, last-good, failed, or the current artifact.
   */
  timeline: {
    heading: "Timeline",
    tabsLabel: "Build timeline",
    statement: "Statement",
    lastGood: "Last good",
    failed: "Failed",
    current: "Current",
    noPartTitle: "No part selected",
    noPart: "Select a part in the rail to rewind its last-good checkpoint.",
    notBuiltTitle: "Not built",
    notBuilt: "This part has no build, so there is no last-good checkpoint to rewind to.",
    okTitle: "Build succeeded",
    ok: "This build completed. The executor did not record a last-good checkpoint to rewind.",
    noCheckpointTitle: "No last-good checkpoint",
    noCheckpoint:
      "This failed build named no last-good artifact, so there is nothing to rewind to.",
    rewind: "Rewind to last good",
    followFailed: "Show the failed build",
    scrub: "Rewind the build",
  },

  /** §10: PARAMS sliders generated from `GET /parts/{part}/params`. */
  params: {
    heading: "PARAMS",
    emptyTitle: "No parameters",
    empty: "This part declares no PARAMS, so there are no sliders to show.",
    noPartTitle: "No part selected",
    noPart: "Select a part in the rail to edit its parameters.",
    loading: "Loading parameters…",
    conflict:
      "The parameter state changed before this edit landed. The sliders now show the live values; edit again to retry.",
    committing: "Applying parameter change…",
    reset: "Reset to default",
  },

  /** §5. The viewport, its overlays, and every named absence it can reach. */
  viewport: {
    label: "Geometry",
    /**
     * §3.3's principle 5: every viewport state is a composed state with a
     * heading of its own. The sentences are unchanged; what they gained is a
     * title, an icon, and an ink that clears the legibility floor.
     */
    absenceTitle: {
      "no-pin": "No artifact pinned",
      loading: "Loading geometry",
      stale: "Showing the previous artifact",
      refused: "Geometry refused",
      "no-webgl": "No WebGL context",
      empty: "Nothing to draw",
    },
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
    /** The same six sentences, keyed by the state the viewport reports. */
    absence: {
      "no-pin": "No artifact is pinned, so there is no geometry to show.",
      loading: "Loading geometry…",
      stale:
        "Loading the newly pinned artifact. Until it arrives this is the last artifact that finished loading, not the one named in the header.",
      refused: "The server did not serve geometry for this artifact.",
      "no-webgl":
        "This browser did not give the page a WebGL context, so the geometry cannot be drawn here. " +
        "Rendered images from the server are still available through the inspector.",
      empty: "This build has no solids to draw.",
    },
    /** §5.5: a screen-space readout, never a measurement, never a <Fact>. */
    readout: {
      view: "View",
      scale: "Scale",
      /** §3.11.5: the readout finally describes something visible. */
      grid: "Grid",
      /** The camera's half-height in model units per the axis label beside it. */
      units: "mm",
    },
    /**
     * §3.11.6's axis triad. The letters are the whole vocabulary: the triad
     * distinguishes its axes by letter rather than by hue, because §3.9 spends
     * hue on status and in that vocabulary red already means `fail`.
     */
    triad: {
      label: "Axis orientation",
      axis: { x: "X", y: "Y", z: "Z" },
    },
    /**
     * Operator appearance cluster (§3.11, §5.5). Words, not icons: the sprite
     * is closed at 18 ids and these controls are a scan, not a status.
     */
    appearance: {
      label: "Viewport appearance",
      wireframe: {
        label: "Wireframe",
        explain: "Hide the fill and keep the silhouette. Hidden solids still disappear with their outline.",
      },
      fit: {
        label: "Fit",
        explain:
          "Frame the pinned artifact the way the renderer frames this named view. Orbit and zoom return to that framing.",
        disabled: "No pinned artifact is on the canvas, so there is nothing to frame.",
      },
      ortho: {
        label: "Ortho",
        explain:
          "Orthographic projection, matching the named views the renderer can reproduce. Off is a perspective viewing aid; Fit and the view cube stay the same camera.",
      },
      grid: {
        label: "Grid",
        explain: "Ground grid, spaced at the step the readout reports.",
      },
      triad: {
        label: "Axes",
        explain: "Axis triad in the same Z-up frame as the camera.",
      },
      material: {
        label: "Material",
        explain:
          "Override every solid with the viewport part colour, at least 4.5:1 against the ground. Off restores the exporter's own material; it does not invent a new one.",
      },
    },
    viewCube: {
      label: "Standard views",
      namedLabel: "Named views",
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
      /** §4.7: a disabled control always says why. */
      resetDisabled: "The assembly is already collapsed.",
    },
    section: {
      label: "Section",
      enable: "Cut a section",
      disable: "Clear the section",
      axis: "Axis",
      side: "Remove",
      offset: "Position",
      render: "Render section",
      renderDisabled: "A plate for this plane has already been asked for.",
      renderingTitle: "Rendering",
      rendering: "Rendering…",
      /** §5.3, said in the interface and not only in the spec. */
      previewLabel: "Live preview — not an evidentiary render",
      previewExplain:
        "The live cut is drawn by this browser while you drag. It is a working view: the rendered plate below is produced by the server's renderer, and that is the image any comparison uses.",
      plateLabel: "Server-rendered plate",
      plateFrom: "Rendered from",
      plateAbsent: "No plate has been rendered for this plane yet.",
      plateRefusedTitle: "No plate for this plane",
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
    /** §4.1(c): the drawer's height is explicit and the handle resizes it. */
    resize: "Resize the inspector",
    tabsLabel: "Inspector",
    tabs: {
      results: "Results",
      properties: "Properties",
      provenance: "Provenance",
      checks: "Checks",
      dfm: "DFM",
      export: "Export",
      sourcing: "Sourcing",
    },
    pending: "This panel is not part of this build of the workspace yet.",
    noPartTitle: "No part selected",
    selectPart: "Select a part in the rail to inspect it.",
  },

  /** §6.1 and §5.4: the build result's geometry list, and what may be hidden. */
  results: {
    heading: "Geometry",
    count: "geometries",
    solids: "solids",
    /** §4.7's EmptyState: an absence is a composed state with a heading. */
    notBuiltTitle: "Not built",
    failedTitle: "Build failed",
    /** The group marker, as a word rather than as a sentence in a chip. */
    group: "group",
    notBuilt: "This part has no current build, so there is no build result to report.",
    failed: "The last build of this part failed, so the geometry list is empty.",
    metricsHeading: "Metrics",
    /** §5.4: a scene-graph property, never geometry. The words say so. */
    show: "Show in the viewport",
    hide: "Hide in the viewport",
    hidden: "hidden",
    /**
     * The count of this part's hidden entries, beside the toggles that produce
     * it. It used to live in the viewport's grid readout, which §5.5 defines as
     * "camera state and scale" — and where it also put chrome pixels into
     * G4.5's control region. See `GridReadout.tsx` for the measurement.
     */
    hiddenCount: (n: number): string => (n === 1 ? "1 hidden" : `${String(n)} hidden`),
    /**
     * ONE sentence, printed only while something is actually hidden.
     *
     * There were two, and they were always on screen: this one plus "Hiding
     * applies on the Viewport tab, to the geometry of the artifact currently
     * pinned." Two paragraphs about a toggle nobody had touched yet, under every
     * built part's geometry list. The fact is worth stating when it is load
     * bearing — a reader wondering whether hiding re-measured anything — and the
     * moment it becomes load bearing is the moment an entry is hidden.
     */
    hiddenNote:
      "Hiding removes the entry's meshes from the Viewport tab's scene graph. Every number here is unchanged.",
    groupNote:
      "This entry covers more than one solid; the toggle covers the group, which is the only namespace the build result gives.",
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
    emptyTitle: "No metadata declared",
    empty: "This part declares none of the manufacturing metadata fields.",
    undeclaredHeading: "Not declared",
    sourceLabel: "Source",
  },

  /** §6.3: the client never runs checks; it renders the report's own verdicts. */
  checks: {
    heading: "Project checks",
    measured: "measured",
    bundle: "Check bundle",
    generation: "Generation",
    emptyTitle: "No checks",
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
    absentTitle: "Not evaluated",
    capabilityTitle: "No secure executor",
    cleanTitle: "No findings",
    descriptorPendingTitle: "Address only",
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

  /**
   * §22 — egress. The only Inspector tab containing a control that **writes**,
   * so its copy has two jobs the others do not: state the subject before the
   * controls, and name the retention every click creates.
   */
  export: {
    heading: "Take this geometry out",
    /** §22.7's TIGHTENING: the subject line, above any format button. */
    subjectHeading: "Exporting",
    pinned: "Artifact",
    pinMode: { current: "following the current build", pinned: "held" },
    part: "Part",
    subjectNote:
      "Every file below is made from this artifact, not from whatever the current build happens to be when you click.",

    subjectKinds: { export: "Model or cut file", drawing: "Drawing", doc: "Document" },
    /**
     * The option TEXT of every picker that names an engine value is that enum
     * value verbatim — `step`, `nested_sheet`, `bom` — and is not translated
     * here. (The one picker that is not an engine enum is the subject chooser,
     * whose values name which of §22.3's three routes a submission is for; its
     * labels are `subjectKinds` above.)
     * §22.1: "The engine's enum **is** the closed vocabulary and the client
     * renders it… never from a list of its own." A friendly-name map would be a
     * second vocabulary that has to be kept in step with the first, and the word
     * an operator picks would then differ from the word the export history, the
     * `paths` and the agent transcript all print. What follows is therefore only
     * the *labels of the controls*, never the values inside them.
     */
    format: "Format",
    layout: "Layout",
    layoutNote:
      "Layout applies to flat cut files only, so it is offered for DXF and SVG and nowhere else.",
    blank: "Blank",
    blankWidth: "Width (mm)",
    blankHeight: "Height (mm)",
    drawingKind: "Drawing",
    sheet: "Sheet",
    docKind: "Document",
    /** §22.7: two steps, not one — two routes with two failure modes. */
    run: "Export",
    running: "Exporting…",
    download: "Download",
    downloading: "Downloading…",
    twoSteps:
      "Export writes the file and records it. Download fetches the bytes. They are separate because they fail differently.",

    /** §22.1: the panel displays the resolved kerf; it never offers to set one. */
    kerfHeading: "Kerf",
    kerfApplied: "Applied",
    kerfSource: "Resolved from",
    kerfProcess: "Process",
    kerfSources: {
      dfm: "the process rule pack",
      explicit: "an explicit value",
      none: "nothing — this file is nominal",
    },
    kerfUncompensated:
      "No kerf was applied, so this cut file is nominal. The file is correct; a machine cutting it will remove material the path does not account for.",
    kerfNotBrowser:
      "Kerf comes from the process rule pack and is not set here. A per-click override would be recorded nowhere a second person would read it.",

    /** §22.6's retention, as designed copy rather than an omission. */
    historyHeading: "Exported from this part",
    historyEmpty: "Nothing has been exported from this part.",
    historyTotal: "Kept on disk",
    retention:
      "Exports are kept until they are unpinned from the command line. This workspace does not delete them.",
    retentionWhy:
      "Each exported file is kept, and so is the build it came from — which is what lets an old artifact be re-exported and its provenance still resolve.",
    source: "Made from",
    recordedPath: "Written to",

    /** §22.7's refusal table. Each is a designed state, not an error toast. */
    refusalHeading: "This cannot be exported",
    refusals: {
      invalid_source:
        "The held artifact is not a successful build's geometry, so there is nothing frozen to export.",
      addressing_error:
        "This part has no successful build to export. Build it, then hold the artifact you want.",
      blank_unknown:
        "Nesting needs a sheet size, and this part does not declare one that can be read without building it. Give a width and height below.",
      target_exists:
        "This exact file has already been exported from this artifact with these options, and files are never overwritten. Download the existing one below.",
      key_payload_mismatch:
        "This export was already run with different options. Change something, or download the file the first run produced.",
      export_too_large:
        "This file is too large for the browser to hold in memory. It is on disk in the project — fetch it from a terminal.",
      unknown_export:
        "The workspace has no committed record of this file, so it will not serve its bytes.",
      capability_not_available:
        "This server has no secure executor, so no geometry can be produced at all.",
      /**
       * §22.7's last table row, reachable since §19.40 wired the store's
       * admission guard into the build and export paths. It has to be named:
       * §22.6 calls "your builds stopped working because you downloaded too
       * much" the most confusing failure this section can produce, and the
       * generic `run_failed` below is exactly that failure with its cause
       * hidden. The remedy is a command, so the sentence is the command.
       */
      protected_quota_exceeded:
        "This project's kept files already exceed its storage quota, so nothing new can be produced until some of it is released. Run 'heph export list' to see what is held, and 'heph export unpin BLOB' to release one — it deletes nothing.",
      run_failed: "The export did not complete.",
    },
    /** §22.7: a stale part is not a refusal — the pin is exported and says so. */
    staleNote:
      "This part's script has moved on since this artifact was built. That is not a reason to refuse: the artifact is a real, complete build, and it is what will be exported.",
    noPin:
      "There is no held artifact to export. Select a part with a build, or hold an artifact in the header.",
    noPart: "Select a part to export from it.",
    tooLarge: "Too large to download here",
    downloadRefused: "The bytes could not be fetched",
  },

  /** §4.3's spine and §4.4's three shapes, each a designed state. */
  provenance: {
    heading: "Selection provenance",
    absentTitle: "Nothing selected",
    addressHeading: "Artifact-bound address",
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

    /**
     * The runtime died under a request (`stream/runtimeFault.ts`).
     *
     * §7.4's five states are all claims about the socket, and the socket
     * survives a sidecar restart — so a well that showed only `live` after
     * `session.prompt` failed was stating the one true thing that did not
     * matter. These three sentences say which grade of "the runtime is not
     * answering" the server actually gave us, and none of them claims more.
     */
    runtimeFault: {
      process_down: "runtime restarted",
      timeout: "runtime not answering",
      unreachable: "runtime unreachable",
    },
    runtimeFaultTitle: "The agent runtime stopped answering",
    runtimeFaultWhy: {
      process_down:
        "The agent runtime restarted or exited while this page was talking to it. Anything it was running at the time is gone — a restart ends every turn in flight — and a run that ended this way records no run-end band below.",
      timeout:
        "The agent runtime did not answer in time. A turn that was running may have been lost, and a run that ended this way records no run-end band below.",
      unreachable:
        "The server failed this session request without naming a reason. The agent runtime is the only process behind these routes, so it is the likely cause — but the server did not say so, and this page does not claim it did.",
    },
    /** The turn is not retried here; §7A.5 forbids it. Say what to do instead. */
    runtimeFaultNext:
      "The composer below still works. Send again when you are ready — nothing is resent on its own, because a turn that may have started must not be started twice.",

    /** §2.4's `agent_unavailable`, said in words rather than as an empty panel. */
    noAgentTitle: "No runtime attached",
    noAgent:
      "This server has no agent runtime attached, so it has no sessions to show. Start it with a provider configuration to create or attach one.",
    noSessionsTitle: "No sessions",
    noSessions: "No sessions are attached to this server.",
    sessionsHeading: "Sessions",
    selectSessionTitle: "No session selected",
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
    /**
     * §2.8's thread state. Only `unlinked` is RENDERED as a word.
     *
     * "threaded" beside a tab that is visibly indented under its parent
     * restates the indent, and at ~380px it was the third metadata string on a
     * one-session tab row — the "wall of badges" an operator read as chrome
     * rather than as content. §2.8's requirement is specifically about the
     * other case ("a pre-existing transcript reopens flat and says why"), so
     * the unlinked word stays, short, with `unlinkedWhy` on its `title`. Both
     * states remain addressable through `data-thread-state`, unchanged.
     */
    threadState: {
      linked: "threaded",
      unlinked: "no parent",
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
    /** The same fact, on the header row that otherwise carries a page count. */
    historyFailedShort: "Transcript unread",

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
      /**
       * The chip's collapsed detail (`stream/toolSummary.ts`).
       *
       * A successful call's headline is above this control; what is behind it
       * is the call's arguments and every field of the result document, which
       * is the wire format and reads like one. §7.2's `data-field` nodes are
       * all still in the DOM — collapsed, never dropped — because the gate
       * reads the attribute set and a reader reads the sentence.
       */
      detail: (fields: number): string =>
        fields === 1 ? "1 result field" : `${String(fields)} result fields`,
      detailNoFields: "Call detail",
      /** §7.2's own count, when nothing in the document was short enough to headline. */
      summaryOpaque: "This result carries identifiers only; open the detail to read them.",
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

    /** §7.3 / §7A.7's AskUserWidget — the one place this workspace answers. */
    ask: {
      title: "Question for you",
      question: "Question",
      options: "Options",
      noOptions: "This question recorded no options.",
      consequenceMissing: "No consequence was recorded for this option.",
      answeredSelf: "Answered from this page.",
      answeredOther: "Answered from another client first.",
      answer: "Answer",
      pending: "Waiting for an answer.",
      /** §7.3: a reopened widget is rebuilt from the call and result, not the events. */
      fromToolResult:
        "Rebuilt from the recorded ask_user call and its result. The live question and answer events are not part of a reopened transcript.",

      /** §7A.7's affordance, named for the operator rather than implied. */
      freeTextLabel: "Or answer in your own words",
      freeTextPlaceholder: "Your answer",
      submit: "Send answer",
      submitMulti: "Send selected answers",
      sending: "Sending your answer…",
      multiHint: "Choose every option that applies, then send.",
      /**
       * §4.7's disabled-reason rule, for the three states that turn a control
       * off without the widget already printing a sentence about it.
       */
      chooseFirst: "Choose at least one option before sending.",
      typeFirst: "Type an answer before sending.",
      answeredAlready: "This question has already been answered.",
      /**
       * §7A.7: `404 unknown_question` is a first-class rendered state, in place
       * and not in a toast. The route cannot tell the three apart, so neither
       * does this sentence — claiming "someone answered first" would state a
       * fact the server did not give us.
       */
      abandoned:
        "This question is no longer open. It was answered elsewhere, abandoned with its run, or never reached this server.",
      /** A named refusal from §2.4's envelope, rendered as itself (§4.4). */
      failed: "The server refused this answer:",
      /**
       * The four reasons a widget cannot be answered from this page, each said
       * out loud: a disabled control with no explanation is indistinguishable
       * from a broken one.
       */
      unavailable: {
        reopened:
          "This is a reopened transcript. The run that asked has ended, so there is no question left to answer.",
        no_question_id:
          "This question carries no question id, so no client can address an answer to it. It was raised by a sidecar older than the id.",
        no_session:
          "This event carries no session id — the run's session binding has been evicted — so an answer cannot be routed to the run that asked.",
        no_answer_shape:
          "This question offers no options and does not allow free text, so it admits no answer this page could give.",
      },
    },
  },

  /** Named absences. A missing answer says which kind of missing it is. */
  absent: {
    unavailable: "unavailable",
    noGit: "This project is not inside a git work tree, so there is no history to show.",
    gitUnavailable: "git is not available to the server, so the working tree cannot be read.",
    loading: "Loading…",
  },

  /**
   * §7A — the composer. The surface that **speaks**.
   *
   * §7A.8's argument for why a disabled composer is right and its silence was
   * wrong governs half of these strings: "a state that exists for a reason
   * reads as designed; the same state with its content missing reads as a bug"
   * (§4.4). Every disabled state below therefore has a reason, and every reason
   * says what to do next.
   */
  composer: {
    label: "Message the agent",
    placeholder: "Ask the agent about this, or tell it what to change.",
    send: "Send",
    sending: "Sending…",
    /**
     * "Cancel the run" wrapped the actions row at 420px, pushing §7A.3's
     * disclosure onto a second line under an idle composer. The word is the
     * control; every reason string below still says which run and why.
     */
    cancel: "Cancel",
    /**
     * The keyboard, which is how a conversation is actually held.
     *
     * A textarea with a Send button and no key binding is a form, not a chat:
     * every turn costs a trip to the pointer. Enter sends and Shift+Enter opens
     * a line, which is the binding every reader already has in their fingers —
     * and it is announced, because an unannounced one is indistinguishable from
     * a text box that loses your newline.
     */
    sendHint: "Enter sends · Shift+Enter for a new line",

    /**
     * §7A.5's TIGHTENING: the composer never retries a prompt automatically.
     * "An auto-retry over an at-least-once route is a duplicate-turn generator
     * with a spinner on it." So the failure state hands the operator their own
     * words back and tells them where the truth is.
     */
    sendUnknownTitle: "This turn may have started",
    sendUnknown:
      "The request to start this turn did not come back. It may have started anyway, so it is not sent again automatically — your text is still here, and the transcript above is the authority for what actually ran.",
    retry: "Send again",

    /** §7A.5's named limit: cancel is unavailable until a run id arrives. */
    cancelNoRun:
      "This turn has not reported a run id yet. Cancelling needs one, and it arrives with the first event of the run.",
    cancelNoStream:
      "This page is not attached to the event stream, so it has no way to learn this run's id. Cancelling needs one.",
    cancelIdle: "There is no turn running to cancel.",
    cancelled: (questions: number): string =>
      questions === 0
        ? "Cancelled."
        : questions === 1
          ? "Cancelled. One pending question was released."
          : `Cancelled. ${questions} pending questions were released.`,

    /**
     * §7A.10's closed `data-disabled-reason` vocabulary, one sentence each.
     * `agent_unavailable` is the long one on purpose (§7A.8): it is the state
     * that produced a product review finding, and silence is what produced it.
     */
    disabled: {
      agent_unavailable:
        "This server has no agent runtime attached, so there is nobody to send this to.",
      run_in_flight:
        "A turn is already running. Wait for it to finish, or cancel it, before starting another.",
      no_session: "No session is selected, so this message has nowhere to go.",
    },
    /**
     * `run_in_flight` disables SEND, never the text box.
     *
     * The shipped composer disabled the textarea on every reason alike, so a
     * `run_in_flight` refusal left a box that could not be typed into and a
     * button that could not be pressed, with nothing in the UI able to clear
     * either — the operator's only exit was another tab. Composing while a turn
     * finishes is exactly what the wait is for, so the box stays live and the
     * refusal clears itself when the run reports its terminal.
     */
    runInFlightCompose: "You can write the next message while this turn finishes.",
    runInFlightHolder: (sessionId: string): string => `The live run belongs to session ${sessionId}.`,

    /**
     * §7A.8's cause vocabulary, rendered where the operator can act on it.
     * The `config_path` comes from the server and is printed beside these —
     * §7A.8: "the disabled composer **names the file the server looked for and
     * does not offer to write it**, because until §23 lands there is nothing
     * behind such an offer but a text editor."
     */
    attachCause: {
      no_provider_config: "No provider configuration was found at:",
      provider_config_invalid: "The provider configuration could not be read:",
      node_missing: "Node is not installed, and the agent runtime needs it.",
      node_too_old: "The installed Node is older than the agent runtime needs.",
      sidecar_failed: "The agent runtime failed to start.",
      auth_link_refused: "The configured credential could not be linked.",
      detached: "The agent runtime was detached from this server.",
    },
    attachHow:
      "Write a provider configuration at that path and restart the server, or run `heph agent` once to create one. This page does not write credential files.",
    attachRetry: "Attach a runtime",
    attachFailed: "Attaching a runtime failed.",

    /** §7A.3's chip row: the references this turn will carry, each droppable. */
    contextHeading: "This message will carry",
    contextDrop: (label: string): string => `Do not send ${label}`,
    contextNone:
      "This message carries no workspace references. The agent is told nothing about what is on this page.",
    contextKey: {
      part: "part",
      artifact_ref: "artifact",
      pin_mode: "pin",
      stage_tab: "stage tab",
      inspector_tab: "inspector tab",
      view: "view",
      explode_t: "explode t",
      section_plane: "section",
      hidden_labels: "hidden",
      selection: "selection",
      focus: "focus",
    },
    hiddenCount: (n: number): string => (n === 1 ? "1 label hidden" : `${n} labels hidden`),
    /** §7A.3's disclosure: what the agent will actually be told. */
    disclose: "What will the agent be told?",
    discloseHide: "Hide what the agent will be told",
    discloseAdvisory:
      "A preview. The message is composed again when it is sent, so what the agent receives is the version echoed back on the turn — not this one.",
    discloseTruncated:
      "This is longer than one context block may be, so it was cut. The agent is told that it was cut.",
    discloseEmpty: "Nothing. The agent is told only what you type.",
    discloseFailed: "The preview could not be composed.",

    /**
     * Session chrome (issue #13). Model identifiers come from
     * `GET /providers` — the text is the provider's own model id, not a
     * house name. Effort is not a prompt field (§7A.3) and is not
     * projected. DFM copy below labels the two §6.4 inspector actions
     * (`[dfm] auto_run` + `run_dfm`); the composer does not host them.
     */
    model: "Model",
    effort: "Effort",
    /**
     * Effort is not a prompt field (§7A.3). The composer used to project a
     * bare "off" next to the model id; that control wrote nothing and read
     * as an unlabelled toggle. The word stays here for the decision module.
     */
    effortOff: "off",
    noModels: "No models are declared in the provider configuration.",
    addCurrentView: "Add current view",
    addCurrentViewWhy:
      "Include this page's view and selection in the context the agent is told. The preview below is advisory — the message is composed again when it is sent.",
    dfmAutoRun: "DFM auto-run",
    dfmRun: "Run DFM",
    dfmNoPart: "No part is selected, so design-for-manufacture has nothing to evaluate.",
    dfmWriting: "Writing the project setting…",
    dfmRunning: "Running DFM…",

    /**
     * §7A.2's create affordances. Two, both explicit, and the profile is shown
     * before it is used — "a user who does not know their session cannot
     * delegate reads `scope_denied` as a broken product".
     */
    createOrchestrator: "New session",
    createPart: (part: string): string => `Ask about ${part}`,
    createTitle: "No session yet",
    /**
     * §7A.2's "where a part comes from, said out loud". The parts-empty state's
     * action creates an orchestrator session and focuses the composer, and the
     * copy names `create_part` as the mechanism, because "a blank canvas the
     * operator has to guess is filled by talking is the same defect as a
     * composer that is not there."
     */
    blankCanvas:
      "There is no part yet. Parts are made by asking an agent for one — it calls `create_part` and writes the script. Start a session and describe what you want.",
    blankCanvasAction: "Start a session",
    /**
     * Empty *session* copy when the project already has parts. The blank-canvas
     * sentence above is a lie on that path — a selected part and `part shelf`
     * context chips with "There is no part yet" is the defect.
     */
    noSessionSelectedPart: (part: string): string =>
      `There is no session yet. ${part} is selected — start a session about it, or a project-wide session.`,
    noSessionHasParts:
      "There is no session yet. This project already has parts. Start a session to work on one, or a project-wide session.",
    /** §15.30: a new *project* is out of reach from here, and is refused by name. */
    noProject:
      "A new project is `heph init` at a terminal. This server opens a project that already exists.",
    /** §7A.2's profile line, composed from the server's own capability facts. */
    profileWhat: (profile: string, canDelegate: boolean, partScoped: boolean): string =>
      `A ${profile} session. It ${canDelegate ? "can delegate to part agents and" : "cannot delegate, and"} ${
        partScoped ? "may only address the part it is bound to" : "addresses every part in this project"
      }.`,
    /** §7A.2: there is no route that closes a session, and none is invented. */
    orphanNote:
      "Starting a session twice leaves an extra idle one. Idle sessions cost nothing and there is no way to close one from here; leave it.",
  },

  /**
   * §23.14 item 15: a **closed** copy vocabulary for both status axes, every
   * refusal reason, and the scope choice — no reason string constructed at a
   * call site. A refusal that a panel phrased for itself is a refusal that says
   * something slightly different in each place it appears, and §23.11's whole
   * point is that the vocabulary is closed and testable by enumeration.
   */
  providers: {
    title: "Model providers",
    eyebrow: "Sign in",
    /**
     * The rail at 800px cannot host the full configuration table, allowlist
     * note, and discovery explainer at once — those put Sign-in at ~3000px.
     * Details stay one click away; the compact row keeps the actions.
     */
    detailsShow: "Show configuration",
    detailsHide: "Hide configuration",
    /** §23.0: the empty state is an action, not a green checkmark. */
    emptyTitle: "No model provider yet",
    emptyBody:
      "This project has no provider configuration, so there is nothing to run a session against. " +
      "Add a provider below, or look for one this machine already has.",
    addProvider: "Add a provider",
    configPath: "Configuration file",
    fileMode: "File mode",
    /** §23.2: a hand-authored file's mode is reported, never changed. */
    fileModeOpen:
      "This file is readable by other users on this machine. The workspace does not change the mode of a file it did not write.",
    allowlist: "Approved credential variables",
    /** §23.6: the one refusal without which this surface is an exfiltration path. */
    allowlistNote:
      "Prepared outside the workspace and read-only here. Nothing in this page can add a name to this list.",
    authSource: "Borrowed credential file",
    authSourceLinked:
      "This project's credential file is a link into the file above. Signing in would write into it, so sign-in and sign-out are refused until the link is removed.",
    unlink: "Stop borrowing",
    egressHosts: "Acknowledged outbound hosts",
    egressNote:
      "Every turn against one of these hosts sends model geometry, script source and transcript to it. This list is kept on disk and printed when the server starts.",
    adopted: "Adopted sources",
    /** §4.4/§6.3: a blank field never stands in for "not known". */
    noneRecorded: "None recorded",

    /** §23.8 axis 1 — what would I have to change to change this? */
    source: {
      label: "Credential",
      none: "None",
      env: "Environment variable",
      serve: "This server only",
      project: "Saved in this project",
      linked: "Borrowed from a linked file",
    },
    /** §23.8 axis 2 — does it work? Never collapsed into axis 1. */
    health: {
      label: "Last seen",
      unused: "Not used yet",
      accepted: "Accepted",
      rejected: "Rejected",
      expired: "Expired",
      unreachable: "Unreachable",
      rate_limited: "Rate limited",
    },
    /** §23.8: "The panel renders 'accepted 14:32', never 'connected'." */
    healthNever: "Nothing has used this credential yet.",
    healthStale: "Last observed",
    availability: "Verification",
    available: "Verified at startup",
    unavailable: "Not usable",
    unavailableNote:
      "This provider is declared but did not verify. It is never substituted by another and cannot run a turn.",

    signIn: "Sign in",
    signOut: "Sign out",
    rotate: "Replace key",
    replaced: "Replaced the credential that was",

    /** §23.7: a credential change is not a hot swap, and this never implies it is. */
    runsInFlight: (count: number) =>
      `Applying this restarts the agent and ends ${count} turn${count === 1 ? "" : "s"} that ${count === 1 ? "is" : "are"} running now.`,
    runsInFlightConfirm: "End them and continue",

    discover: {
      title: "Already on this machine",
      action: "Look for existing sign-ins",
      /** §15.41: nothing here runs on mount, on a timer, or on hover. */
      note:
        "This reads your home directory only when you press the button, and only to list what it finds. Nothing is used until you adopt it.",
      empty: "Nothing found to offer.",
      adopt: "Use this one",
      /** §23.5: the four fields, and nothing derived from a secret. */
      sourcePath: "Found in",
      models: "Models",
      kind: {
        pi_auth: "An existing sign-in",
        providers_json: "An existing provider configuration",
        local_endpoint: "A model server on this machine",
      },
      adopted: "Adopted. It is now named in this project's configuration file.",
    },

    dialog: {
      title: "Sign in to a provider",
      keyLabel: "API key",
      /** §23.3: no `name` a password manager would save under a wrong identity. */
      keyHint: "Pasted into this server only. It is never shown again and never sent anywhere else.",
      scopeLabel: "Where should this key live?",
      /** §23.2: no default. The operator picks, or the server refuses by name. */
      scopeNote: "There is no default. Choose one.",
      scope: {
        serve: "This server only",
        serveNote: "Held in memory. Restarting the server forgets it.",
        project: "This project",
        projectNote: "Written to this project's credential file, readable only by you.",
      },
      endpointLabel: "Endpoint",
      endpointHint: "A local endpoint must be an address on this machine, not a name.",
      egressLabel: "Type the host to confirm outbound traffic",
      /** §23.4: said before the operator clicks, not after they wonder. */
      subscriptionTitle: "Sign in with a subscription",
      subscriptionDisclosure:
        "Your provider will list this sign-in under the name of the agent library this server embeds, not under Hephaestus. This server never refreshes the token — the library does.",
      deviceCode: "Enter this code",
      deviceCodeOpen: "Open the sign-in page",
      pasteLabel: "Paste the address you were redirected to",
      pasteHint:
        "The redirect goes to an address nothing is listening on, so the browser will show an error. Copy what is in its address bar and paste it here.",
      submit: "Sign in",
      cancel: "Cancel",
      waiting: "Waiting for you to finish in the other tab…",
    },

    /** Every §23.11 reason, phrased once. Nothing is built at a call site. */
    refusal: {
      agent_unavailable: "There is no agent runtime attached to this server yet.",
      allowlist_not_web_writable:
        "The approved-variable list and the borrowed-credential path are prepared outside the workspace and cannot be written from this page.",
      auth_source_linked:
        "This project's credential file is a link into another file. Remove the link before signing in or out.",
      authorization_expired: "That sign-in is no longer valid. Start it again.",
      authorization_input_malformed:
        "That does not look like a redirect address or an authorization code.",
      authorization_state_mismatch:
        "That authorization did not match the one this server started. Nothing was changed.",
      credential_expired: "The stored credential has expired.",
      credential_not_allowlisted:
        "This provider reads its key from a variable that is not on the approved list, and this page cannot add one.",
      credential_rejected: "The provider rejected the credential.",
      credential_scope_required: "Choose where the key should live.",
      discovery_source_unknown: "That offer is no longer current. Look again.",
      egress_not_acknowledged: "Type the host name to confirm outbound traffic to it.",
      endpoint_not_loopback: "A local endpoint must be an address on this machine, not a name.",
      login_already_in_progress: "A sign-in for this provider is already under way.",
      model_unknown: "The provider does not offer that model.",
      not_loopback: "Provider settings are only available when the server is bound to this machine.",
      path_not_web_writable: "This page cannot name a file for the server to read.",
      provider_not_authenticated: "This provider has no credential yet.",
      provider_rate_limited: "The provider is rate limiting this account.",
      provider_unknown: "No such provider.",
      provider_unreachable: "The provider could not be reached.",
      runs_in_flight: "A turn is running. Applying this would end it.",
      unsupported_auth_type: "The provider does not offer that way of signing in.",
    },
  },

  errors: {
    title: "The server refused this request",
    unauthorized: "The token this page holds was not accepted. Restart the server and reopen its address.",
    retry: "Try again",
    reason: "Reason",
  },
} as const;

export type Copy = typeof copy;
