---
description: "Reference architecture for the YazSes Android app — the document to read after the ADRs and before a first pull request. Design stage, governed by ADR-MOB-001 to 010."
---

# YazSes for Android — architecture

**Status:** design, no code yet · governed by `docs/mobile/adr/adr-mob-001..010`
**Last updated:** 2026-08-07

This is the reference architecture for the Android app. It is the document a new
contributor reads after the ADRs and before their first PR. Where it says **MUST**, the
constraint comes from an ADR and changing it needs a new ADR.

---

## 1. What the app is

Three pieces of Android system integration around a local speech pipeline:

| Piece | Android class | Desktop analogue |
|---|---|---|
| The keyboard that listens | `InputMethodService` | the hotkey hook + `inject/` |
| The system speech provider | `RecognitionService` | — (no desktop equivalent) |
| Long capture that survives the screen going off | foreground service, type `microphone` | `yazses meeting` |

Everything else — capture, VAD, decode, post-processing, command classification — is the
same pipeline as the desktop, reimplemented in Kotlin against a shared behavioural contract
(ADR-MOB-008).

## 2. The pipeline

Desktop (`core/daemon.py`) and Android run the same stages. The Android version drops the
IPC layer entirely — there is no daemon, no socket, no CLI; the IME *is* the process.

```
Activation source            hold the mic key  |  headset button  |  bubble  |  meeting service
  (ADR-MOB-004)                       │
                                      ▼
:core:audio        AudioRecord 16 kHz mono PCM16 → ring buffer → pre-speech padding
                                      │
                                      ▼
:core:vad          calibrated RMS gate (default)  |  Silero ONNX (optional, sherpa build)
                                      │
                                      ▼
:core:stt          SttEngine.transcribe(pcm, opts)      ← initial_prompt from :core:vocab
                   whisper.cpp (default) | sherpa-onnx (optional)     (ADR-MOB-005)
                                      │
                                      ▼
:core:postprocess  cleanText → disfluency filter → voice punctuation → continuation spacing
                                      │                          ⟵ contract vectors
                                      ▼
:core:commands     grammar.classify() → DICTATE | COMMAND intent
                                      │
                    ┌─────────────────┴──────────────────┐
                    ▼                                    ▼
:feature:ime  InputConnection.commitText()      key/edit action on the InputConnection
              (or clipboard + notice if no       (backspace word, newline, select all…)
               InputConnection — ADR-MOB-003)
```

**Session state machine** (`:core:session`), mirroring the desktop's:

```
LOADING → IDLE ⇄ RECORDING → TRANSCRIBING → DELIVERING → IDLE
                     │                                      ▲
                     └──────── discarded (silent / cancelled) ┘
   plus: MEETING (long capture), ERROR
```

A burst is cancellable at every stage; cancelling MUST stop the native decode, not just
drop its result.

## 3. Module map

`:core:*` are **pure-Kotlin JVM modules** — no `android.*` imports, unit-testable without an
emulator (ADR-MOB-002 §3). That rule is what keeps the test suite fast and the KMP door open.

| Module | Type | Responsibility | Desktop analogue |
|---|---|---|---|
| `:core:config` | JVM | settings model, defaults, TOML import/export, validation against `contract/schema/config.schema.json` | `config.py`, `system/configedit.py` |
| `:core:audio` | JVM | ring buffer, pre-speech padding, resampling, PCM utilities (capture itself is injected) | `audio/padding.py`, `audio/recorder.py` |
| `:core:vad` | JVM | `VoiceActivityGate` interface + calibrated RMS gate; silent-burst discard | `audio/vad_calibrated.py` |
| `:core:stt` | JVM | `SttEngine` interface, `DecodeOptions`, `Transcript`, engine factory | `stt/base.py`, `stt/factory.py` |
| `:core:postprocess` | JVM | cleanText, disfluency filter, voice punctuation, continuation spacing | `postprocess/*` |
| `:core:commands` | JVM | Tier-1 grammar classifier, intent dispatch model | `commands/grammar.py`, `dispatch.py` |
| `:core:vocab` | JVM | personal dictionary, `initial_prompt` merge (incl. built-in "YazSes") | `system/vocabulary.py`, `stt/vocabulary.py` |
| `:core:session` | JVM | state machine, `ActivationSource`, burst orchestration | `core/daemon.py` (logic only) |
| `:core:features` | JVM | capability registry: name, on/off, tier, config keys, availability-in-this-build | `system/features.py`, `system/backends.py` |
| `:core:contract-test` | JVM test | runs `contract/vectors/*.json` against the cores | `tests/test_contract_vectors.py` |
| `:native:whispercpp` | Android lib + CMake | JNI bridge to whisper.cpp (submodule) | — |
| `:native:sherpaonnx` | Android lib | sherpa-onnx engine, VAD, diarization (optional flavour) | `recimport/diarizer.py` |
| `:model` | Android lib | **the only module with `INTERNET`** — catalogue, download, SHA-256 verify, storage, sideload import | — |
| `:platform:audio` | Android lib | `AudioRecord` capture, device selection, audio-focus handling | `audio/recorder.py`, `device_monitor.py` |
| `:feature:ime` | Android lib | `InputMethodService`, key view, delivery, password-field guard | `inject/`, `platform/*/injector` |
| `:feature:recognition` | Android lib | `RecognitionService` | — |
| `:feature:meeting` | Android lib | foreground service, live transcript, finalize | `meeting/` |
| `:feature:transcribe` | Android lib | SAF file import → transcript, share-sheet target | `recimport/` |
| `:feature:settings` | Android lib | Compose settings UI **generated from `:core:features`** | `yazses features` + epic #65 |
| `:feature:bubble` | Android lib | opt-in floating mic overlay | — |
| `:bench` | Android app | on-device benchmark harness, emits device-report JSON | `scripts/` benchmarks |
| `:app` | Android app | assembly, onboarding, permissions, About | `cli.py` + `main.py` |

