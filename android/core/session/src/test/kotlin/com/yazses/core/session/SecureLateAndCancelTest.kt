package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

private val LOUD_SAMPLES = FloatArray(16) { 0.5f }

/** Second review of PR #678: late results in a secure field, cancel, and the secure end cause. */
class SecureLateAndCancelTest {

    private val refused = SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)
    private val abort = listOf<SessionEffect>(SessionEffect.StopCapture, refused)

    // ---- 1. a late decode result that reports a secure field aborts a live capture ----

    @Test
    fun `a late secure decode result during a new hold capture aborts it and nothing is decoded`() {
        val s = HoldSession(CalibratedRmsGate()) // 500 ms debounce
        s.onPress(0L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), s.onTick(500L))
        assertEquals(abort, s.onDecoded("x", fieldIsSecure = true, nowMs = 600L))
        assertEquals(SessionState.Idle, s.state)
        assertEquals(emptyList(), s.onRelease(1_500L, LOUD_SAMPLES))
    }

    @Test
    fun `a late secure decode result during a new toggle capture aborts it and nothing is decoded`() {
        val s = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        s.onPress(0L)
        assertEquals(abort, s.onDecoded("x", fieldIsSecure = true, nowMs = 600L))
        assertEquals(SessionState.Idle, s.state)
    }

    @Test
    fun `a late secure decode failure or delivery during capture aborts it too`() {
        val failed = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        failed.onPress(0L)
        assertEquals(abort, failed.onDecodeFailed(600L, fieldIsSecure = true))

        val delivered = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        delivered.onPress(0L)
        assertEquals(abort, delivered.onDelivered(inserted = true, nowMs = 600L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, delivered.state)
    }

    @Test
    fun `a late normal-field decode result during capture is still refused as not decoding`() {
        val s = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        s.onPress(0L)
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.NOT_DECODING)),
            s.onDecoded("x", fieldIsSecure = false, nowMs = 600L),
        )
        assertEquals(SessionState.Capturing, s.state)
    }

    @Test
    fun `a late secure decode result through the hold driver aborts the capture`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        driver.onTick(500L)
        assertEquals(abort, driver.onDecoded("x", fieldIsSecure = true, nowMs = 600L))
        assertEquals(emptyList(), driver.onRelease(1_500L, LOUD_SAMPLES))
    }

    // ---- 2. cancel() clears the key-repeat block -----------------------------------

    @Test
    fun `hold - cancel after a refused press lets the next press start`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        assertEquals(listOf(refused), driver.onPress(0L, fieldIsSecure = true))
        driver.cancel(100L)
        assertEquals(emptyList(), driver.onPress(200L))
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onTick(800L))
    }

    @Test
    fun `toggle - cancel after a secure abort lets the next tap start`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        assertEquals(abort, driver.onTick(100L, snapshot = { LOUD_SAMPLES }, fieldIsSecure = true))
        driver.cancel(200L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(300L))
    }

    // ---- 3a. the secure abort sets lastEndCause ------------------------------------

    @Test
    fun `a secure tick that aborts a toggle capture sets lastEndCause to SECURE_ABORT`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        driver.onTick(100L, snapshot = { LOUD_SAMPLES }, fieldIsSecure = true)
        assertEquals(EndCause.SECURE_ABORT, driver.lastEndCause)
    }

    @Test
    fun `a secure tap that stops a toggle capture sets lastEndCause to SECURE_ABORT`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        driver.onPress(100L, fieldIsSecure = true, snapshot = { LOUD_SAMPLES })
        assertEquals(EndCause.SECURE_ABORT, driver.lastEndCause)
    }

    @Test
    fun `a secure abort during the hold debounce sets lastEndCause to SECURE_ABORT`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        driver.onTick(200L, fieldIsSecure = true)
        assertEquals(EndCause.SECURE_ABORT, driver.lastEndCause)
    }

    @Test
    fun `a late secure decode result that aborts a capture sets lastEndCause to SECURE_ABORT`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        driver.onDecoded("x", fieldIsSecure = true, nowMs = 100L)
        assertEquals(EndCause.SECURE_ABORT, driver.lastEndCause)
    }

    @Test
    fun `a refused press with no burst running does not set SECURE_ABORT`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L, fieldIsSecure = true)
        assertNull(driver.lastEndCause)
    }
}
