# Chinese support — current-state assessment

**Status:** Assessment of `main` as of 2026-09-20  
**Purpose:** Identify what is already implemented, what is only documented, what is unsafe to expose as a product-level switch, and which architectural seams should be preserved.

## Executive finding

YazSes does **not** need a new Chinese transcription pipeline.

The current architecture already has the correct low-level seams:

- the STT backend is abstracted behind `SttEngine`;
- faster-whisper accepts a configured spoken language and that value reaches all three decode paths;
- multilingual Whisper model names are already understood by the downloader;
- contradictory `.en` + non-English configurations are detected;
- Han-script normalization is already implemented once at the STT factory boundary;
- Simplified and Traditional documentation translations already exist independently of speech recognition.

The gap is above those primitives. There is no first-class operation that says “configure YazSes coherently for Mandarin.” Users currently compose multiple settings manually, and the voice-command classifier remains English-only.

The safest path is therefore to add a **language-profile orchestration layer and localized command grammar** around the existing engine, not a Chinese-specific fork.

---

## Layer-by-layer audit

| Layer | Current state | Chinese readiness | Required action |
|---|---|---:|---|
| Audio capture/VAD | Language-neutral 16 kHz speech path | Ready | None specific to Chinese; validate representative speech levels only. |
| STT engine interface | `SttEngine` protocol: `transcribe`, `transcribe_words`, `decode_window` | Ready | Preserve unchanged for P1. |
| faster-whisper language | `FasterWhisperEngine(language=...)`; shared `_decode_kwargs` reaches batch, word and streaming paths | Ready | Reuse `language="zh"`. |
| Default model | `base.en` | Incompatible | Language preset must move to a multilingual checkpoint before writing `zh`. |
| Model compatibility check | `language_model_problem()` detects non-English + `.en` | Good primitive | Promote from warning/refusal into language-profile preflight. |
| Model download | Explicit helper and cache-aware loading | Ready | Language plan should report/download chosen checkpoint before commit. |
| Chinese script | `[stt] chinese_script`; OpenCC wrapper at STT factory | Ready, optional dep | Make script part of coherent Chinese profile and preflight dependency. |
| Script aliases | `zh-CN/Hans` -> Simplified; `zh-TW/Hant/HK` -> Traditional | Partially ready | Keep aliases for script conversion, but do not interpret `zh-HK` as a speech locale. |
| Settings UI language | Dropdown includes Chinese `zh` | Partial | Add high-level language preset control using shared resolver; leave model controls advanced. |
| CLI language switch | No atomic live-dictation language command | Missing | Add `yazses language list/status/set`. |
| File transcription | Language/model overrides and shared engine path | Mostly ready | Add tests proving profile defaults are inherited and per-file overrides still win. |
| Meeting transcription | Shared engine/factory architecture | Likely ready | Add explicit integration tests; do not rely on architectural assumption alone. |
| Voice command grammar | English regexes and English number-word normalization | Missing | Add language-aware grammar registry; Chinese parser maps to existing semantic actions. |
| Command dispatch | Action names are language-neutral | Ready | No Chinese branches in dispatch. |
| Macros | User-defined trigger strings | Language-neutral by data | Keep exact-match behavior; document that users may define Chinese triggers. |
| Tier-2 SLM routing | Separate optional router | Not required | Do not make it a Chinese dependency in P1. |
| Text injection | Backends vary by OS/session | Needs validation | Validate Han text on each supported desktop path; prefer clipboard fallback where key synthesis is unsafe. |
| Documentation localization | `docs/zh-CN`, `docs/zh-TW`, i18n process | Separate and established | Do not couple locale selection to STT settings. |
| Mandarin-English code switch | Separate Polyglot Switch design | Not P1 | Keep as an independent later feature. |
| Cantonese | No P1 product contract | Not ready | Separate model/corpus/profile work; do not hide under “Traditional Chinese”. |

---

## Existing components to preserve

### 1. `SttEngine` is the architectural boundary

`src/yazses/stt/base.py` intentionally keeps the engine protocol tiny. Chinese P1 should not add methods such as `transcribe_chinese()`, a Chinese-only result type, or call-site checks like:

