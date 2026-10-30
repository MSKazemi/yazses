---
title: XR voice input (adapter library, not yet connected)
description: What the YazSes XR voice-input adapter is for, what exists today (a tested library fed synthetic data only), the privacy model, and the companion wire format for integrators. Not yet connected to the daemon; no config key and no command exist yet.
---

# XR voice input

> **Status: a library, not a feature you can turn on.** The `yazses.xr` adapter exists
> and has unit tests, but those tests use **synthetic** data only: generated rays,
> generated gestures and invented panels. It is **not yet connected to the daemon**: the
> top-level object, `XrSession`, is a pure class that a future host would drive, and nothing
> drives it today.
> There is **no `[xr]` config section and no command-line entry point**, so there is nothing
> to enable, and no headset or glasses integration ships. No accuracy figure has been
> measured on a real device, and none is claimed here. This page describes the
> library's behaviour so a companion-app author can build against it.

## What it is for

In a headset or on glasses there is no keyboard. You dictate into a flat panel floating
in space (a note, a chat, a terminal mirrored from your desktop), and two questions
decide where the words go:

1. **Which panel?** You point at it with a gaze, head or hand ray.
2. **When am I talking?** You hold a gesture (a pinch or a squeeze) the way you would
   hold the dictation key.

A third idea is *deixis*: saying "type here" or "put it there" and having the word
"here" resolved against whatever you were pointing at around the moment you said it.

