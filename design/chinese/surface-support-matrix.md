# Chinese support — product surface and compatibility matrix

**Status:** Proposed scope contract  
**Purpose:** Prevent “Chinese support” from being treated as one boolean. Each YazSes surface has its own implementation dependency, validation method, and release state.

Legend:

- **P1** — intended first-class Mandarin scope.
- **Conditional** — can be P1 only if its named blocker is cleared.
- **Existing primitive** — low-level support exists already but still needs end-to-end validation.
- **Deferred** — deliberately outside P1.

> **Implementation update (2026-10-29):** The table distinguishes intended P1
> support from current evidence. The old Meeting Mode Han-count defect was repaired
> and is covered by model-free tests; **real Mandarin meeting quality is still
> unvalidated**. The CLI/Settings/profile resolver, Tier-1 safe command grammar and
> CJK renderers are implemented, but native command acceptance, benchmark and actual
> OS Unicode input remain open. See
> [as-built audit](2026-10-29-as-built-audit.md) and
> [release validation matrix](2026-10-29-validation-and-release-gates.md).

## Product surfaces

| Surface | P1 target | Current architectural basis | Extra work/evidence | Release condition |
|---|---|---|---|---|
| Hold-to-talk final dictation | **P1** | `SttEngine` + `language=zh` + Han normalizer | atomic switch; real Mandarin benchmark; injection | required |
| Streaming partial/final text | **Conditional** | `decode_window` already receives language and wrapper conversion | latency/stability benchmark; partial/final script consistency | include only if measured |
| Word timestamps | **P1** for Whisper baseline | `transcribe_words`; wrapper converts per-word text | Chinese timestamp smoke + subtitle rendering | required for timestamp claim |
| File transcription | **P1** | shared engine factory and CLI language overrides | inheritance/override tests; real file run; metadata | required |
| Long-form file transcription | **Conditional** | same engine | repetition/hallucination stress run | required for long-form claim |
| Meeting live transcript | **Conditional** | shared configured engine | effective language metadata; Chinese rendering | require meeting audit |
| Meeting batch transcript | **Conditional** | shared engine/factory | long-form decode stability | require meeting audit |
| Meeting quality gate | **Conditional: Han-quality implementation exists; real Mandarin release evidence missing** | `meeting/quality.py::tokenize` and `store.live_word_count()` have CJK quality units and regression tests | run genuine healthy/thin/repetition meetings; check threshold sensitivity and notes context capacity | **do not include meeting claim without measured validation** |
| Meeting minutes | **Deferred until Chinese meeting transcript is trustworthy** | downstream of transcript | verify summary backend/formatting language assumptions separately | separate evidence |
| Tier-1 edit commands | **Conditional P1** | `commands/grammars/zh.py` safe-core exists with anchored rules and negative tests | all `PHRASE_REVIEW` entries provisional; native Simplified + Traditional review required | **native safety approval required** |
| Tier-1 navigation commands | **Conditional P1** | localized grammar/numeral parser implemented | review natural phrases, numeric bounds and false positives in real speech | **native language approval required** |
| Terminal/open-ended run commands | **Deferred or narrow P1 subset** | safety-sensitive existing actions | native phrasing + false-positive corpus + safety-gate proof | do not broaden casually |
| User macros | **Existing primitive** | trigger strings are data | Chinese exact-match fixtures/docs | non-blocking |
| Tier-2 SLM command router | **Deferred** | optional existing path | Chinese model/router evidence | not a P1 dependency |
| Simplified output | **P1** | OpenCC `t2s` decorator | dependency preflight + native acceptance | required |
| Traditional output | **P1** | OpenCC `s2t` decorator | separate native acceptance | required |
| Regional Taiwan/HK vocabulary conversion | **Deferred** | not the current converter’s contract | separate ADR if wanted | not implied by Hant |
| Mandarin-English code switching | **Deferred** | Polyglot Switch design | separate pair model/evaluation | not implied by Mandarin |
| Cantonese | **Deferred** | no P1 model/profile contract | explicit `yue` model/corpus/commands | not implied by Traditional |
| Settings UI language selector | **P1 implementation exists** | Qt-free `settingsui/language_view.py` and shared apply/controller tests | actual Qt/app workflow on supported OS and crash/error recovery | **real Settings smoke required** |
| CLI `language list/status/set` | **P1 implementation exists** | `language/profiles.py`, `plan.py`, `service.py`, `cli.py` with automated tests | real install/cache/restart and cross-OS packaging smoke | **release gate still required** |
| `doctor` diagnostics | **P1** | existing diagnostics | shared coherence checks | required |
| Documentation localization | **Already separate** | `docs/zh-CN`, `docs/zh-TW`, i18n process | keep decoupled from speech | never auto-switch STT |
| Desktop notification text | **Not a speech blocker** | UI strings/localization | localization project if desired | independent |
| Learning/personal vocabulary | **Conditional** | existing engine-agnostic/Whisper mechanisms | audit tokenization/Chinese correction semantics | may remain experimental |
| Prosody formatting | **Conditional** | word timing postprocessor | audit CJK text assumptions | exclude if destructive |
| Filler/disfluency filters | **Conditional** | some English-tuned rules | postprocess audit | default-on destructive filters block |
| Number/date normalization | **Conditional** | generic/English-tuned transforms | CJK audit | gate or disable by language |
| Transliteration | **Separate feature** | translit capability | no dependency on Mandarin profile | do not chain automatically |
| Read-back/TTS | **Deferred from core P1 unless already language-capable** | separate output capability | Chinese voice/model evidence | separate support claim |
| Desktop only | **P1** | current design scope | Linux/macOS/Windows validation | required |
| Mobile | **Deferred** | separate mobile architecture | separate language support project | not inherited automatically |

