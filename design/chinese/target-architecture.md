# Chinese support — target architecture

**Status:** Proposed  
**Primary goal:** Make English ↔ Mandarin switching a coherent operation while preserving the current STT, command, injection and privacy boundaries.

## 1. Architectural shape

The target architecture adds a thin **language orchestration layer** above existing canonical configuration.

```text
                         ┌──────────────────────────┐
CLI / Settings / API ───>│ LanguageProfile resolver │
                         │  pure: no I/O             │
                         └────────────┬─────────────┘
                                      │ LanguagePlan
                                      v
                         ┌──────────────────────────┐
                         │ preflight + transaction  │
                         │ deps / model / validate  │
                         └────────────┬─────────────┘
                                      │ atomic config commit
                                      v
 ┌──────────────┐     ┌────────────────────┐     ┌──────────────────────┐
 │ Audio / VAD  │────>│ SttEngine factory  │────>│ Han-script decorator │
 └──────────────┘     │ existing seam      │     │ existing seam        │
                      └─────────┬──────────┘     └──────────┬───────────┘
                                │                           │ text
                                └───────────────────────────┘
                                                            v
                                            ┌─────────────────────────┐
                                            │ Command grammar registry │
                                            │ en / zh -> semantic IDs  │
                                            └────────────┬────────────┘
                                                         │ CommandIntent
                                                         v
                                            ┌─────────────────────────┐
                                            │ Existing dispatch/inject │
                                            └─────────────────────────┘
```

There is no Chinese-specific daemon pipeline.

---

## 2. New module boundary: `yazses.language`

Proposed package:

```text
src/yazses/language/
    __init__.py
    profiles.py       # pure aliases, profile resolution, compatibility
    plan.py           # LanguagePlan / ConfigMutation data models
    apply.py          # preflight + atomic application
    status.py         # derive current profile/coherence from Config
```

The package must remain lightweight. Importing `profiles.py` or listing language choices must not import faster-whisper, OpenCC, Qt, torch, FunASR, Qwen or any model runtime.

### 2.1 `LanguageProfile`

A profile is a **preset definition**, not stored user state.

Suggested type:

```python
@dataclass(frozen=True)
class LanguageProfile:
    id: str
    speech_language: str
    command_language: str
    han_script: str
    recommended_engine: str
    recommended_model: str
    aliases: tuple[str, ...]
    status: Literal["supported", "experimental", "planned"]
    note: str = ""
```

Initial profiles:

| Profile | Speech | Commands | Script | Engine | Recommended model | P1 status |
|---|---|---|---|---|---|---|
| `en` | en | en | off | faster-whisper | base.en | existing |
| `zh-CN` | zh | zh | simplified | faster-whisper | small | proposed |
| `zh-Hans` | alias of zh-CN | | | | | proposed |
| `zh-TW` | zh | zh | traditional | faster-whisper | small | proposed |
| `zh-Hant` | alias of zh-TW | | | | | proposed |
| `zh-HK` | — | — | — | — | — | reject in P1 with Cantonese/Mandarin explanation |
| `yue-HK` | — | — | traditional | TBD | TBD | planned |

Do not advertise `yue-HK` until an engine and validation plan are implemented. It appears here only to reserve the semantic distinction.

---

## 3. Profiles are not a second configuration system

Canonical persistent settings remain the existing TOML keys:

```toml
[stt]
engine = "faster-whisper"
model = "small"
language = "zh"
chinese_script = "simplified"

[commands]
language = "auto"
```

No `[language] active_profile = "zh-CN"` key is required.

Why:

- users may deliberately customize the model after selecting Chinese;
- a profile name would drift from those real settings;
- migrations would have two truths to reconcile;
- hand-edited configs remain first-class.

`language status` derives state:

```text
Speech: zh (Mandarin)
Script: Simplified
STT: faster-whisper / small
Commands: zh (auto from speech)
Profile match: zh-CN (custom model: no)
Status: coherent
```

For a customized but valid configuration:

```text
Profile match: zh-CN-compatible (custom model: large-v3)
Status: coherent
```

