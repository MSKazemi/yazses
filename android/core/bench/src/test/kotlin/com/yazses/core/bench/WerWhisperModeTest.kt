package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertEquals

// Synthetic fixtures. These check the TextNormalizer switch, not any engine's accuracy.
class WerWhisperModeTest {

    @Test
    fun `under WHISPER_ENGLISH the contraction and its expansion have no word errors`() {
        val r = Wer.wer("I don't know", "I do not know", TextNormalizer.WHISPER_ENGLISH)
        assertEquals(0, r.errors)
        assertEquals(4, r.refLength) // "i do not know": four tokens once expanded
    }

    @Test
    fun `under SIMPLE the same pair keeps its old result`() {
        val r = Wer.wer("I don't know", "I do not know")
        assertEquals(2, r.errors)
        assertEquals(3, r.refLength)
    }

    @Test
    fun `the default is SIMPLE, so an unparameterised call is unchanged`() {
        assertEquals(Wer.wer("I don't know", "I do not know"), Wer.wer("I don't know", "I do not know", TextNormalizer.SIMPLE))
        assertEquals(Wer.normalise("Hello, World!"), Wer.normalise("Hello, World!", TextNormalizer.SIMPLE))
    }

    @Test
    fun `under WHISPER_ENGLISH spelled numbers match digits`() {
        assertEquals(0, Wer.wer("twenty one dollars", "\$21", TextNormalizer.WHISPER_ENGLISH).errors)
    }

    @Test
    fun `under WHISPER_ENGLISH a British spelling matches its American form`() {
        assertEquals(0, Wer.wer("the colour centre", "the color center", TextNormalizer.WHISPER_ENGLISH).errors)
    }

    @Test
    fun `under WHISPER_ENGLISH a filler and a bracket are not counted`() {
        assertEquals(0, Wer.wer("um hello [inaudible] world", "hello world", TextNormalizer.WHISPER_ENGLISH).errors)
    }

    @Test
    fun `under WHISPER_ENGLISH CJK is still counted per character`() {
        val r = Wer.wer("我用 YazSes", "我用 yazses", TextNormalizer.WHISPER_ENGLISH)
        assertEquals(0, r.errors)
        assertEquals(3, r.refLength)
        assertEquals(listOf("我", "用", "yazses"), Wer.wordTokens(Wer.normalise("我用 YazSes", TextNormalizer.WHISPER_ENGLISH)))
    }

    @Test
    fun `corpusWer skips a pair whose reference normalises to nothing, under either normalizer`() {
        val pairs = listOf("[inaudible]" to "x y", "I do not know" to "I do not know")
        assertEquals(0, Wer.corpusWer(pairs, TextNormalizer.WHISPER_ENGLISH).errors)
        assertEquals(4, Wer.corpusWer(pairs, TextNormalizer.WHISPER_ENGLISH).refLength)
        // SIMPLE does not strip brackets, so "[inaudible]" is not empty and its 1 token is counted.
        assertEquals(5, Wer.corpusWer(pairs).refLength)
    }
}
