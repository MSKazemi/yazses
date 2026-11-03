# Cloud-code handoff — ThinkGear qualification (start with issue #827, then #828)

**Prepared 2026-11-03. Status: READY FOR MAINTAINER REVIEW, not authorized for runtime implementation.**  
**Epic:** [#826](https://github.com/MSKazemi/yazses/issues/826)  
**Research branch:** `research/thinkgear-first-device-2026-11-03`  
**Roadmap:** [dependency and evidence gates](2026-11-03-first-device-roadmap.md)  
**Detailed technical contract:** [spec-thinkgear-first-device-qualification](../specs/thinkgear-hardware-qualification.md)  
**ADR:** [ADR-v2-154 — proposed](../adr/adr-v2-154-thinkgear-transport-safety.md).

## Explicit guardrails for a coding agent

1. Read the CURRENT public `AGENTS.md` and `.github/CI_POLICY.md` before changing code/CI, and compare `main` against the research-branch proposal. Do not make up prior CI results or real-hardware measurements.
2. Do not open a PR until the human author has reviewed its diff. Create an appropriately named implementation branch **after** the reviewer decides #827. Preserve main until reviewed.
3. Do not access, name, copy or expose any private GitHub tree, emails, contacts, devices' owner identifiers or confidential research files in the code branch. Technical code and synthetic fixtures only.
4. Avoid new dependencies, any network primitive, telemetry, EEG thought/health interpretation, product endorsement, default-on settings, public CLI/config/IPC changes, extra agent capabilities, paid resources or auto-downloading models.
5. Do not retune blink thresholds based on synthetic or first scored data; do not turn unknown contact into an acceptable event.
6. Don't close/mark other issues done until verified implementation and tests are evidenced. Report blockers, failures and remaining untested hardware openly.

## Copy-paste starter task (only AFTER issue #827's decision)

> Work in the **public MSKazemi/yazses repository**, with #826 as epic. First read AGENTS.md, ADR-030, ADR-v2-152/153, the reviewed ADR-v2-154 and the ThinkGear qualification spec. Re-inspect main for overlapping changes. Work **only on #828**: implement a stdlib-only, injected-clock ThinkGear protocol-health state machine and per-read block health snapshots using the existing ThinkGearParser/ThinkGearSource. Treat unknown, stale or any nonzero POOR_SIGNAL, all parser-rejected packets and intra-read 0/200/0 contamination as untrusted. Never fabricate lost-sample timestamps or turn vendor attention/meditation/blink-strength scores into events. No new public config/CLI/IPC. Add independent fake-serial and fake-clock tests TG-01..TG-11. Run targeted and whole tests, Ruff and mypy; clearly distinguish output observed from not run. Produce a minimal human-reviewable diff and **do not open PR until the author has read it**. Do not touch runtime guard composition; that is #829 after #828.

### After #828 has a reviewed merge

**#829:** Build the smallest ThinkGear source-specific health veto over the existing IntegrityGuard/IntegrityGate/quality pipeline. Preserve provenance across sanitized block copies. Prevent double-blinks crossing faults and preserve one-release watchdog semantics. Regression-test all non-ThinkGear sources. **Do not** alter field-test in this PR.

**#830:** Refactor daemon/monitor/field-test to use the exact same guarded-source construction. Drive identical synthetic packet traces and compare admission, quality reasons and usable-exposure/voiding results. No raw personal data or new CLI flags.

**#831:** Add privacy-safe on-device reasons, docs and test vectors. The Linux Bluetooth serial path is a *hypothesis* until a physical device demonstrates it, so publish a qualified investigation guide rather than a "works with BrainLink" claim.

**#832:** STOP for human hardware operation. Do not claim you paired, wore, measured or tested a unit remotely. The human may share reviewed aggregate counts for subsequent report review.

**#833:** Review results against existing ADR-v2-152 statistical gates. One headset/volunteer is feasibility only; do not move ADR to Accepted or remove 'experimental' without the broader evidence and explicit decision.

## Handoff artifact checklist

- [ ] Reviewed design decision #827, with accepted/revised constants and precise scope.
- [ ] One *code concern per PR* and linked issue #828, then #829, then #830, then #831.
- [ ] Synthetic trace fixtures + TG-01..18 regression suite (each issue owns its cases).
- [ ] No untrusted activation; unchanged behavior on non-ThinkGear sources; default-off verified.
- [ ] Explicit test results for `uv run python -m pytest tests/ -v`, `uv run ruff check src tests scripts`, `uv run mypy src`.
- [ ] Run `scripts/gen-docs.py` and `scripts/gen-adr-index.py` if affected, rather than editing generated files.
- [ ] Deferred real-device and multi-user gates remain open; no fabricated results or timelines.
- [ ] Link issues as **native sub-issues** in GitHub UI to comply with existing milestone policy.

**Important:** This file is an engineering handoff, not instructions to contact any company, pay for hardware, publish personally identifiable biosignal data, or claim device certification.
