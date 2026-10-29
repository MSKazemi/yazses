# Mandarin validation plan, evidence schema and release gates

**Status:** Proposed P1 verification plan (2026-10-29), **not** a record of completed testing.
**Governing ADR:** v2-144; **evidence owners:** [#497](https://github.com/MSKazemi/yazses/issues/497) foundation, [#499](https://github.com/MSKazemi/yazses/issues/499) commands, [#501](https://github.com/MSKazemi/yazses/issues/501) compatibility, [#503](https://github.com/MSKazemi/yazses/issues/503) ASR, [#505](https://github.com/MSKazemi/yazses/issues/505) release.
**Release scope:** Mandarin + Simplified/Traditional output, one verified surface at a time.

## Verification rules

- Treat **unit test**, **packaged integration**, **real model**, **real OS/hardware**, **native speaker**, and **release signoff** as distinct gates. A passing mock or pre-existing source file must never be presented as real-world product validation.
- No human reviewer may be replaced by machine translation, synthetic Chinese phrases, an LLM's confidence or an English maintainer's intuition.
- Default English and the offline/privacy contracts are **non-negotiable blocking regressions**.
- Every P1 support row needs a named owner, test/protocol, artifact path, date, model revision, OS details if relevant, result, limitations and reviewer signoff. Missing evidence means “experimental/unverified”.
- Run the complete repository gates from `AGENTS.md` with an up-to-date checkout before merging production code. If a gate cannot run, state why and do not claim it passed.

## Layer 1: model-free CI (required for every PR)

| Gate | What must be proven | Existing test entrypoint | Additional negative/failure case |
|---|---|---|---|
| G01 profiles | aliases normalize, `zh`/`zh-HK` refuse, correct script/model | `tests/test_language_profiles.py` | invalid override has zero side effects |
| G02 atomic config | one candidate, revisions, lock, comments/unrelated keys preserved, invalid file refused | `tests/test_configedit_atomic.py` | interrupted/duplicate TOML / malformed value |
| G03 side-effect service | dry-run, preflight, refused install/download, repeated edits, restart guard | `tests/test_language_service.py`, `test_cli_language_set.py` | config commits but runtime restart fails |
| G04 command state | `auto` picks actual speech language; explicit pin is preserved and warned | `tests/test_chinese_command_grammar.py`, `test_doctor_language.py` | unsupported grammar never falls back to English |
| G05 command precision | anchored positive + negative Mandarin prose and bounded numerals | `tests/test_mandarin_command_safety.py`, `test_mandarin_command_numerals.py` | edit-looking text inside full sentence stays dictation |
| G06 Han conversion | Simplified/Traditional, no-Han pass-through, mixed ASCII and punctuation | `tests/test_han_script.py`, `test_cjk_text.py` | missing OpenCC and bad script requested |
| G07 STT decode seams | batch/word-timestamps/streaming inherit configured language, detect actual decoded language | `tests/test_stt_language.py`, `test_cjk_transcripts.py`, `test_language_reaches_every_decoder.py` | no inserting whitespace inside Han across segment boundaries |
| G08 transcripts & meetings | captions/MD/TXT/SRT/VTT/JSON, CJK token-count, notes windows | `tests/test_cjk_transcripts.py`, `test_meeting_cjk_word_count.py` | long unspaced turn and 4-byte Unicode |
| G09 decoder compatibility | English-only checkpoints cannot silently decode Mandarin as English | `tests/test_language_capability.py`, `test_stt_factory.py` | specialized engine with conflicting language |
| G10 scoring integrity | CER versions, S/D/I sum, no fake script-fold score, schema/license audit | `tests/test_bench_mandarin.py` | tampered number/revision or absent license fails |
| G11 Settings | same plan/service, no second persistent state, offscreen Qt where available | `tests/test_settings_language_profiles.py` | consent decline, model install failure, quit mid-apply |
| G12 default regression | English keyboard, command semantics, doc generator, egress and private-path constraints | `uv run python -m pytest tests/ -q` | Chinese module absent from base install |

Ordinary offline tests must be deterministic and contain neither private speech nor model downloads. Qt-dependent tests legitimately skip where Qt extra is absent; a successful skip is not a GUI smoke result. Negative cases that expose current bugs should first be committed as a red reproducer in a targeted PR, then fixed in a separate code review where practical.

### CI commands

```sh
uv sync
uv run python -m pytest \
  tests/test_language_profiles.py \
  tests/test_language_service.py \
  tests/test_configedit_atomic.py \
  tests/test_cli_language.py \
  tests/test_cli_language_set.py \
  tests/test_chinese_command_grammar.py \
  tests/test_mandarin_command_numerals.py \
  tests/test_mandarin_command_safety.py \
  tests/test_han_script.py \
  tests/test_cjk_text.py \
  tests/test_cjk_transcripts.py \
  tests/test_meeting_cjk_word_count.py \
  tests/test_bench_mandarin.py -v
uv run python -m pytest tests/ -q
uv run ruff check src tests scripts
uv run mypy src
```

When config/CLI/schema changes, regenerate docs with `uv run python scripts/gen-docs.py` or `make docs` as directed by `AGENTS.md`; do not edit generated reference docs by hand. Any new source dependency needs the project's optional-extra, import and egress gates.

## Layer 2: language-profile installation and lifecycle

For **each** claimed distribution/channel and the three profiles `en`, `zh-CN`, `zh-TW`:

1. Start from a fresh English config, record installed package/version and base `base.en` state.
2. `language set zh-CN --dry-run`: verify *zero* file, package, network, cache, daemon changes.
3. `language set zh-CN --no-download --no-install` without artifacts: verify refusal and byte-identical config.
4. Explicitly approve preparing the script extra and multilingual model; verify cached artifact and coherent one-shot config.
5. Start/restart the daemon, dictate a fixed test sentence, verify status/doctor; **separate configured from running-effective model**.
6. Switch to `zh-TW` with existing `small`: only script changes; no redundant model download.
7. Switch to English in preserve mode: keep compatible multilingual model; optionally `--recommended-model` to return to `base.en`.
8. Concurrent CLI + Settings edit: preserve unrelated changes, one writer wins safely, no partial profile.
9. Fail model download, dependency install, config write and process restart separately: record config bytes, cache state, daemon state and messages.
10. Remove network after cache provisioning and repeat dictation/file/meeting supported flows; no hidden fetch or telemetry.

**Important:** package installs and downloads may remain after a failed later step. That is an expected outcome of the current config-only transaction; the UI must report it accurately.

## Layer 3: real recognition and quality (mandatory for a “dictation supported” label)

Use [the model protocol](2026-10-29-model-selection-protocol.md). Run real authorized Mandarin audio with the shipping adapter and pinned weights. At minimum cover `zh-CN` and `zh-TW` references, short/long speech, mixed Han+Latin, numbers/names, accent/noise, silence, word timestamps, streaming and file transcription. Record `cer_raw`, `cer_normalized`, `cer_script_normalized`, p50/p95 latency, RTF, RSS and core-seconds.

Set **quantitative accept/reject SLOs before evaluating the holdout**. Suggested governance: the release manager pre-registers hardware classes, expected max latency and memory, minimum speaker/sample counts and tolerable absolute CER with native reviewers; the repository currently lacks enough representative Mandarin data to defend one universal absolute CER threshold. Do not pick a threshold after viewing model results.

A model-specific advantage cannot compensate for failed Unicode injection, unsafe commands or data egress. Report all failures, not only successful clips.

## Layer 4: native phrase and usability review

At least one independent native reviewer for Simplified Mandarin and one for Traditional Mandarin must execute:

- Installation, first model/cache preparation, dry-run and offline-after-cache, language switch both ways;
- Natural phrase round-trip for every shipped `commands/grammars/zh.py::PHRASE_REVIEW` action family (all currently provisional); `NUMERAL_REVIEW` for counts and line numbers;
- Negative set: ordinary prose, quoted instructions, sentence-long occurrences of command verbs, navigation/file-name phrases, disfluencies, homophones and incomplete fragments;
- Dictation in a text editor, browser input and office/document field, including Simplified and Traditional punctuation/IME interactions;
- Return to English without losing previous model/settings and without unexpected command execution.

A phrase is accepted only after native reviewer disposition and matching positive/negative tests. One English speaker's literal translations are insufficient. Use the privacy-safe protocol at [human-validation-data-protocol.md](human-validation-data-protocol.md). Store approval as a dated decision + reviewer consent; do not require publication of legal names or private emails.

### Command false-positive policy

A false positive for a destructive/high-impact command is a release blocker on that action family. No broad “Chinese commands supported” claim while any P1 phrase remains unreviewed. A deliberate narrow safe-core subset may be supported with all other families explicitly excluded. The English Tier-2 classifier must remain disabled for Mandarin until a separate safety ADR and benchmark clear it.

## Layer 5: desktop Unicode and physical application matrix

There are **no submitted platform reports** in `docs/research/mandarin-platform/` as of this audit; keep their status unverified.

| Report | Required platform/session | Targets | Required strings / checks |
|---|---|---|---|
| `linux-x11.md` | a real X11 desktop + exact injector/backend | Two real editable applications | Simplified, Traditional, mixed Latin, punctuation, long burst |
| `linux-wayland.md` | named compositor/portal/backend | Two real editable applications | Same, plus clipboard/portal fallback and focus |
| `macos.md` | macOS version + architecture + input permissions | Two real editable applications | Same, UTF-16/surrogates and restart |
| `windows.md` | Windows build + injection backend/IME state | Two real editable applications | Same, surrogate pairs and clipboard fallback |

Fixed public strings: `你好，世界。今天测试 YazSes 123。`; `你好，世界。今天測試 YazSes 123。`; `版本 v2.0，文件 test.py，编号 12345。`; plus a non-BMP emoji and a burst with a Han prefix/suffix around Latin text. Each report must say exact **observed output**, not only “worked”; record whether mixed-mode typing duplicated a prefix, lost focus, or required clipboard.

A failed backend is **not** a reason to hide evidence: mark unsupported or restrict the product's support claim to a verified fallback. Do not classify an OS supported based solely on a test mocking its injector.

## Layer 6: cross-surface matrix and regression

| Product surface | Automated path today | Extra manual evidence | Default public wording until evidence arrives |
|---|---|---|---|
| Hold-to-talk | Engine/language/script tests | Real Mandarin voice + application injection | Experimental |
| Streaming | `decode_window` and CJK joining tests | partial/final no-duplication/stability in actual sessions | Experimental |
| File transcription | `recimport` and renderer tests | real `yazses transcribe` (short/long, format matrix) | Experimental |
| Meeting live/batch | Han quality-unit and notes tests | real multihour, recovery, timestamps, quality/notes context | Unverified for release |
| Editing/navigation commands | anchored grammar and negative corpus tests | reviewed phrases in Simplified + Traditional | Preview; provisional |
| Terminal/open-ended commands | intentionally absent | independent high-risk safety/design gate | Excluded |
| Offline cache | unit tests | network-disabled packaged use after provisioning | Unverified until physical test |
| Cantonese/`zh-HK` | deliberate profile rejection | requires separate model/corpus/grammar | Not included |
| UI/doc translation | documentation exists | native UI and docs audit | Locale independent of dictation |

## Evidence artifact schema

Store aggregate results under tracked public design/docs/result locations *only when safe*. Suggested machine-readable report:

```json
{
  "schema": "yazses.mandarin.release/1",
  "date_utc": "YYYY-MM-DD",
  "yazses_commit": "<immutable SHA>",
  "profile": "zh-CN",
  "surface": "hold-to-talk",
  "platform": {
    "os": "<name+version>",
    "session": "<X11|Wayland|macOS|Windows>",
    "app_versions": ["<target app version>"]
  },
  "model": {
    "id": "small",
    "revision": "<immutable model revision>",
    "license_id": "MIT",
    "weights_sha256": "<sha256>"
  },
  "corpus_sha256": "<authorized corpus manifest SHA256 or null>",
  "evidence": ["<relative public artifact path>"],
  "result": "pass|fail|blocked|not-run",
  "limitations": ["<named limitation>"],
  "review": {
    "native_simplified": "pending|approved|not-applicable",
    "native_traditional": "pending|approved|not-applicable",
    "maintainer": "pending|approved"
  }
}
```

This is a **proposed release-report format**, not an implemented validator or a claim that those files exist. Raw audio, private transcripts, personal home paths, emails and biometric data must not be committed.

## Release checklist and signoff (ADR-v2-144)

- [ ] All governing ADR decisions reviewed; scope and every deferred capability named.
- [ ] CI gates G01–G12 green against exact release commit; full English tests green; lint and import budgets green.
- [ ] Model/corpus license provenance pinned and benchmark JSON validated with a frozen split.
- [ ] Release hardware SLOs pre-registered and met for each claimed device tier.
- [ ] Simplified and Traditional native reviewer approval recorded separately.
- [ ] Every *advertised* platform/session injection report exists and shows tested applications.
- [ ] Real short-file and streaming finalization complete; meeting only if separately cleared.
- [ ] No undesired network egress; fully offline after provisioning.
- [ ] Installer, error-recovery, dry-run, rollback-to-English, and no-restart states verified.
- [ ] Product docs clearly distinguish Mandarin and script, commands preview scope, Cantonese exclusion.
- [ ] Each surface marked supported/experimental/excluded with citations to exact evidence.
- [ ] Maintainer signs/date-stamps release decision and known exceptions; no blanket “Chinese supported” without that matrix.

Until all relevant conditions pass, the release statement is: **“YazSes has experimental offline Mandarin dictation with Simplified/Traditional output; availability and quality vary by tested model, application and platform.”** Do not imply the same validation for Cantonese, arbitrary code switching, every Mandarin accent or every desktop target.
