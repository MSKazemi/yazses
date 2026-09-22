# ADR-v2-140 — Community hardware QA and human research are separate evidence classes

**Status:** Proposed (2026-09-22)  
**Context links:** [[adr-011]], [[adr-v2-135-shared-camera-perception]], [[adr-v2-138-hands-free-composition]], [[adr-v2-139-gaze-calibration-coordinate-space]]

## Context

YazSes needs real-world eye/camera evidence from:
- automated CI;
- synthetic traces;
- contributors running hardware tests on different computers/operating systems;
- repeated sessions;
- future controlled human-participant studies.

The measurements can look superficially similar. A public tester might report:
"40 gaze trials, 35 correct, 2 wrong, 3 fallback." A research participant may produce the same four
numbers.

That does **not** make the two data sources interchangeable.

A public GitHub issue:
- is visible under a GitHub identity;
- was primarily submitted for engineering QA;
- may not contain the information/consent process required for research;
- may persist in mirrors/archives;
- is not an appropriate place to store consent records/contact mappings.

Retroactively treating a public bug/test report as a research participant record creates a purpose,
privacy and ethics mismatch.

At the same time, requiring formal study enrollment for every volunteer hardware smoke test would make
ordinary open-source validation unnecessarily difficult.

## Decision

YazSes uses explicit evidence classes and a machine-readable `study_mode`.

Required modes:

- `ci` — automated software/platform evidence;
- `synthetic` — generated/replayed non-human traces;
- `community_qa` — human-operated engineering validation submitted outside a research protocol;
- `research` — data collected under a named/versioned research protocol after the applicable
  ethics/review determination and participant information/consent.

### Rule 1 — Community QA is not research by default

A public GitHub report is `community_qa`.

It may be used to:
- reproduce bugs;
- validate hardware/OS support;
- identify failure modes;
- prioritize engineering;
- describe community testing coverage in a non-participant engineering sense.

It is not silently inserted into participant-level paper analyses.

### Rule 2 — Research mode requires a protocol identifier

A result may be `research` only when it carries a named/versioned protocol ID and was collected
under that protocol.

Changing the JSON enum after collection is not a consent mechanism.

### Rule 3 — Interested community testers enroll separately

A public tester may say "I am willing to be contacted about future research."

That does not change the existing report from QA to research. If the tester later participates, a new
research session is collected under the research protocol.

### Rule 4 — Raw face/screen/audio data is not part of standard community QA

Default community testing shares derived metrics/provenance only.

The standard report must not request:
- raw webcam frames/video;
- detailed face mesh/eye imagery;
- private desktop recordings/screenshots;
- private dictated text/audio;
- diagnosis/medical records;
- device serials/secrets.

A future study that genuinely requires raw sensor data needs a separate decision/protocol/storage and
consent plan.

### Rule 5 — Public issue identity never enters the research analysis dataset

Research uses random participant/session IDs.

If a contact-to-participant mapping is required, it is private and separate from measurements.
GitHub username/email is not a paper analysis identifier.

### Rule 6 — Paper evidence declares its source class

Tables/analysis pipelines know whether inputs are:
- CI;
- synthetic;
- community QA;
- research.

Research analysis refuses community QA rows by default.

### Rule 7 — Human research is a pre-collection gate

Before collecting publication-intended human-participant data:
- the responsible research environment/institution determines the applicable ethics/review process;
- the protocol, measures, exclusions and analysis are versioned;
- participant information/consent is finalized;
- data sharing/retention/withdrawal are defined.

This happens before recruitment/data collection, not retroactively while writing the paper.

## Alternatives considered

### Treat every hardware report as consent to use the numbers in a paper

Rejected. Contribution to an open-source QA issue and participation in research are different
purposes and expectations.

### Require research enrollment for every community hardware test

Rejected. It would make ordinary engineering validation too difficult and unnecessarily collect
participant-process data.

### Allow an analysis script to choose how to classify old reports

Rejected. Source class is a fact about how/why data was collected and must travel with the artifact.

### Collect raw video "just in case" for future analysis

Rejected. It increases privacy/re-identification risk and storage burden without being necessary for
the current reliability metrics.

## Consequences

Positive:
- non-experts can contribute hardware evidence safely;
- paper data has a defensible provenance/consent boundary;
- analysis scripts can prevent accidental source mixing;
- the project does not need to centralize raw face data;
- withdrawal/research records remain separate from public issue history.

Costs:
- some community QA cannot be repurposed later as participant evidence;
- a future paper requires a separate study/recruitment process;
- result schema and tooling must carry `study_mode` + protocol metadata.

## Implementation

See:
- `design/eye-control/EVALUATION.md`;
- `design/eye-control/METRICS.md`;
- `design/eye-control/DATA_SHARING.md`;
- `design/eye-control/PAPER_EVIDENCE.md`;
- #421–#427;
- public hardware slots #428–#437.

