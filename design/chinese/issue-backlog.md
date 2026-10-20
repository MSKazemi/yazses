# Chinese support — execution backlog

**Status:** Proposed work inventory  
**Important repository convention:** bounded contributor tasks belong in `campaign/tasks.json`, not one GitHub issue per task. This file defines work packages and umbrella discussions; [agent-ready-task-contracts.md](agent-ready-task-contracts.md) defines how packages are split into ADR-023-compliant campaign tasks.

For the architectural dependency graph, see [implementation-roadmap.md](implementation-roadmap.md).

## 1. One epic outcome

### First-class offline Mandarin dictation

A user can switch an English YazSes installation to:

- Mandarin + Simplified output; or
- Mandarin + Traditional output,

use the validated product surfaces, and switch back without changing YazSes' offline-by-default architecture or regressing the default English path.

**Release boundary:** Mandarin only. Cantonese, arbitrary code-switching, and unvalidated surfaces remain separate.

**Governing ADRs:** v2-135 through v2-139.

**Done when:** ADR-v2-144's evidence gate is resolved with a committed support matrix and result artifacts.

## 2. GitHub umbrella issues

After the ADRs are accepted, use a small number of umbrella issues for discussion and coordination:

| Umbrella | Purpose | Roadmap packages |
|---|---|---|
| [#497](https://github.com/MSKazemi/yazses/issues/497) — Mandarin foundation | safe language selection/configuration and user controls | CHN-10..15 |
| [#499](https://github.com/MSKazemi/yazses/issues/499) — Mandarin commands | grammar architecture, numerals, phrase review | CHN-20..23 |
| [#501](https://github.com/MSKazemi/yazses/issues/501) — Mandarin compatibility | postprocessing, file/meeting, desktop injection | CHN-30..32 |
| [#503](https://github.com/MSKazemi/yazses/issues/503) — Mandarin model evidence | harness, baseline, alternative probes | CHN-40..42 |
| [#505](https://github.com/MSKazemi/yazses/issues/505) — Mandarin release validation | native review + release gate | CHN-43..50 |

Do not create one GitHub issue for each 15–30 minute contributor task. ADR-023 and `campaign/README.md` intentionally keep those in the campaign inventory.

### Current campaign mapping

Draft campaign PR [#533](https://github.com/MSKazemi/yazses/pull/533) materializes the first
bounded tasks from this backlog.

**Open before ADR approval because they do not choose architecture:**

- `CHN-QA-CJK-CLEANER-001` — model-free CJK cleaner regression vectors.
- `CHN-QA-HAN-SCRIPT-001` — mixed Han/ASCII/script-normalizer vectors.
- `CHN-QA-MEETING-CJK-001` — minimal Meeting Mode Han-token counting reproducer.
- `CHN-QA-CER-HARNESS-001` — common Mandarin CER scorer/harness.
- `CHN-COMPAT-X11-001`, `CHN-COMPAT-WAYLAND-001`,
  `CHN-COMPAT-MACOS-001`, `CHN-COMPAT-WINDOWS-001` — real-platform Han injection evidence.

**Registered but held in `verified` until the common CER harness lands:**

- `CHN-MEASURE-WHISPER-SMALL-001`
- `CHN-MEASURE-WHISPER-TURBO-001`
- `CHN-MEASURE-WHISPER-LARGE3-001`
- `CHN-MEASURE-QWEN3-ASR-06B-001`

Architecture-sensitive foundation and command implementation stays in the umbrella issues until
ADR-v2-140..139 are accepted/superseded; do not advertise those as first-contribution tasks early.


## 3. Work-package register

These IDs are architectural work packages, not automatically campaign task IDs.

| ID | Work package | Depends on | Risk | Execution mode |
|---|---|---|---:|---|
| CHN-00 | Accept/supersede Chinese architecture ADRs | — | L3 | maintainer ADR review |
| CHN-10 | Pure language profile resolver | 00 | L2 | split into A3 code tasks |
| CHN-11 | Derived language status/coherence | 10 | L1/L2 | A3 campaign task |
| CHN-12 | Atomic language config transaction | 10 | L3-sensitive | experienced/maintainer |
| CHN-13 | `language list/status/set` CLI | 11,12 | L2 | split into A3 tasks |
| CHN-14 | Settings language-profile UX | 11,12 | L2 | split controller/UI |
| CHN-15 | Doctor language diagnostics | 11 | L1/L2 | A3 campaign task |
| CHN-20 | English grammar extraction with parity | 00 | L2 | A3 after vectors fixed |
| CHN-21 | Mandarin core command grammar | 20 | L2 | split by semantic family; native review |
| CHN-22 | Bounded Chinese numeral parser | 20 | L1/L2 | A3 campaign task |
| CHN-23 | Chinese command vectors/negative corpus | 21,22 | L0/L1 | native-review task |
| CHN-30 | CJK postprocessor compatibility audit | 00 | L1 | one component per task |
| CHN-31F | Mandarin file-transcription integration | 10,30 | L2 | A3 where model-free |
| CHN-31M | Mandarin Meeting Mode integration | 10,30 | L2 | separate due R05/R12 |
| CHN-32A | Han injection: Linux X11 | — | L0 | real hardware, cloud false |
| CHN-32B | Han injection: Linux Wayland | — | L0 | real hardware, cloud false |
| CHN-32C | Han injection: macOS | — | L0 | real hardware, cloud false |
| CHN-32D | Han injection: Windows | — | L0 | real hardware, cloud false |
| CHN-40 | Reproducible Mandarin benchmark harness | 00 | L2 | experienced A3 code task |
| CHN-41 | Whisper baseline measurements | 40 | L0 measurement | real model/hardware evidence |
| CHN-42A | SenseVoiceSmall benchmark probe | 40 | L2 research | custom weight license; research-only unless explicitly cleared |
| CHN-42B | Paraformer benchmark probe | 40 | L2 research | pin an Apache-2.0 weight revision before testing for production |
| CHN-42C | Qwen3-ASR-0.6B benchmark probe | 40 | L2 research | Apache-2.0 candidate; optional, no base dependency |
| CHN-43S | Simplified workflow native review | 13,21,41 | L0 | human language evidence |
| CHN-43T | Traditional workflow native review | 13,21,41 | L0 | human language evidence |
| CHN-50 | Final support-evidence gate | release blockers | L3 | maintainer/release decision |

## 4. Milestones

### M1 — Coherent language state

Packages:
CHN-00, 10, 11, 12, 13, 15.

Exit criteria:

- one shared resolver;
- atomic apply;
- dry-run/no-download;
- invalid `base.en + zh` cannot be produced by high-level operation;
- status/doctor can explain manually invalid configs;
- English defaults unchanged.

### M2 — Safe Chinese command layer

Packages:
CHN-20, 21, 22, 23.

Exit criteria:

- English contract parity;
- safe edit/navigation Mandarin commands;
- zero false positives on curated negative fixture;
- native review of Simplified and Traditional phrases;
- terminal/open-ended commands either separately cleared or explicitly omitted.

### M3 — Surface compatibility

Packages:
CHN-30, 31F, 31M, 32A-D.

Exit criteria:

- every default-on postprocessor classified;
- file path verified;
- Meeting Mode either verified or explicitly excluded;
- each desktop platform/session has exact Han injection evidence or documented fallback.

### M4 — Recognition evidence

Packages:
CHN-40, 41, optional 42A-C.

Exit criteria:

- corpus manifest;
- scoring normalization;
- raw + requested-script CER;
- p50/p95 latency/RTF;
- RSS/load time/core-seconds;
- long-form stability;
- artifact/runtime/hardware record.

### M5 — Human acceptance and support gate

Packages:
CHN-43S, CHN-43T, CHN-50.

Exit criteria:

- separate Simplified/Traditional review;
- privacy-safe validation notes;
- risk register blockers resolved or support matrix narrowed;
- exact support wording backed by evidence.

## 5. Contributor lanes

### Pure Python / no Chinese required

Good candidates after prerequisites merge:

- status derivation;
- profile alias tests;
- numeral parser;
- English grammar parity;
- doctor formatting/checks;
- benchmark result-schema validation;
- postprocessor code audits.

### Chinese-language contributors

Useful without writing core Python:

- command phrase review;
- positive/negative command fixtures;
- Simplified UX terminology;
- Traditional UX terminology;
- final acceptance scenarios.

Machine translation is a drafting aid, not acceptance evidence.

### Platform contributors

Independent tasks:

- X11;
- Wayland;
- macOS;
- Windows.

Each uses a fixed public fixture and records expected vs observed text, backend and target app. No personal clipboard/audio data.

### ASR/research contributors

- harness;
- Whisper baseline;
- SenseVoice/Paraformer/Qwen probes;
- error analysis.

Upstream leaderboard copying is not a valid task completion.

## 6. Task-opening rule

A work package becomes an advertised campaign task only when:

1. governing ADR/API is no longer ambiguous;
2. allowed paths are exact;
3. expected time fits one sitting;
4. validation commands already exist;
5. the negative-test failure mode is named;
6. one internal implementation/review pass demonstrates the task is unambiguous;
7. risk lane is L0-L2;
8. hardware/native/model evidence tasks have `cloud_agent_ready=false`.

See [agent-ready-task-contracts.md](agent-ready-task-contracts.md).

## 7. Common acceptance constraints

Every implementation task touching shared behavior inherits these:

### Architecture

- default English model/language behavior unchanged unless a separate accepted ADR says otherwise;
- no Chinese-specific daemon/dispatch fork;
- canonical config remains source of truth;
- optional model/dependency remains lazy;
- runtime remains offline after explicit one-time artifact setup.

### Tests

- positive case;
- negative/failure case;
- English shared-path regression where relevant;
- ordinary CI has no model/network/hardware dependency unless the task is explicitly measurement/compatibility work.

### Documentation

- limitation stated;
- surface support matrix updated when evidence changes;
- no generic “Chinese supported” statement before ADR-v2-144.

## 8. Labels and metadata

Use repository-existing labels only. Check current labels before opening umbrellas.

Conceptual classification:

- multilingual/STT;
- commands;
- Settings/CLI;
- compatibility/platform;
- benchmark/measurement;
- localization/native review;
- help wanted / good first contribution only when ADR-023 readiness is actually satisfied.

Do not create duplicate label taxonomies just for this feature.

## 9. Why this structure is better for community development

The architectural package can stay detailed and cross-cutting, while each contributor sees only a bounded contract. That reduces:

- overlapping edits;
- giant agent-generated diffs;
- native-language judgments made by non-speakers;
- unverifiable hardware claims;
- model measurements with missing environment data;
- reviewer effort.

The roadmap is the plan. GitHub umbrella issues are the discussion layer. `campaign/tasks.json` is the executable contributor queue.
