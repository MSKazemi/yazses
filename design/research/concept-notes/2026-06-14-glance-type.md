# Glance-Type — origin note

> **Written:** 2026-06-14 · **Owner:** Mohsen Seyedkazemi Ardebili
> **Shipped as:** [`design/v2-cognitive-layer/03-glance-type.md`](../../v2-cognitive-layer/03-glance-type.md) ·
> [ADR-v2-010](../../adr/adr-v2-010-gaze-routed-dictation.md) · ADR-011 (offline-by-construction posture)
> **Tier:** `design/` — public. Historical origin note; the implementation docs above are
> the current source of truth.

## The idea

The pitch was to close the loop between attention and action: look at a pane, dictate,
and the text lands there — no click, no Alt-Tab, no reaching for the mouse to re-aim the
caret. The honest boundary was stated up front, before any code: commodity webcam gaze
estimation is region-grade, not pixel-grade, so the buildable version was look-to-**pane**,
never look-to-letter.

The survey that grounded it found the perception half solved — real-time face/iris
tracking at ~90 FPS for a few percent of CPU, and gaze-direction models reporting under
4° angular error on standard benchmarks — but the *screen-mapping* half bounded: the best
published webcam-to-screen accuracy sits in the tens of millimetres even with a still
head, and degrades further under head motion. A line of text is a few millimetres tall;
tens of millimetres of error rules out caret precision on a webcam, full stop. The
decision gate that followed was explicitly conditional: build the coarse, pane-level,
always-falls-back-to-the-focused-window version now, and treat caret precision as blocked
on a state-of-the-art jump that hadn't happened yet.

## What shipped

Look-to-pane targeting shipped as `src/yazses/gaze/` — a MediaPipe-based default backend,
an affine calibration map, and a confidence-gated routing policy that falls back to the
focused window whenever gaze confidence is low, exactly as the original prototype plan
specified. It ships **off by default**, needs a one-time calibration pass and (for window
focusing) X11, and frames are processed in-RAM during a hold and never stored — the
privacy posture the original card treated as non-negotiable. Caret-level precision was
never attempted; the scope stayed at the pane/window grain the evidence supported.
