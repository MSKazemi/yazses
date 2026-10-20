# Postprocessor compatibility audit for Mandarin (CHN-30 / #501 COMP-01)

**Status:** audit of `main` at `6edac14c`, 2026-10-16. Evidence is `file:line` against that commit; every "Chinese result"
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
| F1 | `postprocess/spacing.py:51-63` | A leading space is inserted between consecutive Han bursts. Only the *previous* burst's last character can say whether the seam is Han–Han, and `continuation_prefix` does not receive it. | **Open.** Fix sketch: optional `previous_tail` argument + `daemon.py` tracking the last injected character; no space when both sides are unspaced-script. English byte-identical. Changes a contract unit ⇒ contract bump (cf. #551). |
| F2 | `postprocess/spacing.py:32` | Full-width closers `，。！？；：、）」』》”’` are not in `_NO_LEADING_SPACE_BEFORE`. | **Open**, same contract caveat. |
| F3 | `stt/filters/disfluency.py:233-251`, `:285` | Filler removal consumes only the ASCII comma. Needs an *English filler inside Mandarin text*, which Whisper in `zh` mode rarely emits, so low frequency. | **Open**, contract-adjacent (`contract/vectors/disfluency.json`). |
| F4 | `stt/filters/disfluency.py:544-546` | Rollback boundary recognises only ASCII `. ` `! ` `? `. Same low frequency as F3. | **Open.** |
| F5 | `stt/faster_whisper.py:204,240,252` | Segments joined with `" "` regardless of script. Not in the contract. **Unverified against a real model**: each segment is `.strip()`ped and re-joined with one space, so the space is inserted whenever a decode yields two or more segments; how often a real Mandarin hold-to-talk burst does is not shown here (no Whisper weights were run, the vector uses a fake model). | **Open.** Fix sketch: join with `""` when the left ends and the right starts with an unspaced-script character; English byte-identical. |
| F6 | `recimport/pipeline.py:40` | `yazses transcribe` built a bare `FasterWhisperEngine` and never applied `[stt] chinese_script`, although [README.md](README.md) states that file transcription is covered by the factory wrapper. | **Fixed for `yazses transcribe`** (`_build_engine(config, stt=…)`, `cli.py` passes `cfg.stt`). **Still open** for the other engine-less callers of `transcribe_file` — `mcp/server.py:37` and `meeting/recover.py` (`recover_meeting(d, cfg.meeting)`, `cli.py:903`) — which hold no `[stt]` section; a fix needs either a parameter or a config key (public interface). |
| F7 | `postprocess/hallucination.py` | Han text erased by `_norm`, so a real sentence could be dropped as a ghost phrase or loop. | **Fixed** (opt-in guard). |

## 4. What this audit did not do

- No audio, no Whisper weights, no real transcripts. All text is synthetic.
- No platform injection (COMP-06..09 need a human on each OS/session).
- Meeting quality counting (COMP-04) and Meeting renderers (COMP-05) are untouched.
- `vocab_correct` is deliberately skipped (concurrent edit).
- The opt-in rows in section 2 are classified from code, not run.
