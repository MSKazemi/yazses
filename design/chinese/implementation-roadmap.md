# Chinese support — implementation roadmap

**Status:** Proposed, issue-ready work decomposition  
**Goal:** Provide tasks small and explicit enough for multiple community developers to implement in parallel without having to redesign the feature.

## 1. Workstream graph

```text
CHN-00 design review
   |
   +--> CHN-10 profile model/resolver
   |       |
   |       +--> CHN-11 status derivation
   |       +--> CHN-12 atomic transaction
   |                    |
   |                    +--> CHN-13 CLI
   |                    +--> CHN-14 Settings
   |                    +--> CHN-15 doctor
   |
   +--> CHN-20 English grammar extraction
   |       |
   |       +--> CHN-21 Chinese grammar core
   |       +--> CHN-22 Chinese numerals
   |       +--> CHN-23 command vectors/native review
   |
   +--> CHN-30 postprocess audit
   +--> CHN-31 file/meeting integration
   +--> CHN-32 injection matrix
   |
   +--> CHN-40 benchmark harness
           |
           +--> CHN-41 Whisper baseline run
           +--> CHN-42 alternative model probes
           +--> CHN-43 native-speaker acceptance
                    |
                    +--> CHN-50 support release gate/docs
```

CHN-10 and CHN-20 may begin in parallel after design review. Benchmark harness can also be built independently.

---

## 2. From work package to executable contributor task

A CHN package in this file is **not automatically a GitHub issue and not automatically safe to hand to an agent**.

Current repository policy (ADR-023) separates three layers:

1. **This roadmap** — architectural dependency graph and work packages.
2. **A small umbrella GitHub issue** — design discussion, coordination, decisions.
3. **`campaign/tasks.json`** — bounded 10–30 minute contributor contracts with allowed paths, validation commands, risk lane and cloud/hardware/native-review requirements.

Before a package is advertised, split it until each task is:

- independent;
- useful;
- bounded to one sitting;
- verifiable by an existing command/schema or named human evidence;
- low-review-cost;
- limited to exact allowed paths.

L3 changes — accepted ADR semantics, dependency additions, privacy/network posture, public interfaces, default behavior — remain maintainer/experienced-contributor work and are not advertised as open first tasks.

Every executable task must record:

- ADR/spec source;
- exact allowed paths;
- paths explicitly out of scope where useful;
- risk lane;
- honest minutes estimate;
- whether a cloud agent can produce all evidence;
- exact validation command(s) that already exist;
- human evidence required;
- the negative-test failure mode that a low-effort or fabricated submission might exploit.

See [agent-ready-task-contracts.md](agent-ready-task-contracts.md) for sample campaign rows and [issue-backlog.md](issue-backlog.md) for umbrella/milestone structure.

---

## 3. CHN-00 — Approve Chinese support architecture

**Suggested title:** `design: approve first-class Mandarin language-support architecture`

**Type:** design / maintainer  
**Size:** M  
**Dependencies:** none

### Work

Review and either accept/supersede:

- ADR-v2-140 through ADR-v2-144;
- `specs/chinese-language-support.md`;
- target architecture;
- model strategy;
- validation plan.

Resolve before coding:

- exact CLI naming;
- `commands.language = "auto"` semantics;
- supported baseline model (`small` unless benchmark pre-work changes decision);
- config transaction mechanism consistent with existing writer;
- whether Settings installs extras automatically on every packaging target.

### Definition of done

- ADR statuses changed from Proposed to Accepted where agreed;
- unresolved decisions become explicit follow-up ADRs, not comments;
- no implementation issue depends on ambiguous profile semantics.

---

## 4. CHN-10 — Implement pure language profile resolver

**Suggested title:** `feat(language): add pure English/Mandarin profile resolver`

**Type:** Python core  
**Size:** M  
**Dependencies:** CHN-00  
**Can parallelize with:** CHN-20, CHN-40

### Files

New:
- `src/yazses/language/__init__.py`
- `src/yazses/language/profiles.py`
- `src/yazses/language/plan.py`
- `tests/test_language_profiles.py`

Possibly:
- small engine capability helper under `stt/`.

### Requirements

