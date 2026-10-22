# Postprocessor compatibility audit for Mandarin (CHN-30 / #501 COMP-01)

**Status:** audit of `main` at `6edac14c`, 2026-10-16; findings F1–F6 and the transcript/injection
audit (§5) updated 2026-10-21 on branch `feat/501-cjk-compat`. §3 lists what is fixed and what is open. Evidence is `file:line` against that commit; every "Chinese result"
cell was produced by running synthetic text through the real pipeline, not inferred from reading
(`tests/test_cjk_pipeline_vectors.py`). This is the filled-in matrix that
[surface-support-matrix.md](surface-support-matrix.md) leaves as a template.

**Classes.** *CJK-safe* — leaves Han text and full-width punctuation alone. *ASCII/space-dependent* — assumes
whitespace-delimited words or ASCII punctuation. *Language-specific* — an English (or other) lexical rule that is
inert or wrong for Mandarin.

**How "default-on" was decided.** `Config()` was instantiated and every `enabled` flag read. The only default-on text
steps in the dictation path are: the STT segment join, `clean_text`, the disfluency filter, the command classifier +
revise parser, and continuation spacing. Everything else in the daemon's transform chain ships off.

## 1. Default-on transforms (the live dictation path, in pipeline order)

| # | Step | Evidence | Default | Assumption | Class | Chinese result (probed) | Decision | Vector |
|---|---|---|---|---|---|---|---|---|
| 1 | STT segment join `" ".join(seg.text.strip() …)` (3 sites: batch, word-timestamp, streaming window) | `src/yazses/stt/faster_whisper.py:204`, `:240`, `:252` | on | segments are space-separated words | **ASCII/space-dependent** | A multi-segment Han result gets a space at every segment seam: `你好，世界。 今天测试。` | **Finding F5** — open; needs a script-aware join | `test_han_segments_are_not_joined_with_a_space` (xfail) |
| 2 | `clean_text`: strip, drop blank artefacts, strip leading `[\s.…]` | `src/yazses/postprocess/cleaner.py:3`, `:8`, `:10` | on | ASCII `.` and `…` (U+2026) are the only leading noise | **CJK-safe** | Unchanged on every identity vector. Leading `……` (two U+2026) is stripped, same as English `…`; a leading `。` or `，` is kept. | keep | identity set |
| 3 | Vocabulary correction | `src/yazses/core/daemon.py:2653` → `src/yazses/postprocess/vocab_correct.py:172` | **off** (`[stt] vocab_correction`, `config.py` SttConfig) | whitespace tokens (`t.split()`, `:188`) | not audited here | no-op while off | **Not audited** — another session is editing `vocab_correct*`; re-audit after it merges | — |
| 4 | Hallucination guard | `src/yazses/core/daemon.py:2685` → `src/yazses/postprocess/hallucination.py:31` | **off** | `_norm` keeps only `[a-z0-9 ]`, so Han characters are *erased* before matching | **Language-specific** (English ghost list + loop test) | Before the fix, `我们 thanks for watching 然后` was dropped whole. | **Fixed in this change**: Han-bearing text is never judged a ghost phrase or loop (`hallucination.py:42`, `:69`). Pure-Latin behaviour is unchanged. A Chinese ghost list / Chinese loop test is a separate, measured task. | `test_guard_*` |
| 5 | Disfluency filter — Rule A fillers | `src/yazses/stt/filters/disfluency.py:57`, `:254-340`; regex `:284-285` | **on** (`config.py:313`) | English filler list, `\b` anchors, ASCII `,` consumed | **Language-specific** (inert on Han) with one **ASCII-dependent** defect | Mandarin `嗯`/`呃` are not in the list and survive (by design — no destructive default). An English filler inside a Han sentence is removed but only the ASCII comma is consumed: `Uh，我们开始吧` → `，我们开始吧`; `我觉得，um，很好` → `我觉得，，很好`. | **Finding F3** — open (contract-adjacent) | `test_english_filler_*` (xfail) |
| 6 | Disfluency Rule B — 2-gram dedup | `disfluency.py:60`, `:346-366` | on | whitespace tokens | **ASCII/space-dependent** | Inert on unspaced Han (one token). Normalises `\n` and runs of space to single spaces for *all* text (`' '.join(text.split())`), identical to English. | keep; note only | `zh-two-gram-repeat` |
| 7 | Disfluency Rule C — self-correction triggers | `disfluency.py:66`, `:499-561` | on | English trigger phrases; sentence boundary is ASCII `. `/`! `/`? ` (`:544-546`); word boundary via `isalnum` (`:510`) | **Language-specific** + **ASCII-dependent** boundary | Chinese phrases are not triggers (`我说不用了算了` untouched). With an English trigger inside Han text the prior sentence is lost because `。` is not a boundary: `我今天很忙。 scratch that 我很闲` → `我很闲` (English keeps the earlier sentence). | **Finding F4** — open | `test_english_correction_phrase_*` (xfail) |
| 8 | Disfluency tail: collapse double spaces | `disfluency.py:69` | on | ASCII spaces | **CJK-safe** | `你好  世界` → `你好 世界` (collapses, never inserts); U+3000 is treated as whitespace by `split()` in step 6 and becomes `" "` | keep; note only | — |
| 9 | Command classifier + revise parser | `src/yazses/core/daemon.py:2934` (`parse_revise`), `:2855` (`classify`); grammar `[commands] language`, `config.py:433` | on | per-language grammar (`en`, `zh`) | **Language-specific** (a `zh` grammar exists) | None of the identity vectors was classified as a command under either `stt.language`. Command grammar correctness is its own track (`tests/test_chinese_command_grammar.py`). | out of scope here | identity set |
| 10 | Continuation spacing | `src/yazses/postprocess/spacing.py:32`, `:51-63`; wired at `src/yazses/core/daemon.py:3228`; window default `config.py:259` (30 s) | on | a burst follows another word; closing punctuation is ASCII/Persian only | **ASCII/space-dependent** | Every second burst within 30 s gets a leading space: `今天测试。` → ` 今天测试。`. A full-width closer is not in the suppression set: `，然后` → ` ，然后`. | **Findings F1, F2** — open; the unit is a *contract* unit (`contract/vectors/spacing.json`), so a fix is a contract change and needs a decision | `test_second_han_burst_*`, `test_burst_opening_with_a_fullwidth_comma_*` (xfail) |
| 11 | Inject log line `len(text.split())` "words" | `src/yazses/core/daemon.py:2719` | on | whitespace words | **ASCII/space-dependent** (log only) | Reports a Han run as 1 word. Metadata only; no behaviour depends on it. | note only | — |

