# Chinese support — risk register and release blockers

**Status:** Proposed design control  
**Purpose:** Make failure modes explicit before implementation work is advertised, and connect each risk to an owner, detector, mitigation, and release gate.

This register complements ADR-v2-139. It is intentionally broader than ASR accuracy: a Chinese transcript can be correct and the feature can still be unsafe or unusable if configuration, command parsing, injection, packaging, or long-form behavior is wrong.

## Severity scale

| Level | Meaning |
|---|---|
| **Critical** | Can execute unintended actions, corrupt user configuration/data, violate privacy/offline guarantees, or make a support claim materially false. |
| **High** | Can make a primary Chinese workflow fail silently or regress the default English path. |
| **Medium** | Degrades an important secondary surface or produces confusing/expensive recovery. |
| **Low** | Localized rough edge with an obvious workaround and no data/safety impact. |

Likelihood is estimated only for prioritization and must be updated once evidence exists.

## Register

| ID | Risk | Sev. | Likelihood before testing | Detection / evidence | Required mitigation | Release status |
|---|---|---:|---:|---|---|---|
| CHN-R01 | High-level language switch writes only part of model/language/script state | Critical | Medium | failure-injection transaction tests | preflight all prerequisites; validate candidate; atomic replace; concurrency guard | **Blocker** |
| CHN-R02 | Default English startup/config/latency changes for users who never enable Chinese | High | Medium | English regression suite + import/startup smoke benchmark | keep current defaults; lazy optional deps; zero Chinese model load on default path | **Blocker** |
| CHN-R03 | Chinese prose is falsely classified as a command | Critical | Medium | curated negative Mandarin corpus; semantic command vectors | anchored deterministic rules; precision-first phrase set; no broad catch-all terminal regex | **Blocker** |
| CHN-R04 | Correct Han text cannot be injected reliably on an OS/backend | High | High on some backends | real X11/Wayland/macOS/Windows injection matrix | verified native path or explicit clipboard fallback; never imply untested backend support | **Blocker for claimed backend** |
| CHN-R05 | Meeting quality heuristics miscount unsegmented Han text and can mark a healthy Mandarin meeting `thin` | High | **Confirmed** | Current `meeting/quality.py::tokenize()` uses `[^\\W\\d_]+`; contiguous Han between punctuation becomes one token. `store.live_word_count()` reuses the same tokenizer, so both WPM and live/batch ratio inherit the language assumption. | replace/parameterize the quality unit for CJK (for example language-aware segmentation or a character-rate metric), re-baseline thresholds on Mandarin, and add regression fixtures; otherwise exclude Chinese Meeting Mode | **Blocker for meeting claim** |
| CHN-R06 | `zh-HK` accidentally means Mandarin because the Han converter accepts it as a Traditional-script alias | High | Medium | profile alias tests | script aliases stay local to script resolver; P1 profile rejects zh-HK with Cantonese explanation | **Blocker** |
| CHN-R07 | Model download or optional dependency installation fails after config has changed | High | Medium | network/package-manager failure tests | download/install before commit; `--no-download`; exact remediation | **Blocker** |
| CHN-R08 | Alternative ASR engine adds a mandatory heavy runtime or breaks packaging | High | Medium | dependency/import/package matrix | alternative engines optional + lazy; P1 stays on current runtime unless benchmark justifies change | **Blocker if alternative becomes recommended** |
| CHN-R09 | Model or toolkit license is mistaken for model-weight license | Critical | Medium | explicit license record per artifact | legal/license gate before documented support or redistribution; no inference from toolkit license | **Blocker** |
| CHN-R10 | Benchmark overfits a tiny/easy Mandarin set and yields a misleading support claim | High | High | corpus manifest; multiple speech conditions; error subsets | predeclare corpora/normalization/thresholds; report raw and normalized CER | **Blocker** |
| CHN-R11 | Script normalization hides recognition errors or performs regional vocabulary changes not requested by user | Medium | Medium | raw-vs-normalized scoring; converter fixtures | report both scores; keep character-script conversion separate from regional lexical conversion | **Blocker for benchmark integrity** |
| CHN-R12 | Long-form Whisper decode repeats/hallucinates although short CER looks good | High | Medium | >=30 min Mandarin long-form test; repetition metrics | include long-form stability in model gate; preserve/extend quality safeguards | **Blocker for file/meeting long-form claim** |
| CHN-R13 | Chinese command phrasing is literal machine translation rather than natural user speech | Medium | High | Simplified + Traditional native review | native reviewer signs off phrase fixtures; keep machine-only suggestions as draft | **Blocker for command-support claim** |
| CHN-R14 | Simplified review is treated as sufficient for Traditional UX/terminology | Medium | Medium | independent Traditional review | separate reviewer/checklist and phrase fixtures | **Blocker for zh-TW claim** |
| CHN-R15 | Command-language setting is confused with existing `CommandsConfig.profile` (editor/app behavior) | High | Medium | config/schema tests | dedicated `commands.language`; never overload application profile | **Blocker** |
| CHN-R16 | Language profile becomes a second persistent truth and drifts from real STT keys | High | Medium | status derivation tests; manual customization test | profiles are resolvers/presets only; effective config fields are authoritative | **Blocker** |
| CHN-R17 | Concurrent Settings/CLI writes lose unrelated config changes | High | Low/Medium | stale-plan/concurrent-edit test | lock/re-read/re-resolve before atomic commit | **Blocker** |
| CHN-R18 | Alternative engine cannot implement word timestamps/streaming but profile silently selects it | Medium | Medium | `SttEngine` capability test matrix | explicit engine capability metadata; profile cannot select unsupported surface silently | **Blocker for promoted engine** |
| CHN-R19 | Packaging sandbox cannot install OpenCC or write model cache | High | Medium | Snap/macOS/Windows/distro package validation | bundle where policy permits or give exact preflight refusal/workaround before config mutation | **Blocker per package** |
| CHN-R20 | Documentation/UI locale silently changes recognition language | High | Low | UI/locale isolation tests | localization and speech settings remain independent; only explicit user action changes speech | **Blocker** |
| CHN-R21 | Mandarin-English code-switch expectations creep into P1 and cause false claims | Medium | High | scope review; mixed-language stress results separated | keep Polyglot Switch separate; mixed tokens are stress evidence, not a support claim | Non-blocking if scope is explicit |
| CHN-R22 | Cantonese is inferred from Traditional output instead of validated separately | High | Medium | profile list and docs review | future explicit `yue` profile/model/eval; P1 says Mandarin | **Blocker** |
| CHN-R23 | Native-speaker validation accidentally commits private voice/audio or identifiers | Critical | Low/Medium | contribution/preflight privacy checks | results record observations only; audio stays private unless explicit redistributable consent/license | **Blocker** |
| CHN-R24 | Benchmark result cannot be reproduced because model hash/runtime/hardware is missing | High | Medium | result-schema validation | record commit SHA, model artifact/version/hash, dependency versions, hardware, commands, corpus manifest | **Blocker** |
| CHN-R25 | A large contributor task produces a wide agent-generated diff and high review cost | Medium | High | ADR-023 readiness review | split implementation into A2/A3 campaign task contracts; L3/architecture stays maintainer-owned | Process blocker before advertising task |