Implement canonical:
- en;
- zh-CN / zh-Hans;
- zh-TW / zh-Hant.

Reject zh-HK with typed ambiguity error.

Return `LanguagePlan`; no I/O/network.

Preserve compatible current model by default.

### Tests

All resolver tests from validation plan §3.

### Definition of done

- 100% branch coverage is desirable for the small pure resolver;
- importing resolver does not import model runtimes;
- default English config resolves with zero changes;
- default -> zh plans small + zh + requested script.

---

## 5. CHN-11 — Derive language status/coherence

**Suggested title:** `feat(language): report derived language profile and config coherence`

**Type:** Python core  
**Size:** S  
**Dependencies:** CHN-10

### Files

- `src/yazses/language/status.py`
- tests.

### Requirements

Return structured:
- speech language;
- script;
- command language;
- engine/model;
- exact/compatible/custom profile;
- problems;
- prerequisite status.

No heavy imports or network.

### Definition of done

All coherent/incoherent cases in validation §3.7 pass.

---

## 6. CHN-12 — Atomic multi-key config application

**Suggested title:** `feat(language): apply language plan atomically after artifact preflight`

**Type:** config/reliability  
**Size:** L  
**Dependencies:** CHN-10

### Files

- `src/yazses/language/apply.py`;
- existing configedit infrastructure if generalized;
- `tests/test_language_apply.py`.

### Requirements

- lock/re-read;
- dependency preflight;
- model cache/download preflight;
- candidate parse/validation;
- same-dir temp write;
- atomic replace;
- restart once;
- no partial writes on failure;
- preserve concurrent unrelated edits.

### Special review point

Do not install/download after writing the target language. The old English configuration remains active until all prerequisites are ready.

### Definition of done

Failure-injection tests prove original config byte-for-byte intact for every precommit failure.

---

## 7. CHN-13 — Add language CLI

**Suggested title:** `feat(cli): add language list/status/set`

**Type:** CLI  
**Size:** M  
**Dependencies:** CHN-11, CHN-12

### Commands

- `language list`;
- `language status [--json]`;
- `language set PROFILE`.

Options per spec.

### Tests

Click runner:
- dry-run;
- no-download;
- JSON;
- invalid zh-HK;
- compatible custom model;
- apply with fakes.

### Docs

- CLI reference generator/source;
- man page source if generated separately;
- configuration how-to.

### Definition of done

A default config can be changed to coherent zh-CN and back using only CLI in a temporary test environment.

---

## 8. CHN-14 — Settings language profile control

**Suggested title:** `feat(settings): add validated dictation-language profile control`

**Type:** desktop UI/controller  
**Size:** M  
**Dependencies:** CHN-11, CHN-12

### Requirements

- high-level dictation language control;
- separate Chinese output-script control/label;
- plan preview for model/dependency;
- confirmation before download/install;
- custom-compatible state;
- no mapping duplicated in Qt layer.

### Tests

Qt-free controller first; minimal UI smoke.

### Definition of done

CLI and Settings produce identical `LanguagePlan` for same starting config and selection.

---

## 9. CHN-15 — Doctor language diagnostics

**Suggested title:** `feat(doctor): diagnose language/model/script/command coherence`

**Type:** diagnostics  
**Size:** S/M  
**Dependencies:** CHN-11

### Checks

CHN-001 through CHN-006 in spec.

### Definition of done

Doctor points an invalid `base.en + zh` config to `yazses language set zh-CN`; no duplicate compatibility rule introduced.

---

## 10. CHN-20 — Refactor Tier-1 grammar into registry with zero English change

**Suggested title:** `refactor(commands): extract English Tier-1 grammar behind language registry`

**Type:** commands / high regression sensitivity  
**Size:** M  
**Dependencies:** CHN-00  
**Can parallelize with:** CHN-10

### Files

Likely:
- `commands/grammar.py`;
- new `commands/grammars/en.py`;
- shared types if needed;
- contract generator.

### Requirement

No Chinese rules in this PR. It is a pure behavior-preserving refactor.

### Definition of done

- all existing grammar tests;
- contract vectors identical;
- public classify call remains compatible;
- benchmark remains <5 ms target.

---

