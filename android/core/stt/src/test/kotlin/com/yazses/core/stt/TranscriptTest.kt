package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class TranscriptTest {

    @Test
    fun `a segment must not end before it starts`() {
        assertFailsWith<IllegalArgumentException> {
            Transcript.Segment(startSec = 2.0, endSec = 1.0, text = "x")
        }
    }

    @Test
    fun `a segment must not start before the buffer does`() {
        assertFailsWith<IllegalArgumentException> {
            Transcript.Segment(startSec = -0.5, endSec = 1.0, text = "x")
        }
    }

    @Test
    fun `segment times must be finite`() {
        for (bad in listOf(Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY)) {
            assertFailsWith<IllegalArgumentException>("endSec $bad") {
                Transcript.Segment(startSec = 0.0, endSec = bad, text = "x")
            }
            assertFailsWith<IllegalArgumentException>("startSec $bad") {
                Transcript.Segment(startSec = bad, endSec = 1.0, text = "x")
            }
        }
    }

    @Test
    fun `a zero-length segment is allowed`() {
        Transcript.Segment(startSec = 1.0, endSec = 1.0, text = "")
    }

    @Test
    fun `confidence must be within 0 to 1 when it is reported`() {
        for (ok in listOf(0f, 0.5f, 1f)) {
            Transcript.Segment(startSec = 0.0, endSec = 1.0, text = "x", confidence = ok)
        }
        Transcript.Segment(startSec = 0.0, endSec = 1.0, text = "x", confidence = null)
        for (bad in listOf(-0.01f, 1.01f, Float.NaN, Float.POSITIVE_INFINITY)) {
            assertFailsWith<IllegalArgumentException>("confidence $bad") {
                Transcript.Segment(startSec = 0.0, endSec = 1.0, text = "x", confidence = bad)
            }
        }
    }

    @Test
    fun `a transcript carries per-segment timings when the engine reports them`() {
        val segment = Transcript.Segment(startSec = 0.0, endSec = 1.5, text = "hi", confidence = 0.9f)
        val transcript = Transcript(text = "hi", segments = listOf(segment))
        assertEquals(listOf(segment), transcript.segments)
    }
}