Dependency rule, enforced in CI: `:feature:* → :core:*` and `:feature:* → :platform:*` are
allowed; `:core:* → :feature:*`, `:core:* → android.*`, and any `:core:*`/`:feature:*` →
network dependency are build failures (ADR-MOB-007 B).

## 4. Threading and latency

- **Capture thread** — a dedicated thread reading `AudioRecord` into the ring buffer. Never
  blocked by decode.
- **Decode dispatcher** — a single-threaded coroutine dispatcher; thread count inside
  whisper.cpp capped (performance cores only). Never `Dispatchers.Default`.
- **UI/IME thread** — key handling and `commitText` only. **No native call and no file I/O
  on the main thread**; an ANR inside an IME takes the user's keyboard down.

Latency budget for a 3-second utterance on a mid-range 2023 phone, to be *measured* by
`:bench` rather than assumed (ADR-MOB-005 §7): key-up → text visible is the number that
matters, and the target is "fast enough that the user does not reach for Gboard".
Until the device matrix exists, no numeric claim goes in the docs or the store listing.

## 5. Configuration

Same key names as the desktop, same defaults, validated against the shared schema
(ADR-MOB-008 §5). Stored in DataStore (Proto or Preferences), **not** as a TOML file — but
the Settings screen can import a desktop `config.toml` and export one, which is the
migration path for existing users.

Feature flags follow the desktop's rules exactly: **every new feature ships off by default**,
experimental features require an explicit confirmation to enable, and a feature whose
backend is absent in this build is shown as unavailable with the reason — never silently
inert.

## 6. Error and edge behaviour (non-negotiable)

| Situation | Behaviour |
|---|---|
| No `InputConnection` / delivery fails | copy to clipboard, tell the user (ADR-MOB-003 §4) |
| Password field focused | mic disabled, reason shown |
| Burst below VAD threshold | discard, show "nothing heard", never deliver `[BLANK_AUDIO]` |
| Mic taken by another app | stop cleanly, notify |
| Mic permission revoked mid-session | stop, prompt |
| Model missing/corrupt | actionable error naming the fix; never a silent no-op |
| Decode crash (native) | catch at the JNI boundary, reset the engine, keep the IME alive |
| Meeting hits an OS foreground-service limit | **finalize and save** — never lose audio (ADR-MOB-007 D) |

## 7. Testing strategy

1. **Contract vectors** (`:core:contract-test`) — the definition of correct for all shared
   logic. JVM, no device. This is where most contributions are verified.
2. **JVM unit tests** for the rest of `:core:*`, including the session state machine driven
   by a fake activation source and a fake engine.
3. **Instrumented tests** for `:feature:ime` (a test activity with a real `InputConnection`),
   the airplane-mode round trip (ADR-MOB-007 C3), and JNI lifecycle (open/close 100×).
4. **Robolectric** where it saves an emulator round trip, never as a substitute for the IME
   integration test.
5. **`:bench`** — on-device performance/battery, producing the public device matrix.
6. **Audio fixtures** live in `contract/audio/` (short, licence-clean clips) so a contributor
   with no microphone can still exercise the pipeline end to end.

## 8. What is deliberately not in wave 1

Streaming/partial results, the v2 cognitive layer (gaze, EMG, LSP context, personalization,
polyglot routing), the learning corpus, remote injection, LLM cleanup, TTS read-back, Wear
OS, and a full typing keyboard. Each is a post-M3 conversation with its own ADR. See
[`portability.md`](portability.md) for where each desktop capability lands.
