package com.yazses.core.vad

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class CalibratedRmsGateTest {

    @Test
    fun `an empty buffer is silence`() {
        // Handing an empty buffer to a recogniser is how a confident
        // hallucination gets typed into someone's document.
        assertTrue(CalibratedRmsGate().isSilent(FloatArray(0)))
    }

    @Test
    fun `ordinary speech clears the default gate`() {
        assertFalse(CalibratedRmsGate().isSilent(floatArrayOf(0.2f, -0.25f, 0.18f, -0.22f)))
    }

    @Test
    fun `room tone is discarded`() {
        assertTrue(CalibratedRmsGate().isSilent(floatArrayOf(0.0001f, -0.0002f, 0.00015f)))
    }

    @Test
    fun `the metric is the mean, not the peak`() {
        // One loud click among fifteen silent samples: peak 0.9, mean 0.056.
        val click = FloatArray(16).also { it[15] = 0.9f }
        assertTrue(CalibratedRmsGate(threshold = 0.1f).isSilent(click), "a door slam is not speech")
    }

    @Test
    fun `sign is ignored`() {
        assertFalse(CalibratedRmsGate().isSilent(floatArrayOf(-0.2f, -0.2f, -0.2f)))
    }

    @Test
    fun `lowering the gate is what makes a quiet voice usable`() {
        val quiet = floatArrayOf(0.0001f, -0.0002f, 0.00015f, -0.0001f)
        assertTrue(CalibratedRmsGate().isSilent(quiet))
        assertFalse(CalibratedRmsGate(threshold = 0.00005f).isSilent(quiet))
    }

    @Test
    fun `exactly at the threshold is delivered, not discarded`() {
        assertFalse(CalibratedRmsGate(threshold = 0.2f).isSilent(floatArrayOf(0.2f, -0.2f)))
    }
}
