package com.yazses.core.stt

/**
 * A scripted engine for tests: returns [scripted] for any non-silent buffer and
 * [Transcript.EMPTY] for silence, the way a well-behaved gate would. It records
 * [closeCount] and enforces the [SttEngine.close] contract (use after close throws).
 */
class FakeSttEngine(
    override val id: String = "fake",
    private val scripted: String = "hello world",
) : SttEngine {
    var closeCount: Int = 0
        private set
    val isClosed: Boolean get() = closeCount > 0

    override fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun close() {
        closeCount++
    }

    private fun decode(pcm: FloatArray): Transcript {
        check(!isClosed) { "engine $id used after close()" }
        if (pcm.all { it == 0f }) return Transcript.EMPTY
        return Transcript(text = scripted)
    }
}