```python
if language == "zh":
    ...
```

Any future Chinese-specialized recognizer must implement the same protocol and be selected by the existing factory.

### 2. The language decoder wiring is already correct

`src/yazses/stt/faster_whisper.py` centralizes decode options in `_decode_kwargs()`. This is important because the repository already had a historical failure where a documented language setting did not reach all decode paths.

Chinese work must not reintroduce per-call-site language kwargs. All live, streaming, word-timestamp, file and meeting flows should continue to receive language through engine construction.

### 3. Han conversion is correctly placed after recognition

`src/yazses/stt/factory.py` wraps the raw engine in `_HanScriptEngine`. That gives one conversion chokepoint for:

- plain transcript text;
- word-timestamp output;
- streaming windows.

This is preferable to asking each recognizer to emit a specific script. A recognizer decides what it heard; the output policy decides which equivalent Han script the user wants.

P1 should preserve this decorator design.

### 4. Command dispatch is already language-neutral

The important abstraction in `commands/grammar.py` / `commands/dispatch.py` is:

```
spoken phrase -> CommandIntent(action="save", ...)
             -> action dispatch
```

Only the left side is English-specific. `action="save"`, `action="undo"`, `action="go_to_line"`, etc. are semantic IDs and should stay canonical.

Chinese support should add another parser that emits the same actions rather than copying dispatch logic.

---

## Product-level gaps

### Gap A — users can construct an invalid half-switch

Today these settings are individually editable:

```toml
[stt]
model = "base.en"
language = "zh"
chinese_script = "simplified"
```

The factory warns that `base.en` cannot decode Chinese, but the configuration is still representable. Likewise, enabling only `chinese-script` on a default install can report the feature as enabled while the recognizer is physically unable to emit Han text.

This is acceptable for advanced manual configuration, but not for the primary Chinese workflow.

**Required:** one planned transaction that validates model, language, script dependency and command-language behavior before writing any setting.

### Gap B — `chinese-script` is not “enable Chinese”

The feature registry correctly scopes `chinese-script` to output conversion, but it is an easy capability name for users to interpret as full Chinese support.

Do **not** expand that toggle to mutate model and language. It should remain a narrowly scoped feature because:

- Traditional users may want it with an already configured Chinese model;
- future engines may already produce the desired script;
- changing a model is a large download/performance decision and should not happen behind a text-normalization toggle.

Instead, `yazses language set zh-CN` orchestrates the multiple independent keys explicitly.

### Gap C — command grammar is English-only

Current Tier-1 grammar includes English lexical rules and English number words. In Chinese dictation mode, phrases such as:

- “撤销”
- “保存文件”
- “复制”
- “粘贴”
- “删除最后三个词”
- “跳到第 42 行”

fall through to dictation today.

That is not only a missing convenience. A user switching languages expects the core “dictation versus command” decision to remain functional.

The fix belongs in grammar selection, not dispatch.

### Gap D — injection support is not equivalent to transcription support

Recognizing `你好世界` is not enough. The final backend must reliably place it in the target application.

The existing multilingual documentation already acknowledges backend differences, especially on Wayland. Chinese support needs an explicit platform validation matrix rather than assuming UTF-8 text is equivalent to synthesizable keyboard events.

### Gap E — Chinese quality evidence is too small for a support claim

The repository has valuable existing measurements on 20 ASCEND utterances. They demonstrate a real script-normalization effect and give a useful smoke benchmark, but they are not sufficient to claim production-quality Mandarin across accents, microphones, environments, sentence styles and platforms.

The existing user-facing page is therefore correct to say YazSes does not yet claim Chinese support.

The implementation must preserve that wording until ADR-v2-144’s release gate passes.

---

## Naming and semantic hazards

### Speech language is not script

`zh` answers “what language should ASR decode?”  
`simplified` / `traditional` answers “how should Han output be rendered?”

These must remain separate.

### Documentation locale is not speech language

`docs/zh-CN/` means a Simplified Chinese documentation audience. It does not configure the recognizer. An English-speaking user can read that page; a Chinese-speaking user may use the English UI.

