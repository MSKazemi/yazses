# ADR-v2-140 — Language profiles are transactional presets over canonical config

**Status:** Proposed (2026-09-20)  
**Context:** First-class Chinese language support; `SttConfig.language`; model compatibility; Settings/CLI consistency.

## Context

YazSes already exposes the low-level settings required for Mandarin:

- `[stt] model`
- `[stt] language`
- `[stt] chinese_script`

Those keys are individually correct but jointly constrained. A default installation can represent this invalid intermediate state:

```toml
[stt]
model = "base.en"
language = "zh"
chinese_script = "simplified"
```

`base.en` cannot decode Chinese. The current factory warns, but a high-level “switch to Chinese” control cannot safely implement itself as three independent config writes.

The same issue appears when switching back: forcing the English-only model every time would cause an unnecessary download and discard a perfectly valid multilingual model.

We also need CLI and Settings to make exactly the same decision. Duplicating model/language compatibility logic in each surface would drift.

## Decision

Introduce **language profiles as pure presets/resolvers**, not as a second persistent configuration system.

A language profile maps a user intent such as `zh-CN` to a **LanguagePlan** containing the minimal coherent mutations and prerequisites.

Canonical state remains the existing configuration keys. We do **not** persist an `active_profile` key.

The public high-level operation is transactional:

```text
resolve -> preflight dependencies/model -> validate candidate
        -> atomic config write -> restart once
```

If preflight or validation fails, no config key changes.

### Profile semantics

P1 profiles:

| Requested profile | Speech language | Han script | Recommended engine/model |
|---|---|---|---|
| `en` | en | off | faster-whisper / base.en |
| `zh-CN`, `zh-Hans` | zh | simplified | faster-whisper / small |
| `zh-TW`, `zh-Hant` | zh | traditional | faster-whisper / small |

`zh-HK` is not a P1 speech alias because Hong Kong language choice raises a Cantonese-vs-Mandarin distinction that a script alias cannot answer.

### Preserve-first behavior

By default, switching profiles preserves a current engine/model when that pair is compatible with the requested speech language.

Example: a user on multilingual `small` switching from Chinese back to English keeps `small`; no reason exists to download `base.en` just to regain English.

An explicit `--recommended-model` operation may restore the profile’s measured/default performance preset.

### Status is derived

`yazses language status` derives whether current settings:

- exactly match a profile;
- are profile-compatible but customized;
- are incoherent.

No stored profile identity is required.

## Consequences

### Positive

- A user never sees a half-applied language switch.
- Existing hand-edited configs remain first-class.
- CLI and GUI can consume one resolver.
- Profile definitions can evolve without migrations to an “active profile” field.
- Switching back to English need not redownload or throw away a multilingual model.
- Advanced model selection remains possible.

### Costs

- Multi-key config writes need a true transaction/atomic replace instead of repeated single-key mutations.
- Status derivation needs compatibility logic.
- Model/dependency preflight happens before committing configuration and can make the high-level operation more involved than a simple TOML edit.

## Alternatives considered

### Persist `[language] active_profile = "zh-CN"`

Rejected. It becomes a second source of truth as soon as a user changes `[stt] model` manually. Every settings mutation would have to maintain profile identity, and migrations would need reconciliation rules.

### Make `chinese-script` toggle switch the model/language too

Rejected. Script normalization is a narrow output policy and remains useful independently. A text-conversion toggle should not hide a model download or alter recognition language.

### Let each UI surface write the necessary keys

Rejected. It duplicates compatibility and creates observable intermediate states.

### Always reset to each profile’s recommended model

Rejected as the default. It causes unnecessary downloads and destroys deliberate custom model choices. It remains available as an explicit operation.

## Implementation constraints

- Resolver is pure and import-light.
- Model/dependency download is preflighted before config commit.
- Existing English default behavior remains unchanged.
- Failed Chinese setup leaves previous config intact.
- CLI/Settings/doctor use shared compatibility functions.
