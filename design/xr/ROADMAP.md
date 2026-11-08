# YazSes XR — conditional roadmap

**Status: FUTURE WORK, research only.** No implementation milestone, release version, assigned maintainer, or target date is committed here. The [accepted ADR-030 direction](../adr/adr-030-agent-era-direction.md) remains the active plan.

## Standalone SPECS spatial-review experiment — research only

**Status: proposed external Lens Studio Preview experiment; no YazSes integration, hardware verification, release, or completed submission.** This exploration is adjacent to YazSes's existing compose → review → deliberate confirm interaction research. It is not an approved XR feature milestone or an exception to [ADR-030](../adr/adr-030-agent-era-direction.md).

**Working concept:** *YazSes Spatial Review* — a new standalone SPECS Lens Studio experience for a simulated tabletop task. The user places a note beside a work surface, chooses one of two explicitly labelled **simulated transcription** presets, reviews the text, and deliberately confirms, cancels, or resets it. The text must stay positioned relative to the scene as the viewpoint moves. All input is synthetic, with a persistent **"not live speech"** disclosure. No real speech capture, local ASR, YazSes transport, cloud service, external action, gaze recognition, or physical glasses validation is in scope.

**Experimental boundary:** a [separate public technical repository](https://github.com/MSKazemi/yazses-specs-ar) exists with an [Ubuntu-to-Windows implementation roadmap](https://github.com/MSKazemi/yazses-specs-ar/blob/main/ROADMAP.md) and README, **but no verified native Lens Studio project or Preview result**. Portable TypeScript work on Ubuntu is not Lens validation. A genuine new Lens still requires Windows/macOS Lens Studio, CLAD/MCP, the official Devpost planning skill, and observed Preview testing. Only reviewed technical source and reproducible assets belong in that repo; a Preview prototype itself would not prove physical headset support or offline dictation on glasses.

**Evidence checklist before describing the experiment as working:**
1. Record actual editor/target versions and that the saved SPECS project opens in Lens Studio Preview.
2. Demonstrate scene-relative placement, labelled preset drafts, no auto-confirm, intentional confirm/cancel, idempotent repeated input, and reset/recovery.
3. Record actual Preview observations/Logger and applicable LEAF results, separating **PASS, FAIL, and NOT RUN** from generated code.
4. Preserve a clean technical source snapshot and truthful limitations; do not publish credentials, account data, private strategy, or copyrighted assets without rights.
5. Treat subsequent voice integration only as a **new research question**: test demand, supported host APIs, security/egress, consent, and transport assumptions before any ADR decision.

**Possible follow-on, not scheduled:** the evidence may refine this existing XR discovery programme and its [decision register](DECISIONS.md). It does not satisfy any [entry gate](#entry-gate-do-not-start-a-new-capability-wave-by-default) below: documented non-contributor demand, an ADR-030 amendment and decision, privacy/egress review, a bounded delivery milestone under the [milestone policy](../milestone-policy.md), and a realistic test environment. An optional YazSes adapter could be proposed only after all five hold. No change to `src/yazses/`, the feature registry, release channels or `main` is implied.

## North star

Enable **local, consent-first, multimodal access to supported virtual worlds** without turning YazSes into a virtual world, game automation bot, always-listening assistant, or cloud STT client. A user should be able to compose and review text with voice; later, a user can target an instrumented 3D object via gaze/head ray, propose a bounded action, and see whether it succeeded.

## Entry gate: do not start a new capability wave by default

Research or docs may proceed now. **Implementation only proceeds after:**
1. Documented demand from at least one substantive non-contributor issue/discussion. ADR-030 has no separate mechanism for waiving this: its section 3 ties lifting the freeze to that first substantive non-contributor issue, and any change to the condition is itself an amendment to ADR-030 (gate 2), as the 2026-11-01 biosignal exception was.
2. An explicit amendment/decision under [ADR-030](../adr/adr-030-agent-era-direction.md) that lifts or scopes the breadth freeze for this experiment.
3. Decision on the optional transport, egress, consent and safety boundaries ([DECISIONS.md](DECISIONS.md)); evaluate how proposed [ADR-025](../adr/adr-025-grounded-interaction-kernel.md) applies.
4. A small, bounded GitHub delivery milestone and issue set following [milestone policy](../milestone-policy.md) *after* permission to implement, not before.
5. A baseline and realistic test environment, with no unverified headset compatibility advertised.

If the gate remains closed, this programme stays documented as a future research direction. A PR merging these files does not lift the freeze.

## Phases and evidence gates

| Phase | Outcome (conditional) | Work | Exit gate |
|---|---|---|---|
| R0 — Discovery | A defensible go/no-go decision | User demand, platform/API review, threats, compare existing capabilities | Document need, constraints, and ADR-030 decision |
| P0 — Local demo | Voice-composed text with explicit send | Local test chatbox, review/confirm state, mock transport; no external API | Offline integration tests; zero auto-sends in negative cases |
| P1 — Optional XR Bridge | A narrow reusable local integration | Versioned events, opt-in client auth, permissions, backpressure, diagnostic tooling | Contract tests; no unauthenticated subscriber; latency/error report |
| P2 — Social VR adapter | One platform-specific path | Verify VRChat chatbox prefill and selected avatar OSC bindings on actual client; mock first | Hardware-verified matrix with visible user confirmation |
| P3 — Spatial interaction | Gaze/head ray + voice on known objects | Host app supplies target IDs, ambiguity policy, reversible action + undo | Wrong-object rate and outcome verification evaluated |
| P4 — Accessible interaction | Non-controller route through the same scene | Switch confirmation, pause/recovery, alternative modalities, inclusive testing | Stop/recovery results and voluntary usability evidence |
| P5 — Expansion | Selected higher-value features only | Navigation, scene editing, translation, meeting notes, guide | Separate demand, security and acceptance evidence per feature |

No phase implies that the next one must happen. Stop after R0 or P0 if need, safety, latency, portability or maintainability do not justify more work.

## Phase R0: research and decision (allowed during freeze)

1. **Demand:** ask real social VR participants, XR developers and accessibility users what they struggle with (not just which feature sounds exciting). Record only explicitly volunteered, non-sensitive context. Distinguish opinion from reported use.
2. **Host support:** verify current official VRChat OSC chatbox and avatar-parameter behaviour, including whether a prefilled message can always wait for the user's own send action. Check restrictions, rate limits, OS and headset variants.
3. **Architecture:** compare direct local OSC for one app with an optional event stream for general applications; decide whether adding a WebSocket dependency is justified.
4. **Privacy and authority:** list every audio/text/metadata transfer, its destination, permission and default; review [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md).
5. **Decision:** document the smallest experiment with measurable hypotheses, what a failure would look like, and the amendment needed under ADR-030.

**R0 output:** a reviewed decision record plus evidence log. **Not:** a shipped interface, public promise or new feature-registry toggle.

## Phase P0: build a safe local vertical slice (after entry gate)

**User story:** “I speak a sentence in a virtual chat mock-up; it appears as an editable draft and is only transmitted when I explicitly send.”

- Reuse the existing offline dictation engine and command mode; do not create an XR-only STT fork.
- Implement an in-process adapter to a local mock client first (no headset, third-party account, live service or network requirement).
- Separate **capture → compose → review → native send** with a visible state machine.
- Include cancel/clear, corrections, mic pause and failure recovery.
- Test malicious/malformed events, long/non-ASCII text, duplicate delivery, missing focus, disconnection and permission revocation.
- Capture no real participant audio in the test suite.

**Success:** reproducible demo on a normal PC and traceable tests; 0 external sends because the reference demo has no external destination.

## Phase P1: add the reusable bridge only if P0 earns it

- Specify minimal versioned transcript, recording-state, intent-proposal and outcome events in [ARCHITECTURE.md](ARCHITECTURE.md).
- Consider in-process callbacks first; only introduce a loopback WebSocket server when independently useful to more than one consumer. Treat all local clients and browser origins as potentially untrusted.
- Optional dependency, disabled listener by default, app allowlist and session authorization, bounded queues, no raw audio, fail closed.
- Reject unauthenticated access and remote network binds; a headset on another machine is an **entirely separate**, stronger authenticated transport design.
- Build one sample consumer plus contract/fuzz tests, and record actual end-to-end timings rather than promise a number from research.

## Phase P2: real social VR demonstration

- Start with mocked VRChat OSC behaviour. On a real VRChat PC client, verify the *current* chatbox prefill behaviour and any limitations.
- Never silently invoke “send immediately.” An outbound message is external action and may only be sent through a distinct, deliberate host-native user action.
- Add one allowlisted avatar parameter such as a supported wave gesture; absence of parameter means no action.
- Publish a validation matrix with real OS/client versions, exact device configuration, observed actions and blockers. Do not claim standalone Quest support from PC testing.

## Phase P3: spatial targeting

- Instrument one Unity scene (or equivalent) with several similar objects and stable, app-owned IDs.
- Select targets via fresh headset gaze or head-directed ray; laptop webcam gaze remains coarse and must not be advertised as precise headset eye tracking.
- Use “look + speak” to propose an action; ambiguity and outdated rays force clarification or abstention.
- Make the first mutation reversible, require explicit confirmation where warranted, and verify a resulting object property.
- Keep input semantics independent from Unity so later Unreal/WebXR work is an adapter, not a rewrite.

## Phase P4: hands-free research

- Let a deliberate switch/voice command confirm without a controller and provide more than one recovery path.
- Retain YazSes's existing global stop/pause safety lessons; a “pause” must not automatically rearm on a voice recognition guess.
- Evaluate with users who opt in, and report actual tasks, setup cost, false triggers, fatigue and failure modes—not marketing claims.

## Phase P5: defer the remaining ideas

| Feature | Research condition before taking it on |
|---|---|
| XR-05 navigation | Host-defined destinations, comfort safeguards and undo/cancel |
| XR-07 world editing | User-owned scene API, explicit previews, reliable undo |
| XR-08 multilingual subtitles | Offline multilingual/translation models, speaker consent and quality baseline |
| XR-09 meeting notes | Permitted audio capture, recording consent, diarization evidence |
| XR-10 spatial guide | Trusted object metadata, local retention and uncertainty handling |

## Cross-cutting release gates

A phase is “done” only when its [EVALUATION.md](EVALUATION.md) evidence is attached to a reviewable PR:
- Core dictation and default settings unchanged; optional work fully dormant when disabled.
- Clean, bounded egress inventory; permission revocation tested; no surprise listeners.
- Deterministic tests and explicit negative tests for unintended external actions.
- Honest matrix separating simulation from physical devices, systems and applications.
- Accessibility and stop/recovery paths evaluated at the applicable phase.
- No unsupported claims about latency, word error rate, safety, platform support or real user benefit.

## Mapping all ten ideas

- **P0/P1:** XR-02 local compose-and-review, XR-01 optional app bridge.
- **P2:** XR-02 real integration only if safe; XR-06 avatar expressions.
- **P3/P4:** XR-03 gaze+voice grounding, XR-04 hands-free accessibility.
- **P5:** XR-05 navigation, XR-07 world edit, XR-08 translation, XR-09 meetings, XR-10 spatial guide.

See [TASKS.md](TASKS.md) for concrete units of work and [DECISIONS.md](DECISIONS.md) for blocking questions.