## Injection matrix

A recognizer passing CER does not certify text delivery.

Use this exact fixture family, preserving mixed Han/Latin/digits/punctuation:

```text
Simplified: 你好，世界。简体中文测试 123，YazSes。
Traditional: 你好，世界。繁體中文測試 123，YazSes。
Mixed: 今天 review PR #378，然后保存文件。
```

| Platform/session | Primary backend | P1 status before test | Evidence required | Fallback |
|---|---|---|---|---|
| Linux X11 | current X11 injector | unverified for Han | exact-text comparison in GTK/Qt/browser/Electron | clipboard |
| Linux Wayland | current Wayland/ydotool path | unverified / likely backend-dependent | exact-text comparison + layout/environment record | clipboard |
| macOS | native injector | unverified for Han | exact-text comparison in TextEdit/browser/editor | clipboard |
| Windows | native injector | unverified for Han | exact-text comparison in Notepad/browser/editor | clipboard |

Each report records OS/session, backend selected, target app, expected string, actual string, and whether fallback was used. No usernames, home paths, hostnames, clipboard contents unrelated to the fixture, or private dictated text are committed.

## Language-profile matrix

| User request | Speech model language | Output script | P1 result |
|---|---|---|---|
| `en` | en | none | available; preserves compatible multilingual model by default |
| `zh-CN` | zh (Mandarin) | Simplified | P1 |
| `zh-Hans` | zh (Mandarin) | Simplified | alias of zh-CN |
| `zh-TW` | zh (Mandarin) | Traditional | P1 |
| `zh-Hant` | zh (Mandarin) | Traditional | alias of zh-TW |
| `zh-HK` | ambiguous | Traditional is not enough to choose speech language | refuse in P1 with explanation |
| `yue-HK` | Cantonese | Traditional | planned only after separate ADR/model/eval |

## Postprocessor audit matrix template

CHN-30 must fill this from code, not assumptions:

| Component | Default on? | Text assumption | Chinese-safe? | Decision | Test |
|---|---:|---|---:|---|---|
| burst spacing | TBD | whitespace/token boundary | TBD | preserve/fix/gate | fixture |
| sentence casing | TBD | Latin casing | TBD | no-op/gate | fixture |
| filler removal | TBD | English lexical list | TBD | language gate | fixture |
| vocabulary correction | TBD | token/word similarity | TBD | test/gate | fixture |
| number normalization | TBD | English number grammar | TBD | test/gate | fixture |
| prosody formatting | TBD | word timestamps | TBD | test/gate | fixture |
| meeting quality | TBD | word/ngram counts | TBD | language-neutral fix/exclude | long-form fixture |

A row cannot be marked safe solely because it did not throw an exception.

## Support wording rule

Documentation should name the actual green cells rather than say only “Chinese supported.”

Example after a partial successful gate:

> Mandarin hold-to-talk and file transcription are validated for Simplified and Traditional output on Windows, macOS and Linux X11. Wayland uses clipboard fallback. Chinese Meeting Mode remains experimental while its transcript-quality metrics are being validated.

That wording is more useful and more durable than a single support badge.