Not a postprocessor but the same assumption, tracked separately: `meeting/quality.py::tokenize()` and
`store.live_word_count()` (CHN-R05 in [risk-register.md](risk-register.md)) — COMP-04, not covered here.

## 2. Opt-in transforms that touch the text (all off by default; classified, not exhaustively probed)

| Step | Evidence | Class | Note |
|---|---|---|---|
| Spoken punctuation | `src/yazses/postprocess/voice_punctuation.py:39-51` (`\b` + English phrases) | Language-specific | Inert on Mandarin; a Chinese spoken-punctuation table is feature work, not a bug. |
| Prosody Ink | `src/yazses/postprocess/prosody.py:162-219` (`text.split()` aligned by index to word timings; `" ".join` at `:92`) | ASCII/space-dependent | Whisper word timestamps for Mandarin are not whitespace tokens, so token/word alignment would not hold. Exclude for `zh` until measured (matrix says "exclude if destructive"). |
| Phonetic corrector | `src/yazses/postprocess/phonetic.py:52` (`[^a-z]` key) | Language-specific | Latin sound keys only; inert on Han. |
| LLM cleanup | `src/yazses/postprocess/llm_cleanup.py:124-141` (critical-token guard) | not audited | Off; token guard is whitespace-token based. |
| Han script normaliser | `src/yazses/postprocess/han_script.py:121-135` | CJK-specific | Off until `[stt] chinese_script` is set; no-op without Han (`contains_han`). Wired in the factory only — see F6. |
| Persian normaliser | `src/yazses/postprocess/persian_text.py` | Language-specific | Gated by `[stt] language`; inert otherwise. |
| Streaming injection | `src/yazses/config.py:287` (`StreamingConfig`, off), `src/yazses/stt/streaming.py:192` (`_common_prefix`) | CJK-safe by construction | Character prefix, not word prefix. Not run end to end here. |
| Daemon chain `core/daemon.py:3030-3200` (ITN, GEC, diacritize, translit, sembr, markup, …) | each `enabled=False` | not audited | Each ships dormant (AGENTS.md rule 2). Audit when a Mandarin user turns one on. |

