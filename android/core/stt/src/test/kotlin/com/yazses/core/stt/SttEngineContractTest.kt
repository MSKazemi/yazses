package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class SttEngineContractTest {

    @Test
    fun `silence yields the empty transcript, never a hallucinated word`() {
        val engine = FakeSttEngine()
        val silence = FloatArray(16_000)
        assertEquals(Transcript.EMPTY, engine.transcribe(silence, DecodeOptions()))
        assertEquals(Transcript.EMPTY, engine.decodeWindow(silence, DecodeOptions()))
        engine.close()
    }

    @Test
    fun `an empty buffer yields the empty transcript`() {
        val engine = FakeSttEngine()
        val result = engine.transcribe(FloatArray(0), DecodeOptions())
        assertTrue(result.text.isEmpty())
        assertTrue(result.segments.isEmpty())
        engine.close()
    }

    @Test
    fun `speech is returned as the engine decoded it`() {
        val engine = FakeSttEngine(scripted = "send the report")
        val speech = FloatArray(4_000) { 0.2f }
        assertEquals("send the report", engine.transcribe(speech, DecodeOptions()).text)
        engine.close()
    }

    @Test
    fun `close is idempotent`() {
        val engine = FakeSttEngine()
        engine.close()
        engine.close()
        assertEquals(2, engine.closeCount)
        assertTrue(engine.isClosed)
    }

    @Test
    fun `decoding after close fails instead of touching freed state`() {
        val engine = FakeSttEngine()
        engine.close()
        assertFailsWith<IllegalStateException> {
            engine.transcribe(FloatArray(10) { 0.1f }, DecodeOptions())
        }
        assertFailsWith<IllegalStateException> {
            engine.decodeWindow(FloatArray(10) { 0.1f }, DecodeOptions())
        }
    }

    @Test
    fun `DecodeOptions defaults to 16 kHz with no prompt or task`() {
        val opts = DecodeOptions()
        assertEquals(16_000, opts.sampleRate)
        assertEquals(null, opts.initialPrompt)
        assertEquals(null, opts.task)
    }

    @Test
    fun `DecodeOptions rejects a non-positive sample rate`() {
        assertFailsWith<IllegalArgumentException> { DecodeOptions(sampleRate = 0) }
    }

    @Test
    fun `a segment must not end before it starts`() {
        assertFailsWith<IllegalArgumentException> {
            Transcript.Segment(startSec = 2.0, endSec = 1.0, text = "x")
        }
    }

    @Test
    fun `a transcript carries per-segment timings when the engine reports them`() {
        val segment = Transcript.Segment(startSec = 0.0, endSec = 1.5, text = "hi", confidence = 0.9f)
        val transcript = Transcript(text = "hi", segments = listOf(segment))
        assertEquals(listOf(segment), transcript.segments)
    }
}
