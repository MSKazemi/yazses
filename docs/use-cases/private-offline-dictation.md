---
title: Private dictation with no cloud — offline speech to text for confidential work
description: Speech-to-text that never uploads your audio. For clinical notes, legal work, journalism, research under NDA, and air-gapped machines — transcription runs on your own CPU with no account, no API key and no network.
---

# Private dictation for confidential work

**Short answer:** if your audio must not leave the machine — because of a patient,
a client, a source, an NDA, or a security policy — cloud dictation is not an
option no matter how accurate it is. YazSes transcribes on your own CPU, with no
account and no network call, so there is nothing to leak.

## The problem with cloud dictation

Every mainstream dictation tool — Google Voice Typing, Wispr Flow, most phone
keyboards, and the "AI notetaker" category — works by **streaming your microphone
to someone else's server**. For a lot of work that is simply disqualifying:

- **Clinical** — dictating patient notes to a third-party processor creates a
  disclosure you have to justify and a processor you have to have an agreement with.
- **Legal** — privileged material passing through an external service is a risk
  many firms will not accept.
- **Journalism & research** — source protection is incompatible with an upload you
  do not control.
- **Corporate & government** — machines that are network-restricted or air-gapped
  cannot reach a cloud API at all, so cloud tools do not merely violate policy,
  they do not function.

## What YazSes actually does

| Property | YazSes |
|---|---|
| Where audio is transcribed | On your CPU, locally |
| Network required after install | **None** |
| Account / API key / subscription | **None** |
| Telemetry | **None** |
| Always listening | **No** — hold-to-talk; the mic is only live while you hold the key |
| Where transcripts go | Typed into the focused app; not stored unless you opt in |

The model file is downloaded once during setup. After that you can unplug the
network permanently and dictation continues to work. This is verifiable — the
project is Apache-2.0 licensed and the source is [on
GitHub](https://github.com/MSKazemi/yazses).

## Push-to-talk, not always-on

This is a meaningful design difference from "AI assistant" style tools. There is
no wake word listening in the background by default and no continuous capture.
The microphone is only recording during the window in which you are physically
holding the hotkey down. When you release it, capture stops.

## What is stored, if anything

By default: nothing persistent. The transcript is typed and forgotten.

There is an **opt-in** on-device learning corpus that stores your dictations so
that `yazses tune` can propose accuracy improvements from your own corrections.
It is off unless you turn it on, and when on:

- text and audio are encrypted at rest with a machine-bound AES-256-GCM key;
- it never leaves the machine;
- you configure regex patterns that are scrubbed before anything is written;
- retention and size caps evict old data automatically.

```sh
yazses corpus status    # what has been captured, if anything
yazses corpus destroy   # delete it all
```

Full details in the [privacy statement](../privacy-statement.md).

## Air-gapped and restricted machines

Because there is no licence server or activation call, YazSes runs on a machine
that has never touched the internet, provided you carry in the package and the
model file. Both the snap and the PyPI wheel can be transferred offline, and the
model can be pre-placed in the model cache directory.

## Confidential meetings

The same guarantees extend to meeting capture and to transcribing existing
recordings — both run through the same local pipeline. If your meetings cannot be
sent to Otter.ai or Fireflies, see:

- [Offline meeting notes](../meeting-notes-offline.md) — record, transcribe and
  summarise a whole meeting locally, with speaker labels
- [Transcribe audio files offline](transcribe-audio-offline.md)

## Honest limits

- **Accuracy is not magic.** A local CPU model is very good, but for
  professional medical or legal dictation with specialist vocabulary, a mature
  commercial product like Dragon still has an edge. You can close part of that
  gap with a [personal vocabulary](../how-to/personal-vocabulary.md) and the
  opt-in learning loop, but be realistic.
- **"Offline" is about the audio, not about the operating system.** YazSes cannot
  stop other software on your machine from doing whatever it does.
- **This page is not legal advice.** Whether a given workflow satisfies HIPAA,
  GDPR or your institution's policy is a determination for you and your
  compliance function. What YazSes provides is the technical property those
  frameworks usually care about: the audio is never transmitted.

## Related

- [Privacy statement](../privacy-statement.md)
- [Offline meeting notes](../meeting-notes-offline.md)
- [Comparison with cloud and commercial tools](../comparison.md)
- [FAQ](../faq.md)