## 11. CHN-21 — Add Chinese safe-core command grammar

**Suggested title:** `feat(commands): add reviewed Mandarin edit/navigation grammar`

**Type:** commands + localization  
**Size:** L  
**Dependencies:** CHN-20

### Start with lower-risk actions

- undo;
- save;
- copy/cut/paste;
- delete last word/line;
- select;
- enter/tab/escape/backspace;
- basic navigation;
- go to line.

Defer broad terminal `run ...` forms until negative corpus/safety review is complete.

### Requirements

- Simplified + Traditional reviewed phrases;
- anchored deterministic rules;
- same canonical action IDs;
- command-only normalization.

### Definition of done

Positive vectors pass; curated Chinese prose negative set has zero Tier-1 command false positives.

---

## 12. CHN-22 — Chinese command numeral parser

**Suggested title:** `feat(commands): parse bounded Chinese numerals for command arguments`

**Type:** parsing  
**Size:** S/M  
**Dependencies:** CHN-20; can land before/with CHN-21

### Scope

0–99 minimum; Arabic digits; common Chinese forms.

Pure function with exhaustive table tests.

### Out of scope

General-purpose Chinese number normalization for dictation.

---

## 13. CHN-23 — Chinese command contract vectors and native phrase review

**Suggested title:** `test(commands): add Mandarin command contract and ambiguity corpus`

**Type:** tests/localization  
**Size:** M  
**Dependencies:** CHN-21, CHN-22

### Deliverables

- positive vector file;
- negative/prose vector file;
- reviewer attribution/notes where contributors consent;
- phrase rationale for ambiguous actions.

### Definition of done

Every shipped Chinese Tier-1 action is represented by:
- positive Simplified;
- positive Traditional;
- punctuation variant;
- relevant negative.

---

## 14. CHN-30 — Audit postprocessing for CJK assumptions

**Suggested title:** `audit(i18n): classify postprocessors for Mandarin safety`

**Type:** audit + targeted fixes  
**Size:** L  
**Dependencies:** CHN-00

### Search

Every default-on text transform and quality heuristic.

### Deliverable

Add `design/chinese/postprocess-compatibility.md` table:

- module;
- default state;
- language assumption;
- Chinese result;
- fix/disable decision;
- tests.

### High priority

- meeting “word” counts;
- whitespace insertion between bursts;
- capitalization;
- filler removal;
- number normalization.

### Definition of done

No default-on English-specific transform can silently damage Chinese output without a guard/fix.

---

## 15. CHN-31 — Verify file and meeting Chinese paths

**Suggested title:** `test(multilingual): verify Mandarin file and meeting pipelines`

**Type:** integration  
**Size:** M/L  
**Dependencies:** CHN-10, CHN-30

### Requirements

- file config inheritance;
- per-file override;
- script conversion;
- metadata;
- meeting live/postpass language;
- meeting quality heuristic audit.

### Definition of done

Chinese support matrix explicitly says supported/limited for each surface; tests back every green cell.

---

## 16. CHN-32 — Unicode injection platform matrix

**Suggested title:** `test(injection): validate Han text on supported desktop backends`

**Type:** cross-platform/hardware  
**Size:** L distributed  
**Dependencies:** none for test design; release depends on it

This is ideal for community parallelism: one issue/subtask per OS/session.

### Subtasks

- CHN-32A Linux X11;
- CHN-32B Linux Wayland;
- CHN-32C macOS;
- CHN-32D Windows.

### Standard fixture

Same Unicode string and application categories.

### Deliverable

`design/chinese/results/.../injection-matrix.md`.

### Definition of done

Every platform has verified primary path or documented clipboard fallback.

---

## 17. CHN-40 — Build reproducible Mandarin benchmark harness

**Suggested title:** `bench(chinese): add reproducible CER and latency harness`

**Type:** benchmarking/research  
**Size:** L  
**Dependencies:** CHN-00  
**Can parallelize with:** core implementation

### Deliverables

- corpus manifest format;
- scoring normalization;
- CER breakdown;
- script pre/post normalization;
- timing/RSS;
- JSON result schema;
- command to reproduce.

### No corpus redistribution violations

