# Persian (فارسی) Language Support Program

**Status:** Proposed  
**Audience:** maintainers, contributors, QA, accessibility testers, native Persian reviewers  
**Scope:** Persian dictation, Persian text handling, RTL-safe output, Persian-English code-switching, documentation, benchmarking, and release qualification  
**Non-goal:** this document does not itself claim that YazSes currently provides production-quality Persian recognition.

---

## 1. Why this is a program, not a single switch

YazSes already contains Persian-aware pieces:

- `[stt] language = "fa"` reaches multilingual faster-whisper;
- the Settings language picker exposes **Persian / فارسی**;
- multilingual documentation already explains that non-English use requires a non-`.en` model;
- `fa-en` is the canonical pair in the Polyglot design;
- the transliteration feature contains a built-in Finglish -> Persian mapping;
- contract tests already use Persian as an RTL stress language;
- `docs/fa/index.md` exists but is still a native-review draft;
- ADR-003 already requires the local LLM path to cover Persian/multilingual text.

These pieces are useful groundwork, but they do not yet form a support contract. YazSes still lacks:

1. a measured Persian ASR baseline;
2. Persian-specific output normalization;
3. an RTL injection qualification matrix;
4. a Persian-English mixed-language benchmark;
5. release criteria for saying "Persian is supported".

Persian support is therefore split into five independently testable capabilities:

1. recognize Persian speech;
2. emit stable Persian Unicode;
3. inject/display RTL text safely;
4. preserve Persian-English mixed speech and text;
5. document the feature honestly in Persian and English.

No one capability proves the others.

## 2. Product target

A Persian user should be able to choose Persian once, dictate ordinary Persian into a supported application, receive stable Persian-script text, and keep the same offline/privacy guarantees as English users.

Initial baseline configuration:

```toml
[stt]
model = "small"
language = "fa"
```

This is a **benchmark starting point**, not a permanent recommendation. The final preset must be chosen from measured accuracy, latency, memory, and platform behavior.

The English default must remain unchanged.

## 3. Support levels

### P0 — plumbing

- `fa` selectable;
- language reaches decoder;
- multilingual-model mismatch diagnosed;
- UTF-8 output reaches the injection layer.

No accuracy claim.

### P1 — experimental Persian

- Persian Unicode/RTL contract tests;
- reproducible benchmark harness;
- published model/config results;
- documented limitations;
- English regression suite remains green.

### P2 — Persian preview

- measured recommended model/config;
- Persian normalization profile enabled;
- Linux/macOS/Windows injection verification;
- at least three native-speaker field reports;
- Persian docs reviewed by a native speaker;
- no open P0/P1 text-corruption bugs.

### P3 — supported Persian

- two independent public evaluation corpora;
- frozen benchmark protocol and versioned result schema;
- release-candidate revalidation;
- accessibility pass;
- Persian-English code-switch status explicitly qualified;
- support wording tied to measured evidence.

## 4. Architecture rules

### 4.1 Reuse the existing STT boundary

Do not create a Persian-only daemon or second transcription pipeline.

```text
audio
  -> existing capture/VAD
  -> SttEngine
  -> language output profile
  -> generic post-processing
  -> command-safety path
  -> injection backend
```

The language output profile must be deterministic, offline, and lightweight.

### 4.2 Generalize language-specific post-processing

Chinese currently has a script-normalization wrapper. Persian should motivate a general language-profile abstraction rather than another hard-coded daemon branch.

Proposed interface:

```text
LanguageOutputProfile
  language_code
  normalize_text(text, context)
  normalize_word(word, context)
  validate(text)
```

Languages without a profile remain pass-through.

### 4.3 Keep three operations separate

- **Recognition:** Persian speech -> Persian transcript.
- **Normalization:** Persian transcript -> stable Persian transcript.
- **Transliteration:** Finglish/Latin -> Persian script.

Native Persian dictation must not silently activate transliteration.

### 4.4 No silent model substitution

`language = "fa"` with `base.en`, `small.en`, or another English-only model must produce an actionable error/warning before the user trusts the result.

If an engine does not support Persian, the UI and doctor output must say so. Do not fall back to English transcription while presenting the session as Persian.

### 4.5 Parakeet is not the Persian plan

The current Parakeet multilingual path is not the Persian backend. Persian should stay on faster-whisper unless another local engine explicitly supports Persian and passes the same benchmark gates.

## 5. Workstreams

### WS-1 — Language profile and configuration

Deliver:

- language-profile registry;
- Persian profile activated only for `fa`;
- pass-through for all other languages;
- Persian preset in Settings;
- model/engine compatibility diagnostics;
- `yazses doctor` output for language, engine, model, multilingual capability, and profile status.

Acceptance:

- choosing Persian changes only the Persian configuration;
- incompatible English-only model pairing is rejected or clearly diagnosed;
- existing English output remains unchanged.

### WS-2 — Persian Unicode normalization

Implement the rules in `persian-text-and-rtl.md`.

Principle: **canonicalize obvious encoding variants; do not invent grammar.**

Safe examples:

- Unicode NFC;
- Arabic Yeh -> Persian Yeh where appropriate;
- Arabic Kaf -> Persian Keheh where appropriate;
- preservation of meaningful ZWNJ;
- conservative whitespace handling.

Do not add dictionary-based half-spaces in the default path.

### WS-3 — Benchmark and model selection

Implement `persian-benchmark-and-validation.md`.

Minimum candidates:

- multilingual Whisper base;
- multilingual Whisper small;
- multilingual Whisper medium;
- Whisper large-v3;
- Whisper large-v3-turbo when reproducible in the pinned stack;
- Persian-specific community checkpoints only when license, training-data provenance, conversion, and reproducibility are documented.

