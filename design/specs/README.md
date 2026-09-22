# YazSes v2 Feature Specs

Engineering design specs (ADR house style) for the 10-feature v2 set. Each spec is the
implementation-ready companion to a Vision Card, and is grounded in the feasibility
evidence of the 2026-06-14 ten-feature SoA dossier. The cards and the dossier are
exploratory idea notes kept internal (see [`../README.md`](../README.md)); everything
load-bearing from them is restated in the specs themselves, so these documents stand
alone.

Pipeline that produced these: `/vision-spark` (10 seeds) → `/vision-scout` (cited SoA dossier,
tier-graded) → per-feature `/vision-card` + `/vision-sharpen` + this spec (10 parallel agents).

| # | Feature | Spec | Vision Card | Verdict | Build tier |
|---|---|---|---|---|---|
| 1 | Cocktail Filter | [cocktail-filter.md](cocktail-filter.md) | card *(internal)* | ready-now (gate) | **A** |
| 2 | Voiceprint Mind | [voiceprint-mind.md](voiceprint-mind.md) | card *(internal)* | ready-now (online=partial) | **A** |
| 3 | Say-Macro | [say-macro.md](say-macro.md) | card *(internal)* | ready-now | **A** |
| 4 | Read-Back Loop | [read-back-loop.md](read-back-loop.md) | card *(internal)* | ready-now | **A** |
| 5 | Prosody Ink | [prosody-ink.md](prosody-ink.md) | card *(internal)* | partial (ship ¶+bold) | **B** |
| 6 | Mid-Thought Undo | [mid-thought-undo.md](mid-thought-undo.md) | card *(internal)* | partial (ship templates) | **B** |
| 7 | Punch-In | [punch-in.md](punch-in.md) | card *(internal)* | partial (respeak→candidates→confirm) | **B** |
| 8 | Polyglot Switch | [polyglot-switch.md](polyglot-switch.md) | card *(internal)* | partial (per-pair) | **B** |
| 9 | Glance-Type | [glance-type.md](glance-type.md) | card *(internal)* | too-early (coarse look-to-pane) | **C** |
| 10 | Ghost Ahead | [ghost-ahead.md](ghost-ahead.md) | card *(internal)* | too-early → pivot to endpoint anticipation | **C** |

**Tiers:** A = ship-now, high evidence, reuses existing infra · B = ship the safe sub-feature, gate the
hard one · C = re-scope or pivot before building.

All specs follow ADR-011 (off by default, fully local/offline) and the optional-extra dependency
pattern (deps imported only when the feature is enabled).


## Eye / camera accessibility programme (2026-09)

These specs are the implementation-ready companions to the eye-control ADRs and
[`design/eye-control/`](../eye-control/). They use the same privacy/offline rules as the original
v2 specs but are tracked as a subsystem programme rather than as the original ten-feature set.

| Area | Spec | Status | Primary issues |
|---|---|---|---|
| Shared camera perception | [eye-shared-perception.md](eye-shared-perception.md) | Proposed | #393–#396 |
| Pointer output boundary | [eye-pointer-output.md](eye-pointer-output.md) | Proposed | #400–#403 |
| Head-Pointer runtime | [eye-head-pointer-runtime.md](eye-head-pointer-runtime.md) | Proposed | #404–#405 |
| Face-Gesture Switch | [eye-face-switch.md](eye-face-switch.md) | Proposed | #406–#409 |
| Implicit gaze calibration | [eye-implicit-calibration.md](eye-implicit-calibration.md) | Proposed | #397–#399 |
| Hands-free composition | [eye-handsfree-bundle.md](eye-handsfree-bundle.md) | Proposed | #410 + cross-cutting safety/ops issues |

An issue is `agent-ready` only when the relevant spec and prerequisite ADR are sufficient to
implement the task without inventing a new policy.
