# Mandarin switching: architecture, state machine and failure contract

**Status:** Proposed implementation contract and ADR-v2-140/143 reconciliation; current implementation verified by code inspection at [`4fda340`](https://github.com/MSKazemi/yazses/tree/4fda34030b0cf6e269edad78f8e03ea0d91b0324). No public IPC change is authorized by this document.

## Objectives and non-goals

One user operation selects English, Mandarin + Simplified, or Mandarin + Traditional, without surprising model replacement or breaking an established offline English setup. Speech recognition, output script, command grammar, and UI/document locale must remain independent concerns.

Out of scope for this release: Cantonese (`yue`), `zh-HK` aliasing, automatic per-utterance speech language switching, translation, per-region lexical conversion, forced multi-engine routing, and exposing cloud ASR.

## Decision trace

- **ADR-v2-140**: profile is a pure preset *over existing canonical config*, never a persisted second source of truth.
- **ADR-v2-141**: same faster-whisper backend and multilingual `small` as the baseline; promote alternatives only after product evidence.
- **ADR-v2-142**: command grammar is localized, while `CommandIntent` and action dispatch remain unchanged.
- **ADR-v2-143**: STT speech code `zh` is independent from `chinese_script`, command language, and UI/document locale.
- **ADR-v2-144**: a working config alone does not authorize a release claim.

Implementations already reside in `src/yazses/language/{profiles,plan,status,capability,service}.py`. No second Mandarin daemon or dedicated Chinese STT factory should be introduced.

## Exact configuration and identity contract

| Profile | Aliases | STT language | Script | Recommended runtime/model | Command language |
|---|---|---|---|---|---|
| `en` | `en` | `en` | empty | `faster-whisper/base.en` | `en` when auto |
| `zh-CN` | `zh-cn`, `zh-hans` | `zh` | `simplified` | `faster-whisper/small` | `zh` when auto |
| `zh-TW` | `zh-tw`, `zh-hant` | `zh` | `traditional` | `faster-whisper/small` | `zh` when auto |

Invalid high-level choices must fail without changing config: bare `zh`, `zh-HK`, `yue`, unknown aliases, explicit English-only Mandarin checkpoint, and unsupported explicit engine. Do not map Traditional script to Cantonese, or UI locale to speech language.

```toml
# Example: Mandarin, Simplified (output of the profile resolver)
[stt]
engine = "faster-whisper"
model = "small"
language = "zh"
chinese_script = "simplified"

[commands]
language = "auto"  # Follows the effective STT speech language
```

There is no `[language] active_profile` field to save; status is derived. Explicit `[commands] language = "en"` is preserved and shown as a **warning** when Mandarin is active, not silently rewritten. Custom profiles must be distinguishable from high-level presets.

## End-to-end state machine

```text
IDLE
  | read config revision, resolve profile, validate in memory
  v
PREPARED (read-only plan + requirements + warnings)
  | --dry-run => EXIT without side effects
  | missing requirement + --no-install/--no-download => BLOCKED
  | user declines => EXIT without side effects
  v
AUTHORIZED (explicit confirmation, no implied payment/network consent)
  | install optional script dependency / retrieve missing model, only if allowed
  | verify module importability and cached artifact, no code changes yet
  v
PREREQUISITES_READY
  | writer locks config, verifies expected revision, renders candidate
  | daemon config loader validates *entire* candidate
  | candidate differs from plan or unrelated sections => REJECT
  | concurrent edit => reread/re-resolve (bounded retry)
  v
CONFIG_COMMITTED (one atomic config replace, unrelated sections preserved)
  | if daemon stopped -> configuration becomes active on next start
  | if running + --no-restart -> RESTART_REQUIRED
  | if running + normal mode -> guard Meeting Mode finalization, then restart
  v
RUNTIME_VERIFIED (separate observation; not implied by file commit)
```

**Atomicity boundary:** only the final config write is atomic. Successfully downloaded model files and installed Python dependencies may remain after a config/restart failure. Restart is not inside the file transaction. Do not claim rollback uninstalls packages, deletes cached weights or restores an already running daemon. Clear user messaging must distinguish these outcomes.

### Invariants

1. **Old English path stays unchanged.** New imports on default `en` do not eagerly load OpenCC, PyTorch or a Mandarin checkpoint; no new base dependency and no automatic model download.
2. **No half-switch.** One high-level apply cannot commit `base.en + zh`, or only a Han script without matching language. Manual invalid config is reported, not quietly rewritten.
3. **Safe before side effects.** Dry-run, rejected profile, declined prompt, no-download/no-install and incompatible override never mutate config, install, download or restart.
4. **Optimistic concurrency.** Config revision checked before commit; if another writer touched it, recompute the complete plan and preserve unrelated fields.
5. **No hidden dependency changes.** Optional extras are lazy, local and the user can explicitly refuse install/download.
6. **Restart/active truthfulness.** Configured profile, daemon effective profile, readiness, restart-needed and release-supported are different facts. After `--no-restart`, do not display the configured profile as if it were already active.
7. **No fallthrough executing commands.** Mandarin unmatched prose is dictation or a no-action command-mode miss. Unknown grammar must not secretly fall back to English.
8. **Preserve user choices.** Compatible multilingual model preserved when switching back to English; only `--recommended-model` deliberately restores `base.en`.
9. **Privacy:** no transcript, voiceprint or diagnostic utterance appears in logs, telemetry or release artifacts.

## Public CLI contract (already in source)

```sh
yazses language list
yazses language status --json
yazses language set zh-CN --dry-run
yazses language set zh-CN --no-download --no-install --yes
yazses language set zh-TW --recommended-model --yes
yazses language set en --yes
yazses language set en --recommended-model --yes
yazses language set zh-TW --no-restart --yes
```

`--model` / `--engine` explicitly request supported faster-whisper overrides in preserve mode. `--recommended-model` cannot be combined with explicit model/engine overrides. Model selection must reject incompatible checkpoints, not silently rewrite a user requirement. CLI currently uses exit status 1 (invalid profile), 2 (prerequisite refusal) and 3 (config/transaction error); preserve these categories unless a separate public-interface decision changes them.

**Readiness is not proof of accuracy.** `language status --json` reports configured engine/model, effective model capability, script dependency, cache/readiness and command grammar. This is machine-local technical readiness, not measured Mandarin CER or native acceptance.

### CLI and GUI parity

Both callers must use `language.service.prepare_language_change` and `apply_language_change`, never duplicate model/script selection. Settings controls are derived from the profile registry (`settingsui/language_view.py`); selecting a profile stages a no-I/O preview, displays required install/download actions, and does not write until Apply. Language model selection and low-level config controls must not race with the staged change. A running daemon restart must be announced; a GUI crash or cancellation must not partially write config. Qt-free preview logic has direct tests; real Settings smoke remains separate.

## Failure and recovery table

| Situation | Required effect | User-visible recovery | Test |
|---|---|---|---|
| Unknown or ambiguous profile | No side effects | name `en` / `zh-CN` / `zh-TW`, explain Cantonese separately | `test_language_profiles.py` |
| English-only model selected for Mandarin | Refuse explicit override; auto-repair only in preserve-profile defaults | suggest multilingual `small` | `test_language_profiles.py` + `test_language_capability.py` |
| Missing OpenCC and install refused | No write or download | show optional extra and offline provisioning path | `test_language_service.py` |
| Model not cached + download refused | No write | give cache/provisioning instructions, no hidden fetch | `test_cli_language_set.py` |
| Download fails | Old config remains byte-exact | retry from user-approved state | `test_language_service.py` |
| Install succeeds, config edit later conflicts | Installed dependency may remain; no stale config applied | reread/re-resolve; note irreversible prerequisite | `test_configedit_atomic.py` |
| Duplicate/invalid TOML/candidate repair | Abort before replace | show candidate-specific diagnostic, preserve original | `test_configedit_atomic.py` |
| Concurrent Settings and CLI edits | One writer's unrelated changes survive; no mixed state | bounded retry, then conflict message | `test_language_service.py` |
| Meeting finalization active | Guard restart before switching running process | defer restart/stop safely; keep recording | `test_cli_language_set.py` + real meeting exercise |
| Restart fails after commit | Config is new; runtime may be old or unavailable | explicit restart-needed/recovery state; never claim active success | **Add integration test** |
| Offline after cache | No outbound call and complete dictation works | if model absent, fail with actionable message | **Add real-package offline test** |

## Capability and surface boundaries

`SttEngine` remains the one recognition protocol; the faster-whisper factory wraps Han conversion. Reuse it in live/streaming/file/meeting paths rather than instantiate a raw Chinese engine in call sites. File/MCP/meeting entrypoints must be audited for config propagation. Shared CJK text helpers live in `postprocess/cjk.py`, not regexes scattered among platform injectors.

Script conversion happens **after ASR**, before final text consumers, never as a hidden benchmark normalization. It is not a dialect converter, translator, numeral normalizer or guaranteed meaning-preserving regional lexical converter.

Command matching selects a grammar via `commands.grammars.registry`. Mandarin safe-core Tier-1 rules are anchored and bounded; terminal/open-ended commands and English Tier-2 are not available under the Mandarin P1 policy. Native-review status in `PHRASE_REVIEW` must be treated as a release gate, not silently flipped.

## Compatibility, migration and observability

- Existing `[stt]` and `[commands]` fields stay canonical. No new required config key, IPC method, public command rename, persistent profile field or background language autodetection.
- Retain a read-only migration path for old manual Mandarin configs; doctor explains problems and preview shows exact deltas.
- Log identifiers, model/cache state, selected script and operation outcomes only. Never log spoken text, embeddings or audio. Suppress machine-specific home paths in public QA.
- Emit distinct statuses for configured, pending restart and runtime-effective. If the IPC runtime lacks effective-language reporting, document the limitation and add any IPC change only through maintainer/L3 review, not as an incidental field.

## Acceptance/rollback

The switch feature is only release-ready when all rows of [validation and release gates](2026-10-29-validation-and-release-gates.md) apply. Emergency rollback of this feature means selecting English, optionally selecting `base.en`, and restarting. This must leave the existing English hotkey, injection backend, personal glossary and unrelated config untouched; never delete model cache by default.

**Authority:** If this document and actual source diverge, open a targeted issue with a failing test; do not silently change the resolver's public contract. Material contract changes require an ADR update/supersession, not only a prose edit.