For an invalid one:

```text
Status: INVALID
Reason: language 'zh' cannot be decoded by model 'base.en'
Fix: yazses language set zh-CN
```

---

## 4. Language resolution

Public pure API:

```python
def resolve_profile(
    requested: str,
    current: Config,
    *,
    model: str | None = None,
    engine: str | None = None,
    mode: Literal["preserve", "recommended"] = "preserve",
) -> LanguagePlan:
    ...
```

### 4.1 Preserve mode

Default behavior should minimize destructive changes.

For `zh-CN`:

1. set `stt.language = "zh"`;
2. set `stt.chinese_script = "simplified"`;
3. keep current engine/model **if** they are declared Chinese-capable;
4. otherwise select P1 recommended `faster-whisper/small`;
5. leave unrelated STT tuning untouched;
6. `commands.language = "auto"` continues to follow speech unless user explicitly pinned it.

For `en`:

1. set `stt.language = "en"`;
2. disable `chinese_script`;
3. keep a multilingual model if it can decode English;
4. do not download `base.en` merely to reverse a profile;
5. preserve an explicit `commands.language` override.

This makes switching reversible without unnecessary multi-hundred-MB downloads.

### 4.2 Recommended mode

An explicit mode may restore profile performance defaults:

```sh
yazses language set en --recommended-model
```

This is the operation that may choose `base.en`.

Equivalent Chinese operation may reselect `small` if a user wants the supported baseline rather than an experimental custom model.

---

## 5. Language plan

Before changing anything, the resolver returns an inspectable plan:

```python
@dataclass(frozen=True)
class ConfigMutation:
    section: str
    key: str
    before: object
    after: object
    reason: str

@dataclass(frozen=True)
class LanguagePlan:
    requested: str
    canonical_profile: str
    mutations: tuple[ConfigMutation, ...]
    model_download: str | None
    required_extras: tuple[str, ...]
    warnings: tuple[str, ...]
    restart_required: bool
```

Example:

```text
$ yazses language set zh-CN --dry-run

Language profile: zh-CN (Mandarin, Simplified)
Changes:
  [stt] model: base.en -> small
    reason: base.en is English-only
  [stt] language: en -> zh
  [stt] chinese_script: "" -> simplified

One-time requirements:
  model: small (not currently cached)
  optional package: chinese (OpenCC)

Runtime after setup: offline
Restart required: yes
No files changed (--dry-run)
```

Dry-run output should be generated from the same `LanguagePlan` object that real application consumes.

---

## 6. Transaction semantics

A language switch must be all-or-nothing.

### Required ordering

```text
resolve -> validate plan
        -> preflight dependency
        -> ensure model available
        -> construct candidate Config in memory
        -> run semantic validation
        -> write temp TOML
        -> fsync / atomic replace
        -> restart once
        -> verify daemon state
```

### Failure behavior

| Failure | Required result |
|---|---|
| Unknown profile | No write |
| `zh-HK` P1 request | No write; explain Cantonese vs Traditional script |
| OpenCC install/preflight fails | No write unless user explicitly elects script-unpinned advanced mode |
| Model download fails | Existing English config untouched |
| Candidate config validation fails | No write |
| Atomic file replace fails | Original file intact |
| Restart fails | Config is valid but daemon unavailable; report rollback command/state, do not silently mutate again |
| Runtime model load fails | Existing model error path remains; doctor points to exact profile problem |

Use the repository’s existing config-edit infrastructure where possible, but multiple keys must commit as one transaction. Repeated calls to a one-key editor are insufficient because interruption between calls can expose an invalid state.

### Concurrency

Take the same config-write lock used by other settings mutations, or introduce one if none exists. Settings GUI and CLI must not interleave writes.

---

## 7. CLI contract

Proposed group:

```text
yazses language list
yazses language status
yazses language set <profile>
```

### `language list`

Shows canonical profile, spoken language, script, status and model requirement.

Do not list planned profiles as available choices unless marked clearly `planned`.

### `language status`

Reports derived current state, including contradictions.

Exit codes:

