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
