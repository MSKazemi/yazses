# ADR-v2-138 — Spoken language, Han script, and UI/documentation locale are independent dimensions

**Status:** Proposed (2026-09-20)  
**Context:** `[stt] language`; `[stt] chinese_script`; `docs/zh-CN`; `docs/zh-TW`; Cantonese scope.

## Context

“Chinese” can refer to several distinct technical choices:

- the language spoken into ASR;
- the written Han script desired in output;
- the locale of documentation/UI strings;
- regional varieties such as Mandarin and Cantonese.

The repository already correctly separates the first two: Whisper language uses `zh`, while `chinese_script` selects Simplified or Traditional conversion.

However, aliases such as `zh-HK` are valid inside a script converter and can become dangerous if reused as a speech-profile definition. Traditional characters do not imply Mandarin or Cantonese.

The documentation localization tree also contains `zh-CN` and `zh-TW`, but reading a localized page must never silently change dictation behavior.

## Decision

Treat these as independent dimensions:

### Speech language

P1 supports Mandarin speech through:

```toml
[stt]
language = "zh"
```

### Output script

P1 supports:

```toml
chinese_script = "simplified"
```

or:

```toml
chinese_script = "traditional"
```

using the existing OpenCC postprocessor.

### UI/documentation locale

Localization remains in the existing `i18n/` + `docs/<locale>/` system and has no implicit effect on STT.

### Profile aliases

- `zh-CN`, `zh-Hans` => Mandarin + Simplified output.
- `zh-TW`, `zh-Hant` => Mandarin + Traditional output.
- `zh-HK` => **not a P1 speech profile**. Reject with guidance because the user may mean Cantonese.
- Future Cantonese support uses an explicit speech identity (e.g. `yue`) and its own validated model/corpus decision.

The existing Han-script normalizer may continue accepting `zh-HK` as a **script alias** because its input contract is only “which script target?”, not “which language is spoken?”

## Consequences

### Positive

- No accidental claim that Hong Kong Traditional Chinese means Mandarin.
- Users can use an English UI while dictating Mandarin.
- Users can read Chinese docs while dictating English.
- Script conversion remains replaceable and testable independently of ASR.
- Cantonese gets a clean future path rather than being hidden in a Mandarin preset.

### Costs

- User-facing wording must say “Mandarin” where speech is meant, not merely “Chinese”.
- Settings need separate language and script concepts.
- Profile alias resolver cannot blindly reuse the OpenCC alias table.

## Alternatives considered

### Treat `zh-CN/TW/HK` as ASR language codes directly

Rejected. Whisper’s `zh` language identity does not encode the regional speech distinction this suggests, and `zh-HK` is ambiguous with Cantonese.

### Infer speech language from OS/UI locale

Rejected. Locale is not a reliable statement of what the user wants to dictate, and silent inference would be surprising.

### Let the model pick Simplified/Traditional automatically

Available as the advanced empty-script setting, but rejected as the first-class Chinese profile behavior because existing measurements show substantial per-utterance inconsistency.

## Documentation rule

Any future documentation must distinguish these claims:

- “Simplified Chinese interface/documentation”
- “Mandarin speech recognition”
- “Traditional Han output”
- “Cantonese speech recognition”

They are not interchangeable.
