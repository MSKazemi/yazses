# ADR-v2-134 — Meeting transcript quality gate (two transcripts, one verdict)

**Status:** Accepted (2026-08-26) · Wave P
**Context links:** [[adr-v2-127-live-meeting-mode]] (adds the gate to its finalize path; the
live transcript it already streamed becomes a first-class artefact),
[[adr-v2-128-meeting-minutes-generation]] (the gate suppresses the notes pass),
[[adr-v2-125-diarized-recording-import]] (shares the batch pipeline this judges),
[[adr-011]] (on-device; the recording-retention default is a privacy decision this narrows
deliberately), [[adr-021]] and [[adr-v2-065]] (guards judged on how rarely they fire)

## Context

ADR-v2-127 chose a **hybrid** design: a rolling live decode during capture, and one accurate
batch decode of the whole recording at stop. It also chose to **delete the recording once the
post-pass has consumed it** (`[meeting] retain_audio = false`), which is the right privacy
default and was made safe by deleting *after* success rather than before.

That safety rests on an assumption nobody had written down: **that a post-pass which returns
without raising has produced a record of the meeting.** It has not, and the failure is not
exotic. Autoregressive decoders are known to fall into repetition loops on long audio, emitting
one phrase for the remainder of the file. The output is syntactically perfect and structurally
complete — timestamps, word alignment, the lot — so it raises nothing.

Observed on a maintainer machine, 2026-08-26, meeting `20260826-100205`:

- 41 min 39 s of a real four-person call.
- `transcript.md`: 284 words, 93 consecutive repetitions of "Hello, hello, hello."
- `meeting.json`: `status: "done"`, `capture: "ok"`, `attribution_suspect: ""`.
- The recording was therefore deleted as a successful consumption.
- `live.jsonl` held **4553 words** of the actual meeting — and nothing in the product
  rendered it, listed it, or mentioned it for a finished meeting.

Every guard that exists passed, and each was right to. `capture_state` asks whether audio was
**heard**; it was. `attribution_suspect` asks whether speaker labels can be trusted; there was
one cluster and nothing was mis-attributed. Neither asks whether the *words* are real. Nothing
did, because until this failure "the post-pass returned" and "the meeting was transcribed" were
treated as the same statement.

The consequence is the severe part. A bad transcript is recoverable while the audio exists and
permanently unrecoverable once it does not, and the deletion was gated on precisely the signal
that had failed.

## Decision

**1. A finished transcript is judged, and the verdict is recorded.** New pure module
`meeting/quality.py` (stdlib only, no models, no I/O) returns `ok` / `degenerate` / `thin` /
`unjudged` from four signals:

| signal | fires on |
|---|---|
| top n-gram share ≥ 0.20 | one phrase dominating the transcript |
| distinct n-gram ratio ≤ 0.35 | a transcript with almost no distinct content |
| longest back-to-back repeat ≥ 12 | a collapse that begins *late* in an otherwise healthy meeting |
| < 25 wpm over ≥ 300 s | a long recording that decoded to almost nothing |

Thresholds were fixed **against the five real stored meetings on the machine where the failure
happened**, before any was chosen, and sit clear of both edges rather than against the one bad
sample:

| meeting | duration | wpm | top trigram | distinct | verdict |
|---|---|---|---|---|---|
| 20260710-212029 | 56.7 s | 106.9 | 0.0101 | 1.0000 | ok |
| 20260803-095635 | 8081.4 s | 117.9 | 0.0049 | 0.8210 | ok |
| 20260814-065156 | 26.6 s | 2.3 | — | — | unjudged |
| 20260819-033515 | 11.6 s | 0.0 | — | — | unjudged |
| **20260826-100205** | **2499.7 s** | **6.8** | **0.9681** | **0.0355** | **degenerate** |

Recall 1/1, false alarms 0/4, measured through the shipped CLI on real data — not only in
tests. Two orders of magnitude separate the collapsed decode from the worst healthy one.

**2. The strongest signal needs no threshold at all.** ADR-v2-127 already decodes the same
audio twice. On the collapsed meeting the live pass holds 4553 words against the batch pass's
284 — **16×**; on the healthy 2 h meeting the two agree to **1.008×**. A second independent
opinion on the same input beats any statistic computed from one, so the ratio (≥ 3× with ≥ 20
batch words) is a first-class signal and is reported in its own words.

