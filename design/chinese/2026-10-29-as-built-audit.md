# Mandarin support: implementation audit and gap analysis (2026-10-29)

**Status:** Evidence-based audit, not a product-release approval.
**Code snapshot:** [`main` at `4fda34030b0cf6e269edad78f8e03ea0d91b0324`](https://github.com/MSKazemi/yazses/tree/4fda34030b0cf6e269edad78f8e03ea0d91b0324).
**Scope:** desktop offline Mandarin dictation with Simplified (`zh-CN`) and Traditional (`zh-TW`) output. Cantonese, regional lexical localisation and mixed-language recognition are separate work.

## Executive verdict

The September design package remains a useful *design history*, but it is no longer an accurate inventory of unimplemented features. Profile selection, transactional config writes, CLI/Settings/doctor, Mandarin's conservative Tier-1 grammar, model-free CJK transcript repairs, and the Mandarin CER harness are present in current `main`. That is **implemented/tested in code**, not an evidence-backed claim of native-speaker acceptance, real-model performance, or reliable Unicode injection on every desktop.

**Do not reimplement closed work, change the default English model, introduce another mandatory runtime, or call this a completed Mandarin release.**

## Sources and audit confidence

This audit inspected the public files listed below and the existing tests. A test's presence proves coverage was *written*, not that the full suite passed in this review. No actual microphone, Whisper weights, platform injection, model downloads, Qt window, or end-to-end transcript was executed for this audit. Claims of real-device/model validation therefore remain **unverified**.

| Slice | Implementation reference | Existing automated evidence | Observed state | Next required proof |
|---|---|---|---|---|
| Profile identities and aliases | `src/yazses/language/profiles.py` | `tests/test_language_profiles.py` | Implemented for `en`, `zh-CN/zh-Hans`, `zh-TW/zh-Hant`; `zh` and `zh-HK` rejected as ambiguous | P1 CLI/GUI smoke on real installations |
| Pure plan and preserve/recommended choice | `language/plan.py` | `test_language_profiles.py` | Implemented; keeps compatible selected model and repairs English-only model when switching to Mandarin | Confirm package/engine compatibility and file-based custom models |
| One coherent config transaction | `language/service.py` + `system/configedit.py` | `test_language_service.py`, `test_configedit_atomic.py`, `test_cli_language_set.py` | Implemented; optimistic revision compare, candidate loader validation, retry on concurrent edits | Real install failures, restart failure, process interruption |
| User CLI | `src/yazses/cli.py`, `language list/status/set` | `tests/test_cli_language.py` and `test_cli_language_set.py` | Implemented with dry-run, explicit model/engine, recommended, no-install, no-download, no-restart, yes | Cross-platform binary/package smoke |
| Settings | `settingsui/language_view.py` and Settings controller | `tests/test_settings_language_profiles.py` | Shared service and pure preview exist; Qt tests may skip without PySide6 | Human UX checks on all supported OSes |
| Doctor/readiness | `language/status.py`, `language/capability.py`, `system/doctor.py` | `test_doctor_language.py`, `test_language_capability.py` | Derives configured profile and model capability; no separate profile config | Show configured-vs-running distinction and real prerequisite failures |
| Mandarin safe commands | `commands/grammars/zh.py`, `registry.py`, `commands/grammar.py` | `test_chinese_command_grammar.py`, `test_mandarin_command_safety.py`, `test_mandarin_command_numerals.py` | Deterministic anchored edit/navigation subset; English Tier-2 not used for Mandarin | **All `PHRASE_REVIEW` entries and `NUMERAL_REVIEW` remain provisional**; require native-language review |
| Han script normalisation | `postprocess/han_script.py` + `stt/factory.py` | `test_han_script.py`, `test_stt_factory.py` | Existing optional OpenCC wrapper; source language and output script are distinct | Native Simplified/Traditional lexical QA; dependency/install/air-gapped tests |
| CJK spacing/segments | `postprocess/cjk.py`, `spacing.py`, `stt/faster_whisper.py` | `test_cjk_text.py`, `test_cjk_transcripts.py` | CJK join/spacing fixes committed; September audit's F1–F5 status is historical | Run real model segmented/streaming and mixed Han–Latin traces |
| File/meeting output | `recimport/`, `meeting/quality.py`, `meeting/store.py` | `test_cjk_transcripts.py`, `test_meeting_cjk_word_count.py` | Han quality units and five renderer paths have model-free tests; previous claim that Han counted as one word is outdated | Real long-form meeting/quality and notes-model context windows |
| Model benchmark instrument | `benchmark/bench_mandarin.py`, `mandarin_metrics.py` (harness no longer in this repository) | `test_bench_mandarin.py` (no longer tracked) | `zh-eval-v1` CER scorer and JSON schema, smoke and manifest path existed when audited | Publish actual reproducible Mandarin runs + immutable weight licenses |
| Native OS injection | `inject/`, platform injectors | CJK injection unit tests | In-memory/platform mocking present, but the evidence directory `docs/research/mandarin-platform/` still has README only | Physical X11, Wayland, macOS and Windows reports |
| Published scope | `design/chinese/surface-support-matrix.md` and Chinese how-to | Mostly documentary | Not a measured release contract yet | Release signoff per surface and negative evidence |

## Corrections to earlier planning

1. **ADR IDs changed in main**: use ADR-v2-140 (profiles), 141 (models), 142 (grammar), 143 (speech/script/locale), 144 (release gate), not the old 135–139 identifiers. ADR-v2-135 is now an unrelated face-gesture decision.
2. **Design PR #378 was closed without merging**; the design files nevertheless exist on current main. Use current source and the *current* ADR IDs, not the old branch when creating issues.
3. **Campaign PR #533 was merged**. The `CHN-*` rows already exist in `campaign/tasks.json`; avoid duplicate task IDs or separate issues for each small task.
4. The original `design/chinese/README.md` statement that coherent switching and Mandarin command recognition are still missing describes the *September baseline*, not current main.
5. The original surface matrix calls Meeting Mode's Han token accounting blocked; current `meeting/quality.py::tokenize` and tests explicitly handle Han quality units. **Real Mandarin meeting quality remains unmeasured**.
6. `postprocess-compatibility.md` F1–F5, F7–F9 are marked fixed in its findings table. Open evidence: real model, optional transforms, platform injection, and the reported MCP transcription config propagation defect (F6).
7. The language-switch config transaction is atomic; **optional package installation and model downloads are not rolled back** after a later failure, and an already running daemon may require a restart. Do not claim a system-wide ACID transaction.
8. The `zh-CN`/`zh-TW` profiles represent **Mandarin plus output script**, not separate Mandarin dialect models; `zh-HK` and `yue` are deliberately not P1 aliases.

## As-built flow (no Chinese fork)

```text
user CLI / Settings
  -> language.profiles + language.plan [pure, canonical STT config changes]
  -> language.service [stable read, preflight, optional install/download]
  -> system.configedit [validated atomic replacement]
  -> restart policy owned by caller
  -> core.daemon -> stt.factory -> existing faster-whisper backend
                                 -> optional Han script wrapper
                -> postprocess (pure CJK seam helpers)
                -> commands.grammars.registry (zh grammar only when selected)
                -> platform injection protocols
File transcription / Meeting Mode reuse STT + render/quality seams
```

**Invariants:** the default is `base.en` + English, Mandarin requires a multilingual model, source speech and output script stay independent, no utterance content leaves the device, new heavyweight dependencies are optional/lazy, supported/experimental status is per surface, and the user owns all installations/downloads.

## Live blockers, ordered by potential harm

| Priority | Finding | Specific evidence to close it | Tracking |
|---|---|---|---|
| P0 | No native review of Mandarin command intent phrases; false positives can affect editing | Annotated Simplified and Traditional positive/negative command corpora, reviewer disposition, tests | [#499](https://github.com/MSKazemi/yazses/issues/499), [#505](https://github.com/MSKazemi/yazses/issues/505) |
| P0 | No completed real-device Han injection reports | Four independent dated platform/session reports and at least two target applications per report | [#501](https://github.com/MSKazemi/yazses/issues/501) |
| P0 | No larger, reproducible Mandarin ASR/product benchmark for the release | Pinned benchmark manifest, model revision, CER by slice, CPU latency/RAM, artifact hashes | [#503](https://github.com/MSKazemi/yazses/issues/503) |
| P0 | English default, config safety and offline install must remain intact | Full CI, installer/no-network/restart failure matrix, packaged smoke | [#497](https://github.com/MSKazemi/yazses/issues/497) |
| P1 | Real multi-segment/streaming and long meeting validation absent | Real-audio paths, segmentation, timestamps, meeting recovery, notes context tests | [#501](https://github.com/MSKazemi/yazses/issues/501) |
| P1 | MCP transcription config propagation identified as open in F6 | Minimal red test then fix through the existing recimport config interface, no new network path | [#501](https://github.com/MSKazemi/yazses/issues/501) |
| P1 | Model-card license vs weight revision can diverge | Per-artifact SPDX source, immutable revision, checksums and legal/maintainer review when non-permissive | [#503](https://github.com/MSKazemi/yazses/issues/503) |
| P2 | Optional CJK text transforms not fully checked | Feature-by-feature safety classification; unsupported transforms disabled/clearly excluded | [#501](https://github.com/MSKazemi/yazses/issues/501) |

## What “done” can mean

Maintain four distinct statuses: **implemented (code path exists)**, **automated-tested (identified tests pass)**, **validated (real-model/hardware/native evidence exists)** and **released (maintainer accepted the exact support matrix)**. Do not infer a later status from an earlier one. Results are to be recorded in [release verification](2026-10-29-validation-and-release-gates.md).

**Review rule:** re-run the audit if a language, STT, command, meeting, injection or benchmark PR lands. For every changed line of support wording, link to test + evidence artifact or mark it “not yet verified”.
