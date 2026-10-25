package com.yazses.core.stt

/**
 * A scripted reference engine for tests: returns [scripted] for any non-silent buffer
 * and [Transcript.EMPTY] for an all-zero buffer, the way a well-behaved gate would.
 *
 * It implements the [SttEngine.close] contract exactly: the first close releases
 * the (simulated) resources and later closes do nothing, so [releaseCount] is 0
 * before close and 1 after it, however many times close is called. Decoding after
 * close throws [IllegalStateException].
 */
class FakeSttEngine(
    override val id: String = "fake",
    private val scripted: String = "hello world",
) : SttEngine {
    /** How many times the simulated native resources were released. Never above 1. */
    var releaseCount: Int = 0
        private set

    val isClosed: Boolean get() = releaseCount > 0

    override fun transcribe(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun decodeWindow(pcm: FloatArray, opts: DecodeOptions): Transcript = decode(pcm)

    override fun close() {
        if (isClosed) return
        releaseCount++
    }

    private fun decode(pcm: FloatArray): Transcript {
        check(!isClosed) { "engine $id used after close()" }
        if (pcm.all { it == 0f }) return Transcript.EMPTY
        return Transcript(text = scripted)
    }
}
