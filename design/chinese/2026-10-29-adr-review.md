# Mandarin ADR review and implementation reconciliation (2026-10-29)

**Purpose:** Preserve the authoritative existing ADR decisions without inventing parallel architecture. The current five Mandarin ADRs on `main` are v2-140 through v2-144 and remain **Proposed**, not silently accepted by this review.

## Proposed decision disposition

| ADR | Core choice | As-built evidence | Decision required from maintainer |
|---|---|---|---|
| [v2-140: transactional profiles](../adr/adr-v2-140-language-profile-presets.md) | Canonical config fields, pure derived profiles, atomic apply | `language/profiles.py`, `plan.py`, `service.py`, `system/configedit.py`; CLI/GUI tests | Confirm no public IPC additions; define distinction between config committed and runtime active |
| [v2-141: Whisper baseline/model gate](../adr/adr-v2-141-chinese-model-policy.md) | Reuse faster-whisper and `small` first, avoid mandatory new runtime | `stt/factory.py` and `benchmark/bench_mandarin.py` | Agree license/revision gate, representative CPU SLOs, alternative-model promotion policy |
| [v2-142: localized grammar](../adr/adr-v2-142-localized-command-grammars.md) | Same `CommandIntent`, language-specific bounded Tier-1 | `commands/grammars/zh.py` and `registry.py`; negative tests | Confirm native reviewer approval process, strict exclusion of open-ended commands |
| [v2-143: independent language/script/locale](../adr/adr-v2-143-chinese-script-and-locale-semantics.md) | `zh` Mandarin ASR, `simplified`/`traditional` script, UI locale separate | `language/profiles.py` + OpenCC wrapper | Keep `zh-HK`/`yue` excluded, make Mandarin-vs-script wording explicit everywhere |
| [v2-144: evidence-backed support](../adr/adr-v2-144-chinese-support-validation-gate.md) | Claims are per surface, with performance, privacy, native and hardware evidence | Existing model-free tests + `docs/research/mandarin-platform/README.md` with no reports | Select release hardware classes, pre-register SLOs, require dated signoff and evidence paths |

## Cross-ADR invariants

1. English `base.en`/`en` behavior, imports, command semantics and files are unchanged until explicit opt-in.
2. No parallel Chinese transcription daemon; keep `SttEngine`, the shared decoder and platform abstractions.
3. No hidden network calls, telemetry or voice data uploads; model acquisition is an explicit provisioning step.
4. Profile is a presentation of canonical config, not a second source of truth; UI, CLI and doctor share one resolver/service.
5. Script conversion is a **postrecognition** transform, not translation or Cantonese support.
6. Mandarin command matching is deterministic/anchored, with no English Tier-2 fallthrough; unmatched speech stays dictation.
7. A file transaction does not include installed packages, downloaded model caches or daemon restart.
8. A fixture is **automated evidence**, not a substituted native reviewer, benchmark or OS report.
9. Alternative model defaults require a superseding ADR and per-checkpoint weight license plus product measurements.
10. Every release claim is scoped to specific model revision + hardware/OS/session + surface, with identified limitations.

## Architecture tradeoffs and unresolved decisions

### Active runtime versus desired config

Current `language status --json` describes configured profile, cache and script requirements. It does not by itself verify that an already running daemon has reloaded the new model, especially after `--no-restart` or failed restart. **Proposal:** keep the public CLI backwards compatible, document “configured” explicitly, and add a runtime-effective comparison only if the existing IPC exposes trustworthy state. Any new IPC method/field is L3 and needs an accepted compatibility decision. Do not pretend that commit and restart form a rollback-safe unit.

### Script requirements and offline behavior

OpenCC and the multilingual model are optional prerequisites. The preflight may install/download only with user authorization. Cache presence and importability are prerequisites, not an accuracy guarantee. An air-gapped installation must use a documented pre-provisioned model and extra. A later failure must leave config byte-exact but may leave downloaded or installed prerequisites; report, do not hide, this partial external state.

### Command phrases versus public support

The Mandarin safe-core grammar exists but every `PHRASE_REVIEW` action and `NUMERAL_REVIEW` in `zh.py` is marked `provisional`. The remaining decision is about *human linguistic and safety acceptance*, not inventing another grammar system. High-impact terminal, arbitrary refactor and unsafe "run" phrases stay excluded.

### Measurements versus model choice

The CER harness exists with `zh-eval-v1`; real benchmark evidence remains the gap. Choose model promotion using the same manifest, decoder, CPU/device, exact revision and license. No Whisper/Paraformer/Qwen release claim may be based solely on model cards. SenseVoice's current custom weight license does not meet the default permissive-only policy.

### Documentation state

A historic design description can say “missing” when code now exists. Rather than silently rewriting original decisions, keep a dated [as-built audit](2026-10-29-as-built-audit.md), update the user-facing summary, and require fresh evidence per the [validation plan](2026-10-29-validation-and-release-gates.md). The old ADR IDs 135–139 must not reappear in new issue references.

## Architecture-change review protocol

A contributor may document a proposal or add model-free tests without implicitly accepting an ADR. Any change to a public config key, CLI flag, IPC method, default model, new mandatory dependency, data egress path or terminal-command semantics requires explicit maintainer/L3 review. For accepted ADRs, supersede rather than silently rewrite historical text. For these **Proposed** Mandarin ADRs, maintainer can approve/amend before changing their status.

**Signoff record template:** date, reviewer, each ADR's accepted/superseded/deferred disposition, exact git SHA, implementation exceptions, model/license constraints, native/hardware evidence links, release surface matrix and rollback decision. Until signoff, retain Proposed and describe the Mandarin feature as experimental.
