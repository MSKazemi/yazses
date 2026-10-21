# YazSes v2 Feature Specs

Engineering design specs (ADR house style) for the 10-feature v2 set. Each spec is the
implementation-ready companion to a Vision Card, and is grounded in the feasibility
evidence of the 2026-06-14 ten-feature SoA dossier. The cards and the dossier are
exploratory idea notes kept internal (see [`../README.md`](../README.md)); everything
load-bearing from them is restated in the specs themselves, so these documents stand
alone.

Pipeline that produced these: `/vision-spark` (10 seeds) → `/vision-scout` (cited SoA dossier,
tier-graded) → per-feature `/vision-card` + `/vision-sharpen` + this spec (10 parallel agents).

| # | Feature | Spec | Vision Card | Verdict | Build tier | Delivery status (2026-10-21) |
|---|---|---|---|---|---|---|
| 1 | Cocktail Filter | [cocktail-filter.md](cocktail-filter.md) | card *(internal)* | ready-now (gate) | **A** | P1 gate wired but **experimental** — over-rejects the user's own voice; P2 suppression **blocked** on an open model |
| 2 | Voiceprint Mind | [voiceprint-mind.md](voiceprint-mind.md) | card *(internal)* | ready-now (online=partial) | **A** | P1 biasing **shipped**; LoRA layer **deferred**, not built |
| 3 | Say-Macro | [say-macro.md](say-macro.md) | card *(internal)* | ready-now | **A** | P1 text/snippet macros **shipped**; action chains **deferred** |
| 4 | Read-Back Loop | [read-back-loop.md](read-back-loop.md) | card *(internal)* | ready-now | **A** | P1 read-back **shipped**; P2 confirm loop not built |
| 5 | Prosody Ink | [prosody-ink.md](prosody-ink.md) | card *(internal)* | partial (ship ¶+bold) | **B** | pause→¶ **shipped**; bold behind the `prosody` extra, gate unmeasured; pitch→? not built |
| 6 | Mid-Thought Undo | [mid-thought-undo.md](mid-thought-undo.md) | card *(internal)* | partial (ship templates) | **B** | "scratch that" **shipped** (on by default); open-ended rewrite not built |
| 7 | Punch-In | [punch-in.md](punch-in.md) | card *(internal)* | partial (respeak→candidates→confirm) | **B** | `yazses punch-in` **shipped**, narrower than designed; voice trigger and confirm UX not built |
| 8 | Polyglot Switch | [polyglot-switch.md](polyglot-switch.md) | card *(internal)* | partial (per-pair) | **B** | scaffolding only; P1 **blocked** on an evaluation set ([#518](https://github.com/MSKazemi/yazses/issues/518), [#519](https://github.com/MSKazemi/yazses/issues/519)) |
| 9 | Glance-Type | [glance-type.md](glance-type.md) | card *(internal)* | too-early (coarse look-to-pane) | **C** | coarse look-to-pane **shipped, experimental**, X11 only; caret precision **deferred** |
| 10 | Ghost Ahead | [ghost-ahead.md](ghost-ahead.md) | card *(internal)* | too-early → pivot to endpoint anticipation | **C** | pre-warm **shipped** (streaming path only); speculative finalize not built; content prediction **rejected** |

**Tiers:** A = ship-now, high evidence, reuses existing infra · B = ship the safe sub-feature, gate the
hard one · C = re-scope or pivot before building.

Each of these specs, and the diarized-import spec below, carries a dated **Delivery status
(current)** section under its header. It separates shipped, partial, blocked, deferred and
rejected phases and names the tracker for any remainder; the column above summarises it. The
rest of each spec is the original design, kept as written.

All specs follow ADR-011 (off by default, fully local/offline) and the optional-extra dependency
pattern (deps imported only when the feature is enabled).

## Additional implementation specs

These specs are not part of the original ten-feature v2 set above; they document later cross-cutting work.

| Feature | Spec | Status |
|---|---|---|
| Diarized recording import (`yazses transcribe`) | [diarized-recording-import.md](diarized-recording-import.md) | Phases 1–3 shipped (2026-10-21 check) — file transcription, `--diarize`, voiceprint naming. Phase 4 deferred: forced alignment, Parakeet for files, and cloud escalation, which stays design-only ([ADR-v2-126](../adr/adr-v2-126-cloud-escalation.md)). |
| First-class Mandarin language support | [chinese-language-support.md](chinese-language-support.md) | Proposed — transactional English/Mandarin profiles, Simplified/Traditional output, localized command grammar, and measured release gate. |
| Feature add-on packs (frozen installs) | [feature-addon-packs.md](feature-addon-packs.md) | Proposed — per-build add-on packs fetched on enable, verified against an index built into the installer; decision in [ADR-028](../adr/adr-028-feature-addon-packs.md). |

The companion design package is [`../chinese/`](../chinese/).

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
| Grounded semantic targets | [eye-grounded-targets.md](eye-grounded-targets.md) | Proposed | #441–#445 |
| Gaze-target semantics on Wayland | [eye-wayland-gaze-target.md](eye-wayland-gaze-target.md) | Accepted (desk research; live GNOME/KDE check owed) | #418 |

An issue is `agent-ready` only when the relevant spec and prerequisite ADR are sufficient to
implement the task without inventing a new policy.
