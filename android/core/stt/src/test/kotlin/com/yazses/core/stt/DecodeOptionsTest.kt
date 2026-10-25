package com.yazses.core.stt

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class DecodeOptionsTest {

    @Test
    fun `defaults are 16 kHz with no prompt and no task`() {
        val opts = DecodeOptions()
        assertEquals(16_000, opts.sampleRate)
        assertNull(opts.initialPrompt)
        assertNull(opts.task)
    }

    @Test
    fun `DecodeOptions rejects a non-positive sample rate`() {
        assertFailsWith<IllegalArgumentException> { DecodeOptions(sampleRate = 0) }
        assertFailsWith<IllegalArgumentException> { DecodeOptions(sampleRate = -16_000) }
    }

    @Test
    fun `the two tasks the desktop passes are accepted, and null means the default`() {
        assertEquals("transcribe", DecodeOptions.TASK_TRANSCRIBE)
        assertEquals("translate", DecodeOptions.TASK_TRANSLATE)
        DecodeOptions(task = null)
        DecodeOptions(task = DecodeOptions.TASK_TRANSCRIBE)
        DecodeOptions(task = DecodeOptions.TASK_TRANSLATE)
    }

    @Test
    fun `any other task is rejected, including a case or whitespace variant`() {
        for (task in listOf("", "Translate", "TRANSCRIBE", " translate", "translate ", "summarise")) {
            assertFailsWith<IllegalArgumentException>("task \"$task\"") {
                DecodeOptions(task = task)
            }
        }
    }
}
