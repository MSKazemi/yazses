# ADR-v2-141 — Ground coarse targets into semantic UI entities before planning actions

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-v2-010-gaze-routed-dictation]], [[adr-v2-007-atspi-pilot]],
[[adr-v2-004-context-primed-dictation]], [[adr-v2-051-screen-grounded-dictation]],
[[adr-019-egress-inventory-and-escalation]], [[adr-021-invest-in-error-cost]]

**Research:** [Grounded multimodal interaction](../../docs/research/grounded-multimodal-interaction.md)  
**Programme:** [Eye / camera control](../eye-control/README.md)

## Context

YazSes can already answer a coarse spatial question:

> which window was the user looking at when the utterance began?

That is sufficient for Glance-Type and current gaze deixis such as "focus this window" or
"close that". It is not sufficient for a richer hands-free command such as "click this",
"explain this", or "use this date", because a window can contain dozens of actionable elements.

The existing codebase also has pieces of the next layer:

- `gaze/targeter.py` resolves a gaze sample to a window;
- `gaze/deixis.py` binds demonstratives to that snapshot;
- `pilot/plan.py` can match spoken UI commands to accessibility-tree elements;
- `system/context_read.py` reads active-window/selection context;
- `screengrounded/` extracts useful visible terms;
- `agent/plan.py` separates planning from side-effect confirmation.

The 2026 Google Magic Pointer and Apple Siri AI / onscreen-awareness research reinforces a
general architecture that is older than either product: **pointing identifies a region;
structured semantics identify the exact entity; language supplies the operation**.

The missing YazSes seam is therefore not "a better eye cursor". It is a small layer between
coarse target acquisition and intent/action planning.

## Decision

Introduce a dependency-free **grounded target resolution** layer with three separate concepts:

1. **Target snapshot** — where the user referred, from gaze, mouse, head pointer, explicit
   screen selection, or another modality.
2. **Semantic candidates** — structured entities supplied by an accessibility tree or other
   explicit application/OS source.
3. **Grounded target** — the resolver's result, including provenance, confidence and ambiguity.

Names may change during implementation; the boundaries are the decision.

### The grounding layer does not execute actions

Grounding answers **what object does "this" refer to?**

It does not:

- click;
- close;
- type;
- call a tool;
- decide whether an action is safe.

Action risk remains downstream. A perfectly grounded destructive target may still require
confirmation under the existing safety/error-cost rules.

### Semantic-first resolution order

The first implementation uses structured information only:

1. native accessibility/UI tree;
2. application-native structured context where already available;
3. selected/focused text or element metadata where policy allows;
4. window geometry/metadata for coarse fallback.

**OCR, screenshots and VLM inference are explicitly deferred.**

Adding screenshot/OCR/VLM fallback later requires its own decision because it changes dependency,
privacy, CPU and egress review surfaces. This ADR must not be used as implicit permission to capture
the screen.

### Provenance is part of the result

A grounded target must retain enough evidence to distinguish:

- exact accessibility node;
- app-native entity;
- selected/focused element;
- geometry-only fallback;
- unresolved/ambiguous.

Consumers must not collapse those to one unqualified "confidence" number and then act as if all
sources are equivalent.

### Abstention is a valid result

If a coarse gaze region contains multiple plausible controls and the available intent/context cannot
disambiguate them, the resolver returns **ambiguous/unresolved**.

It must not guess merely to keep a command flowing.

### Voice may refine; it may not manufacture a target

An intent hint such as "click Save" may rank the visible `Save` button above other candidates in the
same plausible region.

It may not pull an unrelated element from elsewhere in the window just because its label matches.
Spatial evidence and semantic evidence are combined, not replaced by language.

### Platform semantic sources stay behind a Protocol

Linux AT-SPI, macOS Accessibility and Windows UI Automation belong behind one small read-only
semantic-source Protocol.