## 3. Findings

| ID | Where | Defect | State |
|---|---|---|---|
| F1 | `postprocess/spacing.py` | A leading space is inserted between consecutive Han bursts. Only the *previous* burst's last character can say whether the seam is Han–Han, and `continuation_prefix` did not receive it. | **Fixed.** Optional `previous_tail` argument. `core/daemon.py` records `_last_dictation_tail` wherever it records `_last_dictation_monotonic`. The seam rule is `postprocess/cjk.py::needs_space`. Contract 7.1.0 (`spacing.json`). |
| F2 | `postprocess/spacing.py` | Full-width closers `，。！？；：、）」』》` were not in `_NO_LEADING_SPACE_BEFORE`. | **Fixed.** Any CJK punctuation mark suppresses the separator, opening marks included, because a full-width glyph carries its own spacing. Contract 7.1.0. |
| F3 | `stt/filters/disfluency.py` Rule A | Filler removal consumed only the ASCII comma. This needs an *English filler inside Mandarin text*, which Whisper in `zh` mode rarely emits, so it is low frequency. | **Fixed.** A trailing `，` or `、` is consumed with the filler. A leading filler's full-width mark is stripped. A dangling final full-width clause mark is tidied. The `_CJK_*` sets are separate, so the code-identifier guards are untouched. Contract 7.1.0 (`disfluency.json`). |
| F4 | `stt/filters/disfluency.py` Rule C | The rollback boundary recognised only ASCII `. ` `! ` `? `. | **Fixed.** `。！？` are boundaries with or without a following space. The trigger clause's own full-width mark is consumed. Contract 7.1.0. |
| F5 | `stt/faster_whisper.py` (`transcribe`, `transcribe_words`, `decode_window`) | Segments were joined with `" "` regardless of script. | **Fixed** (`cjk.join_pieces`). **Not verified against a real model**: no Whisper weights were run, so how often a real Mandarin hold-to-talk burst decodes to two or more segments is not measured. |
| F6 | `recimport/pipeline.py` | File transcription built a bare `FasterWhisperEngine` and never applied `[stt] chinese_script`. | **Fixed for `yazses transcribe`** (8f0edff1) **and for `yazses meeting recover`**: `stt=` is threaded through `recover_meeting` → `finalize_meeting` → `transcribe_file`. Live meetings already used the daemon's factory-wrapped engine. **Still open: `mcp/server.py`.** It passes the whole `Config` as the recimport section, so the MCP `transcribe` tool decodes with `small.en` in English whatever `[recimport]` and `[stt]` say. The defect is wider than Mandarin and needs an owner decision. |
| F8 | `recimport/align.py`, `recimport/subtitles.py`, `meeting/notes.py`, `meeting/store.py::live_text` | Per-character Mandarin word tokens were re-joined with `" "` (`你 好 ， 世 界`) in utterances, JSON words and captions. Captions were measured in code points and broken only at spaces. A long Mandarin turn could not be split for the notes window. | **Fixed.** See §5. |
| F9 | `inject/unicode.py`, `inject/ydotool.py` | The XKB/uinput path raised on the first character the layout lacks, but only *after* typing everything before it. The clipboard fallback then typed the prefix a second time (`YazSes YazSes 版本`). | **Fixed.** The whole burst is resolved before the first keystroke. See §5. |
| F7 | `postprocess/hallucination.py` | Han text erased by `_norm`, so a real sentence could be dropped as a ghost phrase or loop. | **Fixed** (opt-in guard). |

## 4. What this audit did not do

