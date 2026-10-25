package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** Runs the shared [SttEngineContract] over [FakeSttEngine], plus fake-specific checks. */
class FakeSttEngineContractTest : SttEngineContract() {

    override fun createEngine(): SttEngine = FakeSttEngine()

    @Test
    fun `speech is returned as the engine decoded it`() {
        val engine = FakeSttEngine(scripted = "send the report")
        val speech = FloatArray(4_000) { 0.2f }
        assertEquals("send the report", engine.transcribe(speech, DecodeOptions()).text)
        engine.close()
    }

    @Test
    fun `the fake releases its resources once, however often it is closed`() {
        val engine = FakeSttEngine()
        assertFalse(engine.isClosed)
        engine.close()
        engine.close()
        assertEquals(1, engine.releaseCount)
        assertTrue(engine.isClosed)
    }
}