## Risk ownership by workstream

| Workstream | Primary risks |
|---|---|
| Profile/config transaction | R01, R07, R15, R16, R17, R20 |
| STT/model evaluation | R02, R08, R09, R10, R11, R12, R18, R24 |
| Commands | R03, R13, R14, R15 |
| Platform/injection | R04, R19 |
| File/Meeting Mode | R05, R12, R18 |
| Scope/localization | R06, R20, R21, R22 |
| Community validation | R13, R14, R23, R25 |

## Gate rule

A risk marked **Blocker** is not waived by a passing aggregate benchmark. It must be either:

1. mitigated and backed by the named evidence; or
2. used to **narrow the support matrix** so the affected surface is explicitly not claimed.

Examples:

- If Wayland injection remains unverified, Mandarin can still ship for verified platforms, but docs must not present Wayland as fully supported.
- If Meeting Mode quality metrics remain English-specific, live dictation/file transcription may ship while Chinese Meeting Mode remains experimental or excluded.
- If `small` misses the predeclared quality/performance gate, ADR-v2-136 is revisited before release rather than lowering the threshold after seeing results.

## Review cadence

Review this table at four points:

1. ADR acceptance.
2. Before generating/opening campaign tasks.
3. Before the first end-to-end Chinese beta.
4. At the ADR-v2-139 support-release gate.

Any newly discovered failure mode gets an ID before remediation so the test/evidence that closes it remains traceable.