- No audio, no Whisper weights, no real transcripts. All text is synthetic.
- No platform injection (COMP-06..09 need a human on each OS/session).
- `vocab_correct` is deliberately skipped (concurrent edit).
- The opt-in rows in section 2 are classified from code, not run.
- No native speaker reviewed the spacing convention (a Han–Latin seam keeps its space) or the
  disfluency expectations (`我觉得，um，很好` → `我觉得，很好`).

## 5. File transcription, Meeting Mode and injection (2026-10-21)

Every fix uses one rule, `src/yazses/postprocess/cjk.py` (pure, stdlib only). It is built so that
**text holding no CJK character takes exactly the old code path**, and `tests/test_cjk_text.py`
checks that property with Hypothesis.

| Surface | Evidence | Before | After | Vector |
|---|---|---|---|---|
| Word tokens of a `zh` decode | faster-whisper 1.2.1 `Tokenizer.split_to_word_tokens` splits `zh/ja/th/lo/my/yue` on code points, not spaces | `YazSes` came back as `Yaz`, `Ses`. Once stripped, the no-space signal was lost | `stt/faster_whisper.py::_glued_words` regroups by each raw token's leading whitespace. Han–Han pairs stay separate tokens. It runs only for those decode languages (`info.language`) | `test_cjk_transcripts.py::test_mandarin_word_tokens_come_back_as_written` |
| Diarized utterances | `recimport/align.py::merge_utterances` | `你 好 ， 世 界` | `join_pieces` | `test_diarized_utterances_join_han_words_without_spaces` |
| SRT/VTT segments | `recimport/subtitles.py::merge_word_timestamps` | `你 好， 世 界。…`, with the budget counted in code points | `join_pieces`, with the budget counted in display columns (Han = 2) | `test_caption_segment_*` |
| Caption wrapping | `recimport/subtitles.py::wrap_caption` | A Han caption had no space to break at, so it stayed one 80-column line | Broken between characters (`cjk.break_units`), never before `，` or after `「` | `test_mandarin_caption_is_wrapped_between_characters` |
| Every renderer | `recimport/render.py` md/txt/srt/vtt/json | Inherited the faults above | Han text intact in all five formats | `test_every_renderer_keeps_the_han_text_intact` |
| Meeting quality counts (COMP-04) | `meeting/quality.py::tokenize` | Already Han-aware since `6ac8f152` | Unchanged | `test_meeting_quality_counts_han_characters_not_whitespace_runs` |
| Live transcript join | `meeting/store.py::live_text` | Lines joined with `" "` | `join_pieces` | `test_live_text_joins_mandarin_lines_without_a_space` |
| Notes window split | `meeting/notes.py::_split_long_text` | A Mandarin turn has no whitespace, so it was returned whole at any length | Split between characters within the budget | `test_notes_window_splits_a_long_mandarin_turn_within_budget` |
| Portal keysyms | `inject/keysyms.py::char_to_keysym` | Already correct | One keysym per code point (`0x01000000 + cp`), astral planes included; now pinned by a test | `test_cjk_injection.py::test_portal_*` |
| Windows `SendInput`, macOS Quartz | `platform/windows/injector.py::_utf16_units`, `platform/macos/injector.py::_utf16_chunks` | Already correct | Surrogate pairs are sent whole and never split across a chunk; now pinned for Han | `test_windows_*`, `test_macos_*` |
| XKB/uinput and the ydotool mixed path | `inject/unicode.py`, `inject/ydotool.py::_inject_mixed` | The prefix was typed, then the injector raised, then the clipboard pasted the whole burst | `UnicodeInjector._plan` and `ensure_producible` resolve every character before typing | `test_linux_fallback_types_a_mixed_han_burst_exactly_once` |

**Not fixed, recorded:**

- `meeting/notes.py` sizes its window as `tokens × CHARS_PER_TOKEN`, an English ratio. Han text
  costs more tokens per character, so a Mandarin window can still overrun the model context. This
  was not measured, so it was not changed.
- `cli.py` `staged commit` counts "words" with `split()`. The effect is cosmetic.
- The opt-in surfaces (`srpace`, staged dictation, Prosody Ink) were not re-audited.