The design split is deliberate. A small companion app on the headset or phone is meant to
sample rays and gestures and send plain numbers to the desktop. **No such app exists, and
no transport for those numbers exists yet** (see [what is not built
yet](#what-is-not-built-yet)). YazSes does the
arithmetic (which panel was hit, was the gesture held, which panel does "here" mean)
and the speech-to-text stays the same offline Whisper pipeline as everywhere else.
The XR code has no OpenXR, Unity or network dependency of its own.

## What exists and what does not

| Piece | Module | State |
|---|---|---|
| One session composing all of the pieces below | `yazses.xr.session` | Library, synthetic tests; not driven by anything |
| Companion wire format (decode, encode, clock mapping) | `yazses.xr.wire` | Library, synthetic tests |
| Ray against panel intersection (`u`, `v`, distance) | `yazses.xr.raycast` | Library, synthetic tests |
| Ray smoothing (One-Euro filter) and dwell read-out | `yazses.xr.smoothing` | Library, synthetic tests |
| Bind "this / here / there" to a panel | `yazses.xr.binding` | Library, synthetic tests |
| Gesture hold-to-talk state machine | `yazses.xr.ptt` | Library, synthetic tests |
| When to ask for confirmation | `yazses.xr.confirm` | Library, synthetic tests |
| Panel registry and pinned target | `yazses.xr.anchors` | Library, synthetic tests |
| Retention window, log redaction, persistence policy | `yazses.xr.privacy` | Library, synthetic tests |
| Device capability profiles | `yazses.xr.devices` | Static table |
| Coordinate-convention conversion | `yazses.xr.conventions` | Library; two conventions are assumptions |
| Mapping a ray hit onto a grounding target | `yazses.xr.grounded` | Library, synthetic tests |
| Synthetic data generator | `yazses.xr.synth` | Test support |

See [what is not built yet](#what-is-not-built-yet) at the end.

## Privacy model

Eye, head and hand rays reveal what you looked at and for how long, so the package
treats them as sensitive. These are the behaviours of `yazses.xr.privacy`, and they are
what the tests check.

- **Zero egress.** The package declares no outbound path (`EGRESS` is an empty set).
  It is designed to receive numbers from a companion over the paired bridge; no transport
  for them exists yet. It sends nothing anywhere. This is consistent with the project-wide rule in the
  [privacy statement](privacy-statement.md).
- **A bounded retention window.** `SampleRetention` keeps recent samples only.
  Its own defaults are 2.0 seconds and at most 240 samples. A sample older than the window
  is dropped on every add, prune or snapshot (a sample exactly as old as the window is
  kept; older is not). When the cap is exceeded the oldest goes first. A sample that arrives
  already outside the window relative to the newest one held is never stored. `clear()`
  drops everything at once.
  - **`XrSession` holds rays longer: 8.0 seconds and at most 720 samples.** A spoken
    sentence is recognised after it ends, so the rays at a word's onset must still be held
    when the transcript arrives, and a long sentence outlasts 2 seconds. This is longer than
    the "few seconds" the project's interaction-kernel research note asks about, and it is
    **an open privacy decision for the owner**: how long pointing rays may be held in memory
    (they never leave it) is a trade against long-sentence binding, and it has been neither
    decided nor measured. Treat 8.0 s / 720 as provisional, not as policy.
  - **A forged future timestamp is refused.** A sample stamped more than `max_future_s`
    (default 5 s) ahead of the reference clock is refused with `ValueError`, so one
    poisoned timestamp cannot make every later honest sample look stale. Inside a session
    the reference is the desktop clock, and such a frame becomes a rejected frame.
  - **No pickling or copying.** The buffer refuses `pickle`, `copy.copy` and
    `copy.deepcopy` with `TypeError`, so retained rays cannot be serialised or duplicated
    by accident.
- **No coordinates in logs.** `redact_for_log` is the only log-safe rendering of a
  sample, and it gives the source and a coarse confidence bucket (`high` at 0.8 and
  above, `medium` at 0.5 and above, otherwise `low`). It never includes a position,
  a direction or a timestamp, because a timestamp plus a source is enough to line a log
  up against a gaze trace stored elsewhere. The retention buffer's `repr` shows only
  the count and limits, so a stray debug print of the buffer leaks no gaze.
- **No persistence without research consent.** `may_persist` answers `False` for
  every policy except `RESEARCH_CONSENT_ONLY`, and there it returns `True` only when
  consent is the literal `True`. A truthy string or the number `1` is not consent, and
  an unrecognised policy value never allows it. The package itself contains no code that
  writes samples to disk.
- **Hostile input is assumed.** The companion is a separate device on a network link, so
  every frame is validated (see [Rules that apply to every
  frame](#rules-that-apply-to-every-frame)) and the panel registry is bounded.

One caution for integrators: a rejected frame's error message can quote a short,
truncated piece of the offending value. Log that a frame was rejected and how often, not
the frame itself.

## Coordinate convention

All values the library works with use one frame:

- Right-handed, **+X right, +Y up, -Z forward**. This is the OpenXR "local" convention.
- **Metres** for positions and sizes, **seconds** for time, **radians** for angles.
- Directions are unit vectors.

If your engine reports something else, convert at the seam before sending. The
library offers `yazses.xr.conventions` for this: OpenXR (identity), Unity
(left-handed, +Z forward, metres), and Unreal (left-handed, +X forward, +Z up,
centimetres) are derived from the engines' published conventions. **Android XR and
visionOS are currently treated as OpenXR-aligned on an assumption that has not been
confirmed against their SDKs**; check before relying on either. Orientation
quaternions are not converted because nothing in the package consumes them.

A panel is a flat rectangle: a `center`, a unit `normal` (the side the viewer stands
on), a unit `up` perpendicular to it, and a `width` and `height` in metres. Where a ray
hits, the position is given as `u` (0 at the left edge, 1 at the right, as seen from the
front) and `v` (0 at the bottom, 1 at the top).

## The companion wire format

Frames travel companion to desktop. One frame is one UTF-8 JSON object of at most
**4096 bytes** by default (`max_bytes` can be set per decoder). Every frame carries a
version `v` (currently `1`) and a type `t`. The type key is `t`, not `kind`, because a
gesture frame already has a `kind` field.

### Rules that apply to every frame

- **All fields are required and unknown keys are refused.** The set of fields must match
  the table for that type exactly.
- **Anything wrong with a frame raises one error type, `WireError`, and the frame is
  dropped**, for any frame content. The caller counts it and moves on. No frame is
  partially accepted. (A caller's own mistake is different: a non-positive or non-integer
  `max_bytes` argument raises `ValueError`.)
- **Numbers must be finite JSON numbers.** `NaN`, `Infinity`, `-Infinity`, booleans in
  place of numbers, and integers longer than 20 digits are rejected.
- **Duplicate keys, invalid UTF-8, a frame that is not a JSON object, over-deep nesting,
  and a frame over the size limit** are rejected.
- **Unit vectors** (`direction`, `normal`, `up`) must have length 1 within 1e-3.
  A vector within 1e-9 of unit length is used exactly as sent; one in between is
  renormalised. Each component must be within [-2, 2].
- **A panel's `normal` and `up` must be perpendicular** within 1e-3. A small deviation
  is corrected; a larger one is rejected.
- **Identifiers** (`panel_id`) are non-empty printable strings of at most 128 characters.
  The wire layer is the looser gate: the panel registry then accepts only ids made of
  letters, digits and `. _ : -` (after Unicode NFC normalisation and trimming). An id with
  a space or any other character passes the wire layer but is refused by the registry, and
  `XrSession` reports such a frame as rejected.
- **Positions** (`origin`, `center`) are within +/-1,000,000 m. **Sizes** are between
  1e-6 and 1,000,000 m.
- **`device_time_s`** is within [0, 1e9]. **`confidence`** is within [0, 1].

### Frame types

| `t` | Fields | Notes |
|---|---|---|
| `sample` | `device_time_s`, `source`, `origin`, `direction`, `confidence` | `source` is `eye`, `head`, `hand` or `controller` |
| `gesture` | `device_time_s`, `kind`, `confidence` | `kind` is `pinch_start`, `pinch_end`, `squeeze_start`, `squeeze_end` or `tap` |
| `panel` | `panel_id`, `center`, `normal`, `up`, `width`, `height`, `label` | Sent when a panel appears or moves. `label` is printable text of at most 256 characters (may be empty) |
| `panel_gone` | `panel_id` | The panel was closed |

### Worked examples

A pointing sample: an eye ray from head height, looking straight ahead, tracker
confidence 0.9.

```json
{"v":1,"t":"sample","device_time_s":12.5,"source":"eye","origin":[0,1.6,0],"direction":[0,0,-1],"confidence":0.9}
```

A gesture: the user starts a pinch.

```json
{"v":1,"t":"gesture","device_time_s":12.6,"kind":"pinch_start","confidence":1}
```

A panel: a 1.2 m by 0.8 m surface two metres in front of the origin, facing the viewer,
labelled "notes".

```json
{"v":1,"t":"panel","panel_id":"p1","center":[0,1.5,-2],"normal":[0,0,1],"up":[0,1,0],"width":1.2,"height":0.8,"label":"notes"}
```

A panel closing:

```json
{"v":1,"t":"panel_gone","panel_id":"p1"}
```

### Clock handling

The companion's clock is not the desktop's. Samples and gestures carry
`device_time_s` on the **device** clock, and the library maps it onto the desktop's
monotonic clock with `ClockMap` (`rebase` applies it to a frame; panel frames carry no time
and pass through unchanged).

- The first frame fixes an offset (`desktop_now - device_time`).
- After that the offset can move two ways, and **both are rate-bounded**, because the
  offset is what a hostile or broken companion would manipulate.
  - **Up** (more apparent latency, or a slow device clock): by at most `max_drift`
    (default 0.001, so 1 ms per second) per desktop second.
  - **Down** (less apparent latency, or a fast device clock): paid from a credit that
    starts at `jitter_s` (default 0.02 s) when the offset is anchored and refills at
    `max_drift` per desktop second, capped at `jitter_s`. A frame that needs more than the
    available credit is refused. Over any `T` seconds the offset therefore falls by at
    most `jitter_s + max_drift * T` (with the defaults, 0.03 s in 10 s and 0.08 s in
    60 s), however many frames carry it. A device clock running far too fast cannot move
    the mapping; its frames are refused one by one.
  - Either way a sample is never mapped into the future.
- A frame whose apparent offset differs from the current one by more than `max_jump_s`
  (default 0.5 s) is **rejected** and the mapping is left unchanged. That is how a device
  reboot, a clock step or a replayed stream shows up: as a refused frame, not a silent
  shift. Call `reset()` to re-anchor on purpose, for example after a reconnect.
- A stated cost: an honest first frame that arrived more than `jitter_s` later than the
  link's steady latency makes the following on-time frames look like a fast clock, so they
  are refused until credit refills or `reset()` re-anchors on a settled link.

## Hold-to-talk by gesture

A tracked hand is a worse switch than a key: fingers occlude each other and the hand can
leave the camera's view while still "pressed". `GesturePtt` turns the gesture stream into
the same start and stop edges the keyboard path produces, and fails in the safe
direction: the microphone is not left open.

Three modes, one per session:

| Mode | Starts on | Stops on |
|---|---|---|
| `hold_pinch` | `pinch_start` | `pinch_end` |
| `hold_squeeze` | `squeeze_start` | `squeeze_end` |
| `toggle_tap` | first `tap` | next `tap` |

Behaviour, with the defaults:

- **Flicker grace (0.12 s).** A pinch end is not a stop until 0.12 s pass without the
  pinch returning. A start inside that window continues the same utterance, so a
  one-frame tracking drop does not chop a sentence in two.
- **Debounce (0.05 s).** A press shorter than 0.05 s is chatter and is cancelled (the
  utterance never counted). A new press within 0.05 s of a stop is ignored.
- **Minimum confidence (0.5).** A start event below it is ignored, as are gestures of the
  other family and start events older than the last accepted one. A *stop* event is never
  dropped for low confidence or an out-of-order stamp: a weak release must still close the
  microphone, and it closes it at once, without the flicker grace.
- **Forged timestamps are bounded (`max_future_s`, default 5 s).** Once a `tick` or an
  event has given the machine a time reference, a start event stamped further ahead than
  that is clamped to the reference plus 5 s, and a stop event with such a stamp closes the
  microphone immediately. Before the first tick or event there is no reference, so call
  `tick(now_s)` once at start-up to arm the bound.
- **Stuck-gesture safety (120 s).** A start with no end for 120 s is force-stopped.
  A hand that leaves tracking sends nothing at all, so this timer is the only thing that
  closes the microphone in that case. The host must call `tick(now_s)` on a timer; the
  library reads no clock of its own.
- `reset()` (for a reconnect or a mode change) cancels a live utterance and restarts the
  timeline.

## "This", "here", "there"

`bind_demonstrative` weighs the pointing history around the moment a word started, not
the moment speech ended, and either names one panel or declines.

- It considers samples from 0.4 s before the word's onset to 0.2 s after (pointing tends
  to lead the word). Samples under 0.3 confidence are dropped.
- Evidence is measured in **time, not in samples**. Each usable sample is credited with
  the interval it holds (halfway to each neighbour, but never more than 0.05 s per side,
  so a dropout does not credit a stale panel for the whole silence), multiplied by its
  confidence and by a triangular weight that peaks at the onset and is zero at either
  window edge. A panel looked at for 0.1 s therefore counts the same whether the headset
  streams at 30 Hz or 90 Hz.
- Samples that hit no panel still count against the total, so glancing briefly at a panel
  while mostly looking at empty space does not claim the word.
- **A single stray sample never binds.** A binding needs at least 3 usable samples
  covering at least 0.05 s, otherwise the result is **none** ("insufficient evidence").
- The result is **bound** when one panel holds at least 60 percent of the weighted
  evidence and strictly leads the runner-up (a tie is never a binding). It is
  **ambiguous** when another panel is plausible too, and **none** when there is no usable
  evidence, too little of it, or mostly empty space.
- Alongside the verdict the binder reports **facts the confirm policy can check**, and
  never lets them change the verdict: the two best panels, how many degrees the winning
  rays were from the *nearest other panel*, and which other panel the gaze rested on in
  the 1.5 s before the word and how long ago it left it.
- These numbers (the window, `max_gap_s` 0.1 s, `min_samples` 3, `min_coverage_s` 0.05 s,
  `min_share` 0.6) are **unvalidated starting points**. They have not been measured on
  real headset data, and no accuracy figure for the binder is claimed.
- **What the binder cannot do.** If the eyes rested on the panel you meant, moved on, and
  had settled elsewhere for more than about a third of a second before you spoke, the gaze
  record says you meant where you are looking now. No setting recovers the other panel
  from gaze alone; the policy below turns the *recent* cases into a question instead.

The command grammar is small and exact: "type / dictate / write here / there" and
"put / send it / this / that here / there". Any longer sentence that merely contains
"this" or "that" stays ordinary dictation.

## When YazSes asks you to confirm

Confirmation is rare on purpose. A prompt that fires on a clean case teaches people to
dismiss it, after which it catches nothing, so the policy holds only on specific,
checkable signals, each a number compared with a published threshold:

1. The binder could not name one panel: another panel was plausible too (ambiguous binding).
2. **Near a seam.** The rays that chose the panel landed within the *error budget* (3
   degrees by default) of a neighbouring panel, so a tracker that far off could have meant
   the neighbour. This can only happen where panels are closer than the budget; with
   panels farther apart it never fires. `error_budget_deg = 0` turns it off.
3. **Just arrived.** Your gaze reached the chosen panel less than `settle_s` (0.3 s by
   default) before the word, coming from another panel it had rested on: "the panel I was
   leaving" and "the panel I reached" are both plausible. `settle_s = 0` turns it off.
4. **A changed target.** Your gaze has *stayed* on a different panel for at least
   `min_departure_s` (0.5 s by default) at the end of the utterance. A passing glance does
   not count; earlier versions compared two instants and held on any glance.
5. The action is destructive and its target came from a ray.
6. The confidence supplied with the binding is below 0.35, its lead over the runner-up is
   below 0.25, or the chosen panel holds less than 60 percent of the pointing evidence.

When the prompt names a specific alternative (rules 1 to 4) it offers both panels, so the
answer is one word. The ordinary path, a confident and non-destructive target on a panel
the gaze is settled on, is silent. If no ray target exists at all, there is no prompt
either: the text goes to the keyboard-focused window, as with
[Glance-Type](how-to/gaze-look-to-pane.md). Missing data is never treated as a signal. When
a prompt does appear, it is released by one word, "yes" by default.

**Measured only on synthetic gaze.** The thresholds above were swept on invented
trajectories, not on people. They show how the rules trade silent wrong binds against prompts under
stated assumptions, and where the policy stays blind. They are not an accuracy or a
prompt-rate figure for real use. The unit tests assert a prompt rate under 5 percent, but
on an invented mix of cases.

## Device capabilities

`yazses.xr.devices` lists what each class of device can provide, and it is cautious by
design. A capability is "yes" or "no" only where the project's own research or the
glasses-desktop bridge design says so, or where it is safe by construction. **Everything
else stays "unknown", never "no"**, and unknown never upgrades the suggested modality
preset. Query the real runtime for the truth; do not assume from this table.

| device           | eye      | hand     | mic     | preset     |
|------------------|----------|----------|---------|------------|
| phone-companion  | unknown  | unknown  | yes     | voice-only |
| generic-openxr   | unknown  | unknown  | unknown | voice-only |
| meta-quest       | unknown  | unknown  | unknown | voice-only |
| ray-ban-meta     | unknown  | unknown  | unknown | voice-only |
| android-xr       | unknown  | yes      | unknown | balanced   |
| vision-pro       | unknown  | yes      | unknown | balanced   |

That table is the output of `yazses.xr.devices.render_table()` on 2026-10-30. **Eye tracking
is unknown for every profile**, including the phone companion, because nothing in the
repository's research says an app can read a raw gaze ray from any of them. The two "yes"
hand-tracking entries (Android XR, Vision Pro) rest on OS-level statements quoted from the
repository's own research note about each operating system's interaction model; they are not
statements about what an app can read. These entries come from that note,
are **unconfirmed against vendor documentation**, and **unknown means unknown**, not "no".

`suggest_preset` uses only capabilities known to be yes: known eye tracking gives
`hands-free`, known hand tracking alone gives `balanced`, anything else gives
`voice-only`. With the current table no profile has known eye tracking, so none suggests
`hands-free`; Android XR and Vision Pro suggest `balanced`, and the rest `voice-only`. A device appearing in this table says nothing about whether a companion
app exists for it. None does today.

## Panels and the dictation target

The companion reports panels; the registry keeps at most 64 of them and evicts the
least recently seen when a flood of new ids arrives. A panel not refreshed for 30 s is
treated as gone (a panel last seen exactly 30 s ago is already stale, so doubt resolves to
"do not type there"), so a companion should re-send each `panel` frame periodically.

- **Panel ids are restricted.** After Unicode NFC normalisation and trimming, an id must
  match `[A-Za-z0-9._:-]{1,128}`. Homoglyph, blank and padded ids are not silently kept as
  separate entries.
- **A pin.** You can pin one panel explicitly as the dictation target. A pin overrides
  gaze, lasts 60 s by default, and never returns a panel that has since disappeared. It is
  also dropped if the panel under that id is re-posed beyond a tolerance measured against
  its pose at pin time: centre moved more than 0.5 m, normal turned more than 0.5 rad, or
  width or height changed by more than 20 percent. This stops an untrusted companion from
  re-pointing a pinned id at a different surface.
- **Spoken labels are quoted data.** `describe` and `describe_all` read a panel's label
  aloud as a quoted, sanitised string, because the label comes from the companion: it is
  normalised, control, zero-width and bidirectional-control characters are removed,
  `<`, `>`, `&` become spaces, double-quote-like characters become a single quote,
  strong right-to-left characters become `?`, long runs of combining marks collapse to
  `?`, and the result is cut to 40 characters. Panels that share a label get an ordinal
  ("first of 2").

## One session, `XrSession`

`yazses.xr.session.XrSession` composes the pieces above. It has no thread, no clock and no
socket: the host feeds it companion frames and the time, and reads the answers back. It is
still unwired.

- `feed_frame(data, desktop_now_s)` applies one companion frame (decode, clock mapping,
  smoothing, retention, panel registry, push-to-talk) and returns a list of events. It
  never raises for anything the companion sends. A refused frame becomes a
  `FRAME_REJECTED` event whose `detail` is a fixed category such as "unknown frame type",
  never an excerpt of the payload.
- After 20 consecutive rejections the per-frame events stop and a single
  `COMPANION_MISBEHAVING` event is emitted, repeated at most once per 10 s. A stepped
  device clock stays refused, so that event is the host's cue to re-pair the companion and
  call `reset()`.
- **The host must call `tick(now_s)` on a timer** (about 10 Hz is plenty). A hand that
  leaves tracking sends no events, so only `tick` closes the microphone after the flicker
  grace or the hold limit, expires stale panels and prunes old rays.
- `reset()` cancels a live utterance, reports every held panel removed, drops retained
  rays and clears the clock mapping. Call it after `COMPANION_MISBEHAVING`, a reconnect or
  a mode change.
- `resolve_demonstrative(word_onset_s, utterance_end_s, destructive=False)` casts the
  retained rays at the live panels, binds the word, and returns a `SessionResolution`: the
  panel (or none), whether it came from a pin, a ray or nothing, the confirm decision, and
  a supporting `TargetSnapshot`. A pinned target wins and needs no confirmation. It reads
  state and changes none.
- For the snapshot, each panel's coordinate space is `xr-panel:<id>`, **versioned by the
  session**: the version is bumped whenever a panel's pose or size changes, so a snapshot
  taken before a panel moved compares unequal to one taken after. (In the lower-level
  `snapshot_series`, the caller passes a `versions` mapping from panel id to version,
  default 0; without it a moved panel invalidates nothing, and an explicit single `space`
  is accepted only when every hit is on one panel.)

## What is not built yet

- The daemon does not use any of this. No input path reads frames, nothing creates or
  drives an `XrSession`, and no text is typed into a panel.
- No `[xr]` config section, so no way to switch it on, set a window length or choose a
  gesture mode.
- No command-line entry point.
- No transport for these frames: the `bridge/` package holds only a pairing state machine
  and audio framing, so nothing in the daemon or the paired bridge carries companion
  frames to this adapter (no other module imports it).
- No companion app for any headset, glasses or phone.
- No real-device data. Every test input is synthetic, so latency, jitter, the binding
  window, the confirm thresholds and the gesture timings are unvalidated.
- Android XR and visionOS coordinate handling are unconfirmed assumptions.
- Per-device capabilities beyond the table above are unknown.
- No documentation of config keys or commands, because there are none to document.

For a related, separate feature that ships today (experimental, off by default), see
[Aim dictation with your gaze](how-to/gaze-look-to-pane.md). For what is on the
roadmap overall, see the [roadmap](roadmap.md).
