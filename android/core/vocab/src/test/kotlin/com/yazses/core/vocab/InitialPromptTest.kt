package com.yazses.core.vocab

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class InitialPromptTest {
    @Test
    fun `the app name is always primed, even with no vocabulary`() {
        assertEquals(BUILTIN_PROMPT, mergeInitialPrompt())
    }

    @Test
    fun `the built-in phrase comes last, where the decoder cannot cut it`() {
        val merged = mergeInitialPrompt("Kubernetes, Prometheus")!!
        assertTrue(merged.endsWith(BUILTIN_PROMPT), merged)
        assertFalse(merged.startsWith(BUILTIN_PROMPT), merged)
    }

    @Test
    fun `blank parts are dropped rather than producing double spaces`() {
        assertEquals(BUILTIN_PROMPT, mergeInitialPrompt(null, "", "   "))
    }
}
