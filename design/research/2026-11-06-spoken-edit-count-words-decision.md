# Decision packet: Spoken Edit count words ("delete the last twenty words")

**Date / audited revision:** 2026-11-06, `main` @ `8a72bbc6`
**Status:** Proposal, not a decision. Nothing here changes code. The owner decides.
**Found:** Round 7 review, deliberately left unfixed so it could be decided first.
**Related:** [ADR-v2-003 Spoken Edit Mode](../adr/adr-v2-003-spoken-edit-mode.md) ·
[ADR-021 invest in error cost](../adr/adr-021-invest-in-error-cost.md) ·
Mandarin count precedent `src/yazses/commands/grammars/zh.py`

**Evidence labels:** **[Code]** read in this checkout at `8a72bbc6` (`file:line`) ·
**[Assumption]** reasoning with no measurement · **[Unknown]** not established.
No external source was used. No audio or transcript was used.

> **Coordination note.** Another unmerged branch already changes
> `src/yazses/commands/edit_ops.py`. Line numbers below are at `8a72bbc6`. Any
> implementation must start after that branch lands, or rebase onto it.

## 1. The defect, in one line

`parse_edit("delete the last twenty words")` returns `("delete_words", {"n": 1})`. It
deletes **one** word and reports success. Any count word the parser does not know becomes 1.

## 2. Current behaviour

### 2.1 The parser (pure module)

| What | Where | Behaviour |
|---|---|---|
| Number vocabulary | `src/yazses/commands/edit_ops.py:17-20` | `a, an, one … ten`. Nothing above ten. No compounds. |
| Count lookup | `edit_ops.py:29-33` (`_n`) | Digits go through `int()` with **no upper bound**. Any other token gets `_NUMBER_WORDS.get(token, default)` with `default=1`. **This fallback is the defect.** |
| Frame regex | `edit_ops.py:103-105` (`_RE_DEL_WORDS`) | `^delete\s+(?:the\s+)?last\s+(?:(\w+)\s+)?words?$`, case-insensitive. The count slot is **any single `\w+` token**. |
| Parse | `edit_ops.py:129-130` | `("delete_words", {"n": _n(m.group(1) or "one")})` |
| Apply | `edit_ops.py:57-64` | `delete_last_words` splits on whitespace and keeps `words[:-n]`. If `n >= len(words)` it clears the text. `n <= 0` does nothing. |
| Destructive set | `edit_ops.py:151` | `delete_words` is in `DESTRUCTIVE`. |

What the parser does with some inputs, read from the code above [Code]:

| Utterance (after outer-punctuation strip, `edit_ops.py:122`) | Parsed today | Correct? |
|---|---|---|
| `delete the last three words` | `n=3` | yes (`tests/test_edit_ops.py:67-70`) |
| `delete last 2 words` | `n=2` | yes |
| `delete the last twenty words` | `n=1` | **no: silent under-count** |
| `delete the last eleven words` | `n=1` | **no** |
| `delete the last few words` / `several` / `couple` | `n=1` | it guesses. The request is vague. |
| `delete the last bad words` | `n=1` | it guesses. "bad" is not a count. |
| `delete the last for words` (ASR homophone of "four") | `n=1` | **no** |
| `delete the last twenty one words` | `None` (two tokens) | not recognised. In command mode it is discarded, not typed. |
| `delete the last twenty-one words` | `None` (`\w` excludes `-`) | as above |
| `delete the last 500 words` | `n=500` | no cap. In practice it is clamped by the ledger (see 2.2). |
| `delete the last passwords` | `None` | yes, regression-pinned by `tests/test_spoken_edit_does_not_match_a_word_ending_in_words.py` |

### 2.2 Who reaches it (daemon)

- **Command mode only.** `_try_spoken_edit` is called at `src/yazses/core/daemon.py:4799`.
  That is inside the `if command_mode:` branch (`daemon.py:4691`). It runs only after
  `classify(...)` (`daemon.py:4692-4695`) returned `DICTATE`, meaning no grammar rule
  matched (`daemon.py:4717`). Ordinary prose dictation never reaches `parse_edit` [Code].