**3. The live transcript is promoted from recovery format to second artefact.** `live.jsonl`
is rendered to `live-transcript.md`, timestamped, **before** the batch pass runs — a finalize
that dies never reaches a line placed after it. It is written for every meeting and deleted by
nothing.

**4. Deletion is gated on the verdict, not on the absence of an exception.** The recording is
kept whenever the transcript is suspect, regardless of `retain_audio`. This narrows the ADR-011
privacy default in exactly one direction and only in the case where the alternative is
destroying the only copy of a meeting.

**5. Minutes are suppressed on `degenerate`/`thin`**, joining the `no speech` rule ADR-v2-128
already had, and for its stated reason: a summary of invented words is the one artefact nobody
can audit afterwards. Deliberately **not** extended to live-disagreement alone — there the
batch transcript is short but real, so its minutes are incomplete, not fabricated.
`meeting notes --force` overrides.

**6. `status: "done"` stops being the whole story.** `meeting recover` accepts a meeting that
finished *badly*, not only one that never finished, and **archives** prior outputs to
`attempts/<n>/` rather than overwriting them — a retry runs precisely when the last result was
distrusted, and the retry can be worse. Nothing is ever deleted.

**7. The verdict reaches a human without a terminal.** A meeting has no key held and no window
watched; its post-pass ends long after the user has walked away. One readout — built once,
from the metadata just written — is printed by `yazses meeting summary`, written into the folder
as `summary.md`, and shown as a desktop notification. A post-pass that *fails* notifies too.

**8. The repair applies backwards.** `store.ensure_quality` computes a verdict from a stored
transcript on demand and writes it back, so meetings recorded before the gate existed — the
broken one among them — are judged rather than reported blank.

## Consequences

- **Every meeting now costs one extra rendered file and one JSON record.** `quality.json` is
  written for healthy meetings too, on purpose: a verdict is only interpretable next to the
  numbers of the meetings it did not fire on.
- **The privacy default is weaker in one measurable case.** A meeting whose transcript fails the
  gate keeps `audio.wav` until the user acts. This is stated in the CLI, in `summary.md`, and in
  the notification, so it is never silent. It is a deliberate trade: ADR-011 protects the user
  from us, and an unrecoverable meeting harms the user directly.
- **Thresholds are corpus-bound and will need re-measuring.** Five meetings from one machine,
  one language, one model (`base.en`). A different model or a very short/very sparse meeting
  culture could move the healthy edge. The metrics are persisted for exactly this reason: the
  corpus needed to re-fit them accumulates automatically.
- **`recoverable` no longer means "unfinished".** Any surface reading it as a synonym is now
  wrong — one did, and listed a finished meeting as `unfinished`.
- **The gate cannot detect a decode that is wrong but fluent.** A transcript that hallucinates
  plausible sentences at a normal rate passes every signal here. This gate catches *collapse*
  and *silence*, not *inaccuracy*, and must not be described as a correctness check.

## Alternatives considered

- **Keep the recording always** (flip `retain_audio` to true). Simplest, and rejected: it makes
  every meeting a permanent audio file on disk by default, which is a much larger privacy change
  than the failure justifies, and it fixes recoverability without ever telling the user their
  transcript is wrong.
- **Detect the loop inside the decoder** (`condition_on_previous_text=False`, compression-ratio
  thresholds, `no_repeat_ngram_size`). Worth doing as *prevention* and orthogonal to this ADR —
  but it is engine-specific, does not survive an engine swap (`[stt] engine = parakeet`), and
  cannot notice a collapse it fails to prevent. A verdict computed from the finished text works
  for every engine, including ones not yet written.
- **Merge the two transcripts** into one best-effort text. Rejected: it manufactures a third
  artefact that is neither decode, hides the disagreement that is itself the finding, and makes
  "which of these is the record?" unanswerable. They stay separate and the user is told which
  to read.
- **Fail the finalize outright** on a bad verdict. Rejected: the collapsed transcript is
  evidence, the diarization and timings around it may still be useful, and an exception here
  would land in the one place (a `daemon=True` finalize thread) where it is least visible.