- 0 coherent;
- 1 configuration incoherent;
- 2 runtime prerequisite missing.

### `language set`

Proposed options:

```text
--dry-run
--model <name>             advanced override
--engine <name>            advanced override
--recommended-model        restore the supported model for that profile
--no-download              fail rather than access network
--no-restart               write valid config but do not restart
```

Do not add `--force` as a shortcut around semantic incompatibility such as `base.en + zh`. Advanced users can still edit TOML manually, but the safe high-level operation should remain safe.

---

## 8. Settings UI contract

The Settings window should expose a high-level row near STT controls:

```text
Dictation language
[ English                         v ]

Chinese output script
[ Simplified                     v ]  # visible/enabled for zh only
```

Implementation rules:

- UI calls the same resolver/controller used by CLI.
- Selecting Chinese shows the planned model download before applying.
- If current config is customized, display “Custom Chinese-compatible setup” rather than snapping dropdown values.
- Advanced model selector remains independent.
- Changing model after language selection runs compatibility validation.
- Choosing Traditional changes script, not speech language.
- Never infer this control from the UI translation locale.

---

## 9. Command grammar architecture

### 9.1 Add a grammar-language selector

Proposed config:

```python
@dataclass
class CommandsConfig:
    ...
    language: str = "auto"
```

Semantics:

- `auto`: resolve from `stt.language` when a Tier-1 grammar exists; otherwise English only if the speech is English, else no non-English Tier-1 rules.
- `en`: explicitly use English command phrases.
- `zh`: use Chinese command phrases.

Do **not** overload `CommandsConfig.profile`; that field selects application/editor behavior.

### 9.2 Registry, not conditional sprawl

Proposed structure:

```text
src/yazses/commands/
    grammar.py                 # public classify(), tier ordering, registry
    grammar_common.py          # CommandIntent, normalization interfaces
    grammars/
        __init__.py
        en.py                  # existing rules moved with behavior preserved
        zh.py                  # Chinese lexical rules
```

Alternative naming is acceptable; the architectural rule is not.

`grammar.classify()` remains the stable public entrypoint. It resolves a Tier-1 grammar and returns canonical `CommandIntent`.

### 9.3 Same semantics across languages

Example mapping:

| English | Simplified | Traditional | Canonical action |
|---|---|---|---|
| undo | 撤销 | 復原 / 撤銷 | `undo` |
| save file | 保存文件 | 儲存檔案 | `save` |
| copy | 复制 | 複製 | `copy` |
| paste | 粘贴 | 貼上 | `paste` |
| select all | 全选 | 全選 | `select_all` |
| go to line 42 | 跳到第42行 | 跳到第42行 | `go_to_line{n=42}` |

The final exact phrase set must be reviewed by native speakers. The table illustrates semantics, not linguistic approval.

### 9.4 Command-only normalization

Chinese grammar may normalize:

- outer `。！？；：`;
- whitespace around digits/Latin identifiers;
- common numeral forms;
- equivalent Simplified/Traditional command lexemes if deliberately enumerated.

It must not normalize all dictated text.

### 9.5 Tier ordering remains

```text
Tier 0 user macro
 -> Tier 1 selected deterministic grammar
 -> Tier 2 optional local SLM
 -> DICTATE
```

P1 does not require a Chinese SLM router. Deterministic rules cover the core actions first.

---

## 10. STT model architecture

P1:

```text
LanguageProfile(zh-CN)
 -> SttConfig(engine="faster-whisper", model="small", language="zh")
 -> build_engine()
 -> FasterWhisperEngine
 -> _HanScriptEngine(simplified)
```

No new engine API is introduced.

Future candidate:

```text
SttConfig(engine="sensevoice", ...)
 -> build_engine()
 -> SenseVoiceEngine implements SttEngine
 -> _HanScriptEngine
```

The language profile resolver asks an engine capability registry whether a configured engine/model supports `zh`; it should not contain engine-specific string heuristics beyond the current Whisper compatibility helper.

Longer-term interface:

