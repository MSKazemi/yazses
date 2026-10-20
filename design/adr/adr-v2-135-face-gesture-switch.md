# ADR-v2-135 — Face-gesture switch access: a held facial movement as the hotkey

**Status:** Accepted (2026-09-02) · implemented in the same change
**Context links:** [[adr-v2-129-killer-features-10x]] (the activation-source seam this is
the third source through), [[adr-v04-003-emg-serial]] (the second source, and the pattern
copied here), [[adr-v2-010-gaze-routed-dictation]] (the camera and the model, already
running for a different purpose), [[adr-011]] (frames in RAM, nothing leaves the machine),
issue #102 (epic: hands-free bundle)

## Context

YazSes has two activation sources: a keyboard hotkey, and an EMG armband over serial or
BLE. Both assume something the users this project was built for may not have — a key you
can press, or hardware you can buy and wear. The gap is the classic *switch access* case:
someone who can speak, and can move their face, and cannot reliably do either of the
other two.

The free Linux stack for that is a graveyard. eViacam has been unmaintained since ~2019
and Google's Project Gameface was archived in 2025; commercial eye-gaze AAC devices are
$10,000–20,000 and Windows/iPad-locked (evidence and citations:
`docs/research/muscle-brain-control.md`). Issue #102 collects this as the "hands-free
bundle" epic and says each sub-feature is independently shippable.

The parts were already here and already paid for. Glance-Type downloads MediaPipe's
FaceLandmarker (~3.7 MB) and runs it on the webcam; that model reports 52 ARKit-style
**blendshape** activations per frame — `jawOpen`, `browInnerUp`, `mouthPucker` and the
rest — alongside the landmarks gaze uses. ADR-v2-129 built the seam
(`_build_activation_sources`) precisely so a non-keyboard trigger could be added without
touching the pipeline. Nothing read the blendshapes.

## Decision

Add an opt-in **face-gesture switch**: `[facegesture] enabled = false`, a third source
through the ADR-v2-129 seam. A held facial movement *is* the key — the mic opens while
you hold it and closes when you relax — so the transcript, the guards, the injector and
every downstream feature are reached unchanged.

Split the way the rest of the v2 layer is split: `facegesture/detector.py` is the entire
activation policy and is **pure** (a score per frame in, `"start"` / `"end"` / nothing
out), so it is tested frame by frame with no camera, no model and no MediaPipe;
`facegesture/backend.py` is the capture loop and duck-types `HotkeyBackend` exactly as
the two EMG transports do, taking the same two callbacks and the same `mode` decision.

Three choices inside the policy are load-bearing:

1. **Hysteresis, not a threshold.** A blendshape score is continuous and noisy. A gesture
   held right at a single threshold crosses it several times a second, and each crossing
   would be a separate recording — a burst of one-word transcripts instead of one
   sentence. The mic opens at `hold_threshold` and closes only below `release_threshold`.
2. **A frame-count debounce (`min_hold_frames`).** Talking, laughing and yawning all
   spike `jawOpen` transiently; a switch that fires on one frame fires on all of them.
   This is the Midas-touch defence, and its latency is affordable *here specifically*
   because the audio path already prepends `[accessibility] pre_speech_padding_ms` of
   ring-buffered audio — the words spoken during the debounce are still in the recording.
   That is a property of this pipeline, not of switch access in general.
3. **No reading counts toward release.** A frame with no face — the user turned away, the
   camera dropped a frame — is not "still holding". The alternative is a microphone that
   stays open until they come back. It goes through the same `min_release_frames`
   debounce as a low score, so one blurred frame does not cut a sentence in half.

`mode` defaults to `full_text` here, where `[emg] mode` defaults to `command`: a squeeze
is usually a *second* input beside a keyboard, and a face gesture is the *replacement*
for one.

## Consequences

- The first maintained, free, offline face-switch activation on Linux, using only the
  webcam already in the lid. No new dependency: the same `gaze` extra (opencv +
  mediapipe) and the same model asset — enabling it after Glance-Type installs nothing,
  which `system/depsize.py` now prices correctly for both slugs.
- Privacy is unchanged (ADR-011): frames are processed in-RAM, never stored, never sent.
- Off by default and **experimental** — `features enable facegesture` requires `--force`.
  The thresholds shipped are reasoned, not measured on real faces; that measurement is
  the ask in #102, and the honest position is to say so rather than to imply a tuned
  default.
- Cost, and it is real: a camera and a face-landmark inference run for as long as the
  daemon does, where the keyboard hook costs nothing. That is why it is opt-in rather
  than a fallback the daemon reaches for on its own.
- Not addressed here, and still open in #102: dwell-to-talk (gaze, not gesture), and
  Wayland injection via libei — the desktop half remains X11-only, though *this* feature
  does not need it, because it drives the same injector the hotkey does.
