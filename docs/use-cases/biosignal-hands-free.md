---
title: Hands-free computing with a muscle, blink or jaw-clench switch
description: Use a muscle squeeze as an offline push-to-talk when you cannot hold a key, what a blink or jaw-clench switch can and cannot do, and why the switch watches its own false-positive rate.
---

# Hands-free computing with a muscle, blink or jaw-clench switch

**Short answer:** if holding a key is the problem, a small, deliberate muscle contraction can stand in for
it. A **muscle squeeze** read by an electrode can hold the microphone open like the hold-to-talk key, and
you speak the words. It is experimental, it is off by default, and it has not yet been measured over real
workdays, so this page is as much about its limits as its use.

Everything runs on your machine. The electrodes are read locally, no network connection is made, and the
signal is not stored unless you ask for a recording. That matters for this audience: assistive tooling that
depends on a service can be taken away.

## Who it is for

- People who can still contract one muscle on purpose (a forearm, a finger, the jaw or face) but cannot press
  or hold a key reliably, because of repetitive strain injury, a motor impairment, fatigue or pain.
- People whose hands are busy: at a workbench, at an instrument, with a sleeping child.
- Anyone who wants a trigger that needs no keyboard and nothing on screen.

It is **not** a way to type with your muscles. A wristband that decodes handwriting reaches roughly 21 words
per minute in the best published result, against about 150 for speech (the
[research page](../research/muscle-brain-control.md) has the numbers). So the muscle carries the *intent to
speak* and your voice carries the words: the same split YazSes uses for every non-keyboard trigger.

## What it can do

| Gesture | What it does by default | Notes |
|---|---|---|
| **Squeeze** (a muscle electrode) | A light squeeze holds the microphone open and types what you say; a hard squeeze speaks a command. | The recommended trigger. Strength comes from your own calibration. |
| **Double blink** | Runs a single command phrase, **undo** by default, through the confirmation gate. | A blink is an eye-movement artifact on a frontal channel. Two quick blinks is the gesture because a single blink is involuntary. |
| **Jaw clench** | Does nothing until you map it to a command. Off by default. | A clench is a muscle artifact, and chewing, yawning and talking all look like one. A speech guard suppresses it while you dictate, so a clench made mid-sentence may be missed. |

**Blink and jaw clench are artifacts, not brain signals.** On an EEG headband you are reading eye and
muscle activity that leaks into the headband. The research page records the best measured blink switch at
99.5% accuracy but 0.10 false positives per minute, which is about 50 stray activations in a workday without
extra safeguards. That is why the squeeze is the recommended trigger, and why blink and jaw events run only
a short, reversible command rather than dictation. YazSes does not read thoughts, imagined movement or
attention, and this feature does not try to.

## How to start

1. **Pick the hardware.** A DIY muscle sensor (MyoWare 2.0 or a BioAmp EXG Pill) on a microcontroller is the
   cheapest and most dependable squeeze trigger. A board BrainFlow supports (an OpenBCI board, a Muse
   headband) gives raw-signal control and lets YazSes measure its own mistakes. The
   [hardware guide](../how-to/biosignal-hardware.md) compares them, and covers the mains setting and the
   safety rules. It is not a medical device, and electrodes must never be connected to mains-powered
   equipment.
2. **Try it without hardware.** Set `source = "synthetic"` and run `yazses biosignal monitor` to see
   scripted gestures go through the real detectors.
3. **Check the real signal.** `yazses biosignal doctor` checks the chain, then `yazses biosignal calibrate`
   learns your relaxed level, a light and a hard squeeze, a blink and a clench. `yazses biosignal evaluate` scores the detectors on a scripted session or on a recording you labelled.
4. **Use it, and read your own numbers.** `yazses biosignal report` shows how often each gesture fired and
   how often you cancelled it. That is the evidence that decides whether you keep it on.

The step-by-step configuration is in
[Use a muscle, blink or jaw-clench switch](../how-to/biosignal-switch.md).

## A switch that watches itself

A trigger that fires when you did not mean it is worse than none. Two guards keep that in check:

- **The false-positive budget.** YazSes counts the activations you cancel. If the rate goes over the budget
  you set, it first **desensitizes** the detectors, and if the cancelled rate stays over the budget it then
  **suspends** them, and you release it with one action. You are never locked out.
- **A global pause.** With the hands-free global stop on, `yazses handsfree pause` stops the switch with the
  other hands-free inputs, so you can stop it from a terminal or the settings window.

## Honest limits

- **Unmeasured.** The detectors have been tested on synthetic and replayed signals. They have not been
  shown to work for any particular person, electrode or board, and every default is a provisional starting
  point.
- **It is personal.** Skin, electrode placement and muscle differ between people. Calibrate to yourself, and
  again whenever an electrode moves.
- **A bad signal means no events.** A flat, clipped or hum-filled channel is ignored on purpose, and the tools
  say why.
- **Fatigue and spasm are yours to judge.** A trigger that needs a repeated squeeze can itself tire you. If
  it does, lower the demand (a lighter squeeze, a different muscle) or use another trigger.
- **Not a medical device.** It is not for diagnosis, monitoring or safety-critical control.

If you try it, please report what worked and what did not: accessibility feedback is the most useful
feedback this project can receive, and
[an issue](https://github.com/MSKazemi/yazses/issues) is the place for it. Do not attach a recording of your
signal to a public issue; share the output of `yazses biosignal doctor` instead.

## Related

- [Use a muscle, blink or jaw-clench switch](../how-to/biosignal-switch.md) · [Hardware guide](../how-to/biosignal-hardware.md)
- [Accessibility, RSI and hands-free use](accessibility-rsi-hands-free.md): the voice, face and mouth-sound options
- [Set up hands-free input](../how-to/hands-free-setup.md)
- [Research: muscle & brain control](../research/muscle-brain-control.md): why the muscle, not the brain
