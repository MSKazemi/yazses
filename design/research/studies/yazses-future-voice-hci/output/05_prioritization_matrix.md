---
id: prioritization-yazses-future-voice-hci
title: "YazSes v0.4 — Capability Prioritization Matrix"
type: prioritization_matrix
status: in-review
scenario: "yazses-future-voice-hci"
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-005, src-006, src-007, src-010, src-011]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "HUMAN REVIEW REQUIRED — confirm MVP selection (cap-001, cap-002, cap-003) before proceeding to PRD"
---

## Scoring Rubric

Each capability is scored on four dimensions, each 1–5:

| Dimension | 1 | 3 | 5 |
|-----------|---|---|---|
| **user_pain** | Nice-to-have; workaround exists and is adequate | Frequent friction; workaround is suboptimal | Blocking; no workaround; users disengage |
| **feasibility** | Very hard; requires novel research or unvalidated tech | Achievable with significant engineering; key questions remain | Straightforward; technology validated; integration is the main work |
| **novelty** | Widely available in competing tools | Differentiated but has partial alternatives | Unique; no competing tool offers this combination |
| **production_value** | Prototype-only; breaks under real use | Works reliably for primary use case; some edge cases remain | Works reliably across all documented scenarios; directly enables daily-driver use |

`total_score` = user_pain + feasibility + novelty + production_value (max: 20)

---

## Matrix

| cap_id | title | user_pain | feasibility | novelty | production_value | total_score | recommendation |
|--------|-------|:---------:|:-----------:|:-------:|:----------------:|:-----------:|---------------|
| cap-001 | Offline LLM Intent Routing Layer | 5 | 4 | 5 | 5 | **19** | MVP |
| cap-002 | Code-Aware Voice Dictation via LSP | 5 | 3 | 5 | 5 | **18** | MVP |
| cap-003 | EMG Silent Speech Backend | 4 | 4 | 5 | 4 | **17** | MVP |

All scores are tagged [HYPOTHESIS] unless noted otherwise — see CapabilityCard scoring rationale sections for evidence citations per dimension.

---

## MVP Selection Rationale

The three capabilities above are all recommended for the v0.4 MVP. This selection is justified by three converging reasons:

**Score separation.** All three capabilities score 17–19/20, placing them in a distinct cluster. No other gap from the gap analysis (gap-004 through gap-009) scores above 16/20 on the same rubric (estimated: gap-004 ≈ 15, gap-008 ≈ 13, gap-009 ≈ 11). The gap between cap-003 (17) and the next-best gap is sufficient to exclude lower-priority gaps without risk of under-delivery. [HYPOTHESIS]

**Strategic sequencing.** cap-001 (LLM routing) is a prerequisite for several future capabilities (gap-004 soft gaze, gap-005 gaming protocol) and an enhancement for cap-002 (LSP context consumed by the SLM prompt). Building cap-001 first maximises the value of subsequent capabilities. cap-003 (EMG backend) is fully independent of cap-001 and cap-002 and can be developed in parallel, making it a natural parallel workstream for a two-developer team. [EVIDENCE gap analysis §Sequencing Constraints]

**User population coverage.** cap-001 benefits all YazSes users. cap-002 specifically targets the developer cohort — the highest-value users who are most likely to become evangelists and contributors. cap-003 opens two new user populations (open-office workers, accessibility users) who currently have no viable voice daemon option. Together, the three capabilities address every documented persona from the research scope without overlap or redundancy. [HYPOTHESIS]

**Excluded from MVP:**

- **gap-004 (Soft Gaze via OS Accessibility):** Depends on cap-001; deferred to v0.4.1 after cap-001 is proven stable. Score estimate: ~15/20.
- **gap-005 (Gaming Voice Protocol):** Niche use case relative to developer and office personas; deferred to v0.5. Score estimate: ~14/20.
- **gap-006 (AAC Mode):** High moral value; depends on cap-003 being proven first; deferred to v0.5. Score estimate: ~14/20.
- **gap-007 (Dysarthric Speech / LoRA):** Engineering cost is high and total addressable user count is lower; deferred pending additional SoA research. Score estimate: ~12/20.
- **gap-008 (Ambient/Wake-Word Mode):** Independent but lower urgency; can be added as a NEXT release item. Score estimate: ~13/20.
- **gap-009 (Voice Error Correction Protocol):** Low delta over existing rollback mechanism; DEFER. Score estimate: ~10/20.

---

*Study: [[yazses-future-voice-hci/input/research_scope|yazses-future-voice-hci]]*
