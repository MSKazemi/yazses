# Spec: First-class Mandarin language support

| Field | Value |
|---|---|
| **ID** | spec-chinese-language-support |
| **Status** | Proposed |
| **Date** | 2026-09-20 |
| **Primary modules** | `src/yazses/language/` (new), `src/yazses/commands/`, `src/yazses/settingsui/`, `src/yazses/system/doctor.py` |
| **Existing STT modules reused** | `stt/base.py`, `stt/factory.py`, `stt/faster_whisper.py`, `postprocess/han_script.py` |
| **P1 speech scope** | Mandarin (`zh`) |
| **P1 output scripts** | Simplified and Traditional Han |
| **P1 recognizer** | faster-whisper, multilingual `small` supported-baseline candidate |
| **Offline contract** | all inference local after explicit one-time artifact setup |

## 1. Problem statement

YazSes already contains the primitives needed to transcribe Mandarin, but they are exposed as independent low-level settings. A user must understand that:

- `base.en` cannot decode Mandarin;
- a multilingual model must be selected;
- `language = "zh"` must reach recognition;
- output script is an independent preference;
- OpenCC is optional;
- English-only command regexes will not understand Chinese commands;
- some text-injection backends are less reliable for non-Latin scripts.

The project therefore has **manual Mandarin configuration**, not a coherent Mandarin product capability.

This spec adds a first-class, validated workflow without creating a Chinese-specific transcription architecture.

---

## 2. Goals

### Functional goals

1. Switch a default English installation to Mandarin/Simplified with one operation.
2. Switch to Mandarin/Traditional with one operation.
3. Switch back to English without destructive or unnecessary model changes.
4. Prevent a high-level switch from ever writing `zh` alongside an English-only model.
5. Keep recognition local/offline after setup.
6. Make Chinese command phrases resolve to existing semantic command actions.
7. Ensure file transcription and meeting transcription inherit the configured language coherently.
8. Expose precise diagnostics for model/language/script/dependency/injection problems.
9. Use the same behavior in CLI and Settings.
10. Preserve the default English path and package footprint.

### Engineering goals

- no second source of configuration truth;
- no Chinese branches at daemon call sites;
- no P1 change to `SttEngine` protocol;
- no mandatory PyTorch/Qwen/FunASR runtime;
- all profile decisions pure and unit-testable;
- language application transactional;
- validation reproducible and community-contributor friendly.

---

## 3. Non-goals

P1 does not implement:

- Cantonese speech recognition;
- arbitrary Mandarin-English code-switching;
- automatic OS-locale-based language switching;
- per-application language routing;
- cloud ASR;
- full GUI/CLI string localization;
- automatic translation to/from Chinese;
- pinyin input/transliteration;
- Chinese-specific dictation formatting beyond existing generic postprocess behavior;
- fuzzy/LLM-dependent Chinese commands;
- a new model-training pipeline.

These may be independent future projects.

---

## 4. User stories

### US-1: Simplified Mandarin

As a Mandarin speaker using Simplified Chinese, I can run:

```sh
yazses language set zh-CN
```

and receive an explicit plan, required one-time downloads/installations, and a coherent configuration.

### US-2: Traditional Mandarin

As a Mandarin speaker using Traditional Chinese, I can run:

```sh
yazses language set zh-TW
```

and the same recognized content is rendered in Traditional Han.

### US-3: Inspect before changing

As an air-gapped/security-conscious user, I can run:

```sh
yazses language set zh-CN --dry-run
```

and see all planned writes and network-required artifacts without changing anything.

### US-4: No-network application

If all artifacts are cached, I can run:

```sh
yazses language set zh-CN --no-download
```

with networking disabled.

If an artifact is missing, the command refuses before writing config and says exactly what is missing.

### US-5: Return to English

After Chinese use, I can run:

```sh
yazses language set en
```

and regain English recognition without downloading `base.en` when my current multilingual model already supports English.

### US-6: Restore original English preset

I can explicitly request:

```sh
yazses language set en --recommended-model
```

to return to the project’s supported English model choice.

### US-7: Chinese voice command

While Chinese command grammar is active, saying a reviewed equivalent of “save file” emits canonical action `save`; the dispatch path is identical to English.

### US-8: Chinese prose is not accidentally executed

Ordinary Chinese prose that merely contains a command-like word does not trigger a command unless it matches an anchored reviewed rule or explicit macro.

### US-9: Customized model

If I manually choose a Chinese-capable model, `language status` reports “zh-CN-compatible/custom” rather than overwriting it.

### US-10: Cantonese ambiguity is explicit

