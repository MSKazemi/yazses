# ADR-025 — Introduce a Grounded Interaction Kernel before new agent, spatial, or robot stacks

**Status:** Proposed (2026-09-23)  
**Decision required:** maintainer review before implementation  
**Context links:** [grounded multimodal interaction](../../docs/research/grounded-multimodal-interaction.md) ·
[Grounded Interaction Kernel research architecture](../../docs/research/interaction-kernel.md) ·
[ADR-020 — agent protocols](adr-020-agent-protocols.md) ·
[ADR-021 — carry error cost through the pipeline](adr-021-invest-in-error-cost.md) ·
[ADR-022 — a confirmation a voice user cannot give](adr-022-a-confirmation-a-voice-user-cannot-give.md) ·
[ADR-v2-006 — Spoken MCP](adr-v2-006-spoken-mcp.md)

---

## Context

YazSes has accumulated multiple interaction features that solve adjacent parts of the same
problem:

- gaze produces a coarse target and confidence;
- deixis resolves "this" / "that";
- context readers expose the current application/selection;
- accessibility-oriented planners match semantic UI elements;
- the agent planner constructs structured tool calls;
- the destination guard knows whether a useful text target exists;
- command safety and staged dictation hold consequential actions;
- overlays/read-back provide user feedback.

The current implementation treats these as feature-specific paths. That was reasonable
while each capability was experimental, but it is now producing repeated questions:

- what exactly was observed?
- what object is the user referring to?
- what are the competing interpretations?
- how confident is each interpretation?
- what is the cost of being wrong?
- is the action actually authorized?
- should YazSes execute, ask, abstain or fall back?
- how do we verify that the requested action actually happened?

The September 2026 grounded-multimodal research synthesis identifies the missing seam
between raw target acquisition and planning. ADR-021 independently identifies the same
architectural pressure from the safety side: several point guards are really one question
about **the consequence of an error at a destination**.

At the same time, ADR-020 deliberately rejects A2A because YazSes is not an autonomous
goal-seeking agent. We therefore need a composition layer that improves human intent
grounding **without inventing agency**.

## Proposed decision

Introduce a small, dependency-free **Grounded Interaction Kernel** as the common contract
between perception/context sources and execution.

The core conceptual types are:

1. `Observation` — one sensor/software fact with source, time and confidence.
2. `GroundedTarget` — a candidate referent with semantic identity, evidence and confidence.
3. `IntentHypothesis` — one possible action interpretation; multiple hypotheses may coexist.
4. `AuthorityContext` — explicit scope, consequence class, confirmation and expiry.
5. `ActionProposal` — the exact side effect under consideration, with provenance.
6. `ActionOutcome` — what was observed after execution and how it was verified.

A policy function decides among:

```text
execute
confirm
clarify
abstain
fall back
```

based on **both uncertainty and consequence**.

### Proposed package boundary

If this ADR is accepted, the first implementation should be pure Python under:

```text
src/yazses/interaction/
```

It must initially have:

- no model dependency;
- no network dependency;
- no camera dependency;
- no accessibility runtime dependency;
- no MCP dependency;
- no OpenXR/OpenUSD/ROS dependency;
- deterministic unit-testable behavior.

Existing feature modules remain the adapters.

## Invariants

### 1. Observation is not inference

A gaze point, transcript, UI node or EMG event is recorded as evidence. It does not silently
become a user intention.

### 2. Ambiguity remains explicit

A resolver may return multiple `IntentHypothesis` objects. It must not manufacture
certainty merely because an executor requires one action.

### 3. Low confidence is not the only reason to stop

A high-confidence interpretation may still require confirmation because the consequence of
being wrong is high.

### 4. Authority is separate from model confidence

No model output, tool output, webpage, email or retrieved document acquires permission to
perform a side effect merely by containing an instruction.

### 5. Consequential ambiguity is never guessed through

For external, destructive or future physical actions, unresolved ambiguity routes to
clarification or abstention.

### 6. Execution is not success

The executor returning successfully is insufficient. Where possible, `ActionOutcome`
records an observable postcondition and verification method.

### 7. This does not make YazSes autonomous

The kernel represents and guards human interaction. It does not add persistent goals,
self-directed task pursuit or agent-to-agent negotiation.

### 8. Existing offline and egress guarantees remain unchanged

The kernel is local data flow. It creates no new outbound path.

## Consequence classes

The first shared vocabulary should distinguish at least:

| Class | Meaning | Default posture |
|---|---|---|
| `OBSERVE` | read-only | may execute automatically |
| `REVERSIBLE` | local, easily undoable change | policy/user mode |
| `EXTERNAL` | sends/publishes/changes external state | confirm or explicit scope |
| `DESTRUCTIVE` | deletes/overwrites/irreversible loss | strong confirmation / clarify |
| `PHYSICAL` | affects a device/robot/environment | reserved; requires separate ADR and safety boundary |

`PHYSICAL` is a vocabulary reservation, not approval of robot control.

## First implementation slice

Do not wire every modality.

The first experiment after acceptance should be **gaze + voice + accessibility semantics**
on one platform:

```text
coarse gaze region
    +
spoken "click this"
    +
accessibility candidates
    ->
ranked target/intent hypotheses
    ->
execute / confirm / clarify / abstain
```

The point of the experiment is not to prove that gaze can emulate a mouse. It is to test
whether semantic grounding can make commodity webcam gaze useful without requiring
pixel-level precision.

## Evaluation requirements

Any implementation PR must report more than command accuracy.

At minimum:

- target-resolution accuracy;
- intent-resolution accuracy;
- wrong-action rate;
- unsafe-action rate;
- clarification rate;
- unnecessary-clarification rate;
- task-completion rate;
- time-to-action;
- cost-weighted error;
- confirmation burden.

For consequential tasks, the critical metric is:

```text
incorrect consequential actions executed
-----------------------------------------
consequential action opportunities
```

The desired optimization target is safe selective action, not maximum automation.

## Alternatives considered

### A. Keep every feature-specific path

**Rejected as the long-term direction.** It preserves local simplicity but repeats target,
confidence, confirmation and outcome logic in each new modality.

### B. Adopt a universal external "intent protocol" immediately

**Rejected for now.** The hard problem is grounding and uncertainty, not serialization.
Publishing a protocol before we know the right semantics would fossilize guesses.

### C. Turn YazSes into an autonomous agent and use A2A

**Rejected.** ADR-020 already records the stronger reason: YazSes has no goals of its own.
A2A would invent agency to justify a protocol.

### D. Send all context to an LLM and let it decide

**Rejected.** This hides uncertainty, weakens deterministic testing, introduces prompt
injection/authority confusion, and conflicts with the CPU/offline default.

### E. Build digital-twin / OpenXR / ROS integration first

**Rejected as sequencing.** Those integrations depend on the same unresolved questions:
identity, grounding, authority, consequence and verification. If they ever become useful,
they should adapt into the kernel rather than define it.

## Consequences

### Good

- one place to carry evidence, uncertainty and consequence;
- gaze, pointer, head pose, EMG and future modalities can share downstream logic;
- ADR-021's cost-weighted-error direction becomes representable end to end;
- confirmation policy can eventually be unified instead of multiplied;
- future MCP/mobile/spatial/robot adapters can remain outside the core;
- the research program gains measurable abstention and unsafe-action metrics.

### Accepted cost

The interaction model introduces abstraction before all use cases are known. Keeping the
core small and dependency-free is the mitigation.

### Main failure mode

The kernel becomes a new umbrella under which dozens of features are added.

If it increases the number of independent runtime paths rather than collapsing them, this
ADR has failed.

## What this ADR explicitly does not decide

It does not approve:

- A2A;
- long-horizon autonomous agents;
- persistent personal-memory expansion;
- third-party in-process plug-ins;
- network services;
- OpenXR or OpenUSD;
- ROS 2 or robot control;
- VLM-on-screenshot as a default grounding path;
- automatic execution of ambiguous consequential actions.

Those remain separate decisions.

## What would make us reject this ADR

Reject or supersede this proposal if a prototype shows that:

1. the six-type contract cannot represent existing gaze, safety and tool-planning flows
   without feature-specific escape hatches;
2. the abstraction adds latency/complexity without reducing duplicated policy;
3. confidence sources cannot be calibrated well enough to improve execute-vs-clarify
   decisions;
4. users experience unacceptable clarification/confirmation burden;
5. the first vertical slice does not improve task completion over existing focus/window
   routing.

## Implementation order after acceptance

1. golden vectors and property tests for the pure contract;
2. pure `interaction/` package;
3. read-only adapter from existing gaze/context sources;
4. one reversible semantic-action experiment;
5. measurement;
6. only then consider unifying existing consequence/confirmation guards.

No daemon refactor is justified before steps 1–5 produce evidence.
