# YazSes XR feature catalogue (proposed)

**All entries are design candidates, not available YazSes features.** IDs are planning identifiers only, not feature-registry toggles or CLI names. The order reflects dependencies, not delivery promises. Acceptance checks are conditional on the [ROADMAP.md](ROADMAP.md) entry gates.

| ID | Candidate | Example user request | Proposed priority | Primary dependency |
|---|---|---|---|---|
| XR-01 | XR Voice Bridge | “Open the inventory” | P0 foundation | Local event contract, consent |
| XR-02 | VRChat text composition | “Type hello to everyone” | P0 demonstrator | Host prefill + explicit send |
| XR-03 | Look & Speak object actions | “Make this cube blue” | P1 research | Scene object IDs, target confidence |
| XR-04 | Hands-free accessibility | Look + deliberate switch + speak | P1 research | Proven stop/re-arm + switch safety |
| XR-05 | Bounded voice navigation | “Go to the meeting room” | P2 | App-provided safe destinations |
| XR-06 | Avatar expression mapping | “Wave hello” | P1 experiment | Allowlisted avatar OSC parameters |
| XR-07 | Voice-based world editing | “Add three chairs” | P3 | Scene editor adapter + undo |
| XR-08 | Multilingual social subtitles | “Translate my message to Italian” | P3 | Local multilingual + translation models |
| XR-09 | Virtual meeting notes | “Summarize the session” | P2 | Authorized audio + local diarization |
| XR-10 | Spatial guide and bookmarks | “What is this object?” | P3 | App metadata + bounded local memory |

**Meaning of priorities:** P0 = a useful, small proof of concept; P1 = research value once P0 is validated; P2/P3 = deferred pending demand and explicit review. None of the priorities overrules [ADR-030](../adr/adr-030-agent-era-direction.md).

## XR-01 — XR Voice Bridge

**Need:** a VR/XR application can consume a YazSes transcript without embedding a speech engine.

**Proposed experience:** an opt-in local app subscribes to final transcripts and, separately, structured command proposals. It displays recording state and never interprets a transcript as an executable command by default.

**Definition of done for a future prototype:**
- A versioned, machine-readable, documented event contract and at least one in-process or local test client.
- Default-off endpoint; authorization of each client/application; invalid origins/tokens and oversized payloads rejected.
- No raw audio export, no change to current desktop dictation, and explicit handling of disconnected/slow clients.
- Offline automated contract tests plus observed end-to-end latency measurements; no aspirational latency reported as achieved.

## XR-02 — VRChat text composition

**Need:** entering text in a virtual world is laborious or inaccessible.

**Proposed experience:** speak “Hello everyone” to fill a local compose buffer. Review the result. A human then uses the host's native explicit send action.

**Definition of done:**
- Local fake chatbox tests work with no VRChat installation, account or internet.
- Research confirms current VRChat OSC chatbox behaviour in a real client before claiming compatibility; prefer documented prefill behavior, never auto-send. An independent user action is required to publish.
- Capture UTF-8, text length, truncation and formatting behaviour using actual supported limits; never silently truncate an important message.
- On missing host permission or disconnected client, explain the failure and keep the draft local.