```python
@dataclass(frozen=True)
class EngineCapabilities:
    languages: frozenset[str] | Literal["dynamic"]
    word_timestamps: bool
    streaming: bool
    translation: bool
    cpu_supported: bool

def capabilities(stt: SttConfig) -> EngineCapabilities: ...
```

P1 may begin with a small capability function instead of a full registry, but avoid baking “`.en` means English-only” into generic language orchestration.

---

## 11. File transcription and meetings

No separate Chinese implementation.

Rules:

- if a file command supplies `--language`, that per-operation override wins;
- otherwise it uses configured profile settings;
- the same Han script decorator applies;
- meeting live and post-pass decode must use the same resolved language unless a meeting-specific override explicitly exists;
- metadata should record the effective engine/model/language/script so a result is reproducible.

Add tests proving these rules.

---

## 12. Injection strategy

The injector still receives Unicode text. No Chinese-specific injector protocol is needed.

However, profile validation should surface backend suitability:

```text
Chinese text injection:
  X11 xdotool: verified
  clipboard: verified
  Wayland ydotool: unverified for current layout -> clipboard fallback recommended
```

A future `doctor --language` probe may inject into a YazSes-owned test field, but it must never type arbitrary test text into the user’s currently focused application without consent.

P1 release validation must test real Han text on all supported desktop OS/session families.

---

## 13. Diagnostics

`yazses doctor` should add a compact language section when non-default or invalid:

```text
[OK] Dictation language: Mandarin (zh)
[OK] STT model: small is multilingual and cached
[OK] Han output: Simplified (OpenCC available)
[OK] Command grammar: zh
[WARN] Injection: ydotool cannot guarantee Unicode on this layout; clipboard fallback available
```

Invalid example:

```text
[FAIL] Dictation language: zh with English-only model base.en
       Fix: yazses language set zh-CN
```

Diagnostics must use the same compatibility functions as the setter. Never duplicate rules in doctor.

---

## 14. Privacy and networking

The project’s offline contract is unchanged.

Language switching may require one-time downloads:

- model checkpoint;
- optional script-normalization dependency.

The plan must name each network operation before it happens. After artifacts are cached, recognition and script conversion remain local.

`--no-download` makes an air-gapped workflow deterministic: fail early and print the exact missing artifact rather than attempting a network connection.

---

## 15. Telemetry and learning

No new telemetry is required.

If opt-in local learning events already record model/language context, include the effective language/profile-compatible state without recording new sensitive audio solely for Chinese validation.

Public benchmark corpora must be license-reviewed; private native-speaker validation recordings remain outside the repository unless explicit redistributable consent/license exists.

---

## 16. Migration and backward compatibility

Existing TOML files:

- remain valid;
- default to English exactly as before;
- need no migration to a stored profile key.

Existing programmatic `classify(text, profile, ...)` callers must keep working. Add the grammar language as a keyword/defaulted argument or resolve it in the daemon without reinterpreting the current positional `profile`.

Existing manual Chinese setup remains valid.

Existing `chinese-script` feature remains a script-only toggle.

---

## 17. Rollback

Because the design does not introduce a new persistent profile graph, rollback is straightforward:

```sh
yazses language set en
```

This resets speech language and script policy while preserving any multilingual model that remains valid for English.

For the original performance footprint:

```sh
yazses language set en --recommended-model
```

restores the English recommended checkpoint.

A failed experimental alternative engine can be disabled by switching `[stt] engine` back to faster-whisper; all callers remain unchanged.

---

## 18. Architecture acceptance criteria

The implementation is architecturally complete when all of the following are true:

- no Chinese branch exists in daemon/file/meeting/dispatch call sites;
- `SttEngine` protocol is unchanged for P1;
- profile state is derived, not redundantly stored;
- config switch is atomic;
- CLI and Settings use one resolver;
- doctor uses one compatibility implementation;
- English grammar semantics are unchanged;
- Chinese grammar emits existing action IDs;
- Han conversion remains a post-STT decorator;
- UI/docs locale does not alter speech config;
- `zh-HK` cannot silently mean Mandarin or Cantonese;
- an unconfigured English installation imports/loads no Chinese-only dependency.
