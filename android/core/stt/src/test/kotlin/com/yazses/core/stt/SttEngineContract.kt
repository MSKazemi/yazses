package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * The behaviour every [SttEngine] must satisfy, written once.
 *
 * A concrete test class extends this and supplies [createEngine]; each `@Test`
 * here builds a fresh engine, runs one check on it and closes it. The checks are
 * public so [SttEngineContractSelfTest] can point them at deliberately broken
 * engines and prove that they fail.
 *
 * Kept in `src/test` on purpose: exposing it to another module would need a
 * `java-test-fixtures` plugin change in `:core:stt`, which this module does not
 * make yet. A future engine module must therefore copy or move this file.
 */
abstract class SttEngineContract {

    /** A fresh, open engine under test. Each call returns a new instance. */
    abstract fun createEngine(): SttEngine

    @Test
    fun `silence yields the empty transcript, never a hallucinated word`() =
        withFreshEngine { checkSilenceIsEmpty(it) }

    @Test
    fun `an empty buffer yields the empty transcript`() =
        withFreshEngine { checkEmptyBufferIsEmpty(it) }

    @Test
    fun `close is idempotent`() =
        withFreshEngine { checkCloseTwiceDoesNotThrow(it) }

    @Test
    fun `decoding after close fails instead of touching freed state`() =
        withFreshEngine { checkDecodingAfterCloseFails(it) }

    @Test
    fun `an engine accepts every valid DecodeOptions`() =
        withFreshEngine { checkAcceptsValidOptions(it) }

    /** Silence must come back as [Transcript.EMPTY] from both decode entry points. */
    fun checkSilenceIsEmpty(engine: SttEngine) {
        val silence = FloatArray(16_000)
        assertEquals(Transcript.EMPTY, engine.transcribe(silence, DecodeOptions()))
        assertEquals(Transcript.EMPTY, engine.decodeWindow(silence, DecodeOptions()))
    }

    /** A zero-length buffer must come back as [Transcript.EMPTY] from both entry points. */
    fun checkEmptyBufferIsEmpty(engine: SttEngine) {
        assertEquals(Transcript.EMPTY, engine.transcribe(FloatArray(0), DecodeOptions()))
        assertEquals(Transcript.EMPTY, engine.decodeWindow(FloatArray(0), DecodeOptions()))
    }

    /** A second [SttEngine.close] must return normally and change nothing. */
    fun checkCloseTwiceDoesNotThrow(engine: SttEngine) {
        engine.close()
        engine.close()
    }

    /** Once closed, both decode entry points must throw [IllegalStateException]. */
    fun checkDecodingAfterCloseFails(engine: SttEngine) {
        engine.close()
        val pcm = FloatArray(10) { 0.1f }
        assertFailsWith<IllegalStateException> { engine.transcribe(pcm, DecodeOptions()) }
        assertFailsWith<IllegalStateException> { engine.decodeWindow(pcm, DecodeOptions()) }
    }

    /** Every valid option set is accepted; silence still yields the empty transcript. */
    fun checkAcceptsValidOptions(engine: SttEngine) {
        val silence = FloatArray(1_600)
        val valid = listOf(
            DecodeOptions(),
            DecodeOptions(sampleRate = 8_000),
            DecodeOptions(initialPrompt = "YazSes, Whisper"),
            DecodeOptions(task = DecodeOptions.TASK_TRANSCRIBE),
            DecodeOptions(task = DecodeOptions.TASK_TRANSLATE),
        )
        for (opts in valid) {
            assertEquals(Transcript.EMPTY, engine.transcribe(silence, opts), "options: $opts")
        }
    }

    private fun withFreshEngine(check: (SttEngine) -> Unit) {
        val engine = createEngine()
        try {
            check(engine)
        } finally {
            engine.close()
        }
    }
}