Harness downloads or points to legal corpus sources; repository stores only allowed manifests/results/code.

---

## 18. CHN-41 — Establish Whisper Chinese baseline

**Suggested title:** `bench(chinese): measure small, large-v3-turbo and large-v3`

**Type:** benchmark  
**Size:** M compute  
**Dependencies:** CHN-40

### Arms

At minimum:
- small;
- large-v3-turbo;
- large-v3.

Record condition_on_previous_text where relevant.

### Definition of done

Model strategy can name a supported baseline from measured YazSes results rather than only existing microset evidence.

If `small` fails release thresholds, ADR-v2-141 must be revisited before support ships.

---

## 19. CHN-42 — Prototype optional Chinese-specialized engines

Split into independent issues; do not block P1 unless baseline fails.

### CHN-42A SenseVoiceSmall

Adapter prototype behind `SttEngine`, benchmark only first.

### CHN-42B Paraformer

Investigate offline + streaming contract and timestamps.

### CHN-42C Qwen3-ASR-0.6B

Measure CPU/RAM/package implications and dialect opportunity.

Each prototype must record:
- exact weight license;
- dependency footprint;
- adapter feasibility;
- benchmark result.

Do not merge a production backend solely to run the benchmark if an isolated probe suffices.

---

## 20. CHN-43 — Native-speaker acceptance

**Suggested title:** `validation(chinese): Simplified and Traditional native-speaker acceptance`

**Type:** community validation  
**Size:** distributed  
**Dependencies:** CHN-13, CHN-21, CHN-41

Separate reviewers for Simplified and Traditional.

Use validation checklist; private audio remains private.

### Definition of done

- phrasing corrections landed;
- UX terminology corrections landed;
- major recognition limitations documented;
- no machine-only translation is used as the sole language-quality approval.

---

## 21. CHN-50 — Support release gate and documentation transition

**Suggested title:** `release(chinese): run first-class Mandarin support gate`

**Type:** release/evidence  
**Size:** L  
**Dependencies:** all release-blocking workstreams

### Work

- collect machine artifacts;
- English regression;
- packaging;
- injection;
- native review;
- exact model/license record;
- offline test;
- final pass/fail report.

If passed:
- update Chinese voice-typing page from “not claimed” wording;
- add supported matrix to features/docs;
- release notes;
- roadmap status.

If failed:
- keep experimental wording;
- publish failure/limitation honestly;
- create focused remediation issues.

---

## 22. Parallel contributor lanes

### Lane A — core/config
CHN-10 -> 11 -> 12 -> 13/14/15

### Lane B — commands/localization
CHN-20 -> 21/22 -> 23

### Lane C — compatibility
CHN-30 -> 31

### Lane D — platforms
CHN-32A/B/C/D independently

### Lane E — research
CHN-40 -> 41 -> 42*

### Lane F — community language review
Begins phrase review during CHN-21 and completes CHN-43.

This structure allows many contributors without multiple people editing the same core files at once.

---

## 23. Review ownership suggestions

These are skill requirements, not named-person assignments:

| Work | Reviewer expertise |
|---|---|
| profile/config transaction | Python + reliability/config |
| command grammar | Python parsing + command safety |
| Simplified phrases | fluent/native Simplified Chinese |
| Traditional phrases | fluent/native Traditional Chinese |
| model benchmark | ASR evaluation/statistics |
| alternative model adapter | ML inference/packaging |
| Linux injection | Linux input stack |
| macOS injection | macOS accessibility/input |
| Windows injection | Win32 input/clipboard |
| licensing | maintainer/release/legal-awareness |

No contributor should be expected to certify Mandarin naturalness solely because they implemented the parser.

---

## 24. Merge strategy

Prefer small PRs in dependency order.

Especially separate:

1. English grammar refactor from Chinese rules.
2. Profile resolver from config mutation.
3. CLI from Settings.
4. Benchmark harness from model recommendation.
5. Alternative-engine research from production integration.

This keeps regressions bisectable and lets documentation/design contributions land before code.

---

## 25. Final milestone acceptance

The Mandarin milestone closes only when the release gate in ADR-v2-144 is resolved with a committed evidence report.

“Code merged” is not the milestone definition.
