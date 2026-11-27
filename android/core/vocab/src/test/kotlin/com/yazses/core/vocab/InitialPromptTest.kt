package com.yazses.core.vocab

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
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

    @Test
    fun `English and unpinned languages keep the built-in phrase`() {
        for (language in listOf(null, "", "  ", "auto", "translate", "en", "EN", "en-GB", "en_US")) {
            assertEquals(BUILTIN_PROMPT, mergeInitialPrompt(language = language), "language=$language")
        }
    }

    @Test
    fun `another language gets no English sentence`() {
        for (language in listOf("fa", "fa-IR", "zh", "de_DE")) {
            assertNull(mergeInitialPrompt(language = language), "language=$language")
            assertEquals(
                "Kubernetes",
                mergeInitialPrompt("Kubernetes", language = language),
                "language=$language",
            )
        }
    }
}
