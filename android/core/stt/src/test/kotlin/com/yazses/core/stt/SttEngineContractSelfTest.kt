package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertFails

/**
 * Proves the [SttEngineContract] checks can fail. Each test hands a deliberately
 * broken engine to one check and requires that check to throw. Without these, a
 * contract that accepts everything would look exactly like a passing suite.
 */
class SttEngineContractSelfTest {

    private val suite = object : SttEngineContract() {
        override fun createEngine(): SttEngine = FakeSttEngine()
    }

    @Test
    fun `silence check rejects an engine that invents text for silence`() {
        assertFails { suite.checkSilenceIsEmpty(BrokenEngine(silenceText = "[BLANK_AUDIO]")) }
    }

    @Test
    fun `empty-buffer check rejects an engine that invents text for an empty buffer`() {
        assertFails { suite.checkEmptyBufferIsEmpty(BrokenEngine(silenceText = "you")) }
    }

    @Test
    fun `close check rejects an engine whose second close throws`() {
        assertFails { suite.checkCloseTwiceDoesNotThrow(BrokenEngine(closeTwiceThrows = true)) }
    }

    @Test
    fun `use-after-close check rejects an engine that keeps decoding after close`() {
        assertFails { suite.checkDecodingAfterCloseFails(BrokenEngine(decodesAfterClose = true)) }
    }

    @Test
    fun `option check rejects an engine that throws on a valid option set`() {
        assertFails { suite.checkAcceptsValidOptions(BrokenEngine(rejectsOptions = true)) }
    }

    @Test
    fun `the checks pass on a conforming engine`() {
        val engine = FakeSttEngine()
        suite.checkSilenceIsEmpty(engine)
        suite.checkEmptyBufferIsEmpty(engine)
        suite.checkAcceptsValidOptions(engine)
        suite.checkCloseTwiceDoesNotThrow(engine)
        suite.checkDecodingAfterCloseFails(FakeSttEngine())
    }

    /**
     * One engine with a switch per violation. Each switch breaks exactly one rule
     * of [SttEngine]; with every switch off it behaves like the fake.
     */
    private class BrokenEngine(
        private val silenceText: String = "",
        private val closeTwiceThrows: Boolean = false,
        private val decodesAfterClose: Boolean = false,
        private val rejectsOptions: Boolean = false,
    ) : SttEngine {
        override val id: String = "broken"
        private var closed = false
        private var closeCalls = 0

        override fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm, opts)

        override fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm, opts)

        override fun close() {
            closeCalls++
            if (closeCalls > 1 && closeTwiceThrows) throw IllegalStateException("closed twice")
            closed = true
        }

        private fun decode(pcm: FloatArray, opts: DecodeOptions): Transcript {
            if (closed && !decodesAfterClose) throw IllegalStateException("used after close")
            if (rejectsOptions && opts.sampleRate != DecodeOptions.DEFAULT_SAMPLE_RATE) {
                throw IllegalArgumentException("unsupported sample rate")
            }
            if (pcm.all { it == 0f }) return Transcript(text = silenceText)
            return Transcript(text = "speech")
        }
    }
}