If I request `zh-HK`, P1 does not silently configure Mandarin. It explains that Traditional script is available via `zh-TW` for Mandarin, while Cantonese support is a separate planned capability.

---

## 5. Public CLI

### 5.1 `yazses language list`

Output columns:

| Column | Meaning |
|---|---|
| ID | canonical profile |
| Speech | human-readable spoken language |
| Script | output policy |
| Model | supported baseline |
| Status | available / experimental / planned |
| Note | important distinction |

Example:

```text
ID      SPEECH     SCRIPT       MODEL  STATUS
en      English    —            base.en available
zh-CN   Mandarin   Simplified   small  experimental
zh-TW   Mandarin   Traditional  small  experimental
```

Do not show `zh-HK` as available.

### 5.2 `yazses language status`

Must print:

- effective speech language;
- script policy;
- effective command grammar language;
- engine/model;
- compatibility result;
- model cached status;
- OpenCC availability if script pin active;
- derived profile match;
- restart-needed status if detectable;
- injection warning when known.

Machine-readable option is desirable:

```sh
yazses language status --json
```

Suggested JSON:

```json
{
  "speech_language": "zh",
  "script": "simplified",
  "command_language": "zh",
  "engine": "faster-whisper",
  "model": "small",
  "profile": "zh-CN",
  "customized": false,
  "coherent": true,
  "problems": [],
  "requirements": {
    "model_cached": true,
    "script_dependency_available": true
  }
}
```

### 5.3 `yazses language set PROFILE`

Syntax:

```text
yazses language set PROFILE
  [--dry-run]
  [--model MODEL]
  [--engine ENGINE]
  [--recommended-model]
  [--no-download]
  [--no-restart]
```

Rules:

- profile names case-insensitive for ASCII aliases;
- canonical IDs rendered consistently;
- `--model` override is validated;
- `--engine` override is validated by engine capability contract;
- `--model` and `--recommended-model` are mutually exclusive;
- `--dry-run` performs no file mutation, package install, model download, or restart;
- `--no-download` permits cache inspection but no network;
- no generic `--force` bypass of known incompatible model/language pairs.

Exit codes:

| Code | Meaning |
|---:|---|
| 0 | success / coherent dry-run |
| 1 | invalid requested profile or incompatible override |
| 2 | prerequisite unavailable |
| 3 | config transaction failed |
| 4 | config committed but restart/verification failed |

Exact project-wide CLI exit conventions may supersede these numbers; the distinction must remain machine-readable.

---

## 6. Proposed configuration additions

### 6.1 Command language

Add:

```python
@dataclass
class CommandsConfig:
    ...
    language: str = "auto"
```

No new top-level language-profile config section.

### 6.2 Existing STT fields remain canonical

```python
SttConfig.engine
SttConfig.model
SttConfig.language
SttConfig.chinese_script
```

### 6.3 Validation

`commands.language` accepted values initially:

- `auto`
- `en`
- `zh`

Unknown manual values should fail config validation or degrade according to existing config-load policy, but they must not silently choose an unrelated grammar.

---

## 7. New data model

### 7.1 `LanguageProfile`

```python
from dataclasses import dataclass
from typing import Literal

ProfileStatus = Literal["available", "experimental", "planned"]

@dataclass(frozen=True)
class LanguageProfile:
    id: str
    aliases: tuple[str, ...]
    speech_language: str
    command_language: str
    han_script: str
    recommended_engine: str
    recommended_model: str
    status: ProfileStatus
    description: str
```

### 7.2 `ConfigMutation`

```python
@dataclass(frozen=True)
class ConfigMutation:
    section: str
    key: str
    before: object
    after: object
    reason: str
```

### 7.3 `ArtifactRequirement`

```python
@dataclass(frozen=True)
class ArtifactRequirement:
    kind: Literal["model", "python-extra"]
    name: str
    satisfied: bool
    download_bytes: int | None = None
    source: str = ""
```

`download_bytes` may be unknown without contacting a source; do not require network just to populate it.

### 7.4 `LanguagePlan`

```python
@dataclass(frozen=True)
class LanguagePlan:
    request: str
    canonical_profile: str
    mutations: tuple[ConfigMutation, ...]
    requirements: tuple[ArtifactRequirement, ...]
    warnings: tuple[str, ...]
    restart_required: bool
```

---

## 8. Pure resolver API

Suggested module `language/profiles.py`:

```python
def profile_for_id(value: str) -> LanguageProfile:
    """Resolve aliases or raise UnknownLanguageProfile."""

def resolve_profile(
    requested: str,
    current: Config,
    *,
    model_override: str | None = None,
    engine_override: str | None = None,
    use_recommended_model: bool = False,
) -> LanguagePlan:
    """Return a complete, side-effect-free plan."""
```

Properties:

- deterministic;
- no filesystem writes;
- no network;
- no package installation;
- no heavy imports;
- testable with plain dataclasses.

### 8.1 Resolver algorithm: `zh-CN`

1. Resolve canonical profile.
2. Set desired speech = `zh`.
3. Set script = `simplified`.
4. Determine engine/model:
   - explicit overrides first;
   - otherwise preserve current combination if capability check says it can decode zh;
   - otherwise select faster-whisper/small.
5. Validate model/language compatibility.
6. Determine whether OpenCC requirement is satisfied.
7. Determine model cached state without downloading.
8. Produce only mutations whose before != after.
9. Do not mutate command language when current value is explicit `en`/`zh`; default `auto` follows speech.
10. Return warnings for explicit override choices that are supported but unvalidated.

### 8.2 Resolver algorithm: `zh-TW`

Same as zh-CN except script = `traditional`.

### 8.3 Resolver algorithm: `en`

1. desired speech = en;
2. script = off;
3. preserve compatible current engine/model unless `--recommended-model`;
4. if recommended, choose project English baseline;
5. do not touch an explicit command-language override unless a future `--sync-commands` option is deliberately added.

### 8.4 `zh-HK`

Throw typed error:

```text
zh-HK is ambiguous for speech in the P1 language profiles.
If you speak Mandarin and want Traditional characters, use zh-TW.
Cantonese speech recognition is planned separately and is not enabled by selecting a script.
```

---

## 9. Engine capability check

P1 can use a narrow API:

```python
def supports_language(stt: SttConfig, language: str) -> bool:
    ...
```

For faster-whisper:

- `.en` model + non-en => false;
- multilingual short name / explicit model => true unless known otherwise.

For Parakeet/Moonshine or future engines, capability comes from their adapter/factory metadata.

Do not hardcode all engine rules into `language/profiles.py`.

Longer-term preferred type is documented in target architecture.

---

## 10. Transaction API

Suggested `language/apply.py`:

```python
@dataclass(frozen=True)
class ApplyResult:
    changed: bool
    config_path: Path
    restarted: bool
    warnings: tuple[str, ...]

def apply_language_plan(
    plan: LanguagePlan,
    *,
    config_path: Path,
    allow_download: bool,
    install_optional: bool,
    restart: bool,
) -> ApplyResult:
    ...
```

### 10.1 Preflight ordering

1. re-read current config under write lock;
2. re-resolve or verify plan preconditions so a stale GUI plan cannot overwrite concurrent edits;
3. satisfy optional package requirement;
4. satisfy model cache requirement;
5. construct candidate config text in memory;
6. parse candidate through normal config loader/validator;
7. write temporary file in same directory;
8. flush + fsync file;
9. atomic replace;
10. fsync directory where supported;
11. restart once if requested;
12. verify daemon/status if current command architecture provides a reliable probe.

### 10.2 Package installation

Reuse the feature/dependency installation mechanism rather than invoking `pip` from a second implementation.

If package management cannot be safely automated in a particular packaging format (Snap/Flatpak/etc.), preflight reports the platform-specific remediation before writing language config.

### 10.3 Model download

Reuse `stt.download.download_stt_model` for faster-whisper.

If `allow_download=False` and cache missing, fail before config mutation.

### 10.4 Backup

Atomic replace protects against torn writes. The project may also retain one previous config backup if consistent with existing config-edit policy, but the primary rollback guarantee is that prerequisites are completed before mutation.

---

## 11. Settings UI API

Add controller method:

```python
def set_language_profile(
    self,
    profile: str,
    *,
    model: str | None = None,
    use_recommended_model: bool = False,
) -> ToggleResult:
    ...
```

The UI controller must call the shared resolver/apply functions.

Before any download/install, show a confirmation describing:

- model name;
- whether cached;
- optional dependency;
- config changes;
- restart.

Do not implement a separate Qt-only profile mapping.

---

## 12. Command grammar API

Maintain public `classify` compatibility.

One compatible shape:

```python
def classify(
    text: str,
    profile: str = "default",
    slm_router: _SlmRouter | None = None,
    macro_table: _MacroTable | None = None,
    *,
    language: str = "en",
) -> CommandIntent:
    ...
```

The daemon resolves:

```python
command_language = resolve_command_language(
    cfg.commands.language,
    cfg.stt.language,
)
```

and passes it by keyword.

