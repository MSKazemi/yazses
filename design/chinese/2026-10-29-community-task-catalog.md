# Mandarin community implementation backlog — issue-ready work packages

**Status:** Proposed follow-up tasks, 2026-10-29. **These are not newly opened GitHub Issues or new campaign rows.**
**Primary references:** [as-built audit](2026-10-29-as-built-audit.md), [architecture](2026-10-29-language-switch-architecture.md), [model policy](2026-10-29-model-selection-protocol.md), [validation](2026-10-29-validation-and-release-gates.md).
**Task convention:** one concern per PR; exact files + validation + evidence required; keep architecture/privacy/public-interface changes in L3 maintainer review.

## How to use this without duplicating work

1. Read the current code and tests on main, not stale design status tables. The core profile/CLI/Settings/grammar/CJK fixtures/benchmark scorer exist; tasks below target **remaining evidence, gaps, and review**.
2. Check existing [issues #497](https://github.com/MSKazemi/yazses/issues/497), [#499](https://github.com/MSKazemi/yazses/issues/499), [#501](https://github.com/MSKazemi/yazses/issues/501), [#503](https://github.com/MSKazemi/yazses/issues/503), [#505](https://github.com/MSKazemi/yazses/issues/505) and open PRs before creating work. Name the **umbrella issue** in each task's source.
3. Existing campaign inventory already includes four QA tasks, four platform reports and four model evaluation tasks. Their IDs are `CHN-QA-*`, `CHN-COMPAT-*` and `CHN-MEASURE-*`. **Reconcile those states first:** some underlying tests have subsequently landed. Do not create competing tasks or mark evidence complete without a real result.
4. For new work, split into a bounded row in `campaign/tasks.json` only after exact allowed paths, a command that actually exists, explicit negative-test guards, risk/effort, and reviewer evidence are verified. Run `uv run python scripts/campaign.py --generate` and `--check`; never edit generated campaign pages manually.
5. `L0` = evidence/hardware, `L1` = scoped docs, `L2` = bounded code, `L3` = maintainer architecture/privacy/API/dependency. L3 cannot be an advertised first task; native/hardware/evaluation tasks must set `cloud_agent_ready=false`.
6. A green existing test does **not** prove a new behavior. The PR must add a failing/negative case that would reject a fake fix; no personal audio, transcripts, secrets, local absolute paths or fabricated hardware results.

## Dependency order

```text
Phase 0: reconcile campaign state and confirm ADR-v2-140..144 dispositions
   |
   +-- foundation: runtime-truth tests + Settings failure-mode tests
   |        |
   |        +-- packaged/offline smoke on real target
   |
   +-- commands: independent zh-CN / zh-TW native phrase review
   |        |
   |        +-- narrow reviewed phrase corrections + negative corpus
   |
   +-- CJK compatibility: MCP red test -> bug fix
   |                   notes context token-budget test -> fix
   |                   optional feature audit
   |                   real streaming, file, meeting and 4 platform reports
   |
   +-- model evidence: license manifest -> real Whisper small baseline
   |                                  -> turbo/large comparison; Qwen isolated probe
   |
   +-- native end-to-end workflows -> evidence matrix -> docs -> maintainer release
```

The original [implementation-roadmap.md](implementation-roadmap.md) remains the *design-phase* task graph. This file is the **as-built remainder**, not a replacement for a historical ADR.

## Work package overview

| ID | Umbrella | Risk | Time | Goal |
|---|---|---|---:|---|
| `CHN-NEXT-101` | [#497](https://github.com/MSKazemi/yazses/issues/497) | L1 | 30 min | Reconcile current task inventory against already landed Mandarin code |
| `CHN-NEXT-102` | [#497](https://github.com/MSKazemi/yazses/issues/497) | L2 | 60 min | Test configured-versus-running profile after no-restart and restart failure |
| `CHN-NEXT-103` | [#497](https://github.com/MSKazemi/yazses/issues/497) | L2 | 60 min | Validate Settings profile errors and preview against the CLI contract |
| `CHN-NEXT-104` | [#497](https://github.com/MSKazemi/yazses/issues/497) | L0 | 45 min | Prove cached Mandarin setup works after network isolation |
| `CHN-NEXT-201` | [#499](https://github.com/MSKazemi/yazses/issues/499) | L0 | 60 min | Native review of Simplified Mandarin safe-command phrase families |
| `CHN-NEXT-202` | [#499](https://github.com/MSKazemi/yazses/issues/499) | L0 | 60 min | Native review of Traditional Mandarin safe-command phrase families |
| `CHN-NEXT-203` | [#499](https://github.com/MSKazemi/yazses/issues/499) | L2 | 45 min | Turn native-reviewed phrase decisions into deterministic safe grammar and fixtures |
| `CHN-NEXT-204` | [#499](https://github.com/MSKazemi/yazses/issues/499) | L1 | 45 min | Human review of Mandarin numeral naturalness and ranges |
| `CHN-NEXT-301` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L2 | 45 min | Capture MCP transcription config propagation defect as a red test |
| `CHN-NEXT-302` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L2 | 60 min | Correct MCP recimport language propagation behind existing interface |
| `CHN-NEXT-303` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L2 | 60 min | Measure and repair long Mandarin notes context windows |
| `CHN-NEXT-304` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L1 | 45 min | Audit optional CJK-affecting text transforms and their opt-in contracts |
| `CHN-NEXT-305` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L0 | 90 min | Real Whisper Mandarin streaming/segment seam validation |
| `CHN-NEXT-306` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L0 | 90 min | Real Mandarin file transcription and format matrix |
| `CHN-NEXT-307` | [#501](https://github.com/MSKazemi/yazses/issues/501) | L0 | 120 min | Real Mandarin Meeting Mode, recovery and quality verdict |
| `CHN-NEXT-401` | [#503](https://github.com/MSKazemi/yazses/issues/503) | L1 | 45 min | Prepare immutable weight-license and benchmark manifest inventory |
| `CHN-NEXT-402` | [#503](https://github.com/MSKazemi/yazses/issues/503) | L0 | 120 min | Run Whisper small Mandarin reference benchmark |
| `CHN-NEXT-403` | [#503](https://github.com/MSKazemi/yazses/issues/503) | L0 | 120 min | Run same-data Whisper turbo/large model comparisons |
| `CHN-NEXT-404` | [#503](https://github.com/MSKazemi/yazses/issues/503) | L2 | 180 min | Isolate optional Qwen3-ASR-0.6B probe without adding production dependencies |
| `CHN-NEXT-501` | [#505](https://github.com/MSKazemi/yazses/issues/505) | L0 | 60 min | Native Simplified end-to-end workflow review and accessibility check |
| `CHN-NEXT-502` | [#505](https://github.com/MSKazemi/yazses/issues/505) | L0 | 60 min | Native Traditional end-to-end workflow review and accessibility check |
| `CHN-NEXT-503` | [#505](https://github.com/MSKazemi/yazses/issues/505) | L1 | 60 min | Fill evidence-backed Mandarin surface support matrix |
| `CHN-NEXT-504` | [#505](https://github.com/MSKazemi/yazses/issues/505) | L1 | 60 min | Align Simplified/Traditional user docs and README support language |
| `CHN-NEXT-505` | [#505](https://github.com/MSKazemi/yazses/issues/505) | L3 | 90 min | Maintainer ADR disposition and measured release authorization |

## Exact developer contracts

The named validation commands are a **minimum smoke** and must be supplemented by full pytest/ruff/type/packaging gates when applicable. A command naming a *new* test file is only executable after the contributor creates it; validate the task contract before advertising it in the campaign.

### CHN-NEXT-101 — Reconcile current task inventory against already landed Mandarin code

**Source:** [#497](https://github.com/MSKazemi/yazses/issues/497); **risk:** L1; **estimate:** 30 minutes; **blocked by:** current main + audit.

**Allowed files (proposal, narrow further before campaign publication):** `campaign/tasks.json; design/chinese/issue-backlog.md`.

**Implementation / evidence:** For every open CHN task, identify whether its intended deliverable is already on main; propose the correct state/continuation, without deleting contributor history or fabricating a merge.

**Given–when–then / negative acceptance:** No duplicate task IDs and no task marked merged without an actual merged PR; benchmark results remain held pending approval.

**Reviewer command:** `uv run python scripts/campaign.py --check`. **Out of scope / human requirement:** No claims of model/hardware evidence; separate campaign task-state PR and regenerate generated files.

### CHN-NEXT-102 — Test configured-versus-running profile after no-restart and restart failure

**Source:** [#497](https://github.com/MSKazemi/yazses/issues/497); **risk:** L2; **estimate:** 60 minutes; **blocked by:** ADR-v2-140 / architecture review before any public IPC change.

**Allowed files (proposal, narrow further before campaign publication):** `tests/test_cli_language_set.py; tests/test_language_service.py`.

**Implementation / evidence:** Add mocked lifecycle tests for committing zh-CN with --no-restart, failed restart, successfully restarted process, and switching back to en. Check user-facing status does not assert a runtime transition it cannot observe.

**Given–when–then / negative acceptance:** A committed TOML file with old running daemon is not treated as 'active Mandarin'; no rollback of downloaded artifacts is claimed.

**Reviewer command:** `uv run python -m pytest tests/test_cli_language_set.py tests/test_language_service.py -q`. **Out of scope / human requirement:** Do not add/change IPC fields or platform lifecycle Protocols in this task.

### CHN-NEXT-103 — Validate Settings profile errors and preview against the CLI contract

**Source:** [#497](https://github.com/MSKazemi/yazses/issues/497); **risk:** L2; **estimate:** 60 minutes; **blocked by:** Qt test environment available; language service already merged.

**Allowed files (proposal, narrow further before campaign publication):** `tests/test_settings_language_profiles.py; src/yazses/settingsui/language_view.py`.

**Implementation / evidence:** Test invalid profile, missing optional dependency, declined download, concurrent edit, and noop; require the preview to use the exact canonical plan.

**Given–when–then / negative acceptance:** Clicking Apply after a decline must not mutate config, install packages or start a download; no divergence between CLI and Settings preview.

**Reviewer command:** `uv run python -m pytest tests/test_settings_language_profiles.py -q`. **Out of scope / human requirement:** No UI redesign or new library; actual platform UI requires a separate human report.

### CHN-NEXT-104 — Prove cached Mandarin setup works after network isolation

**Source:** [#497](https://github.com/MSKazemi/yazses/issues/497); **risk:** L0; **estimate:** 45 minutes; **blocked by:** P1 packaged build; cached model and OpenCC provisioned; real machine.

**Allowed files (proposal, narrow further before campaign publication):** `docs/research/mandarin-platform/offline-cache.md`.

**Implementation / evidence:** Run dry-run and real dictation with network disabled; capture exact install channel, model revision, messages and result; verify no external access.

**Given–when–then / negative acceptance:** A missing model must fail with clear message, never silently fetch or fall back to English.

**Reviewer command:** `uv run python -m pytest tests/test_stt_model_cache.py -q`. **Out of scope / human requirement:** Physical network-isolation evidence; cloud_agent_ready=false; do not share audio or personally identifying paths.

### CHN-NEXT-201 — Native review of Simplified Mandarin safe-command phrase families

**Source:** [#499](https://github.com/MSKazemi/yazses/issues/499); **risk:** L0; **estimate:** 60 minutes; **blocked by:** Mandarin grammar and positive/negative vectors already exist.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/reviews/zh-cn-commands.md`.

**Implementation / evidence:** A native reader reviews every current PHRASE_REVIEW family for natural Simplified wording, collision with prose, confirmation and intent mapping; record decisions action by action.

**Given–when–then / negative acceptance:** Flag any phrase that can accidentally delete content or execute on ordinary prose. Include at least one unambiguous negative example per action family.

**Reviewer command:** `uv run python -m pytest tests/test_chinese_command_grammar.py tests/test_mandarin_command_safety.py -q`. **Out of scope / human requirement:** Native evidence required, cloud_agent_ready=false; no anonymous 'AI translation verified' statement or audio collection.

### CHN-NEXT-202 — Native review of Traditional Mandarin safe-command phrase families

**Source:** [#499](https://github.com/MSKazemi/yazses/issues/499); **risk:** L0; **estimate:** 60 minutes; **blocked by:** Independent from Simplified review, native Traditional writer.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/reviews/zh-tw-commands.md`.

**Implementation / evidence:** Independently review same PHRASE_REVIEW + NUMERAL_REVIEW list, Taiwan terminology, command ambiguity and negative examples; distinguish script conversion from lexical choices.

**Given–when–then / negative acceptance:** Do not approve a Traditional phrase simply because a Simplified phrase passed OpenCC; include quoted and embedded-command prose.

**Reviewer command:** `uv run python -m pytest tests/test_chinese_command_grammar.py tests/test_mandarin_command_numerals.py -q`. **Out of scope / human requirement:** Native evidence required; cloud_agent_ready=false.

### CHN-NEXT-203 — Turn native-reviewed phrase decisions into deterministic safe grammar and fixtures

**Source:** [#499](https://github.com/MSKazemi/yazses/issues/499); **risk:** L2; **estimate:** 45 minutes; **blocked by:** CHN-NEXT-201/202 accepted; maintainer approval for semantics.

**Allowed files (proposal, narrow further before campaign publication):** `src/yazses/commands/grammars/zh.py; tests/test_chinese_command_grammar.py; tests/test_mandarin_command_safety.py`.

**Implementation / evidence:** Implement only approved phrase corrections; update PHRASE_REVIEW per-action state with a review-record reference; keep anchored rules and English parity.

**Given–when–then / negative acceptance:** Negative Mandarin sentences must remain DICTATE, unknown language never English-fallbacks, no English Tier-2 calls; high-impact terminal commands remain absent.

**Reviewer command:** `uv run python -m pytest tests/test_chinese_command_grammar.py tests/test_mandarin_command_safety.py -q`. **Out of scope / human requirement:** One command family per PR; no SLM or command executor refactor.

### CHN-NEXT-204 — Human review of Mandarin numeral naturalness and ranges

**Source:** [#499](https://github.com/MSKazemi/yazses/issues/499); **risk:** L1; **estimate:** 45 minutes; **blocked by:** CHN-NEXT-201/202 or separate native numeral reviewer.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/reviews/mandarin-numerals.md`.

**Implementation / evidence:** Review 一十, 一百一, 两百五 and other abbreviations; recommend explicit bounded forms, preserving count 0-99 and line 0-999 ceilings unless separately approved.

**Given–when–then / negative acceptance:** Never infer ambiguous numbers or add unbounded repetition; examples outside range must stay dictation.

**Reviewer command:** `uv run python -m pytest tests/test_mandarin_command_numerals.py -q`. **Out of scope / human requirement:** Recommendation only; parser change requires a separate approved L2 task.

### CHN-NEXT-301 — Capture MCP transcription config propagation defect as a red test

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L2; **estimate:** 45 minutes; **blocked by:** Audit F6 in design/chinese/postprocess-compatibility.md.

**Allowed files (proposal, narrow further before campaign publication):** `tests/test_mcp_transcribe_language.py`.

**Implementation / evidence:** Create a minimal server-tool test that selects zh + traditional through the real effective config and asserts the recimport STT section is passed, not the entire Config.

**Given–when–then / negative acceptance:** The test must fail on the old wrong-config path and must not call a network endpoint or use real audio.

**Reviewer command:** `uv run python -m pytest tests/test_mcp_transcribe_language.py -q`. **Out of scope / human requirement:** This validation command becomes executable when the test file is added; do not change MCP public schema yet.

### CHN-NEXT-302 — Correct MCP recimport language propagation behind existing interface

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L2; **estimate:** 60 minutes; **blocked by:** CHN-NEXT-301 repro accepted; verify L3 if public IPC changes needed.

**Allowed files (proposal, narrow further before campaign publication):** `src/yazses/mcp/server.py; tests/test_mcp_transcribe_language.py`.

**Implementation / evidence:** Route canonical recimport + STT config using existing recimport signatures; verify OpenCC and language reach recognizer on MCP path.

**Given–when–then / negative acceptance:** Existing English MCP transcription remains unchanged; no new egress, no private transcript logging and no new MCP method.

**Reviewer command:** `uv run python -m pytest tests/test_mcp_transcribe_language.py tests/test_cjk_transcripts.py -q`. **Out of scope / human requirement:** One bug only; if new public methods are required, stop for maintainer/ADR review.

### CHN-NEXT-303 — Measure and repair long Mandarin notes context windows

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L2; **estimate:** 60 minutes; **blocked by:** Han-aware notes splitting exists but token budget remains English-ratio based.

**Allowed files (proposal, narrow further before campaign publication):** `src/yazses/meeting/notes.py; tests/test_cjk_transcripts.py`.

**Implementation / evidence:** Create a long unspaced Han fixture; document model token budget and split at safe semantic boundaries or conservative budget without truncation.

**Given–when–then / negative acceptance:** No context overflow with test fake, no loss of Han characters; English context behavior unchanged.

**Reviewer command:** `uv run python -m pytest tests/test_cjk_transcripts.py tests/test_minutes_windows_fit_the_model_context.py -q`. **Out of scope / human requirement:** Model-specific tokenizer integration is optional and cannot become a base dependency.

### CHN-NEXT-304 — Audit optional CJK-affecting text transforms and their opt-in contracts

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L1; **estimate:** 45 minutes; **blocked by:** Default-on CJK repairs already in main.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/postprocess-compatibility.md`.

**Implementation / evidence:** For Prosody Ink, staged dictation, SRPace, vocab correction, LLM cleanup and spoken punctuation, map code path, default, Han risk, and a precise test recommendation.

**Given–when–then / negative acceptance:** Do not label a transform safe merely because it is off by default; do not enable any opt-in transform by this documentation task.

**Reviewer command:** `uv run python -m pytest tests/test_cjk_text.py -q`. **Out of scope / human requirement:** Read-only assessment; one follow-up issue per confirmed independent fault.

### CHN-NEXT-305 — Real Whisper Mandarin streaming/segment seam validation

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L0; **estimate:** 90 minutes; **blocked by:** Whisper small cached on a local machine, valid public test phrases.

**Allowed files (proposal, narrow further before campaign publication):** `docs/research/mandarin-platform/streaming.md`.

**Implementation / evidence:** Record partial and final text for multiple segments, long Han-Latin mixes, punctuation and silence, including whether displayed interim text duplicates characters.

**Given–when–then / negative acceptance:** Any duplicated/omitted Han at chunk boundaries is a failure even if final CER is good.

**Reviewer command:** `uv run python -m pytest tests/test_cjk_transcripts.py tests/test_stt_language.py -q`. **Out of scope / human requirement:** Requires real microphone/model; no cloud agent as sole reviewer, no unconsented audio in repo.

### CHN-NEXT-306 — Real Mandarin file transcription and format matrix

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L0; **estimate:** 90 minutes; **blocked by:** Whisper small cached and authorized short + long files.

**Allowed files (proposal, narrow further before campaign publication):** `docs/research/mandarin-platform/file-transcription.md`.

**Implementation / evidence:** Exercise yazses transcribe with zh-CN and zh-TW and inspect TXT/MD/SRT/VTT/JSON for Han spacing, timestamps, subtitles and exact script.

**Given–when–then / negative acceptance:** Output containing '你 好' character-separated text, missing timestamps or wrong script fails; keep CLI defaults intact.

**Reviewer command:** `uv run python -m pytest tests/test_cjk_transcripts.py tests/test_file_transcription_honours_the_config.py -q`. **Out of scope / human requirement:** Real audio may not be published; attach aggregate anonymized results.

### CHN-NEXT-307 — Real Mandarin Meeting Mode, recovery and quality verdict

**Source:** [#501](https://github.com/MSKazemi/yazses/issues/501); **risk:** L0; **estimate:** 120 minutes; **blocked by:** File smoke passes; authorized extended audio; meeting owner.

**Allowed files (proposal, narrow further before campaign publication):** `docs/research/mandarin-platform/meeting-mode.md`.

**Implementation / evidence:** Capture a real Mandarin session and exercise live, stop/finalize, recovery, transcript render, quality gate and notes context. Compare word/character-quality units to human perception.

**Given–when–then / negative acceptance:** A healthy Han meeting must not be thin due to whitespace-count assumption; a missing batch decode must not falsely pass.

**Reviewer command:** `uv run python -m pytest tests/test_meeting_cjk_word_count.py tests/test_cjk_transcripts.py -q`. **Out of scope / human requirement:** No broad meeting-support claim before actual report; never commit raw private meeting audio.

### CHN-NEXT-401 — Prepare immutable weight-license and benchmark manifest inventory

**Source:** [#503](https://github.com/MSKazemi/yazses/issues/503); **risk:** L1; **estimate:** 45 minutes; **blocked by:** Choose exact candidate revisions; dataset permissions known.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/model-license-inventory.md`.

**Implementation / evidence:** Record each checkpoint URL, commit, model weight license source, redistributable artifacts, dependent aligner/tokenizer licensing, and decision state.

**Given–when–then / negative acceptance:** A toolkit license alone cannot certify weights; no production recommendation for custom-licensed SenseVoice without separate review.

**Reviewer command:** `uv run python -m pytest tests/test_bench_mandarin.py -q`. **Out of scope / human requirement:** Documentation only; maintainer/legal clearance if the license is non-permissive.

### CHN-NEXT-402 — Run Whisper small Mandarin reference benchmark

**Source:** [#503](https://github.com/MSKazemi/yazses/issues/503); **risk:** L0; **estimate:** 120 minutes; **blocked by:** Common corpus manifest accepted; CHN-MEASURE-WHISPER-SMALL-001 already in campaign.

**Allowed files (proposal, narrow further before campaign publication):** `results/probes/**; docs/benchmarks.md`.

**Implementation / evidence:** Use real pinned small weights and the frozen corpus; record raw/punct/normalized/script CER, S/D/I, latency, RTF, RSS, core-seconds and exact host.

**Given–when–then / negative acceptance:** Missing immutable model revision, corpus hash, consent/license provenance or OpenCC fold state invalidates the result.

**Reviewer command:** `uv run python -m pytest tests/test_bench_mandarin.py -q`. **Out of scope / human requirement:** Reuse existing CHN-MEASURE task, do not register a duplicate. No raw private audio.

### CHN-NEXT-403 — Run same-data Whisper turbo/large model comparisons

**Source:** [#503](https://github.com/MSKazemi/yazses/issues/503); **risk:** L0; **estimate:** 120 minutes; **blocked by:** CHN-NEXT-402 baseline frozen; separate existing CHN-MEASURE-TURBO/LARGE3 tasks.

**Allowed files (proposal, narrow further before campaign publication):** `results/probes/**; docs/benchmarks.md`.

**Implementation / evidence:** Run identical manifest/split/normalizer/threads on the same hardware where feasible; report quality-resource tradeoffs and long-form failures.

**Given–when–then / negative acceptance:** No comparing numbers from different speakers/corpora as if same sample; never silently promote heavier default.

**Reviewer command:** `uv run python -m pytest tests/test_bench_mandarin.py -q`. **Out of scope / human requirement:** Reuse existing candidate tasks; label hardware not strong enough as not-run.

### CHN-NEXT-404 — Isolate optional Qwen3-ASR-0.6B probe without adding production dependencies

**Source:** [#503](https://github.com/MSKazemi/yazses/issues/503); **risk:** L2; **estimate:** 180 minutes; **blocked by:** Permissive model-weight revision and benchmark corpus pinned.

**Allowed files (proposal, narrow further before campaign publication):** `benchmark/probes/**; results/probes/**`.

**Implementation / evidence:** Run research-only adapter in isolated environment, emit comparable schema and document CPU load, model size, timestamps/forced aligner and offline cache behavior.

**Given–when–then / negative acceptance:** A success on GPU or vendor benchmark cannot be used to claim YazSes CPU support. No mandatory imports in src/yazses.

**Reviewer command:** `uv run python -m pytest tests/test_bench_mandarin.py -q`. **Out of scope / human requirement:** Reuse existing CHN-MEASURE-QWEN3-ASR-06B-001, not a production feature PR.

### CHN-NEXT-501 — Native Simplified end-to-end workflow review and accessibility check

**Source:** [#505](https://github.com/MSKazemi/yazses/issues/505); **risk:** L0; **estimate:** 60 minutes; **blocked by:** Real dictation and language switch installed; human reviewer.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/reviews/zh-cn-workflow.md`.

**Implementation / evidence:** Review installation, switching, mixed text, native typography, command scope, restore English, errors and documentation.

**Given–when–then / negative acceptance:** Native evidence must distinguish successful install from transcription quality; no identifiable audio logs.

**Reviewer command:** `uv run python -m pytest tests/test_cli_language_set.py -q`. **Out of scope / human requirement:** Cloud_agent_ready=false; reviewer consent for public attribution is separate.

### CHN-NEXT-502 — Native Traditional end-to-end workflow review and accessibility check

**Source:** [#505](https://github.com/MSKazemi/yazses/issues/505); **risk:** L0; **estimate:** 60 minutes; **blocked by:** Independent real Traditional-script Mandarin reviewer.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/reviews/zh-tw-workflow.md`.

**Implementation / evidence:** Review all steps as CHN-NEXT-501 independently, including Taiwan terms and Traditional punctuation.

**Given–when–then / negative acceptance:** A locale/script fold alone does not prove natural Taiwan vocabulary or Cantonese coverage.

**Reviewer command:** `uv run python -m pytest tests/test_cli_language_set.py -q`. **Out of scope / human requirement:** Cloud_agent_ready=false; no private data or forced public identity.

### CHN-NEXT-503 — Fill evidence-backed Mandarin surface support matrix

**Source:** [#505](https://github.com/MSKazemi/yazses/issues/505); **risk:** L1; **estimate:** 60 minutes; **blocked by:** Hardware + native + model reports completed, release gate reviewed.

**Allowed files (proposal, narrow further before campaign publication):** `design/chinese/surface-support-matrix.md; design/chinese/2026-10-29-validation-and-release-gates.md`.

**Implementation / evidence:** Each surface has outcome supported/experimental/excluded, exact evidence links, model/revision/hardware limits and reviewer signoff.

**Given–when–then / negative acceptance:** Do not turn missing platform evidence into pass or use a small synthetic corpus for release accuracy claims.

**Reviewer command:** `uv run python -m pytest tests/test_docs_frontmatter.py -q`. **Out of scope / human requirement:** Documentation only, cannot approve release without maintainer.

### CHN-NEXT-504 — Align Simplified/Traditional user docs and README support language

**Source:** [#505](https://github.com/MSKazemi/yazses/issues/505); **risk:** L1; **estimate:** 60 minutes; **blocked by:** CHN-NEXT-503 approved evidence matrix.

**Allowed files (proposal, narrow further before campaign publication):** `docs/use-cases/chinese-voice-typing.md; docs/zh/chinese-voice-typing.md; docs/zh-CN/**; docs/zh-TW/**`.

**Implementation / evidence:** Update both language-switch commands, setup/rollback, model license, limits, P1 supported surfaces, and link evidence; obtain native translation review.

**Given–when–then / negative acceptance:** No claim of Cantonese, full commands, all OSes, or real benchmark quality beyond evidence.

**Reviewer command:** `uv run python -m pytest tests/test_docs_frontmatter.py tests/test_citation_hygiene.py -q`. **Out of scope / human requirement:** Follow docs generators for generated locale pages; do not hand-edit generated output.

### CHN-NEXT-505 — Maintainer ADR disposition and measured release authorization

**Source:** [#505](https://github.com/MSKazemi/yazses/issues/505); **risk:** L3; **estimate:** 90 minutes; **blocked by:** All P0 blockers closed; every claimed surface evidence-backed.

**Allowed files (proposal, narrow further before campaign publication):** `design/adr/adr-v2-140-language-profile-presets.md; design/adr/adr-v2-141-chinese-model-policy.md; design/adr/adr-v2-142-localized-command-grammars.md; design/adr/adr-v2-143-chinese-script-and-locale-semantics.md; design/adr/adr-v2-144-chinese-support-validation-gate.md`.

**Implementation / evidence:** Review accepted vs superseded choices, record deviations and date/owner; authorize support wording only for passing surfaces.

**Given–when–then / negative acceptance:** A green mock suite, missing native review or missing real OS report is insufficient.

**Reviewer command:** `uv run python -m pytest tests/ -q`. **Out of scope / human requirement:** Maintainer-only, not advertised as open L3 campaign task.

## Issue/PR definition of done

Each bounded task or its campaign record must state:

- **Goal:** exactly one user-visible, test, or evidence outcome;
- **Why:** which release gate/risk it closes and why already-merged tests are inadequate;
- **Entry conditions:** prerequisite issue, accepted ADR and exact source revision;
- **Allowed paths:** reviewers can mechanically enforce the diff scope;
- **Non-goals:** no redesign or second feature disguised in an easy task;
- **Acceptance:** Given/When/Then, positive and **negative** failure vector, expected runtime/error/result;
- **Validation:** commands that can run offline and what hardware/native work cannot be automated;
- **Privacy/consent:** no raw speech/identifiers, separate consent for research/publication/model training;
- **Review:** risk lane, human evidence, exact model/platform provenance where applicable;
- **Docs:** user-facing and changelog changes if actual behavior changes, regenerated sources when required.

## Review and reporting cadence

Review architecture and public-interface changes first, let independent native reviewers and hardware testers work in parallel, then approve only evidence-backed surface claims. Contributors submit one PR per task and link the umbrella. Update [validation matrix](2026-10-29-validation-and-release-gates.md) after every completed evidence record. Report a blocked task honestly; do not fill its missing result with a synthetic example.
