# Desktop → Android portability matrix

**Status:** design · **Last updated:** 2026-08-07
**Governed by:** `docs/mobile/adr/adr-mob-001..010`

Where every desktop capability lands on Android, and why. "Wave 1" is the Android
programme; milestones M0–M4 are defined in `docs/mobile/index.md`.

Legend — **Port**: same behaviour, reimplemented in Kotlin against the contract ·
**Adapt**: same intent, different mechanism · **Later**: designed for, deferred ·
**No**: does not apply or is deliberately excluded.

---

## Core dictation

| Desktop capability | Android | Milestone | Notes |
|---|---|---|---|
| Hold-to-talk hotkey | **Adapt** | M1 | hold the IME mic key; hold/toggle switch for accessibility (ADR-MOB-004) |
| Audio capture + pre-speech padding | **Port** | M1 | `AudioRecord`; padding logic is contract-covered |
| Calibrated VAD gate | **Port** | M1 | `vad_threshold` key name shared; `yazses mic-level`'s job becomes an in-app calibration screen |
| faster-whisper decode | **Adapt** | M1 | no CTranslate2 for Android → whisper.cpp (ADR-MOB-005) |
| `initial_prompt` / built-in "YazSes" vocab | **Port** | M1 | contract-covered |
| `clean_text` artefact stripping | **Port** | M1 | contract-covered |
| Disfluency filter (3-pass) | **Port** | M1 | contract-covered |
| Voice punctuation | **Port** | M2 | contract-covered; off by default, as on desktop |
| Continuation spacing between bursts | **Port** | M2 | contract-covered |
| Tier-1 command grammar + dispatch | **Port** | M2 | key/edit actions run against the `InputConnection` |
| Text injection (xdotool/ydotool/wtype) | **Adapt** | M1 | `InputConnection.commitText()` (ADR-MOB-003) |
| "No text target" guard → clipboard | **Port** | M1 | no `InputConnection` → clipboard + notice |
| Personal vocabulary (`yazses vocab`) | **Port** | M2 | in-app list; contract-covered merge |
| Mic pinning / device change guard | **Adapt** | M2 | Android routes audio itself; the useful part is Bluetooth/headset routing + "another app took the mic" |
| Tray icon state colours | **Adapt** | M1 | the IME key *is* the state indicator (idle / recording / decoding / no-target / error) |
| `yazses doctor` | **Adapt** | M2 | an in-app diagnostics screen: permissions, model, keyboard enabled, default recogniser, storage |
| Overlay (sonar rings) | **Adapt** | M1 | an audio-level meter in the key bar |
| Config file + comment-preserving writer | **Adapt** | M2 | DataStore + TOML import/export (ADR-MOB-008 §5) |
| Feature registry + `yazses features` | **Port** | M2 | drives a generated settings screen, same as desktop epic #65 |
| Shell completions, CLI, IPC/JSON-RPC, systemd | **No** | — | no daemon and no CLI on Android |

## Beyond dictation

| Desktop capability | Android | Milestone | Notes |
|---|---|---|---|
| File transcription (`yazses transcribe`) | **Port** | M3 | SAF picker + share-sheet target; PyAV/ffmpeg → `MediaExtractor`/`MediaCodec` |
| Speaker diarization | **Adapt** | M3 | sherpa-onnx; flavour-dependent, honestly reported when absent (ADR-MOB-009 §2) |
| Meeting Mode | **Port** | M3 | foreground service; FGS time limits are an open risk (ADR-MOB-007 D) |
| Meeting minutes via local LLM | **Later** | post-M3 | a 1–3 B GGUF on a phone is plausible but battery-hostile; needs its own ADR |
| Streaming / partial results | **Later** | post-M3 | LocalAgreement port; only worth it once batch latency is measured |
| Read-back / TTS | **Later** | post-M3 | Android TTS exists but is usually a Google service — conflicts with the offline claim |
| Learning corpus + `yazses tune` | **Later** | post-M3 | off-by-default, encrypted-at-rest, its own ADR (desktop `adr-012` applies) |
| LLM cleanup | **Later** | post-M3 | same battery question as minutes |
| Remote injection (`yazses-agent`) | **Later** | post-M3 | see "phone as a desktop microphone" below |
| Gaze / Glance-Type | **No** | — | front camera + always-on inference; battery and privacy cost fail the bar |
| EMG / YESP serial | **Later** | — | USB-OTG or BLE is feasible; it plugs into `ActivationSource` (ADR-MOB-004 §7) |
| LSP / editor context | **No** | — | no editor to bridge to |
| Cocktail Filter, Voiceprint Mind, Polyglot | **Later** | — | need the voiceprint infra and the learning corpus first |
| Wear OS companion | **Later** | — | plugs into `ActivationSource`; a natural community project once M2 lands |

## Deferred idea: phone as a desktop microphone

The desktop already has the receiving half — `yazses-agent` accepts injected text over TCP
and `remote/local_proxy.py` speaks to it. An Android app could capture on the phone,
transcribe on the phone, and deliver into the desktop's focused window over the LAN, or
act as a wireless mic for a desktop that does the decoding.

It is genuinely attractive (a phone is a better microphone than most laptops) but it is
**not the mobile product** (ADR-MOB-001, Rejected) — it needs a desktop on the same
network, so it does nothing for the phone-only user who is the reason for the port. It is
tracked as a post-M3 candidate, and if it happens it needs an ADR covering pairing,
authentication and the fact that it puts recognised text on a network — which is a
meaningful change to the [[adr-011]] posture and cannot be enabled by default.

## Things the phone gets that the desktop never had

- Dictation into apps that have no desktop equivalent (messaging, notes, forms) — the
  common case, and the reason the port matters.
- Being the system speech recogniser for *other* apps (`RecognitionService`).
- Share-sheet transcription of a voice note someone sent you.
- A meeting recorder that is already in your pocket when the meeting starts.
