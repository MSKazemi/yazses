package com.yazses.core.session

import com.yazses.core.vad.CalibratedRmsGate
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Time is a plain number the test moves by hand. Nothing here reads a real clock. */
private class FakeClock(var nowMs: Long = 0L) {
    fun advance(ms: Long): Long {
        nowMs += ms
        return nowMs
    }
}

private val LOUD = FloatArray(16) { 0.5f }
private val SILENT = FloatArray(16)

class HoldSessionTest {

    private val debounce = HoldSession.DEFAULT_DEBOUNCE_MS
    private fun session() = HoldSession(CalibratedRmsGate(), debounce)

    @Test
    fun `the default debounce is the desktop hold threshold of 500 ms`() {
        assertEquals(500L, HoldSession.DEFAULT_DEBOUNCE_MS)
    }

    @Test
    fun `one millisecond short of the debounce starts no capture`() {
        val session = session()
        val clock = FakeClock()
        session.onPress(clock.nowMs)
        assertEquals(emptyList(), session.onTick(clock.advance(debounce - 1)))
        assertEquals(SessionState.Holding(0L), session.state)
        // A release one millisecond short of the debounce is a tap: nothing runs at all.
        assertEquals(emptyList(), session.onRelease(clock.advance(0), LOUD))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `exactly the debounce starts capture`() {
        val session = session()
        val clock = FakeClock()
        session.onPress(clock.nowMs)
        val effects = session.onTick(clock.advance(debounce))
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), effects)
        assertEquals(SessionState.Capturing, session.state)
    }

    @Test
    fun `a release past the debounce with no tick never started capture so nothing is decoded`() {
        val session = session()
        session.onPress(0L)
        // No onTick arrived, so the caller recorded no audio. The burst must not decode.
        val effects = session.onRelease(debounce, LOUD)
        assertEquals(listOf<SessionEffect>(SessionEffect.NothingHeard), effects)
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a release one millisecond short with no tick is a tap`() {
        val session = session()
        session.onPress(0L)
        assertEquals(emptyList(), session.onRelease(debounce - 1, LOUD))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a key-repeat while holding does not restart the debounce`() {
        val session = session()
        session.onPress(0L)
        session.onPress(300L) // auto-repeat from the OS
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), session.onTick(debounce))
    }

    @Test
    fun `a silent burst delivers nothing and reports nothing heard`() {
        val session = session()
        session.onPress(0L)
        session.onTick(debounce)
        val effects = session.onRelease(900L, SILENT)
        assertEquals(listOf<SessionEffect>(SessionEffect.StopCapture, SessionEffect.NothingHeard), effects)
        assertEquals(SessionState.Idle, session.state)
        assertNull(session.undo.undo())
    }

    @Test
    fun `the voice gate is injected and decides what counts as silence`() {
        val session = HoldSession({ true }, debounce) // a gate that calls everything silent
        session.onPress(0L)
        session.onTick(debounce)
        val effects = session.onRelease(900L, LOUD)
        assertEquals(SessionEffect.NothingHeard, effects.last())
    }

    @Test
    fun `a burst that clears the gate is decoded, delivered and undoable once`() {
        val session = session()
        session.onPress(0L)
        session.onTick(debounce)
        assertIs<SessionEffect.Decode>(session.onRelease(900L, LOUD).last())
        assertEquals(SessionState.Decoding, session.state)

        val delivered = session.onDecoded("hello", fieldIsSecure = false, nowMs = 950L)
        assertEquals("hello", assertIs<SessionEffect.Deliver>(delivered.single()).text)
        assertEquals(SessionState.Delivering("hello"), session.state)

        assertEquals(emptyList(), session.onDelivered(inserted = true, nowMs = 960L))
        assertEquals(SessionState.Idle, session.state)

        assertEquals(5, session.undo.undo()?.length)
        assertNull(session.undo.undo())
    }

    @Test
    fun `text is refused in a password field and nothing is undoable`() {
        val session = session()
        runToDecoding(session)
        val effects = session.onDecoded("hunter2", fieldIsSecure = true, nowMs = 950L)
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)),
            effects,
        )
        assertEquals(SessionState.Idle, session.state)
        assertNull(session.undo.undo())
    }

    @Test
    fun `a blank decode is refused, not typed`() {
        val session = session()
        runToDecoding(session)
        val effects = session.onDecoded("   ", fieldIsSecure = false, nowMs = 950L)
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.BLANK_TEXT)),
            effects,
        )
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a decoder failure returns to idle and delivers nothing`() {
        val session = session()
        runToDecoding(session)
        assertEquals(listOf<SessionEffect>(SessionEffect.DecodeFailed), session.onDecodeFailed(950L))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a clipboard fallback is not undoable because nothing was inserted`() {
        val session = session()
        runToDecoding(session)
        session.onDecoded("hello", fieldIsSecure = false, nowMs = 950L)
        session.onDelivered(inserted = false, nowMs = 960L)
        assertNull(session.undo.undo())
    }

    @Test
    fun `a new insert replaces the one before it for undo`() {
        val session = session()
        runToDecoding(session)
        session.onDecoded("first", fieldIsSecure = false, nowMs = 950L)
        session.onDelivered(inserted = true, nowMs = 960L)
        runToDecoding(session, start = 1_000L)
        session.onDecoded("second!", fieldIsSecure = false, nowMs = 1_950L)
        session.onDelivered(inserted = true, nowMs = 1_960L)
        assertEquals(7, session.undo.undo()?.length)
    }

    @Test
    fun `a press during decoding is queued and replayed when the decode ends`() {
        val session = session()
        runToDecoding(session)
        assertEquals(emptyList(), session.onPress(1_000L))
        assertEquals(emptyList(), session.onRelease(1_100L, SILENT))
        assertEquals(SessionState.Decoding, session.state)

        session.onDecoded("hi", fieldIsSecure = false, nowMs = 1_200L)
        val replayed = session.onDelivered(inserted = true, nowMs = 1_300L)

        // Replayed at 1300 ms, both events together: a tap, so no capture starts.
        assertEquals(emptyList(), replayed)
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a queued key-repeat is not queued twice`() {
        val session = session()
        runToDecoding(session)
        session.onPress(1_000L)
        session.onPress(1_050L)
        session.onPress(1_100L)
        session.onRelease(1_200L, SILENT)
        session.onDecoded("hi", fieldIsSecure = false, nowMs = 1_250L)
        val replayed = session.onDelivered(inserted = true, nowMs = 1_300L)
        assertEquals(emptyList(), replayed)
        assertTrue(session.state == SessionState.Idle)
    }

    @Test
    fun `a release when nothing is running is ignored`() {
        val session = session()
        assertEquals(emptyList(), session.onRelease(10L, LOUD))
        assertEquals(SessionState.Idle, session.state)
    }

    @Test
    fun `a negative debounce is rejected`() {
        val failure = runCatching { HoldSession(CalibratedRmsGate(), debounceMs = -1L) }
        assertTrue(failure.isFailure)
    }

    @Test
    fun `cancel stops a stuck capture when the key-up was lost, and the next press works`() {
        val session = session()
        session.onPress(0L)
        session.onTick(debounce) // Capturing; the key-up never arrives
        assertEquals(listOf<SessionEffect>(SessionEffect.StopCapture), session.cancel(600L))
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onPress(10_000L))
        assertEquals(SessionState.Holding(10_000L), session.state)
        assertEquals(listOf<SessionEffect>(SessionEffect.StartCapture), session.onTick(10_000L + debounce))
    }

    @Test
    fun `cancel frees a decode that never reports back, and its late result is ignored`() {
        val session = session()
        runToDecoding(session)
        session.onPress(1_000L) // queued behind the stuck decode
        assertEquals(emptyList(), session.cancel(1_100L))
        assertEquals(SessionState.Idle, session.state)
        // The late result of the cancelled decode must not be delivered, and must not
        // replay the press that was queued before the cancel.
        assertEquals(emptyList(), session.onDecoded("late", fieldIsSecure = false, nowMs = 1_200L))
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onPress(2_000L))
        assertEquals(SessionState.Holding(2_000L), session.state)
    }

    @Test
    fun `cancel returns to idle from delivering and from holding without any effect`() {
        val delivering = session()
        runToDecoding(delivering)
        delivering.onDecoded("hello", fieldIsSecure = false, nowMs = 950L)
        assertEquals(emptyList(), delivering.cancel(960L))
        assertEquals(SessionState.Idle, delivering.state)

        val holding = session()
        holding.onPress(0L)
        assertEquals(emptyList(), holding.cancel(100L))
        assertEquals(SessionState.Idle, holding.state)
    }

    @Test
    fun `alternating presses and releases while stuck cannot grow the queue past its bound`() {
        // Zero debounce so every replayed press starts a capture and every release
        // reports NothingHeard: each queued event then shows up as an effect.
        val session = HoldSession(CalibratedRmsGate(), debounceMs = 0L)
        runToDecoding(session)
        for (i in 0 until 10_000) {
            session.onPress(1_000L + 2 * i)
            session.onRelease(1_001L + 2 * i, SILENT)
        }
        session.onDecoded("hi", fieldIsSecure = false, nowMs = 40_000L)
        val replayed = session.onDelivered(inserted = true, nowMs = 40_100L)
        // Unbounded, all 20,000 events would replay as 30,000 effects.
        assertTrue(
            replayed.size <= 3 * HoldSession.MAX_QUEUED_EVENTS,
            "replayed ${replayed.size} effects; the queue must be bounded",
        )
    }

    @Test
    fun `a secure field refuses the press, starts nothing, and the release delivers nothing`() {
        val session = session()
        assertEquals(
            listOf<SessionEffect>(SessionEffect.Refused(DeliveryGuard.Refusal.SECURE_FIELD)),
            session.onPress(0L, fieldIsSecure = true),
        )
        assertEquals(SessionState.Idle, session.state)
        assertEquals(emptyList(), session.onTick(debounce))
        assertEquals(emptyList(), session.onRelease(debounce + 100L, LOUD))
        assertEquals(SessionState.Idle, session.state)
        assertNull(session.undo.undo())
    }

    @Test
    fun `a clipboard-only burst makes the earlier insert no longer undoable`() {
        val session = session()
        runToDecoding(session)
        session.onDecoded("first", fieldIsSecure = false, nowMs = 950L)
        session.onDelivered(inserted = true, nowMs = 960L)
        runToDecoding(session, start = 1_000L)
        session.onDecoded("second", fieldIsSecure = false, nowMs = 1_950L)
        session.onDelivered(inserted = false, nowMs = 1_960L)
        // Undo would delete the first burst's characters from wherever the cursor now is.
        assertNull(session.undo.undo())
    }

    @Test
    fun `invalidateUndo forgets the last insert, for example after the user typed`() {
        val session = session()
        runToDecoding(session)
        session.onDecoded("hello", fieldIsSecure = false, nowMs = 950L)
        session.onDelivered(inserted = true, nowMs = 960L)
        session.invalidateUndo()
        assertNull(session.undo.undo())
    }

    @Test
    fun `a stray decode while idle is a silent no-op, not an error`() {
        val session = session()
        assertEquals(emptyList(), session.onDecoded("hi", fieldIsSecure = false, nowMs = 0L))
        assertEquals(SessionState.Idle, session.state)
    }

    /** Presses, holds past the debounce, and releases with loud audio: leaves the session Decoding. */
    private fun runToDecoding(session: HoldSession, start: Long = 0L) {
        session.onPress(start)
        session.onTick(start + debounce)
        session.onRelease(start + 900L, LOUD)
        assertEquals(SessionState.Decoding, session.state)
    }
}