Never derive `[stt] language` from OS/UI/docs locale without an explicit user operation.

### `zh-HK` is especially dangerous

The Han normalizer currently accepts `zh-HK` as an alias for Traditional script. That is reasonable inside a **script resolver**.

It must **not** become a P1 speech profile alias:

- Traditional script is used for Mandarin in Taiwan and for Cantonese in Hong Kong.
- The speech model language code and evaluation corpus must distinguish those use cases.
- P1 is Mandarin.

Therefore:

- `zh-TW` / `zh-Hant` -> Mandarin speech + Traditional output in P1.
- `zh-HK` -> refuse as an automatic P1 language preset with an explanation.
- A future Cantonese profile should use an explicit speech-language identity (for example `yue`) backed by a validated engine.

### “profile” is already overloaded

`CommandsConfig.profile` currently means application/editor behavior (auto/VS Code/etc.), not spoken language.

Do not reuse it for Chinese.

Add a dedicated `commands.language` selector (recommended default `"auto"`, resolving from STT language) or an equivalent explicit grammar-language field.

---

## Chinese command-parser considerations

Chinese Tier-1 parsing cannot be a direct character-for-character translation of the English regex table.

It needs locale-specific normalization for command recognition only:

- Chinese terminal punctuation: `。！？；：`;
- optional spaces inserted by ASR around Latin identifiers or numbers;
- Arabic digits and common Chinese numerals;
- classifiers such as “第 … 行”;
- synonyms that native speakers naturally use;
- Traditional-character variants where the phrase differs by script.

Important: normalization applies to the **command candidate**, not to ordinary dictated text. Do not globally NFKC/strip/convert user prose in order to make commands match.

Suggested P1 numeral coverage:

- `一` through `十`;
- compositional 11–99 (`十一`, `二十五`);
- common `两` where natural;
- Arabic numerals unchanged.

Larger number parsing can be added once requirements demonstrate it.

---

## Compatibility risks

### English regression

The dominant risk is not Chinese failure; it is accidentally changing the default English path.

Guardrails:

- `SttConfig()` remains `base.en` + `en`;
- no Chinese dependency is imported when Chinese script normalization is off;
- English grammar behavior remains byte/semantic compatible;
- command-language `auto` must resolve to English under the current default config;
- no additional model is loaded on English startup.

### Config evolution

Older configs do not contain new language-profile metadata. The design should avoid requiring metadata at all.

Profiles should be **resolvers over existing canonical settings**, not persistent truth. Status can be derived from the current keys.

### Optional dependency failure

OpenCC absence must not crash the daemon. Existing behavior already degrades honestly.

The high-level language setter should improve this by preflighting/installing the optional dependency before committing a profile that requires deterministic script output.

### Model download failure

A failed Chinese model download must leave the previous English config untouched.

This is the strongest reason for “download/preflight first, commit second.”

---

## What should not be changed in P1

- Do not replace the default English model.
- Do not make auto-language detection the default.
- Do not add Chinese branches to audio, daemon injection, meeting, file-transcription or dispatch call sites.
- Do not move OpenCC into the mandatory base dependency.
- Do not bundle a second ML runtime before benchmarks justify it.
- Do not rename the existing `language` key.
- Do not merge code-switching into monolingual Chinese support.
- Do not claim Cantonese because an output script is Traditional.
- Do not couple docs/UI locale to speech behavior.

---

## Recommended first implementation sequence

1. Introduce pure language-profile resolver + plan object, no writes.
2. Add tests for profile resolution and invalid aliases.
3. Add atomic config application with dry-run/preflight/rollback behavior.
4. Add CLI `language list/status/set`.
5. Add Settings UI integration using the same resolver/controller.
6. Refactor grammar selection without changing English behavior.
7. Add Chinese grammar + numeral/punctuation normalization.
8. Add doctor diagnostics.
9. Run injection/platform validation.
10. Run reproducible Chinese model benchmark.
11. Run native-speaker validation.
12. Only then update the user-facing support claim.

This order keeps the high-risk behavioral changes small and independently reviewable.
