package com.yazses.core.postprocess

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Unit tests for the ported units.
 *
 * The *contract* lives in `:core:contract-test`, which runs the same JSON the
 * Python suite uses — that is what says whether the port is correct. These are
 * the cases worth stating in Kotlin as well, because they are the ones a future
 * refactor is most likely to break quietly.
 */
class PostprocessTest {

    @Test
    fun `a blank-audio artefact never reaches the user`() {
        assertEquals("", cleanText("[BLANK_AUDIO]"))
    }

    @Test
    fun `a continuation gets one space, and none before closing punctuation`() {
        assertEquals(" ", continuationPrefix("I mean", hadRecentInjection = true))
        assertEquals("", continuationPrefix(".", hadRecentInjection = true))
        assertEquals("", continuationPrefix("first burst", hadRecentInjection = false))
    }

    @Test
    fun `spoken punctuation hugs the preceding word`() {
        assertEquals("hello, world.", applyVoicePunctuation("hello comma world period"))
    }

    @Test
    fun `a filler is removed and its stranded comma with it`() {
        assertEquals("this is probably fine", filterTranscript("this is probably fine, you know").text)
        assertEquals("the tests are slow", filterTranscript("the tests, you know, are slow").text)
    }

    @Test
    fun `a hedge is not a filler`() {
        val text = "it seems basically correct"
        assertEquals(text, filterTranscript(text).text)
    }

    @Test
    fun `a sentence that merely contains a correction phrase is left alone`() {
        for (text in listOf(
            "delete that file when you are done",
            "never mind the warning",
            "you should never mind the warning",
            "please do not delete that branch",
        )) {
            assertEquals(text, filterTranscript(text).text, "must not be treated as a correction")
        }
    }

    @Test
    fun `a real correction still rolls back`() {
        assertEquals(
            "send it to the inbox",
            filterTranscript("send it to the archive scratch that send it to the inbox").text,
        )
    }

    @Test
    fun `a code identifier containing a filler survives`() {
        assertEquals("call basically_fn in main.py", filterTranscript("call basically_fn in um main.py").text)
    }

    @Test
    fun `disabled is a no-op even on obvious fillers`() {
        val text = "um so like the thing"
        assertEquals(text, filterTranscript(text, DisfluencyConfig(enabled = false)).text)
    }
}