Select the recommendation from measurement, not reputation.

### WS-4 — RTL display and injection qualification

Test independently:

1. internal transcript representation;
2. overlay/tray/settings rendering;
3. clipboard injection;
4. native injection backends.

Required content:

- Persian only;
- Persian + ASCII digits;
- Persian + Persian digits;
- Persian punctuation;
- embedded English names;
- URLs/emails/paths;
- ZWNJ-containing words;
- multiline text;
- emoji;
- copy/paste round trip;
- cursor placement where testable.

A visual bidi bug and a Unicode corruption bug are separate defects.

### WS-5 — Persian-English code-switching

Reuse `[polyglot] pair = "fa-en"`.

Phase A:

- benchmark current per-span routing;
- publish mixed error rate and boundary failures;
- run Persian normalization only on Persian spans.

Phase B:

- train/obtain a dedicated adapter only if Phase A misses the agreed gate;
- keep training data out of runtime packaging;
- require held-out improvement before describing the adapter as better;
- preserve opt-in `adapter_path`.

Normal Persian dictation must never depend on a code-switch adapter.

### WS-6 — Documentation and native review

- complete native review of `docs/fa/index.md`;
- keep draft status until a named native reviewer approves reviewed scope;
- add a Persian voice-typing guide only after benchmark data exists;
- document exact model/config requirements;
- document RTL/injection troubleshooting;
- link benchmark evidence;
- keep the rule: translated docs are not proof of STT quality.

## 6. Release gates

Persian **preview** requires all of:

- benchmark artifacts for at least two public Persian corpora;
- measured recommended model/config;
- no known text corruption in Linux/macOS/Windows matrix;
- Persian normalization contract tests;
- English regression tests;
- native-reviewed Persian quickstart;
- explicit known limitations.

Persian **supported** requires a later release to repeat those gates successfully. A one-off good run is not enough for a permanent support claim.

## 7. Community issue decomposition

### FA-01 — Language-profile architecture
**Skills:** Python architecture  
**Blocked by:** none  
**Output:** registry + pass-through profile + tests  
**Acceptance:** no behavior change outside `fa`.

### FA-02 — Conservative Persian normalizer
**Skills:** Python, Unicode  
**Blocked by:** FA-01  
**Output:** pure module + tests  
**Acceptance:** rules in `persian-text-and-rtl.md`; idempotent.

### FA-03 — Persian contract vectors
**Skills:** testing; good first issue  
**Blocked by:** FA-02 interface  
**Output:** portable Persian/RTL/mixed-script vectors.

### FA-04 — Persian benchmark harness
**Skills:** Python/data/ASR  
**Blocked by:** none  
**Output:** reproducible Common Voice + FLEURS runner.

### FA-05 — CPU model sweep
**Skills:** benchmarking  
**Blocked by:** FA-04  
**Output:** accuracy + latency + memory table.

### FA-06 — Recommended Persian preset
**Skills:** configuration/product  
**Blocked by:** FA-05  
**Output:** measured preset and compatibility guardrails.

### FA-07 — RTL overlay/settings audit
**Skills:** Qt/UI  
**Blocked by:** FA-02  
**Output:** mixed RTL/LTR display validation.

### FA-08 — Cross-platform injection matrix
**Skills:** Linux/macOS/Windows QA  
**Blocked by:** FA-02, FA-03  
**Output:** exact-code-point injection results.

### FA-09 — fa-en evaluation protocol
**Skills:** bilingual Persian/English, data  
**Blocked by:** benchmark schema  
**Output:** consented/licensed evaluation set or reproducible local collection protocol.

### FA-10 — fa-en routing qualification
**Skills:** ASR/polyglot  
**Blocked by:** FA-09  
**Output:** measured baseline before adapter training.

### FA-11 — Native Persian documentation review
**Skills:** native Persian; browser-only  
**Blocked by:** none  
**Output:** reviewed `docs/fa/index.md`.

### FA-12 — Persian voice-typing guide
**Skills:** documentation  
**Blocked by:** FA-05, FA-06, FA-08  
**Output:** measured setup guide with limitations.

### FA-13 — Persian preview release gate
**Skills:** maintainer/QA  
**Blocked by:** relevant prior tasks  
**Output:** evidence-linked release checklist.

## 8. Explicit non-goals for the first milestone

Do not block initial Persian preview on:

- full Persian UI localization;
- Persian voice-command grammar;
- Persian TTS/read-back;
- a trained fa-en adapter;
- aggressive grammatical half-space insertion;
- local-LLM rewriting;
- cloud ASR fallback.

The first milestone is a small, offline, measurable, non-destructive Persian dictation path.

## 9. Definition of done

Repository evidence must answer:

1. Which configuration should a Persian user choose?
2. Which model was measured, on which data, and on what hardware?
3. What errors remain?
4. Which Unicode changes does YazSes make?
5. Does final text survive supported injection backends?
6. What happens to embedded English?
7. What is the status of fa-en code-switching?
8. Which parts were reviewed by native Persian speakers?
9. What evidence justifies support wording?
10. Can validation be repeated without cloud speech processing?

If an answer depends on maintainer memory instead of a file, test, or result artifact, the Persian program is not done.

## 10. External references

- Whisper large-v3: https://huggingface.co/openai/whisper-large-v3
- Whisper large-v3-turbo: https://huggingface.co/openai/whisper-large-v3-turbo
- NVIDIA Parakeet TDT 0.6B v3: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Mozilla Common Voice datasets: https://commonvoice.mozilla.org/en/datasets
- Google FLEURS: https://huggingface.co/datasets/google/fleurs
- Unicode UAX #31: https://www.unicode.org/reports/tr31/
