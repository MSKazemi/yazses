package com.yazses.core.session

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ActivationSourceTest {

    // ---- ToggleSource (ADR-MOB-004 §2 toggle mode, §7 seam) -------------------

    @Test
    fun `the default toggle cap is the shared desktop max_record_seconds of 300 s`() {
        // ADR-MOB-004 erratum (2026-10): the cap is [audio] max_record_seconds, desktop default 300.
        assertEquals(300_000L, ToggleSource.DEFAULT_MAX_BURST_MS)
    }

    @Test
    fun `the first activation starts capture`() {
        val source = ToggleSource()
        assertEquals(listOf<ActivationEdge>(ActivationEdge.HoldStart), source.onHoldStart(0L))
    }

    @Test
    fun `the second activation stops capture and is not a new start`() {
        val source = ToggleSource()
        source.onHoldStart(0L)
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.SECOND_ACTIVATION)),
            source.onHoldStart(2_000L),
        )
    }

    @Test
    fun `a third activation starts a new capture`() {
        val source = ToggleSource()
        source.onHoldStart(0L)
        source.onHoldStart(2_000L)
        assertEquals(listOf<ActivationEdge>(ActivationEdge.HoldStart), source.onHoldStart(3_000L))
    }

    @Test
    fun `releasing the key does nothing in toggle mode`() {
        val source = ToggleSource()
        source.onHoldStart(0L)
        assertEquals(emptyList(), source.onHoldEnd(500L))
        // Still running: the next activation is the stop.
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.SECOND_ACTIVATION)),
            source.onHoldStart(2_000L),
        )
    }

    @Test
    fun `one millisecond short of the cap does not stop the capture`() {
        val source = ToggleSource(maxBurstMs = 1_000L)
        source.onHoldStart(0L)
        assertEquals(emptyList(), source.onTick(999L))
    }

    @Test
    fun `exactly the cap force-stops the capture with CAP_REACHED`() {
        val source = ToggleSource(maxBurstMs = 1_000L)
        source.onHoldStart(0L)
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.CAP_REACHED)),
            source.onTick(1_000L),
        )
    }

    @Test
    fun `the cap is measured from the activation, not from the last tick`() {
        val source = ToggleSource(maxBurstMs = 1_000L)
        source.onHoldStart(400L)
        assertEquals(emptyList(), source.onTick(1_399L))
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.CAP_REACHED)),
            source.onTick(1_400L),
        )
    }

    @Test
    fun `ticks after a cap stop emit nothing, and a new activation starts a fresh cap`() {
        val source = ToggleSource(maxBurstMs = 1_000L)
        source.onHoldStart(0L)
        source.onTick(1_000L)
        assertEquals(emptyList(), source.onTick(5_000L))
        assertEquals(listOf<ActivationEdge>(ActivationEdge.HoldStart), source.onHoldStart(6_000L))
        assertEquals(emptyList(), source.onTick(6_999L))
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.CAP_REACHED)),
            source.onTick(7_000L),
        )
    }

    @Test
    fun `ticks while idle emit nothing`() {
        assertEquals(emptyList(), ToggleSource(maxBurstMs = 1_000L).onTick(10_000L))
    }

    @Test
    fun `reset returns toggle to idle so the next activation starts`() {
        val source = ToggleSource()
        source.onHoldStart(0L)
        source.reset()
        assertEquals(listOf<ActivationEdge>(ActivationEdge.HoldStart), source.onHoldStart(10L))
    }

    @Test
    fun `a non-positive cap is rejected`() {
        assertTrue(runCatching { ToggleSource(maxBurstMs = 0L) }.isFailure)
    }

    // ---- HoldKeySource (ADR-MOB-004 §1, hold is the default) ------------------

    @Test
    fun `key down starts and key up ends a hold`() {
        val source = HoldKeySource()
        assertEquals(listOf<ActivationEdge>(ActivationEdge.HoldStart), source.onHoldStart(0L))
        assertEquals(
            listOf<ActivationEdge>(ActivationEdge.HoldEnd(EndCause.KEY_UP)),
            source.onHoldEnd(900L),
        )
    }

    @Test
    fun `a key-up with no key-down emits nothing`() {
        assertEquals(emptyList(), HoldKeySource().onHoldEnd(10L))
    }

    @Test
    fun `a key-repeat while held emits no second start`() {
        val source = HoldKeySource()
        source.onHoldStart(0L)
        assertEquals(emptyList(), source.onHoldStart(300L))
    }

    @Test
    fun `hold never force-stops on a tick`() {
        val source = HoldKeySource()
        source.onHoldStart(0L)
        assertEquals(emptyList(), source.onTick(10_000_000L))
    }

    @Test
    fun `reset forgets a held key so the next key-up is ignored`() {
        val source = HoldKeySource()
        source.onHoldStart(0L)
        source.reset()
        assertEquals(emptyList(), source.onHoldEnd(100L))
    }
}
