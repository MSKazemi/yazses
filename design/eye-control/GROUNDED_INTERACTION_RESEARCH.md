# Grounded interaction research and evaluation plan

**Programme:** Eye / camera control  
**Date:** 2026-09-22  
**Input research:** [`docs/research/grounded-multimodal-interaction.md`](../../docs/research/grounded-multimodal-interaction.md)  
**Proposed decision:** [ADR-v2-151](../adr/adr-v2-151-grounded-target-resolution.md)  
**Implementation spec:** [`eye-grounded-targets.md`](../specs/eye-grounded-targets.md)

This plan answers the questions that code generation cannot settle. The goal is to learn whether a
semantic grounding layer actually reduces the precision burden on webcam gaze and improves
hands-free task completion **without introducing a screenshot-first architecture**.

## Hypothesis

A coarse gaze/window target plus structured accessibility/application semantics and a spoken intent
can identify the intended desktop entity more reliably than coordinate-only webcam interaction.

The alternative outcomes are useful too:

- accessibility semantics may be absent in too many target apps;
- candidate density may remain too high for coarse gaze;
- intent hints may overfit/choose the wrong repeated label;
- Wayland may expose read semantics but not safe focus/action semantics.

Those are reasons to narrow the product claim, not to hide negative results.

## Research questions

### RQ-G1 — structured semantic coverage

Across representative desktop applications, what proportion of visible actionable controls is exposed
through AT-SPI, macOS Accessibility or Windows UI Automation with usable role, bounds and action
metadata?

**Measure:** eligible controls, exposed controls, controls with bounds, controls with action, stale
or duplicated nodes.

### RQ-G2 — candidate ambiguity under coarse gaze

Given an honest webcam-gaze error envelope, how many semantic candidates commonly fall inside the
plausible target region?

**Measure:** candidate count distribution per target; proportion of cases with exactly 0 / 1 / >1.

### RQ-G3 — value of voice intent hints

When >1 candidate is spatially plausible, how often do role/label hints from a command resolve the
correct candidate, and how often do they pull resolution toward the wrong repeated label?

Compare:

1. geometry/window only;
2. geometry + role;
3. geometry + role + label tokens.

### RQ-G4 — confidence and abstention

Can a deterministic policy abstain on ambiguous cases enough to reduce wrong-target actions without
making the feature useless?

Report the curve/trade-off between:

- grounded coverage;
- wrong-target rate;
- ambiguity/abstention rate.

Do not select a product default from one developer's machine.

### RQ-G5 — platform/session differences

How do X11, GNOME Wayland, KDE Wayland, macOS and Windows differ in:

- tree availability;
- bounds coordinate space;
- target/focus semantics;
- actionable operations;
- permission prompts;
- stale-tree behavior?

This extends, but does not replace, #418's Wayland target-semantics work.

### RQ-G6 — the real semantic gap

After structured sources are exhausted, which useful target classes remain unavailable?

Only this measured gap can justify later OCR/VLM research.

Examples may include custom canvases, remote desktops, video frames or applications that expose no
accessibility semantics. Record the category; do not jump directly to a vision model.

## Evaluation layers

### Layer A — pure deterministic fixtures

No hardware, no OS APIs.

Build synthetic layouts with:

- one obvious candidate;
- overlapping controls;
- repeated labels;
- nested roles;
- stale candidates;
- conflicting coordinate spaces;
- off-region label matches.

This proves resolver logic, not product utility.

### Layer B — recorded semantic traces

Capture **privacy-safe derived traces**, not screenshots.

A trace may contain:

- normalized/fixture window rectangle;
- target point/region;
- candidate role;
- candidate bounds;
- synthetic or redacted stable candidate ID;
- source kind;
- action names/categories;
- confidence/freshness;
- expected candidate ID.

Do not store real document/email text or window titles.

Where a real label is needed to evaluate label matching, replace it locally with an equivalent
synthetic token before saving the trace.

### Layer C — live platform coverage

Human tester selects pre-defined, non-sensitive targets in representative app classes.

Suggested classes:

- terminal;
- web browser with a controlled local test page;
- code editor;
- native settings/preferences app;
- file manager;
- simple form/document editor.

Use a local test page/document with invented text so reports are publishable.

### Layer D — end-to-end gaze + voice study

Only after resolver + semantic source are stable.

For each trial:

1. present a known target;
2. user looks at it naturally;
3. user gives a bounded command such as "focus this", "click this button", or "choose Save";
4. system either grounds, abstains or selects;
5. log derived outcome and timing;
6. no destructive real-world target is used.

## Metrics

Do not collapse everything into "accuracy".

Report:

- **target acquisition success** — coarse gaze/window target available;
- **semantic coverage** — usable candidate metadata available;
- **grounded coverage** — resolver returns a target;
- **top-1 correct rate** — correct among trials where resolver returns grounded;
- **wrong-target rate** — wrong candidate / all trials;
- **abstention rate** — ambiguous + unresolved / all trials;
- **candidate count** — before and after intent hint;
- **recovery count** — how often user must re-target/re-speak;
- **time-to-ground** — target snapshot -> resolved/abstained;
- **task completion time** in later end-to-end study.

For consequential actions, also report whether an incorrect target would have reached confirmation.
A test must never bypass confirmation merely to simplify measurement.

## Baselines

Compare against what YazSes can already do:

1. focused window only;
2. current gaze -> window routing;
3. current gaze + window-level deixis;
4. target + semantic grounding;
5. target + semantic grounding + intent hint.

The new layer earns its complexity only if it reduces wrong-target/recovery cost or enables a task
the window-only baseline cannot safely perform.

## Evidence gates

### Accept ADR-v2-151

Requires:

- deterministic resolver prototype passes Layer A;
- no evidence that intent hints can select spatially impossible candidates;
- abstention is explicit;
- no screen capture/egress requirement;
- platform research plan is executable.

### Start platform implementation

Requires:

- pure contract/resolver merged;
- one platform adapter can be isolated behind the Protocol;
- real tree behavior is measured rather than assumed from API documentation.

### Consider OCR/VLM fallback

Requires Layer C evidence showing a meaningful class of desired targets is unavailable from structured
sources.

Then write a **separate ADR**. Do not add OCR/VLM opportunistically inside a semantic-source PR.

### Promote exact-element grounding beyond experimental

Requires multi-environment evidence, an accessibility review, measured wrong-target + abstention rates,
and no unresolved high-impact risk in the programme risk register.

## Participant / contributor data

Hardware/accessibility studies should explain what is recorded before the trial.

Collect only what is needed:

- OS/session/version;
- app class/version if material;
- camera/tracker class;
- display scale/topology where relevant;
- derived success/error/latency metrics;
- voluntary free-text usability observations.

Do not request:

- face/video uploads;
- raw landmarks;
- typed private content;
- email/document text;
- disability/diagnosis information;
- identity/demographic data unless a later ethics-approved study has a concrete research reason.

## Jules / cloud-agent boundary

A cloud coding agent can implement:

- pure data contracts;
- resolver;
- synthetic fixtures;
- trace parser/evaluator;
- fake semantic-source adapters.

A cloud coding agent **cannot certify**:

- AT-SPI/AX/UIA behavior on a real user's desktop;
- Wayland compositor behavior;
- webcam gaze quality;
- accessibility comfort/fatigue;
- human intent or false-target experience.

Keep those as separate research/evidence tasks so a green PR cannot masquerade as a field result.