- **Two opt-ins, both off by default.** `[commands] spoken_edit = False`
  (`src/yazses/config.py:520`) gates the call (`daemon.py:4796`).
  `[commands] spoken_edit_destructive = False` (`config.py:524`) gates deletes. With it off,
  a delete is recognised, logged as `spoken_edit_skipped` and **not applied**
  (`daemon.py:8030-8035`) [Code].
- **Bounded to the last dictation.** The edit applies to `self._ledger.last_text()`
  (`daemon.py:8036`) through `_replace_last_burst`. The ledger stays updated, so
  "scratch that" undoes it (`daemon.py:8010-8022`). An over-count can at worst clear the
  last dictation. It cannot reach text from before that dictation [Code].

Who is affected today: users who turned on **both** flags and then say a count above ten
or a non-number word. [Unknown] how many such users there are. Telemetry is forbidden,
so this cannot be measured in the field.

### 2.3 The digit path is a different code path (adjacent finding)

The English grammar matches `^delete\s+(?:the\s+)?last\s+(\d+)\s+words?$`
(`src/yazses/commands/grammars/en.py:58`) **before** Spoken Edit ever sees the phrase. The
dispatcher then sends Ctrl+BackSpace `n` times (`src/yazses/commands/dispatch.py:226-230`).
That path has **no cap** and **no ledger bound**. It is not gated by
`spoken_edit_destructive`: "delete the last 500 words" sends 500 word-deletes into the
focused app. The same holds for `delete_lines` (`en.py:60`) and `undo_n` (`en.py:63`,
`dispatch.py:241-244`).

The Mandarin grammar already solved this. It uses a closed 0-99 count
(`zh.py:36-39`, `MAX_COUNT = 99`) and a parser with "no fuzzy fallback"
(`zh.py:118-140`, `parse_command_number`). Its destructive actions are reachable only
through a literal prefix with a capped count (`zh.py:285-290`).

This packet is about the **word** path in `edit_ops.py`. The uncapped English digit path
should be raised as its own issue so the two decisions stay separate. It is listed under
"Owner decisions" below.

[Unknown] Which form Whisper or Parakeet produces for a spoken count ("20" or "twenty")
has not been measured here. If the decoder mostly emits digits, most real traffic takes
the grammar path in 2.3, not this one. That is why section 6 includes a measurement step.

## 3. Options

### A. Extend the number vocabulary (closed set)

Recognise 0-99 as words: `zero`…`nineteen`, the tens `twenty`…`ninety`, and compounds
`twenty one` / `twenty-one`. The set is closed and checked exactly. This is the same shape
as `zh.py`.

- **Fixes:** "twenty", "eleven", "twenty one", "twenty-one".
- **Does not fix on its own:** "few", "bad" and "for". These still fall back to 1 unless
  B is also adopted.
- **Cost:** a pure helper (about 25 lines) plus a regex built from the vocabulary. Do not
  reuse `itn/normalize.py:12-17` (`_NUM`). Its `"oh": 0` belongs to version strings, and
  an import would couple two features that are both off by default.

### B. Refuse an unknown count, with a notice

Delete the `default=1` fallback. If the token is not in the vocabulary, return a
**recognised-but-refused** result, for example `("edit_refused", {"reason":
"unknown_count", "heard": "few"})`. The daemon then shows one notice through its existing
notification path (`notify(...)`, as used at `daemon.py:8000-8006`):

> Nothing deleted: "few" is not a number. Say, for example, "delete the last 3 words".

The daemon returns `True`, so nothing is typed and the event is filed as
`spoken_edit_refused`.

- **Fixes:** every silent wrong count. A wrong action becomes no action plus one sentence.
- **Order relative to the destructive gate:** check the destructive gate first. With
  `spoken_edit_destructive` off, keep today's quiet `spoken_edit_skipped`. A notice about
  an operation the user never enabled would be noise.