See [VRChat OSC overview](https://docs.vrchat.com/docs/osc-overview) and the [historical chatbox prefill/send distinction](https://docs.vrchat.com/docs/vrchat-202222p3). Documentation is not hardware-validation evidence.

## XR-03 — Look & Speak object actions

**Need:** name or select a virtual object without fiddly menus.

**Proposed experience:** an application supplies a fresh, explicitly scoped, stable object ID for the thing in the user's headset gaze/head-ray; YazSes interprets “make this blue” as a reversible proposal.

**Definition of done:**
- Test scene with known object IDs, raycast/gaze freshness, unique target selection and alternative input.
- Ambiguous/occluded/stale target => clarify or abstain; never arbitrarily pick an object.
- Reversible edit + verifiable object state; separate confirmation for consequential or external effects.
- Measure target accuracy, wrong-object changes, task completion and extra confirmations; report headset or desktop simulation separately.

## XR-04 — Hands-free accessibility

**Need:** participate in virtual environments without controllers or a physical keyboard.

**Proposed experience:** speech for text, head/gaze for target, deliberate face gesture or other accessible switch for commit, with predictable pause/fallback.

**Definition of done:**
- More than one confirmation modality; deliberately configurable, non-default gestures; no automatic blink-to-click.
- Stop/pause works under tracking loss, misrecognition, mode changes and network failure; cannot silently re-arm.
- Representative accessibility usability testing with informed consent and no coercive, diagnostic or disability claims.
- Track false activations, recovery time, fatigue and successful independent completion, including failures.

## XR-05 — Bounded voice navigation

**Need:** move between defined spaces without complex menu interaction.

**Proposed experience:** “Go to the meeting room” selects a destination supplied by the host app.

**Definition of done:**
- Explicit allowlist of destinations; preview and cancel options; no arbitrary coordinates or continuous motion by voice alone.
- Respect host permissions and comfort/safety preferences; a safe fallback if navigation is blocked.
- Record cancellation rate, wrong-destination rate and user-reported comfort. No claim of cybersickness prevention absent evidence.

## XR-06 — Avatar expression mapping

**Need:** trigger configured avatar expressions without searching menu wheels.

**Proposed experience:** “Wave hello” proposes an allowlisted avatar parameter action; the host executes only if that avatar exposes it.

**Definition of done:**
- OSC avatar parameter names/types discovered or configured from documented host data, not guessed.
- Confirm actual avatar support before claiming an expression succeeded; release any held button/axis states safely.
- Test mock transport, mismatched parameter types, avatar change and disconnected client.
- No impersonation or actions on other participants' avatars.

See [VRChat OSC avatar parameters](https://docs.vrchat.com/docs/osc-avatar-parameters).

## XR-07 — Voice-based world editing

**Need:** use language to perform repetitive edits in a user-owned, supported scene.

**Proposed experience:** in a sandbox scene editor, “Add three chairs” places predefined assets as a preview; the user accepts or undoes.

**Definition of done:**
- Named asset catalogue and ownership/permission boundaries; no arbitrary model generation by default.
- Deterministic action plan, scene-level undo and postcondition check.
- Multi-object and destructive operations require explicit confirmation.
- Measure scene correctness, undo reliability and unintended edits before exposing shared-world changes.

## XR-08 — Multilingual social subtitles

**Need:** communicate across languages without a remote speech service.

**Proposed experience:** locally transcribe an explicitly enrolled speaker's audio, translate using a separately installed on-device model, display or prefill translated text for review.

**Definition of done:**
- Separate STT language support, translation-model quality and output transport; all labelled by actual validation.
- No capture of other participants without permission; opt-in for translation and any sharing.
- Preserve names/negation, provide easy original/translated comparison, measure meaning errors.
- A translation engine or real-time subtitle client is **not** currently guaranteed.

## XR-09 — Virtual meeting notes

**Need:** retain decisions from consented virtual classes or team meetings.

**Proposed experience:** authorized meeting audio enters YazSes's local meeting pipeline, and the user reviews a labelled transcript and optional minutes.

**Definition of done:**
- Reliable, consented access to each permitted audio channel; no background recording.
- Local speaker labels explicitly qualified when attribution is uncertain.
- Document retention, deletion and sharing; no automatic upload or mailing.
- Compare transcript quality, attribution, summary fidelity and false attributions with held-out examples.

## XR-10 — Spatial guide and bookmarks

**Need:** ask about known objects or find a previously visited location.

**Proposed experience:** the host provides a stable scene object reference and metadata; a user asks “What is this sculpture?” or bookmarks an allowed location locally.

**Definition of done:**
- Read-only object lookup works without generating invented facts; cite object/source metadata if available.
- Bookmark storage local and explicitly removable; never publish location history.
- “Unknown object” and changed worlds lead to clarification or “I don't know,” not fabricated answers.
- Measure object grounding and retrieval accuracy on known scenes.

## Candidate sequencing

The **first useful proof** is XR-02 in a local test scene with native confirmation. XR-01 then provides a reusable local application boundary, XR-06 tests narrow app-specific actions, and XR-03 + XR-04 advance the existing gaze/hands-free research. XR-05, XR-07, XR-08, XR-09 and XR-10 remain later options with independent evidence and governance gates.

Do **not** register these in the shipped feature catalogue or add user-facing install commands until code, integration tests, release gates and real platform validation exist.