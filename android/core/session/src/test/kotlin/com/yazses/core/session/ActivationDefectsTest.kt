package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

private val LOUD = FloatArray(16) { 0.5f }
private val SILENT = FloatArray(16)

/** Regression tests for the independent review of PR #678. */
class ActivationDefectsTest {

    private fun toggle(maxBurstMs: Long = ToggleSource.DEFAULT_MAX_BURST_MS): ActivationDriver =
        ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource(maxBurstMs))

    private val secureRefused = SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)

    // ---- 1. queued tap in a secure field; source resynchronised ------------------

    @Test
    fun `a queued tap cannot open the mic in a secure field, and the next tap is a start`() {
        val driver = toggle()
        driver.onPress(0L) // start
        driver.onPress(2_000L, snapshot = { LOUD }) // stop -> Decoding
        assertEquals(emptyList(), driver.onPress(2_100L)) // queued, normal field
        assertEquals(listOf(secureRefused), driver.onPress(2_200L, fieldIsSecure = true))
        driver.onRelease(2_250L, SILENT) // the key comes up: a refused press is released once

        val decoded = driver.onDecoded("hi", fieldIsSecure = true, nowMs = 2_300L)
        assertTrue(decoded.none { it == SessionEffect.StartCapture }, "got $decoded")

        // The source must not still think it is running: the next tap is a start.
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(2_400L))
    }

    // ---- 2. secure observation during Holding (hold path, default debounce) -----

    @Test
    fun `a hold repeated into a secure field never starts capture on the debounce`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        assertEquals(listOf(secureRefused), driver.onPress(200L, fieldIsSecure = true))
        assertEquals(emptyList(), driver.onTick(500L))
    }

    // ---- 3. the end cause reaches the UI ----------------------------------------

    @Test
    fun `a key-up sets lastEndCause to KEY_UP`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), HoldKeySource())
        driver.onPress(0L)
        driver.onRelease(900L, LOUD)
        assertEquals(EndCause.KEY_UP, driver.lastEndCause)
    }

    @Test
    fun `a second tap sets lastEndCause to SECOND_ACTIVATION`() {
        val driver = toggle()
        driver.onPress(0L)
        driver.onPress(2_000L, snapshot = { LOUD })
        assertEquals(EndCause.SECOND_ACTIVATION, driver.lastEndCause)
    }

    @Test
    fun `the cap sets lastEndCause to CAP_REACHED`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        driver.onTick(1_000L, snapshot = { LOUD })
        assertEquals(EndCause.CAP_REACHED, driver.lastEndCause)
    }

    @Test
    fun `lastEndCause is cleared by the next start`() {
        val driver = toggle()
        driver.onPress(0L)
        driver.onPress(2_000L, snapshot = { LOUD })
        driver.onDecoded("hi", fieldIsSecure = false, nowMs = 2_100L)
        driver.onDelivered(inserted = true, nowMs = 2_200L)
        driver.onPress(3_000L)
        assertNull(driver.lastEndCause)
    }

    // ---- 4a. toggle requires a debounce of zero -----------------------------------

    @Test
    fun `a toggle source on a session with a non-zero debounce is rejected with a clear message`() {
        val failure = assertFailsWith<IllegalArgumentException> {
            ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 500L), ToggleSource())
        }
        assertTrue(failure.message.orEmpty().contains("debounceMs = 0"), "message was: ${failure.message}")
    }

    // ---- 4b. a stop tap after the cap, with no tick in between -------------------

    @Test
    fun `a stop tap one millisecond before the cap is a second activation`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        driver.onPress(999L, snapshot = { LOUD })
        assertEquals(EndCause.SECOND_ACTIVATION, driver.lastEndCause)
    }

    @Test
    fun `a stop tap exactly at the cap with no tick is reported as CAP_REACHED and decodes the audio`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        val audio = LOUD
        val effects = driver.onPress(1_000L, snapshot = { audio })
        assertEquals(EndCause.CAP_REACHED, driver.lastEndCause)
        assertEquals(SessionEffect.StopCapture, effects[0])
        assertSame(audio, assertIs<SessionEffect.Decode>(effects[1]).samples)
    }

    @Test
    fun `the toggle source reports CAP_REACHED on a tap at the cap, not one millisecond before`() {
        val before = ToggleSource(maxBurstMs = 1_000L)
        before.onHoldStart(0L)
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.SECOND_ACTIVATION)),
            before.onHoldStart(999L),
        )
        val at = ToggleSource(maxBurstMs = 1_000L)
        at.onHoldStart(0L)
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.CAP_REACHED)),
            at.onHoldStart(1_000L),
        )
    }

    // ---- 4c. session.cancel() called directly must not leave the source stale ----

    @Test
    fun `after a direct session cancel, one tap is a start`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        val driver = ActivationDriver(session, ToggleSource())
        driver.onPress(0L) // running
        session.cancel(500L) // bypasses the driver
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(1_000L))
    }

    // ---- 4d. a secure-field stop tap while capturing still stops -----------------

    @Test
    fun `a secure-field tap while toggle capture runs stops it and does not decode`() {
        // Changed from "still stops it, then decodes": the secure observation that stops the
        // burst is the same one that forbids delivery, so the audio is discarded.
        val driver = toggle()
        driver.onPress(0L)
        val effects = driver.onPress(2_000L, fieldIsSecure = true, snapshot = { LOUD })
        assertEquals(listOf(SessionEffect.StopCapture, secureRefused), effects)
    }
}