The pure resolver accepts candidate values. It does not import `pyatspi`, PyObjC, Win32 libraries or
screen-capture code.

This keeps the resolver fully testable in ordinary CI and lets platform coverage improve without
rewriting gaze/deixis/planning.

### Existing behavior remains the fallback during integration

The first implementation must not change today's live Glance-Type/deixis behavior.

If semantic grounding is unavailable, disabled, stale or ambiguous:

- ordinary gaze-routed dictation keeps its existing window-level fallback;
- current window-level deixis keeps its existing confirmation/ignore semantics;
- no new exact-element action is synthesized.

Semantic refinement is additive.

## Conceptual contracts

The implementation spec may refine names/fields, but the shape should remain small:

```python
@dataclass(frozen=True)
class TargetSnapshot:
    source: TargetSource
    timestamp_s: float
    confidence: float
    point: Point | None
    bounds: Rect | None
    window_id: str | None

@dataclass(frozen=True)
class SemanticCandidate:
    source: SemanticSourceKind
    entity_id: str
    role: str
    bounds: Rect | None
    label: str | None
    actions: tuple[str, ...]
    confidence: float

@dataclass(frozen=True)
class GroundedTarget:
    target: TargetSnapshot
    candidate: SemanticCandidate
    resolution_confidence: float
    evidence: tuple[GroundingEvidence, ...]
```

The public contract must not contain raw screenshots, camera frames, MediaPipe result objects, or
platform-specific accessibility objects.

## Alternatives considered

### A. Eye gaze directly moves the pointer and exact click happens at the coordinate

Rejected as the general architecture. Commodity-webcam gaze is coarse; the eye-control research
already scopes it to pane/window targeting. Head-Pointer remains the continuous pointer path.

### B. Send the whole screen to a multimodal model

Rejected for the first implementation. It is slower, less deterministic, harder to test, and
materially expands privacy/dependency review when structured UI semantics may already answer the
question exactly.

### C. Put accessibility-tree logic directly in `gaze/deixis.py`

Rejected. Mouse, head pointer and explicit selection should be able to reuse the same grounding
layer. Gaze is one target source, not the semantic architecture.

### D. Let the planner resolve UI candidates itself

Rejected. A planner should receive a grounded/ambiguous target with provenance rather than silently
mixing geometry, accessibility traversal and side-effect planning.

## Consequences

### Positive

- webcam gaze can remain honestly coarse while still supporting exact semantic controls;
- the same downstream resolver can serve gaze, mouse, head pointer and explicit selection;
- exact accessibility actions can be preferred over synthetic pixel clicking;
- wrong-target behavior becomes measurable independently from speech recognition;
- privacy review is simpler because the first tier is screen-capture-free;
- pure candidate ranking becomes agent-friendly work with deterministic tests.

### Cost

- each desktop platform needs a semantic-source adapter and coverage study;
- accessibility trees are incomplete or stale in some apps;
- candidate ambiguity becomes an explicit state the UI/voice feedback must handle;
- confidence must carry both target uncertainty and semantic-resolution uncertainty.

## Validation before acceptance

Move this ADR from Proposed to Accepted only after:

1. `TargetSnapshot` / candidate / grounded-result contracts can be expressed without platform deps;
2. a pure resolver handles deterministic geometry + role/label fixtures;
3. ambiguous fixtures **abstain** rather than guess;
4. intent hints cannot select a spatially implausible candidate;
5. the existing gaze/deixis test suite remains unchanged/green when grounding is absent;
6. no screen capture, OCR, VLM or network path is introduced;
7. the evaluation plan defines wrong-target and abstention metrics.

## Delivery

See:

- `design/specs/eye-grounded-targets.md`;
- `design/eye-control/GROUNDED_INTERACTION_RESEARCH.md`;
- `design/eye-control/ROADMAP.md` cross-cutting track X8;
- EYE-GROUND-* tasks in `design/eye-control/AGENT_TASKS.md`.