- **Rejected sub-option:** mapping homophones ("for"→4, "to"/"too"→2, "won"→1). That is a
  heuristic guess, which is exactly what ADR-021 rules out (`adr-021…md:85-87`: "hold only
  on a *specific, checkable* signal, never on a heuristic"). Refusing and letting the user
  repeat costs one utterance. Deleting the wrong number of words costs a correction.

### C. Cap the count

Accept counts only up to a ceiling, and refuse anything above it, by the same route as B.

- **Spoken Edit path:** this matters little here, because the ledger already bounds the
  harm (2.2). Its value is consistency, so that "delete the last 5000 words" gets the same
  refusal everywhere.
- **Recommended ceiling:** 99, the same as `zh.py:39` (`MAX_COUNT`). One number across
  languages is easier to document and test.
- **Grammar digit path (2.3):** a cap there would change real behaviour, because nothing
  else bounds it. That is a separate decision.

### D. Do nothing, but document it

Keep the fallback to 1 and document "counts up to ten". This is the cheapest option, but
the failure stays silent: the user sees one word disappear and has no reason to believe
the command was misunderstood.

## 4. Which phrases newly become commands

The key point: **the frame regex already accepts any single token as the count**
(`edit_ops.py:103-105`). Options A and C on single tokens therefore create **no new
command phrases**. They change only *how many* words a phrase that already matches will
delete.

| Option | Phrases that are newly recognised | Phrases whose effect changes |
|---|---|---|
| A, single-token words | none | `eleven`…`ninety`: from 1 word to the stated count (clamped to the last dictation) |
| A, compounds (`twenty one`, `twenty-one`) | **yes**: today these return `None` and are discarded in command mode | they newly delete 21…99 words, clamped |
| B | none newly *applied* | `few`, `several`, `bad`, `for` …: from "delete 1 word" to "delete nothing, show one notice" |
| C (99) | none | digits ≥ 100 and their word forms: from "clear the last dictation" to a refusal notice |

To keep A narrow, build the compound alternative **from the vocabulary itself**, as in
`(twenty|thirty|…|ninety)[\s-](one|…|nine)`. Do not widen the slot to `\w+\s+\w+`. A
widened slot would also capture "delete the last bad french words" and send it down the
refusal path, which adds notice traffic for no gain.

## 5. False-trigger risk (ADR-021: judged on how rarely it fires)

Two separate risks follow.

**5.1 An unwanted destructive edit.** Today's exposure is limited by three things already
in the code [Code]:

1. the command key is held (`daemon.py:4691`);
2. no grammar rule matched (`daemon.py:4717`);
3. the user opted into both flags (`config.py:520,524`).

The harm is also bounded to the last dictation and undoable by "scratch that". A adds
destructive reach only for compound counts, and only up to 99. A *larger* deletion than
today, when the user really asked for twenty words, is the requested behaviour, not a
false trigger. [Assumption] The residual risk is that the decoder turns "two" into
"twenty". That is an ASR error which no parser can detect, and "scratch that" recovers it.

**5.2 The refusal notice from B and C.** ADR-021 asks how often the notice interrupts.
It fires only when all of these hold:

- the command key is held;
- the utterance matches the exact frame `delete [the] last <token> word(s)`;
- `<token>` is outside a closed, enumerable set (or above 99);
- `spoken_edit_destructive` is on.

The signal is **specific and checkable**: membership in a finite set, with no scoring or
threshold. The release is free, because there is nothing to confirm: the user simply says
the command again with a number. It never fires during prose dictation.
[Assumption] It fires less often than any guard already shipped. That should be measured
by the synthetic replay in 6.3 before it is claimed.

The notice is not a confirmation prompt. It holds nothing and asks nothing, so the "users
learn to confirm reflexively" failure in ADR-021 (`adr-021…md:89-92`) does not apply.

## 6. Test plan (for whoever implements; none of this exists yet)

All tests are deterministic and offline, with no audio, model or microphone. Planned file:
`tests/test_spoken_edit_count_words.py`.

### 6.1 Pure parser (`edit_ops.py`)

- **Fails on `8a72bbc6`:** `parse_edit("delete the last twenty words") == ("delete_words", {"n": 20})`.
  Today it returns `n=1`.
- **Exhaustive 0-99 round trip.** For every n in 0..99, render the English words with an
  **independent oracle written in the test**: a small table-driven speller, not the
  production table. Then assert `parse_edit(f"delete the last {words} words")` gives `n`,
  in both the spaced and hyphenated compound forms. This follows the pattern of
  `tests/test_mandarin_command_numerals.py`, which proves regex and parser agree.
- **Refusal (option B).** `few`, `several`, `couple`, `bad`, `for`, `hundred`,
  `twenty-ten` and `one hundred` each give `("edit_refused", {"reason": "unknown_count",
  "heard": …})`. None of them gives `delete_words`.
- **Cap (option C).** `100`, `500` and `005` (zero-padded, as in `zh.py:131-134`) are
  refused. `99` is accepted.
- **Unchanged.** `delete the last word` gives `n=1`. `delete the last passwords` gives
  `None`. `delete the last bad french words` gives `None` (the slot was not widened).
  `tests/test_edit_ops.py:67-70` still passes.
- **`apply_edit`.** A refused phrase returns `EditResult(text, False)` and is never
  dispatched as a delete. `twenty` on a 5-word burst clears it, which pins the ledger clamp.
- **Optional property test.** Use Hypothesis over `delete the last <random token> words`:
  the result is either `n` in 0..99 from the oracle, or a refusal. It is never `n=1` for a
  token outside the vocabulary.

### 6.2 Daemon wiring (`_try_spoken_edit`, mocked ledger, injector and notify)

- `spoken_edit_destructive=True` with "delete the last few words": no injection, no
  `_replace_last_burst` call, `notify` called **once**, the event's `intent_type` is
  `spoken_edit_refused`, and the function returns `True`.
- `spoken_edit_destructive=False` with the same phrase: today's `spoken_edit_skipped`, and
  `notify` is **not** called.
- With "delete the last twenty words" and a 30-word ledger entry, the retyped text is the
  first 10 words.

### 6.3 Firing-rate check (ADR-021)

Use a synthetic list of command-mode utterances: the existing grammar fixtures, plus
generated `delete the last <n> words` phrases, plus non-count fillers. Count how often the
refusal fires, and assert it fires only on the frame. The list must be synthetic or
explicitly de-identified (AGENTS.md: no real transcripts).

**Decoder-output measurement ([Unknown] in 2.3).** Synthesise TTS clips of "delete the last
twenty words" and similar phrases, then record whether the pinned decoder emits digits or
words. This decides whether the word path or the uncapped digit path carries real traffic.

### 6.4 Gates once implemented

```sh
uv run python -m pytest tests/test_spoken_edit_count_words.py tests/test_edit_ops.py \
  tests/test_spoken_edit_does_not_match_a_word_ending_in_words.py -v
uv run python -m pytest tests/ -n auto
uv run ruff check src tests scripts
uv run mypy src
```

There is no config key, CLI flag or generated-doc change, so `scripts/gen-docs.py` is not
needed. A CHANGELOG entry is.

## 7. Recommendation (proposal)

Adopt **A + B + C together**, on the Spoken Edit word path only:

- a closed 0-99 vocabulary, with hyphenated or spaced compounds built from that vocabulary;
- no fallback; an unknown or over-cap count gives one notice and deletes nothing;
- the same ceiling as Mandarin (99).

This removes a silent wrong action. On single-token phrases it adds no new command
phrases. Its only new interruption fires on a closed-set membership test, in command mode,
behind two opt-ins.

Not recommended:

- homophone mapping, because it is a heuristic (ADR-021);
- widening the count slot to free text;
- reusing `itn/_NUM`.

## 8. Owner decisions

1. Accept A + B + C for `edit_ops.py`, or pick a subset. D, documenting "up to ten", is the
   minimum honest option.
2. Wording of the refusal notice, and whether it also appears on the overlay or only as a
   desktop notification.
3. **Separate issue:** cap the English grammar digit path (`en.py:58,60,63` and
   `dispatch.py:226-244`) at 99, as Mandarin does. Today "delete the last 500 words" sends
   500 Ctrl+BackSpace presses with no opt-in beyond the command key.
4. Whether ADR-v2-003 needs a note. Its point 3 (`adr-v2-003…md:24-25`) promises a
   confirm step for multi-word deletes. The code instead uses an opt-in flag plus
   "scratch that" (`daemon.py:8014-8018`). That gap predates this packet and is out of
   scope, but whoever revisits the ADR should know about it.
