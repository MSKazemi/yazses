---
title: Dictation for lawyers, clinicians and journalists — when the audio may not leave the building
description: Offline voice dictation and transcription for work under a confidentiality duty. YazSes transcribes on your own machine, so privileged, clinical or source material is never sent to a third-party service. What it does, and what it does not promise.
---

# When the audio is not allowed to leave the building

Most dictation tools are a convenience. For some work they are a **prohibition** — the
audio contains privileged client discussion, patient information, or a source who agreed
to talk on the understanding that the recording stays with you.

For that work the question is not "which tool is most accurate?" but "which tool can I use
at all?" Cloud dictation sends the audio to someone else's servers, and that single fact
disqualifies it in a lot of professional contexts regardless of how good it is.

YazSes runs the speech recognition **on your own CPU**. No audio, no transcript, and no
metadata is transmitted, because there is nothing to transmit to — there is no account, no
API key and no server component.

!!! warning "Read this before you rely on any of the above"
    **YazSes is not certified, audited, or validated against any regulatory framework.**
    It carries no HIPAA, GDPR, SOC 2, ISO 27001, CJIS or bar-association attestation, and
    nothing on this page should be read as legal or compliance advice.

    What the project can honestly tell you is *technical*: transcription happens locally,
    and you can verify that yourself rather than trust it (see
    [Prove it, don't trust it](#prove-it-dont-trust-it) below). Whether that satisfies your
    obligations is a decision for you, your data protection officer, or your professional
    body — and it depends on the rest of your setup (disk encryption, backups, device
    security, retention) at least as much as on this tool.

    **Accuracy is also your responsibility.** Speech recognition makes mistakes, including
    on names, drug names, dosages, legal terms and numbers. Read the transcript.

---

## What it actually does for this kind of work

| Situation | What you run | What happens |
|---|---|---|
| Dictate a note, letter or memo | Hold the hotkey, speak, release | Text is typed into whatever window you have focused |
| Transcribe an interview or recorded meeting | `yazses transcribe interview.m4a` | A transcript beside the file, optionally tagged with who said what |
| Capture a whole meeting | `yazses meeting start` … `stop` | A speaker-labelled transcript, and optionally minutes |

All three are local. The meeting recording is **deleted after transcription** unless you
explicitly ask to keep it (`[meeting] retain_audio`), and speaker names come from
voiceprints you enroll yourself — never from a cloud identity.

---

## Prove it, don't trust it

The whole claim on this page rests on "it runs locally", so do not take that on faith from
a documentation page. Check it in one command:

```sh
docker run --rm --network none \
    -v yazses-models:/models -v "$PWD:/data" yazses interview.m4a
```

`--network none` gives the container no route to the internet at all. It still produces a
correct transcript. See [try it without installing](../try-without-installing.md).

On a normal install, the equivalent check is to watch for connections and find none:

```sh
ss -tunp 2>/dev/null | grep -i yazses || echo "no network connections"
```

The one time YazSes needs the network is the **first** run, to download the speech model.
After that it does not, which is why the air-gapped case works at all. The full detail is
in the [privacy statement](../privacy-statement.md), and a machine-readable dependency
inventory ships as
[`sbom.cdx.json`](https://github.com/MSKazemi/yazses/blob/main/sbom.cdx.json) for reviews
that require one.

---

## By profession

### Legal

The recurring blocker is that privileged material cannot be processed by a third party
without going through a vendor-assessment process, and often not even then. Local
transcription removes the transfer entirely rather than trying to make it acceptable.

Practical notes:

- **Add your own vocabulary.** Case names, statutes, Latin terms and party names are
  exactly what a general model gets wrong. `yazses vocab add <word>` builds a personal
  dictionary that is fed to the recogniser.
- **Use a larger model for anything you will file.** `small.en` is measurably more
  accurate than the default `base.en` — see [benchmarks](../benchmarks.md) — at the cost of
  speed. For dictation you read back anyway, accuracy is usually the better trade.
- Transcripts are ordinary text files on your disk. They inherit whatever retention and
  encryption policy you already apply to client files; the tool imposes none of its own.

### Clinical and healthcare

Same shape, higher stakes. The honest position:

- Local processing means patient audio is not disclosed to a transcription vendor.
- It does **not** make your setup compliant with anything. Device encryption, access
  control, audit and retention are all outside this tool's scope.
- **Never dictate a dosage or a drug name without reading it back.** Numbers and
  similar-sounding drug names are a known weak point of general speech models, and this
  one has not been evaluated on clinical vocabulary.

If your institution requires validated clinical documentation software, this is not that.
It is a general-purpose dictation tool that happens not to phone home.

### Journalism

The interest here is usually the **source**, not a regulator:

- A recording that never leaves your laptop cannot be subpoenaed from a vendor, produced
  in response to a legal demand to a third party, or exposed in that vendor's breach.
  It can still be taken from your device — this narrows the surface, it does not remove it.
- `yazses transcribe` with `--diarize` tags who said what, which makes a two-hour interview
  searchable without sending it anywhere.
- It works with no connectivity at all — on a plane, in the field, in a building where you
  would rather not join the Wi-Fi.

### Researchers handling consented data

Ethics approvals frequently specify that recordings not be shared with third parties.
See the dedicated page on
[research interviews and ethics approval](research-interview-transcription.md).

---

## What would make this the wrong choice

Stated plainly, because a page like this is worthless if it only argues one way:

- **You need a documented compliance attestation.** YazSes has none. A vendor with a signed
  BAA or DPA may be the correct answer even though it processes in the cloud.
- **You need certified accuracy** for medical or legal transcription. Specialist tools are
  trained on that vocabulary and are validated for it; this is a general model.
- **You need a managed audit trail** of who transcribed what. There is deliberately no such
  logging, because there is no telemetry — which is a feature for privacy and a gap for
  governance.
- **Your language is not well covered.** The default models are English; other languages
  need a multilingual model and accuracy varies. See
  [multilingual dictation](multilingual-dictation.md).

---

## Getting started

1. [Install](../install-linux.md) — or [try it first](../try-without-installing.md) with
   nothing installed.
2. `yazses vocab add <term>` for the vocabulary your field uses.
3. Set a more accurate model in `~/.config/yazses/config.toml`:
   `[stt] model = "small.en"`.
4. `yazses verify` to confirm the whole chain works before you rely on it.

Related: [private and confidential work](private-offline-dictation.md) ·
[offline meeting notes](../meeting-notes-offline.md) ·
[comparison with other tools](../comparison.md)
