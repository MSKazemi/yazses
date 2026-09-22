# Chinese language support design package

**Status:** Proposed design package (2026-09-20)  
**Scope:** First-class Mandarin dictation in Simplified and Traditional Chinese, without regressing English or changing YazSes' offline-by-default architecture.

This directory is the implementation-planning record for Chinese language support. It deliberately separates three things that are easy to conflate:

1. **Speech language** — what the speaker says to the recognizer (Mandarin: `zh`).
2. **Output script** — which Han script is written (`simplified` / `traditional`).
3. **Documentation/UI locale** — which language YazSes documentation or interface text uses.

A user must be able to run an English UI and dictate Chinese, or read Chinese documentation while dictating English. These concerns therefore remain independent.

## Executive decision

Chinese support should **extend the current STT and command seams**, not add a parallel Chinese pipeline.

The repository already contains most of the low-level transcription plumbing:

- `[stt] language` reaches every faster-whisper decode path.
- Multilingual Whisper checkpoints are already understood by the model downloader.
- `[stt] chinese_script` and the OpenCC-backed Han normalizer already cover batch, streaming, word timestamps, file transcription, and meeting transcription through the STT factory wrapper.
- The Settings UI already exposes `Chinese -> zh`.
- The STT engine is already abstracted behind `SttEngine`.

The missing product-level capability is a **validated, atomic language switch** plus Chinese-aware command recognition, diagnostics, benchmarking, platform validation, and an honest release gate.

The P1 implementation therefore uses the existing faster-whisper backend and a multilingual Whisper model. The starting balanced preset is `small`; higher-cost checkpoints such as `large-v3-turbo` are benchmark candidates, not assumptions. Chinese-specialized engines (Qwen3-ASR, SenseVoice, Paraformer) may be evaluated later behind the existing `SttEngine` protocol and must earn their inclusion by measurement.

## Documents

| Document | Purpose |
|---|---|
| [Current-state assessment](current-state-assessment.md) | File-by-file audit of what already works, what is incomplete, and the architectural risks. |
| [Target architecture](target-architecture.md) | Boundaries, language-profile resolver, atomic config transaction, command grammar localization, data flow, failure handling, and compatibility rules. |
| [Model strategy](model-strategy.md) | P1 model decision, benchmark candidates, alternative engine evaluation criteria, licensing/dependency gates, and promotion rules. |
| [Test and validation plan](test-and-validation-plan.md) | Unit, contract, integration, platform, benchmark, native-speaker, regression, and release-validation requirements. |
| [Implementation and community work plan](implementation-roadmap.md) | Dependency-ordered engineering work packages and definitions of done. |
| [Execution backlog](issue-backlog.md) | Umbrella issues, milestones, contributor lanes, and the mapping from work packages to the repository campaign queue. |
| [Agent-ready task contracts](agent-ready-task-contracts.md) | ADR-023/A2/A3 rules, risk lanes, allowed paths, validation commands, negative tests, and sample campaign tasks. |
| [Risk register](risk-register.md) | Cross-cutting failure modes, severity, detection, mitigation, ownership, and release-blocker status. |
| [Surface support matrix](surface-support-matrix.md) | Per-surface Mandarin scope: live, streaming, file, meeting, commands, postprocessing, injection, platform, and deferred capabilities. |
| [Human validation and data protocol](human-validation-data-protocol.md) | Privacy-minimized community QA, native review, audio-consent boundaries, and separation between product testing and research/publication data. |
| [Chinese language support spec](../specs/chinese-language-support.md) | Implementation contract: CLI, config behavior, APIs, profile resolution, diagnostics, compatibility, acceptance criteria. |

## ADRs

The design is split into small decisions so future maintainers can supersede one choice without reopening the entire feature:

- [ADR-v2-135 — Language profiles are transactional presets](../adr/adr-v2-135-language-profile-presets.md)
- [ADR-v2-136 — Chinese P1 stays on the existing Whisper engine](../adr/adr-v2-136-chinese-model-policy.md)
- [ADR-v2-137 — Localize command grammars, not command semantics](../adr/adr-v2-137-localized-command-grammars.md)
- [ADR-v2-138 — Separate spoken language, Han script, and locale](../adr/adr-v2-138-chinese-script-and-locale-semantics.md)
- [ADR-v2-139 — Chinese support is gated by measured validation](../adr/adr-v2-139-chinese-support-validation-gate.md)

