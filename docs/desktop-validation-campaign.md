---
title: Desktop reliability and first-user validation campaign
description: Evidence-led plan for validating YazSes desktop releases before broad adoption claims.
---

# Desktop reliability and first-user validation campaign

**Proposed 29 October 2026.** This is a coordination plan, **not** a declaration that its gates have passed. The current stable release is **v2.46.0**; always record the actual release under test. It implements the existing [ADR-030 direction](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-030-agent-era-direction.md) and does not replace the authoritative [release evidence standard](contribute/validation.md) or [validation matrix](validation-matrix.md).

## Scope and freeze

Prioritize a reliable desktop hold-to-talk path (Linux first, Windows/macOS preview) and independently observed first use. Freeze *new* desktop capability waves, not defect fixes, release tooling, security maintenance, already-planned integrations, or Android's separately managed M1 work. The opt-in camera, eye, EMG and HCI/Hugging Face research tracks are not implied to be production-ready by this campaign.

**CI success is not human hardware validation.** The matrix retains the precise result wording and version-specific citations; failures stay visible until a later hardware retest. Do not promote preview claims, cross-platform support, or hands-free defaults from a green test suite.

## Proposed execution order (four weeks, dependent on evidence)

| Window | Outcome | Existing tracking and evidence | Pass condition |
|---|---|---|---|
| Week 1: correctness | No unintended insertion from a silent hold/eye gesture | [#598](https://github.com/MSKazemi/yazses/issues/598) | Controlled no-speech and live-model regressions across activation sources and streaming/batch; real quiet/whispered speech is not indiscriminately dropped |
| Week 1: release paths | Safe updates, protected merges and truthful distribution status | [Windows installer PR #666](https://github.com/MSKazemi/yazses/pull/666), [branch gate #462](https://github.com/MSKazemi/yazses/issues/462), [channel drift workflow](https://github.com/MSKazemi/yazses/blob/main/.github/workflows/channel-drift.yml) | Reviewer validates the installer upgrade; owner approves GitHub ruleset changes; current channel state independently checked |
| Week 2: hardware | Versioned end-to-end desktop evidence | [matrix](validation-matrix.md), [Linux X11 #642](https://github.com/MSKazemi/yazses/issues/642), [Wayland #643](https://github.com/MSKazemi/yazses/issues/643), [Mac #562](https://github.com/MSKazemi/yazses/issues/562), [cross-platform #504](https://github.com/MSKazemi/yazses/issues/504) | At least one complete *Verified (HW)* report per claimed primary desktop path; explicitly retain any unavailable or failed path as preview/blocked |
| Week 3: onboarding | Independent first installation and first successful dictation, or a clearly diagnosed blocker | [first-use community QA #714](https://github.com/MSKazemi/yazses/issues/714) and [test guide](contribute/validation.md) | At least 5 voluntary *independent* first-use reports spanning at least two OS families as an initial recruitment target; this is a **target**, not observed data |
| Week 4: launch decision | Evidence-backed go / limited-preview / no-go decision | This campaign, [matrix](validation-matrix.md), [privacy statement](privacy-statement.md), [media library draft PR #688](https://github.com/MSKazemi/yazses/pull/688) | All critical correctness failures resolved or explicitly block expansion; demo claims cite actual tested configurations; no raw-user speech in media |

These weeks are **planning windows, not promises or automatically scheduled work**. There is no need to ship an additional release solely to meet a calendar date.

## Release and adoption gate

For a broader public launch, a maintainer must explicitly review and record:

- [ ] **Safety:** #598's silent-activation failure is fixed with deterministic tests and a real-model smoke test. No partial streaming text escapes the same guard. Speech-presence confidence and false rejection of quiet/atypical speech are considered, not assumed.
- [ ] **Primary platforms:** real humans exercised install → permissions → activation → capture → decode → injection into two app classes → restart on the *named* version; update path retested where relevant. Separate X11, GNOME Wayland, KDE Wayland, Windows and Apple silicon Mac paths. A successful test on one does not certify another.
- [ ] **Blocking regressions:** link each known failing device report to a retest (particularly macOS #562/#578). “Fix merged” is not “fixed on the reporter's hardware.”
- [ ] **Protection and provenance:** branch rules reviewed per #462; release channels and unsigned installer warnings described accurately. Do not change GitHub admin settings by implication from a document.
- [ ] **First use:** #714 yields independent first-user reports; maintain a short list of first blockers and corrections. Do not collect private transcripts, audio, identifying system data or automatically instrument users.
- [ ] **Public claims:** compare the README, platform support page and product demonstrations with the validation matrix. Keep macOS/Windows in *preview* while their corresponding evidence is incomplete.
- [ ] **Launch decision:** record **GO** (precise tested configurations), **LIMITED PREVIEW** (known gaps stated), or **NO-GO** (remaining correctness/privacy/blocking failures), with dated links and an owner.

Do not start or claim human-subjects research from ordinary GitHub QA. Any separate research recruitment, personal data retention or paper-intended study follows its own consent and ethics gate.

## Minimal, privacy-safe observation metrics

Track counts only from voluntarily submitted reports; never invent baseline numbers.

| Metric | Numerator / denominator | Interpretation |
|---|---|---|
| First-dictation success | First-time testers reporting success / first-time testers who attempted it | Self-selected volunteer outcome, **not population adoption** |
| First-use blocker category | Counts by install, launch/permissions, capture, activation, decode, injection, restart | Prioritize earliest repeated blocker |
| Evidence coverage | Primary OS/session pathways with complete current-version HW records / identified primary pathways | This is **validation coverage**, not a global support percentage |
| Unintended silent insertion | Unwanted inserts / silent test activations | Track alongside false rejection of genuine quiet speech |
| Upgrade regression | Successful checked upgrade paths / attempted checked upgrades | Distinguish install channel and OS |

Publish aggregates only when meaningful, label sample size, and preserve negative reports. Avoid interpreting a missing response as success. For actual user research, use a separate protocol.

## Parallel work that does **not** block desktop maintenance

Android M1 remains tracked by [#81](https://github.com/MSKazemi/yazses/issues/81), especially the [engine #87](https://github.com/MSKazemi/yazses/issues/87) and [IME #89](https://github.com/MSKazemi/yazses/issues/89). Proposed agent handoffs ([#637](https://github.com/MSKazemi/yazses/issues/637)–[#639](https://github.com/MSKazemi/yazses/issues/639)) and HCI research should not override the safety and hardware-truth gates. Review existing draft PRs rather than merging them automatically.

## Tracking etiquette

Keep implementation details and hardware test reports in their existing issues, not in a duplicate epic. The [QA matrix issue #388](https://github.com/MSKazemi/yazses/issues/388) coordinates verified evidence, [#387](https://github.com/MSKazemi/yazses/issues/387) maintains the evidence policy, and #714 collects the open-ended first-use feedback. No contributor is assigned without agreeing to the role. This document changes **planning only**, no code, account permissions, CI, release or published claims.
