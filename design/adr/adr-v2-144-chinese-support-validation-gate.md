# ADR-v2-144 — “Chinese supported” is a measured release claim, not a config capability

**Status:** Proposed (2026-09-20)  
**Context:** Existing Chinese how-to explicitly disclaims product support; small ASCEND probe; cross-platform injection; community validation.

## Context

The repository can already be manually configured to decode Mandarin, and it contains a useful 20-utterance ASCEND measurement demonstrating that Han-script normalization matters.

That establishes feasibility, not broad support.

“Supported” for YazSes means more than “the model emitted Chinese once.” It includes:

- repeatable recognition quality;
- interactive latency;
- script correctness;
- command behavior;
- file/meeting paths;
- Unicode injection;
- offline model availability;
- Linux/macOS/Windows behavior;
- understandable diagnostics;
- a native-speaker usability check.

Changing the documentation claim before these are measured would turn architecture capability into an unsupported promise.

## Decision

Keep Chinese first-class support behind an explicit validation gate.

Implementation may merge incrementally, but user-facing documentation may only replace the current “not claimed / usable but rough” language after the gate is satisfied and evidence is committed.

### Required gate categories

1. **Recognition benchmark**
   - more than one Mandarin speech condition/corpus;
   - exact corpus/split/license/normalization recorded;
   - CER plus insertion/deletion/substitution breakdown;
   - raw-script and normalized-script scores.

2. **Performance**
   - reference CPU identified;
   - p50/p95 RTF and release-to-text latency;
   - peak RSS and model load time;
   - no hidden online call after cache warm-up.

3. **Functional paths**
   - live dictation;
   - streaming (where enabled);
   - file transcription;
   - word timestamps/subtitles;
   - meeting transcription;
   - language switch and rollback.

4. **Commands**
   - Chinese deterministic grammar precision/recall on reviewed phrase fixtures;
   - unknown prose must remain dictation;
   - command actions match English semantic contracts.

5. **Injection**
   - Linux X11;
   - Linux Wayland;
   - macOS;
   - Windows;
   - fallback documented for any backend that cannot guarantee Han injection.

6. **Native-speaker review**
   - Simplified workflow reviewed by at least one fluent/native reviewer;
   - Traditional workflow reviewed independently;
   - command phrasing reviewed for naturalness, not machine translation only.

7. **English regression**
   - existing test suite;
   - English model/config defaults unchanged;
   - no Chinese optional dependency imported/loaded in default path;
   - selected English latency/behavior smoke benchmark within declared tolerance.

### Evidence artifact

Commit a versioned report under the design/benchmark or public results convention already used by the project. It must record:

- commit SHA;
- model artifact/version;
- dependency versions;
- hardware/OS;
- corpus manifest;
- commands to reproduce;
- raw result files;
- pass/fail against predeclared thresholds.

### Threshold discipline

Thresholds are declared **before** the final release run. If they need revision, change the design record with rationale before rerunning the release gate.

This prevents fitting the definition of “supported” to whichever result happened to appear.

## Consequences

### Positive

- Marketing/docs claims remain evidence-backed.
- Contributors know exactly what remains before release.
- Model upgrades can be compared against a stable contract.
- Platform injection failures cannot hide behind ASR accuracy.
- Native-language quality is not certified by non-speakers.

### Costs

- First-class support takes longer than simply exposing `language = "zh"`.
- Corpus licensing and reproducibility work become release blockers.
- Some platform/backend combinations may remain “supported with clipboard fallback” rather than receiving an unconditional pass.

## Alternatives considered

### Declare support once `language set zh-CN` works

Rejected. That tests configuration plumbing, not product quality.

### Rely on upstream Whisper/Qwen/FunASR benchmarks

Rejected. Upstream hardware, decoding, corpora and product surfaces differ from YazSes.

### Require one maintainer’s manual test

Rejected. It is not reproducible and does not cover Traditional Chinese or platform injection.

## Release wording

Before gate:

> Mandarin can be configured experimentally; current evidence is limited. Test on your own speech.

After gate:

The wording may state supported Mandarin/Simplified/Traditional workflows, but must still name measured limitations, hardware assumptions and any backend fallback. It must not expand to Cantonese or arbitrary Chinese dialects unless separately validated.

---
## Implementation reconciliation and actual release state (2026-10-29)

Model-free regressions now exist for language profiles, config transaction, CLI/Settings/doctor, Mandarin command safety, CJK spacing, subtitles/renderers, Meeting Mode Han quality units and the Mandarin CER scorer. This does **not** satisfy the release requirement alone. At the audited revision, `docs/research/mandarin-platform/` has no physical X11/Wayland/macOS/Windows evidence reports; native command phrase statuses in `zh.py` are all provisional; a release-quality, multi-slice, real-audio Mandarin model comparison has not been demonstrated by this review.

The release manager must complete the [dated evidence matrix](../chinese/2026-10-29-validation-and-release-gates.md), including real model/corpus revision and permission record, representative CPU latency/RAM and long-form stability, native Simplified and Traditional approval, installer/offline-after-cache, actual Unicode injection, negative command cases, and the full English regression suite. Every *claimed* surface requires its own pass, limitation or explicit exclusion. The absence of physical evidence is a **blocker for that platform claim**, not an automatic defect in all models or platforms.

Status remains **Proposed** until maintainer disposition. Neither a working `language set zh-CN` command nor a green CI fixture is authorization to publish blanket “Chinese supported” wording. The supported release scope must exclude Cantonese, unrestricted Mandarin-English code switching, open-ended commands and unvalidated meeting modes.

