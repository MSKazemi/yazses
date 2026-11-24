# YazSes standards register — canonical cross-repository reference

**Status:** Draft research link; **not** a certification, claim of legal compliance, or authorization to change runtime defaults.  
**Updated:** 2026-11-21 (Europe/Rome).  
**Related project:** [YazSes](https://github.com/MSKazemi/yazses).  
**Canonical 98-reference standards register:** [MSKazemi/standards — projects/yazses.md](https://github.com/MSKazemi/standards/blob/main/projects/yazses.md).  
**Repository-wide standards index:** [MSKazemi/standards](https://github.com/MSKazemi/standards).

The shared register documents 98 **potentially relevant** standards, technical specifications, evaluation frameworks, and regulations across 10 categories: accessibility/usability, speech/audio, multilingual text, security/privacy, AI lifecycle, software quality, open-source supply chains, desktop and agent interoperability, optional XR/biosignal/medical pathways, and jurisdiction-specific legal considerations.

**This YazSes file is intentionally a pointer, not a second copy.** To correct an edition, validate a publisher link, or refine the relevance of a standard, update the [shared register](https://github.com/MSKazemi/standards/blob/main/projects/yazses.md) rather than allowing two catalogs to drift.

## YazSes-specific engineering evidence

- [AGENTS.md](https://github.com/MSKazemi/yazses/blob/main/AGENTS.md): mandatory offline/default-off, citation, consent and safe contribution rules.
- [ADR-011](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-011.md) and [ADR-019](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md): privacy and egress boundaries.
- [Privacy statement](https://github.com/MSKazemi/yazses/blob/main/docs/privacy-statement.md) and [threat model](https://github.com/MSKazemi/yazses/blob/main/design/threat-model.md): current documented data handling and threat assumptions.
- [Accessibility and throughput spec](https://github.com/MSKazemi/yazses/blob/main/design/accessibility-and-throughput-spec.md), [epic #790](https://github.com/MSKazemi/yazses/issues/790): user-facing accessibility testing and research.
- [Proposed ADR-033](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-033-reproducible-asr-evaluation-gate.md), [ASR epic #787](https://github.com/MSKazemi/yazses/issues/787): repeatable WER/CER/latency quality gates.
- [Proposed ADR-v2-150](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-v2-150-evaluation-evidence-and-research-consent.md): distinct engineering-QA and human-participant research evidence classes.
- [SBOM](https://github.com/MSKazemi/yazses/blob/main/sbom.cdx.json): existing CycloneDX evidence, which must be evaluated separately from the current version of the specification.

## Review protocol

Review applicable clauses per feature, record the exact edition and official catalogue source, document owner/evidence/tests/gaps, and link existing YazSes issues for any validated engineering work. Verify regulatory scope with qualified expertise where relevant. Existing implementation and tests are not a declaration of full conformance. No new external endpoints, telemetry, model downloads, medical claims, or confidential commercial information are authorized by this index.
