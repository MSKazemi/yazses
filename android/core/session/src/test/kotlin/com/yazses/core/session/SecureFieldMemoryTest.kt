package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private val LOUD_AUDIO = FloatArray(16) { 0.5f }

/** HoldSession must never start a capture in a secure field, whichever path would start it. */
class SecureFieldMemoryTest {

    private val secureRefused = SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)

    @Test
    fun `a queued normal-field tap is dropped, not replayed, when the field is secure at replay`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L) // StartCapture
        session.onRelease(2_000L, LOUD_AUDIO) // Decoding
        assertEquals(emptyList(), session.onPress(2_100L)) // queued, normal field
        assertEquals(listOf(secureRefused), session.onPress(2_200L, fieldIsSecure = true))

        val effects = session.onDecoded("hi", fieldIsSecure = true, nowMs = 2_300L)

        assertTrue(
            effects.none { it == SessionEffect.StartCapture },
            "the queued tap opened the mic in a secure field: $effects",
        )
        assertTrue(effects.contains(secureRefused), "the dropped tap must report a refusal: $effects")
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a queued tap is dropped when decode fails in a secure field`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L)
        session.onRelease(2_000L, LOUD_AUDIO)
        session.onPress(2_100L)
        val effects = session.onDecodeFailed(2_200L, fieldIsSecure = true)
        assertTrue(effects.none { it == SessionEffect.StartCapture }, "got $effects")
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a queued tap is replayed in a normal field`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L)
        session.onRelease(2_000L, LOUD_AUDIO)
        session.onPress(2_100L)
        session.onDecoded("hi", fieldIsSecure = false, nowMs = 2_200L)
        val replayed = session.onDelivered(inserted = true, nowMs = 2_300L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), replayed)
    }

    @Test
    fun `a secure observation during Holding cancels the pending burst and nothing starts`() {
        val session = HoldSession(CalibratedRmsGate()) // default 500 ms debounce
        session.onPress(0L)
        assertEquals(listOf(secureRefused), session.onPress(200L, fieldIsSecure = true))
        assertEquals(emptyList(), session.onTick(500L))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a tick that reports a secure field during Holding cancels the pending burst`() {
        val session = HoldSession(CalibratedRmsGate())
        session.onPress(0L)
        assertEquals(listOf(secureRefused), session.onTick(500L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onTick(600L))
    }

    @Test
    fun `a normal press after a secure refusal starts a fresh burst`() {
        val session = HoldSession(CalibratedRmsGate())
        session.onPress(0L, fieldIsSecure = true)
        session.onPress(100L) // normal field again
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), session.onTick(600L))
    }

    @Test
    fun `isIdle is true after cancel and false while a burst is held`() {
        val session = HoldSession(CalibratedRmsGate())
        session.onPress(0L)
        assertEquals(false, session.isIdle)
        session.cancel(10L)
        assertEquals(true, session.isIdle)
    }

    @Test
    fun `the debounce is readable from the session`() {
        assertEquals(500L, HoldSession(CalibratedRmsGate()).debounceMs)
    }
}
