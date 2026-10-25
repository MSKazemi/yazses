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
    fun `under WHISPER_ENGLISH a CJK run without spaces is one token, as jiwer counts it`() {
        // jiwer splits on the ASCII space only (transforms.py:150-179), so "我用" is one word.
        val r = Wer.wer("我用 YazSes", "我用 yazses", TextNormalizer.WHISPER_ENGLISH)
        assertEquals(0, r.errors)
        assertEquals(2, r.refLength)
        assertEquals(listOf("我用", "yazses"), Wer.whisperWordTokens(Wer.normalise("我用 YazSes", TextNormalizer.WHISPER_ENGLISH)))
    }

    @Test
    fun `under WHISPER_ENGLISH 你好世界 ok against 你好世 ok is one error in two words, as jiwer scores it`() {
        // jiwer.process_words("你好世界 ok", "你好世 ok"): 1 substitution, 2 reference words.
        val r = Wer.wer("你好世界 ok", "你好世 ok", TextNormalizer.WHISPER_ENGLISH)
        assertEquals(1, r.errors)
        assertEquals(2, r.refLength)
    }

    @Test
    fun `under WHISPER_ENGLISH a mixed-script pair is one error in three words, as jiwer scores it`() {
        // jiwer.process_words("我用 yazses 听写", "我用 yazses 听"): 1 substitution, 3 reference words.
        val r = Wer.wer("我用 YazSes 听写", "我用 yazses 听", TextNormalizer.WHISPER_ENGLISH)
        assertEquals(1, r.errors)
        assertEquals(3, r.refLength)
    }

    @Test
    fun `under SIMPLE CJK is still counted per character, the legacy behaviour`() {
        val r = Wer.wer("你好世界 ok", "你好世 ok")
        assertEquals(1, r.errors)
        assertEquals(5, r.refLength)
    }

    @Test
    fun `a reference of dollar and percent normalises to nothing and is skipped, as the desktop skips it`() {
        // Whisper gives " " for "$%" (jiwer.process_words sees 2 insertions and 0 reference words); bench_wer.py:224 drops it.
        assertEquals(" ", EnglishTextNormalizer.normalize("\$%"))
        val pairs = listOf("\$%" to "hello world", "I do not know" to "I do not know")
        val r = Wer.corpusWer(pairs, TextNormalizer.WHISPER_ENGLISH)
        assertEquals(0, r.errors)
        assertEquals(4, r.refLength)
        assertEquals(ErrorRate(0, 0), Wer.corpusWer(listOf("\$%" to "hello world"), TextNormalizer.WHISPER_ENGLISH))
    }

    @Test
    fun `a non-breaking-space-only reference is skipped, because Python strips it`() {
        assertEquals(ErrorRate(0, 0), Wer.corpusWer(listOf("\u00A0" to "hello world"), TextNormalizer.WHISPER_ENGLISH))
        assertEquals(ErrorRate(0, 0), Wer.corpusWer(listOf("\u00A0" to "hello world")))
    }

    @Test
    fun `SIMPLE keeps its count for a dollar-and-percent reference`() {
        // Not a desktop number: SIMPLE does not drop "$%" in its normaliser, so the old count is kept.
        assertEquals(ErrorRate(2, 1), Wer.corpusWer(listOf("\$%" to "hello world")))
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