This avoids shifting existing positional arguments.

### 12.1 Registry protocol

```python
class Grammar(Protocol):
    language: str
    def classify(self, text: str) -> CommandIntent | None: ...
```

`None` means no Tier-1 match; the outer classifier continues to SLM/dictation.

### 12.2 English extraction

Move existing regex definitions with no semantic change. Contract vectors must prove parity before Chinese rules land.

### 12.3 Chinese P1 command inventory

P1 should cover every action currently represented in the stable core English grammar **or explicitly document exclusions**.

At minimum:

#### Editing
- undo / undo N
- save
- copy / cut / paste
- delete last word(s)
- delete last line(s)
- comment line
- select N lines
- select to end
- select all
- Enter/new line
- Tab
- Escape
- Backspace

#### Navigation
- go to line N
- page up/down
- line home/end
- arrow up/down/left/right
- go to function/class/file

#### Terminal/refactor
These are more safety-sensitive and phrase-naturalness-sensitive. They may land after the safe edit/navigation subset, but if omitted P1 must expose a capability matrix rather than implying full command parity.

### 12.4 Phrase source file

Prefer data or small per-language rule modules so native reviewers can inspect Chinese phrases without navigating dispatch implementation.

Each phrase/rule should have:

- semantic action;
- Simplified accepted form(s);
- Traditional accepted form(s);
- arguments;
- examples;
- ambiguity note where relevant.

### 12.5 Chinese numerals

Implement a bounded pure parser for command arguments.

Required:
- 0–99 Arabic digits;
- 零/〇;
- 一二三四五六七八九十;
- 十一 … 九十九;
- 两 in natural count positions.

Optional P1:
- hundreds.

Out of scope unless required:
- financial numerals;
- arbitrary Chinese number parsing in normal dictation.

---

## 13. Script handling

Existing `han_script.py` remains authoritative.

Changes only if validation reveals bugs:

- keep Simplified/Traditional alias resolution;
- preserve no-op fast path for non-Han text;
- ensure command text is classified **after** the STT wrapper’s selected script normalization;
- do not phrase-convert Taiwan/Hong Kong regional vocabulary when only character-script normalization was requested.

OpenCC conversion mode remains character-oriented `t2s` / `s2t` unless a separate ADR chooses regional lexical conversion.

---

## 14. Effective configuration by surface

| Surface | Default effective language | Override |
|---|---|---|
| Live dictation | `cfg.stt.language` | language profile / manual config |
| Streaming window | engine language | same engine config |
| File transcription | config language | explicit CLI `--language` |
| Meeting live | config language | meeting-specific future override only |
| Meeting post-pass | same effective language as meeting live | must be recorded in metadata |
| Commands | `commands.language` -> auto from STT | explicit commands.language |
| Docs/UI | independent | locale selector only |

---

## 15. Metadata/reproducibility

Where recording/file outputs already contain metadata, add/ensure:

```json
{
  "stt_engine": "faster-whisper",
  "stt_model": "small",
  "speech_language": "zh",
  "chinese_script": "simplified"
}
```

Do not store “profile=zh-CN” as authoritative if the actual config is customized. A derived profile label may be included as informational metadata alongside the effective fields.

---

## 16. Doctor diagnostics

Add checks:

### CHN-001 model-language contradiction
Fail when non-English language is paired with an English-only Whisper checkpoint.

### CHN-002 script dependency missing
Warn/fail depending on requested deterministic script behavior.

### CHN-003 command grammar unavailable
If `commands.language=auto` resolves to a language with no grammar, report that dictation works but Tier-1 spoken commands in that language do not.

### CHN-004 model cache
Report exact model and whether cached.

### CHN-005 injection
Report known backend Unicode caveat and clipboard fallback.

### CHN-006 unsupported region alias
If a manual profile-like value reaches a profile surface, explain `zh-HK` semantics.

Doctor must call shared rules, not duplicate conditions.

---

## 17. Configuration generator/docs

Update generated example config to document:

```toml
[commands]
language = "auto" # spoken command grammar; auto follows [stt] language when supported
```

Do not change default STT model/language.

Update configuration reference with:

- high-level language command;
- manual equivalent;
- distinction between speech and script;
- Cantonese scope;
- model download/offline behavior.

Do not update the Chinese support marketing claim until ADR-v2-144 passes.

---

## 18. Error model

Typed internal exceptions make CLI/UI behavior consistent:

```python
class LanguageError(Exception): ...
class UnknownLanguageProfile(LanguageError): ...
class AmbiguousLanguageProfile(LanguageError): ...
class IncompatibleLanguageModel(LanguageError): ...
class MissingLanguageArtifact(LanguageError): ...
class LanguageConfigTransactionError(LanguageError): ...
```

User-facing surfaces translate them into concise remediation.

No raw Hugging Face/OpenCC/package-manager traceback should be the primary error for a routine language switch.

---

## 19. Security and safety

### Command safety

Localized grammar must not broaden terminal execution.

Example: a Chinese rule for “run X” is security-equivalent to English `run_command` and must pass the same command-safety gate. Do not add permissive catch-all Chinese regexes before safety coverage exists.

### Unicode confusables

Do not add aggressive normalization to all Chinese text. Existing SafeGlyph/security components remain separate.

### Downloads

Report source and artifact name before network access.

### Privacy

No audio leaves the device for language selection, detection, script conversion or validation at runtime.

---

## 20. Test requirements

Detailed plan is in `design/chinese/test-and-validation-plan.md`. Minimum code gate:

### Resolver
- every alias;
- preserve vs recommended mode;
- base.en -> small when zh selected;
- multilingual custom model preserved;
- en switch preserves compatible model;
- zh-HK refused;
- dry-run plan contains exact mutations.

### Transaction
- dependency failure => zero config changes;
- model download failure => zero config changes;
- candidate validation failure => zero config changes;
- success writes all keys as one coherent state;
- concurrent config edit detected/re-resolved;
- restart called once.

### Grammar
- English contract parity before/after extraction;
- Chinese fixtures for every shipped action;
- Simplified and Traditional phrase variants;
- punctuation;
- numerals;
- unknown prose => DICTATE;
- terminal/safety paths retain same gate.

### STT
- zh reaches transcribe/transcribe_words/decode_window (existing language tests generalized);
- Han wrapper stays on all paths;
- language plan builds an engine with expected kwargs;
- English default unchanged.

### Integration
- CLI set/status/list;
- settings controller;
- file overrides;
- meeting effective metadata;
- doctor diagnostics;
- no Chinese imports on default path.

---

## 21. Performance requirements

P1 code path overhead excluding model decode:

- language profile resolution: <5 ms;
- Chinese Tier-1 command classification: <5 ms target on ordinary desktop CPU;
- Han conversion: negligible relative to decode; measure on long text;
- default English startup: no measurable model/dependency overhead from language package.

ASR gates are defined in model strategy and ADR-v2-144.

---

## 22. Observability

Useful log events:

```text
language_plan_resolved profile=zh-CN engine=faster-whisper model=small
language_model_download_required model=small
language_profile_applied speech=zh script=simplified
command_grammar language=zh source=auto
```

Do not log dictated content merely to diagnose language selection.

---

## 23. Rollout plan

### Phase A — orchestration, no behavior claim
- resolver;
- plan;
- status;
- tests.

### Phase B — atomic CLI switch
- preflight;
- transaction;
- model/dependency path;
- doctor.

### Phase C — Settings
- high-level control;
- shared controller path.

### Phase D — command localization
- English grammar extraction + parity;
- Chinese safe core commands;
- native review;
- extended commands.

### Phase E — platform validation
- Unicode injection matrix;
- file/meeting;
- packaging.

### Phase F — benchmark/release gate
- Mandarin corpus;
- performance;
- native-speaker acceptance;
- publish result;
- update support claim only if passed.

Alternative recognizer research can run in parallel after benchmark harness exists.

---

## 24. Definition of done

This spec is implemented when:

1. `language list/status/set` exists and is documented.
2. `zh-CN` and `zh-TW` apply coherently and atomically.
3. `zh-HK` is not silently accepted as a Mandarin/Cantonese speech profile.
4. model/dependency failure cannot corrupt or half-switch config.
5. Settings uses the same resolver.
6. Chinese core commands map to canonical actions.
7. English grammar contract is unchanged.
8. live/file/meeting paths are verified.
9. Unicode injection matrix is published.
10. benchmark + native-speaker gate is complete.
11. default English install/model/import behavior is unchanged.
12. support wording reflects the evidence actually obtained.

## 25. Source-of-truth documents

- ADR-v2-140: profile transaction semantics.
- ADR-v2-141: P1 model/runtime decision.
- ADR-v2-142: localized command grammar architecture.
- ADR-v2-143: speech/script/locale semantics.
- ADR-v2-144: support validation gate.
- `design/chinese/model-strategy.md`: candidate evaluation.
- `design/chinese/test-and-validation-plan.md`: full verification protocol.
- `design/chinese/implementation-roadmap.md`: work decomposition.
