# Spec: Grounded Targets — coarse pointing to exact semantic UI entities

| Field | Value |
|---|---|
| **ID** | spec-eye-grounded-targets |
| **Status** | Proposed |
| **Date** | 2026-09-22 |
| **Programme** | `design/eye-control/` |
| **Decision** | ADR-v2-151 (Proposed) |
| **Research** | `docs/research/grounded-multimodal-interaction.md` |
| **Related** | ADR-v2-010 gaze routing; ADR-v2-007 Voice Pilot; ADR-019 egress; ADR-021 error cost |

## Goal

Allow a coarse target signal such as webcam gaze to be refined into an **exact structured UI
entity** without pretending the sensor itself is pixel-precise.

The first delivery is deliberately semantic-first and screen-capture-free.

## Non-goals

This spec does **not**:

- replace Head-Pointer or Voice Mouse Grid;
- add caret-level webcam gaze;
- add OCR;
- capture screenshots;
- add a local or cloud VLM;
- execute arbitrary actions;
- make accessibility APIs available where an OS/app does not expose them;
- change current Glance-Type behavior before an explicit integration phase;
- decide destructive-action policy.

## Architecture

```text
gaze / mouse / head / selection
          |
     TargetSnapshot
          |
          v
  SemanticSource Protocol
 (AT-SPI / AX / UIA / app)
          |
   SemanticCandidate[]
          |
          v
  Pure TargetResolver  <--- optional parsed intent hint
          |
   +------+------+
   |             |
Grounded      Ambiguous /
Target        Unresolved
   |
   v
intent / planner / safety / executor
```

## Data contracts

Exact names are implementation choices; semantics are binding.

### `TargetSnapshot`

Required concepts:

- source modality;
- monotonic timestamp;
- explicit source confidence;
- point and/or rectangular target region;
- target window when already known;
- coordinate-space identifier/version when geometry is present.

No raw sensor/frame object is allowed.

### `SemanticCandidate`

Required concepts:

- stable-for-snapshot entity identifier;
- source/provenance;
- role/type;
- bounds when available;
- optional human-visible label/value;
- declared semantic actions when the platform exposes them;
- freshness/source confidence.

Do not store a live platform object in this value.

### `GroundingEvidence`

A small enum/value record explaining why the resolver preferred a candidate, for example:

- `inside_target_region`;
- `nearest_to_target_point`;
- `window_match`;
- `role_match`;
- `label_hint_match`;
- `exact_accessibility_focus`;
- `source_quality`.

The evidence record exists for debugging/tests and confidence policy. It must not become a dump of
private UI text.

### Result type

Resolution is tri-state:

- **grounded** — one candidate satisfies policy;
- **ambiguous** — multiple plausible candidates remain;
- **unresolved** — no usable candidate.

Ambiguous and unresolved are successful safety outcomes, not exceptions.

## Pure resolver policy

The first resolver is deterministic.

### Step 1 — reject stale/invalid inputs

Reject or abstain when:

- target timestamp exceeds configured freshness budget;
- target confidence is below caller policy;
- candidate geometry is in a different/unconvertible coordinate space;
- candidate snapshot is stale.

Product defaults for freshness/ambiguity thresholds must be evidence-driven; unit tests inject a
`ResolutionPolicy` explicitly.

### Step 2 — enforce the coarse spatial envelope

When geometry exists, candidate must be spatially plausible:

- bounds contain the target point; or
- bounds intersect the explicit target region; or
- caller policy defines a bounded distance expansion for coarse gaze uncertainty.

A label match alone may not import a candidate from elsewhere in the window.

### Step 3 — rank semantic evidence

Within the plausible set, score/order using deterministic evidence such as:

- exact focused/selected semantic entity when it lies in the target envelope;
- accessibility/app source reliability;
- role compatibility with parsed intent;
- label/name hint compatibility;
- geometric closeness;
- candidate confidence/freshness.

The first implementation must expose score components/evidence in tests rather than burying them in
one opaque number.

### Step 4 — ambiguity gate

If the top result is not sufficiently separated from another plausible candidate under the injected
policy, return ambiguous.

Do not break ties by arbitrary traversal order.

## Intent hints

The resolver may receive a small, already-parsed hint:

```python
IntentHint(
    verb="click",
    role="button",
    label_tokens=("save",),
)
```

This is **not** an LLM prompt. It should come from the existing command grammar/planner layer.

Rules:

- hint is optional;
- no hint -> spatial/semantic resolution still works;
- role/label can narrow plausible candidates;
- hint cannot override the target envelope;
- destructive/non-destructive policy is not part of this object.

## Semantic source Protocol

Conceptual shape:

```python
class SemanticSource(Protocol):
    def snapshot(
        self,
        *,
        window_id: str | None,
        region: Rect | None,
    ) -> Sequence[SemanticCandidate]: ...
```

Platform adapters:

- Linux: AT-SPI where available;
- macOS: Accessibility APIs;
- Windows: UI Automation;
- application-native providers may later implement the same protocol.

The protocol module must remain dependency-free.

## Integration phases

### P0 — contracts only

Create pure value types and validation. No runtime wiring.

**Issue:** EYE-GROUND-001.

### P1 — pure resolver

Geometry + semantic candidate ranking, ambiguity/abstention, intent hints, evidence output.

**Issue:** EYE-GROUND-002.

### P2 — existing gaze/deixis integration seam

Feed the current window-level gaze snapshot into the resolver when a fake/available semantic source
is provided. Absence preserves current behavior exactly.

**Issue:** EYE-GROUND-003.

### P3 — semantic-source coverage research

Measure what AT-SPI / macOS Accessibility / UIA can actually expose across representative apps and
desktop sessions before promising cross-platform exact-element grounding.

**Issue:** EYE-GROUND-004.

### P4 — evaluation harness

Replay target/candidate/intent fixtures and report:

- grounded top-1 correct;
- wrong target;
- ambiguous/abstained;
- unresolved;
- target-source failure;
- semantic-source failure;
- resolution time for live adapter benchmarks.

**Issue:** EYE-GROUND-005.

### Deferred — OCR/VLM fallback

Only consider after P3 quantifies the **semantic gap**: cases where the user refers to something
useful that no structured source exposes.

Any OCR/VLM fallback needs a separate ADR covering:

- screenshot/region capture permission;
- local-only vs egress;
- dependency/download budget;
- CPU/latency;
- data retention;
- confidence and confirmation policy.

## Privacy

P0–P4 add no runtime network path and require no screenshot.

Field/evaluation reports should prefer aggregate data:

- OS/session/app class;
- count of semantic nodes;
- role distribution;
- target candidate count;
- grounded/wrong/ambiguous/unresolved outcome;
- latency.

Do not publish window titles, document text, email content, screenshots or accessibility labels that
contain private content. Synthetic fixtures should use invented labels.

## Failure behavior

- no semantic source -> preserve current window-level behavior;
- source exception -> isolate/report; do not break ordinary dictation;
- stale source -> unresolved;
- ambiguous -> ask/fallback at a later UX layer, never guess;
- low gaze confidence -> existing focused-window fallback;
- destructive operation -> existing safety policy remains downstream.

## Test plan

### Pure unit tests

No optional dependencies:

- point inside one candidate;
- overlapping candidates -> ambiguous without additional evidence;
- role hint resolves plausible candidates;
- label hint resolves plausible candidates;
- matching label outside target envelope stays rejected;
- stale target/source abstains;
- coordinate-space mismatch abstains;
- traversal order does not change result;
- evidence/provenance retained;
- empty candidate set -> unresolved.

### Integration tests

With fake semantic source:

- existing gaze target + one element -> grounded;
- semantic source unavailable -> old gaze/deixis behavior unchanged;
- low-confidence gaze never gains confidence from semantics;
- resolver never executes actions;
- destructive confirm tests remain downstream and unchanged.

### Platform adapter tests

Platform libraries are faked/isolated. Ordinary CI must not require a desktop session.

Real platform claims belong to EYE-GROUND-004 evidence.

## Definition of implementation-ready

A child issue may receive `agent-ready` only when:

- ADR-v2-151 is accepted or the issue is explicitly limited to non-binding research/prototype work;
- prerequisite issue is merged;
- issue names allowed files/seams;
- exact narrow test command is present;
- no unresolved platform/product policy is delegated to the implementer.

Do **not** apply the execution-triggering `jules` label merely to classify readiness.
