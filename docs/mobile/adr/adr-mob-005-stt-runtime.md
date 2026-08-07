# ADR-MOB-005 — STT runtime: an engine seam, whisper.cpp as the default, sherpa-onnx as the second

**Status:** Accepted (2026-08-07) · design only, no code yet
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-mob-002]] (native stack), [[adr-mob-006]] (model distribution),
[[adr-mob-009]] (F-Droid), [[adr-v2-129]] (desktop `SttEngine` seam),
desktop analogue: `src/yazses/stt/base.py`, `src/yazses/stt/factory.py`

---

## Context

The desktop learned this lesson the expensive way: faster-whisper was hard-wired for two
years, `StreamingEngine` reached into its private `_model`, and adding Parakeet required
inventing an `SttEngine` Protocol and a factory first ([[adr-v2-129]]). The Android port
should start where the desktop ended up.

Which engine, though, is constrained by more than accuracy:

- **CTranslate2 (faster-whisper's runtime) has no Android build.** The desktop default is
  simply unavailable, so "the same engine as desktop" is not on the menu.
- **whisper.cpp** is a small, self-contained CMake/C++ project with first-class Android
  support (it ships an Android example), GGML quantisation down to ~Q5/int8, and it is what
  the closest FOSS neighbour (Transcribro) ships. Being a small CMake project matters
  disproportionately for [[adr-mob-009]]: F-Droid forbids prebuilt binaries and requires
  native code to be built from source in the build recipe, and whisper.cpp is realistically
  buildable there.
- **sherpa-onnx** (k2-fsa) covers more ground — streaming Zipformer, Whisper, Parakeet-TDT,
  Silero VAD, and *speaker diarization* — with official Android AAR support, and the
  desktop already depends on it for diarization (`recimport/diarizer.py`). Its runtime is
  ONNX Runtime, which is a much heavier from-source build for an F-Droid recipe, and the
  convenient path is a prebuilt AAR that F-Droid's main repo will not accept.
- Model size is bounded by phone RAM and by the fact that decode must finish in the second
  or two after the user lifts their finger. `tiny.en`/`base.en` class models are the
  realistic mobile defaults; `small.en` is a high-end-device option, and medium/large are
  out of scope.

So the two engines are not competitors to be ranked once — they are complements with
different packaging consequences, which is exactly the situation an engine seam exists for.

## Decision

1. **`:core:stt` defines the engine seam**, deliberately mirroring the desktop's
   `SttEngine` Protocol so the two stay conceptually identical:
   ```kotlin
   interface SttEngine {
       val id: String                       // "whisper-cpp" | "sherpa-onnx"
       fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript
       fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript   // streaming seam
       fun close()
   }
   ```
   Selection is by config key `[stt] engine`, same key name as the desktop, resolved by a
   factory. **No `:feature:*` module may reference a concrete engine.**
2. **whisper.cpp is the default engine** (`:native:whispercpp` — a git submodule plus a
   thin JNI bridge and a CMake target). Default model `base.en`-class for English; the
   model is downloaded, not bundled ([[adr-mob-006]]).
3. **sherpa-onnx is the second engine** (`:native:sherpaonnx`), shipped in M3 and required
   for the capabilities whisper.cpp does not provide: Silero VAD, speaker diarization for
   Meeting Mode / file import, and Parakeet-TDT for users who want the desktop's
   high-accuracy engine. It is a **build variant / optional download**, never a hard
   dependency of the dictation path — see [[adr-mob-009]] for how the F-Droid and
   GitHub/Play variants differ.
4. **The engine boundary is PCM in, `Transcript` out.** No engine sees the config object,
   the Android `Context`, or the delivery layer. `Transcript` carries text, per-segment
   timings and (when the engine supports it) token confidence, because the desktop's
   confidence-ink and hallucination-guard ideas depend on it and must not be designed out.
5. **Decode runs on a dedicated single-thread dispatcher**, thread count capped and pinned
   to performance cores, never on `Dispatchers.Default` (which would let decode starve the
   IME's input handling). Cancellation on burst-abort is mandatory.
6. **Hardware acceleration (NNAPI, QNN, GPU delegates) is deferred**, behind the same seam.
   Reason: NNAPI's deprecation and vendor-driver variability make it a per-device lottery
   that would cost more in bug reports than it returns in latency at `base.en` scale. It is
   revisited only with on-device benchmark data from `:bench` ([[adr-mob-008]] §5).
7. **Every claim about speed or accuracy must come from `:bench`, not from a blog post.**
   The benchmark harness is a first-class module: it runs a fixed audio corpus on-device
   and emits JSON (device, SoC, Android version, engine, model, real-time factor, peak RSS,
   battery delta). Community device reports populate a public matrix. Until that matrix
   exists, the app and the docs state performance as "measure it on your device", not as a
   number.

## Consequences

- The dictation path is buildable entirely from source with one small C++ dependency,
  which is what makes an F-Droid listing realistic ([[adr-mob-009]]).
- Diarization and neural VAD arrive with sherpa-onnx in M3 and are therefore *variant-
  dependent* features; the feature registry must mark them unavailable-in-this-build
  honestly, exactly as the desktop's `system/backends.py` distinguishes "the optional
  dependency is missing" from "this build cannot supply it".
- Two JNI bridges are two chances to leak memory or crash the IME process. Mandatory:
  every native handle behind a `Closeable` with an explicit lifecycle owner, an
  instrumentation test that opens/closes an engine 100× without growth, and no native call
  on the main thread.
- Whisper's well-known hallucination on silence must be handled before delivery, reusing
  the desktop's `postprocess/cleaner.py` behaviour through the shared vectors, plus the VAD
  gate. A silent burst delivers nothing — never `[BLANK_AUDIO]`.
- Model-quality expectations must be set honestly in-app: a phone-class `base.en` is not
  the desktop's `small.en`, and the onboarding should say so rather than let users conclude
  YazSes is inaccurate.

## Rejected

- **faster-whisper / CTranslate2** — no Android build. Not a judgement, an availability fact.
- **A single hard-wired engine** — the exact mistake [[adr-v2-129]] had to undo on desktop.
- **Cloud STT of any kind, including "just for the first run"** — [[adr-011]] §3 forbids a
  cloud fallback; the app ships with no such code path at all.
- **Android's built-in `SpeechRecognizer` as a backend** — it is the thing YazSes exists to
  replace, and on most devices it is Google's service.
- **MLC/LLM-based ASR or a large multimodal model on-device** — memory and battery are not
  there for a keyboard that must respond in ~1 s.
- **Bundling model weights in the APK** — see [[adr-mob-006]].
