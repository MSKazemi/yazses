package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private val AUDIO = FloatArray(16) { 0.5f }

/**
 * A secure focus change during an active capture aborts it: the audio is discarded, nothing
 * is decoded or delivered, and the next tap in a normal field is a start (architecture.md §6:
 * mic disabled in a password field).
 */
class SecureAbortTest {

    private val refused = SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)
    private val abort = listOf<SessionEffect>(SessionEffect.StopCapture, refused)

    // ---- HoldSession: the abort itself -----------------------------------------

    @Test
    fun `a secure tick during hold capture aborts, discards the audio, and goes idle`() {
        val session = HoldSession(CalibratedRmsGate()) // 500 ms debounce
        session.onPress(0L)
        session.onTick(500L) // Capturing
        assertEquals(abort, session.onTick(600L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, session.state)
        // The release that follows finds nothing to decode.
        assertEquals(emptyList(), session.onRelease(700L, AUDIO))
    }

    @Test
    fun `a secure press during hold capture aborts, discards the audio, and goes idle`() {
        val session = HoldSession(CalibratedRmsGate())
        session.onPress(0L)
        session.onTick(500L)
        assertEquals(abort, session.onPress(600L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onRelease(700L, AUDIO))
    }

    @Test
    fun `a secure press during toggle capture stops it without decoding`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L) // StartCapture
        assertEquals(abort, session.onPress(500L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onRelease(600L, AUDIO))
    }

    @Test
    fun `a secure tick during toggle capture aborts without decoding`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L)
        assertEquals(abort, session.onTick(500L, fieldIsSecure = true))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a normal press after a secure abort starts a fresh capture`() {
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        session.onPress(0L)
        session.onTick(500L, fieldIsSecure = true)
        session.onRelease(600L, AUDIO)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), session.onPress(700L))
    }

    // ---- ActivationDriver: source resynchronised, both modes ---------------------

    @Test
    fun `hold mode - a secure focus change mid-capture aborts, and the next normal press is a start`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onTick(500L))
        assertEquals(abort, driver.onTick(600L, snapshot = { AUDIO }, fieldIsSecure = true))
        driver.onRelease(700L, AUDIO)
        driver.onPress(800L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onTick(1_300L))
    }

    @Test
    fun `toggle mode - a secure focus change mid-capture aborts, and the next normal tap is a start`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        assertEquals(abort, driver.onTick(500L, snapshot = { AUDIO }, fieldIsSecure = true))
        driver.onRelease(600L, AUDIO)
        // A stale source would read this tap as a stop, and nothing would start.
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(800L))
    }

    @Test
    fun `toggle mode - a secure tap mid-capture stops without decoding, and the next normal tap starts`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource())
        driver.onPress(0L)
        assertEquals(abort, driver.onPress(500L, fieldIsSecure = true, snapshot = { AUDIO }))
        driver.onRelease(600L, AUDIO)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onPress(800L))
    }

    @Test
    fun `the cap stop arriving in a secure field aborts and does not decode`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource(1_000L))
        driver.onPress(0L)
        val effects = driver.onTick(1_000L, snapshot = { AUDIO }, fieldIsSecure = true)
        assertEquals(abort, effects)
        assertTrue(effects.none { it is SessionEffect.Decode }, "decoded in a secure field: $effects")
    }

    @Test
    fun `the cap stop reached in a secure tap aborts and does not decode`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate(), debounceMs = 0L), ToggleSource(1_000L))
        driver.onPress(0L)
        val effects = driver.onPress(1_000L, fieldIsSecure = true, snapshot = { AUDIO })
        assertTrue(effects.none { it is SessionEffect.Decode }, "decoded in a secure field: $effects")
        assertEquals(refused, effects.last())
    }

    // ---- key still down after a refusal (hold) ---------------------------------

    @Test
    fun `after a refusal a key-repeat does not start a new hold until the key is released`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        assertEquals(listOf(refused), driver.onPress(200L, fieldIsSecure = true))
        // Key-repeat, now in a normal field, with the key still physically down.
        assertEquals(emptyList(), driver.onPress(300L))
        assertEquals(emptyList(), driver.onTick(900L))
        assertEquals(emptyList(), driver.onTick(1_500L))
        driver.onRelease(1_600L, AUDIO)
        // A new press after the release is a new burst.
        driver.onPress(1_700L)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), driver.onTick(2_200L))
    }

    @Test
    fun `a secure tick during hold debounce also keeps the key-repeat refused until release`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L)
        assertEquals(listOf(refused), driver.onTick(600L, fieldIsSecure = true))
        assertEquals(emptyList(), driver.onPress(650L))
        assertEquals(emptyList(), driver.onTick(1_200L))
    }

    @Test
    fun `a refused secure press cleared by release is not held against the next press`() {
        val driver = ActivationDriver(HoldSession(CalibratedRmsGate()), HoldKeySource())
        driver.onPress(0L, fieldIsSecure = true)
        driver.onRelease(100L, AUDIO)
        driver.onPress(200L)
        assertFalse(driver.onTick(700L).isEmpty(), "the press after release must start a burst")
    }
}
