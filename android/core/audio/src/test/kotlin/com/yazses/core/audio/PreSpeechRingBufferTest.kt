package com.yazses.core.audio

import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class PreSpeechRingBufferTest {

    private fun buffer(ms: Int = 10, rate: Int = 1000) = PreSpeechRingBuffer(ms, rate)

    @Test
    fun `an untouched buffer contributes nothing`() {
        assertContentEquals(FloatArray(0), buffer().get())
    }

    @Test
    fun `a partially filled buffer returns only what it has`() {
        val b = buffer()                       // capacity 10
        b.push(floatArrayOf(1f, 2f, 3f))
        assertContentEquals(floatArrayOf(1f, 2f, 3f), b.get())
    }

    @Test
    fun `the oldest samples fall off once it wraps`() {
        val b = buffer()                       // capacity 10
        b.push(FloatArray(8) { (it + 1).toFloat() })   // 1..8
        b.push(floatArrayOf(9f, 10f, 11f, 12f))        // wraps
        // Oldest first, and the two earliest samples are gone.
        assertContentEquals((3..12).map { it.toFloat() }.toFloatArray(), b.get())
    }

    @Test
    fun `a chunk larger than the window keeps only its tail`() {
        val b = buffer()                       // capacity 10
        b.push(FloatArray(25) { (it + 1).toFloat() })
        assertContentEquals((16..25).map { it.toFloat() }.toFloatArray(), b.get())
    }

    /**
     * The reason this class exists: audio that starts partway into the burst
     * still carries the leading word once the padding is prepended.
     */
    @Test
    fun `padding recovers a word that began before the key was pressed`() {
        val b = PreSpeechRingBuffer(paddingMs = 50, sampleRate = 1000)   // 50 samples
        val leadingWord = FloatArray(50) { 0.5f }
        b.push(leadingWord)

        val captured = FloatArray(100) { 0.4f }
        val padded = b.prependPadding(captured)

        assertEquals(150, padded.size, "the leading word must not be lost")
        assertTrue(padded.take(50).all { it == 0.5f }, "padding comes first, in order")
        assertContentEquals(captured, padded.copyOfRange(50, 150))
    }

    @Test
    fun `with no padding configured the audio passes through untouched`() {
        val b = PreSpeechRingBuffer(paddingMs = 0, sampleRate = 16_000)
        val audio = floatArrayOf(1f, 2f, 3f)
        assertContentEquals(audio, b.prependPadding(audio))
    }

    @Test
    fun `clearing discards what was buffered`() {
        val b = buffer()
        b.push(floatArrayOf(1f, 2f, 3f))
        b.clear()
        assertContentEquals(FloatArray(0), b.get())
    }
}
