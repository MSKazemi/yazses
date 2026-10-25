package com.yazses.core.stt

/**
 * The speech-to-text engine seam: PCM in, [Transcript] out.
 *
 * Mirrors the desktop `SttEngine` Protocol (`src/yazses/stt/base.py`) so the two
 * stay conceptually identical (ADR-MOB-005 §1). The engine never sees files,
 * audio focus, the config object or any Android type: it receives 16 kHz mono
 * float PCM and returns text.
 *
 * Implementations own their native resources. Callers must invoke [close] when
 * done (see the contract on [close]).
 */
public interface SttEngine {

    /** Stable engine id, the value `[stt] engine` selects: `"whisper-cpp"` or `"sherpa-onnx"`. */
    public val id: String

    /** Decode a whole utterance. Silence or an empty buffer yields [Transcript.EMPTY]. */
    public fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript

    /**
     * Fast decode of a rolling streaming window (the LocalAgreement seam, the
     * desktop's `decode_window`). Same input and output shape as [transcribe].
     */
    public fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript

    /**
     * Release native resources. Idempotent: a second call does nothing. After
     * [close], [transcribe] and [decodeWindow] must fail with
     * [IllegalStateException] rather than decode against freed memory.
     */
    public fun close()
}
