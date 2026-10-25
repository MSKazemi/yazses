package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertSame
import kotlin.test.assertTrue

private val LOUD_AUDIO = FloatArray(16) { 0.5f }
private val SILENT_AUDIO = FloatArray(16)

class ActivationDriverTest {

    // Toggle taps have no debounce (ADR-MOB-004 §1: debounce is the hold semantics),
    // so a toggle session is built with debounceMs = 0.
    private fun toggle(maxBurstMs: Long = ToggleSource.DEFAULT_MAX_BURST_MS): ActivationDriver {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        return ActivationDriver(session, ToggleSource(maxBurstMs))
    }

    @Test
    fun `the first toggle tap starts capture`() {
        val driver = toggle()
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(0L))
    }

    @Test
    fun `the second toggle tap stops capture and decodes the audio it is given`() {
        val driver = toggle()
        driver.onPress(0L)
        val effects = driver.onPress(2_000L, snapshot = { LOUD_AUDIO })
        assertEquals(SessionEffect.StopCapture, effects[0])
        assertSame(LOUD_AUDIO, assertIs<SessionEffect.Decode>(effects[1]).samples)
    }

    @Test
    fun `the cap does not fire one millisecond early`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        assertEquals(emptyList(), driver.onTick(999L, snapshot = { LOUD_AUDIO }))
    }

    @Test
    fun `the cap force-stops at exactly the cap and decodes the audio captured so far`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        val effects = driver.onTick(1_000L, snapshot = { LOUD_AUDIO })
        assertEquals(SessionEffect.StopCapture, effects[0])
        assertSame(LOUD_AUDIO, assertIs<SessionEffect.Decode>(effects[1]).samples)
    }

    @Test
    fun `a silent burst is discarded when the cap stops it`() {
        val driver = toggle(maxBurstMs = 1_000L)
        driver.onPress(0L)
        assertEquals(
            listOf<SessionEffect>(SessionEffect.StopCapture, SessionEffect.NothingHeard),
            driver.onTick(1_000L, snapshot = { SILENT_AUDIO }),
        )
    }

    @Test
    fun `a silent toggle burst stopped by a second tap is discarded`() {
        val driver = toggle()
        driver.onPress(0L)
        assertEquals(
            listOf<SessionEffect>(SessionEffect.StopCapture, SessionEffect.NothingHeard),
            driver.onPress(2_000L, snapshot = { SILENT_AUDIO }),
        )
    }

    @Test
    fun `a toggle tap in a secure field is refused and never starts capture`() {
        val driver = toggle()
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)),
            driver.onPress(0L, fieldIsSecure = true),
        )
        assertEquals(emptyList(), driver.onTick(1_000L))
    }

    @Test
    fun `a refused secure tap does not consume the toggle, so the next normal tap starts`() {
        val driver = toggle()
        driver.onPress(0L, fieldIsSecure = true)
        driver.onRelease(100L, SILENT_AUDIO) // the key comes up before the next tap
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(2_000L))
    }

    @Test
    fun `cancel during toggle capture stops the capture`() {
        val driver = toggle()
        driver.onPress(0L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StopCapture), driver.cancel(500L))
    }

    @Test
    fun `after a cancel the next toggle tap starts a new capture`() {
        val driver = toggle()
        driver.onPress(0L)
        driver.cancel(500L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(1_000L))
    }

    @Test
    fun `a toggle tap while decoding is queued and starts capture when the decode ends`() {
        val driver = toggle()
        driver.onPress(0L)
        assertIs<SessionEffect.Decode>(driver.onPress(2_000L, snapshot = { LOUD_AUDIO }).last())
        assertEquals(emptyList(), driver.onPress(2_100L))

        driver.onDecoded("hi", fieldIsSecure = false, nowMs = 2_200L)
        val afterDelivery = driver.onDelivered(inserted = true, nowMs = 2_300L)
        assertTrue(
            afterDelivery.contains(SessionEffect.StartCapture),
            "the queued tap must start a new capture, got $afterDelivery",
        )
    }

    @Test
    fun `the hold source drives the same session effects after activation`() {
        val session = HoldSession(CalibratedRmsGate())
        val driver = ActivationDriver(session, HoldKeySource())
        assertEquals(emptyList(), driver.onPress(0L))
        assertEquals(emptyList(), driver.onTick(499L))
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onTick(500L))
        val effects = driver.onRelease(900L, LOUD_AUDIO)
        assertEquals(SessionEffect.StopCapture, effects[0])
        assertSame(LOUD_AUDIO, assertIs<SessionEffect.Decode>(effects[1]).samples)
    }

    @Test
    fun `the hold source refuses a secure field the same way the session does`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)),
            driver.onPress(0L, fieldIsSecure = true),
        )
    }
}