All five ADRs are **Proposed**. They are documentation for review, not a claim that the implementation already exists.

## P1 user experience

The intended user-facing operation is one command rather than three independent edits:

```sh
yazses language set zh-CN
```

The resolver will plan a coherent Chinese configuration, preflight dependencies/model availability, validate the complete configuration, and commit it atomically. For a default English install it resolves to approximately:

```toml
[stt]
engine = "faster-whisper"
model = "small"
language = "zh"
chinese_script = "simplified"

[commands]
language = "auto"    # resolves to zh while [stt] language = "zh"
```

Traditional Mandarin is:

```sh
yazses language set zh-TW
```

which changes the script target to `traditional` while keeping the speech language `zh`.

Returning to English is:

```sh
yazses language set en
```

The switch back must not destructively replace a compatible model just to restore `.en`. If the current multilingual model can decode English, it may be kept. A separate explicit option may restore the recommended English performance preset.

The command will support `--dry-run` so users can see the model download, dependency work, config changes, and restart requirement before anything is changed.

## Explicit scope

### P1 in scope

- Mandarin dictation (`zh`) on desktop YazSes.
- Simplified output (`zh-CN` / `zh-Hans` aliases).
- Traditional output (`zh-TW` / `zh-Hant` aliases).
- File transcription and meeting transcription inheriting the same configured language by default.
- Chinese Tier-1 command grammar mapping to the existing semantic intents.
- Unicode-safe injection validation on Linux X11, Linux Wayland, macOS, and Windows.
- Existing offline/privacy contract.
- CLI and Settings integration.
- Reproducible Chinese benchmark harness and native-speaker validation.

### Explicitly out of P1

- Cantonese support. `zh-HK` is not silently treated as Mandarin; Cantonese requires its own speech-language decision and evidence.
- Arbitrary Mandarin-English code-switching. The existing [Polyglot Switch spec](../specs/polyglot-switch.md) remains a later, separate capability.
- Full translation of every CLI/GUI string. Documentation localization already has its own `i18n/` process.
- Cloud inference.
- Silent auto-detection as the default. An explicit language is faster and more stable when the user knows what they are speaking.
- Shipping a new heavyweight ML runtime in the base package solely for Chinese.

## Architectural invariants

Any implementation derived from this package must preserve these invariants:

1. **English defaults remain unchanged.** A user who never invokes Chinese support keeps `base.en`, `language = "en"`, and the current command behavior.
2. **No second source of truth.** Language profiles are presets/resolvers over canonical config keys, not a parallel persistent configuration graph.
3. **One STT protocol.** Chinese engines, if added later, implement `SttEngine`; callers do not branch on Chinese.
4. **Semantic command actions stay language-neutral.** Chinese utterances resolve to the same `CommandIntent.action` names as English.
5. **Script conversion stays post-recognition.** It is an output normalization concern and remains at the STT factory chokepoint.
6. **A switch is atomic.** The user never lands in an intermediate state such as `language = "zh"` with `base.en`.
7. **No hidden network dependency at runtime.** Downloads are one-time, explicit/preflighted, and cached; decoding remains local.
8. **Support claims follow measurements.** Documentation may call Chinese "supported" only after the validation gate in ADR-v2-139 passes.

## Relationship to existing Chinese documentation

The existing Chinese voice-typing page is useful and should remain the manual/advanced path. It currently tells users to edit:

- `model = "small"`
- `language = "zh"`
- `chinese_script = "simplified"`

This design does not invalidate that configuration. It formalizes it into a safe product operation, adds Chinese commands and validation, and makes the state inspectable by `doctor`, Settings, and tests.

The existing `docs/zh-CN/` and `docs/zh-TW/` trees are documentation translations. They do **not** determine speech-recognition settings.

## Definition of success

The design is considered implemented when:

- a fresh English install can switch to Simplified or Traditional Mandarin with one validated operation;
- switching cannot leave a partially mutated config;
- Chinese dictation reaches all existing STT surfaces without Chinese-specific call-site branches;
- Chinese voice commands pass the same semantic action contract as English;
- English regression tests and benchmark guardrails pass;
- Chinese CER/latency/resource results are published from a reproducible harness;
- native speakers validate both Simplified and Traditional workflows;
- all supported desktop injection backends have an explicit pass/warn/fallback result;
- `yazses doctor` can explain an invalid or incomplete Chinese configuration in one actionable message;
- the project can roll the capability back by config/feature change without removing or forking the core pipeline.
