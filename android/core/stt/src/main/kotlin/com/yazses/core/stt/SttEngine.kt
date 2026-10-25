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
 *
 * Cancelling an in-flight decode is NOT part of this interface yet. The
 * architecture requires it (burst-abort) for the native engine, and it is to be
 * added together with that engine, not speculatively here. Until then a call to
 * [transcribe] or [decodeWindow] runs to completion.
 */
public interface SttEngine {

    /**
     * Stable engine id, the key an [SttEngineFactory] registers this engine under:
     * `"whisper-cpp"` or `"sherpa-onnx"` for the planned engines.
     */
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
