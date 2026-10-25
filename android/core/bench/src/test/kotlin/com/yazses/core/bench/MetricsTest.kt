package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

// All fixtures are SYNTHETIC: hand-made strings and numbers, not measurements of any engine.
class MetricsTest {

    @Test
    fun `identical text has zero word errors`() {
        val r = Wer.wer("the cat sat down", "the cat sat down")
        assertEquals(0, r.errors)
        assertEquals(0.0, r.rate)
    }

    @Test
    fun `one substitution in four words is 0 point 25`() {
        val r = Wer.wer("the cat sat down", "the cat sad down")
        assertEquals(1, r.errors)
        assertEquals(4, r.refLength)
        assertEquals(0.25, r.rate)
    }

    @Test
    fun `a deletion and an insertion each count once`() {
        assertEquals(1, Wer.wer("a b c", "a c").errors)
        assertEquals(2, Wer.wer("a b", "a x b y").errors)
    }

    @Test
    fun `an empty hypothesis costs the whole reference`() {
        assertEquals(3, Wer.wer("a b c", "").errors)
    }

    @Test
    fun `case and punctuation are not counted`() {
        assertEquals(0, Wer.wer("Hello, World!", "hello world").errors)
    }

    @Test
    fun `an empty reference has no rate, not a rate of zero`() {
        val r = Wer.wer("", "some words")
        assertEquals(2, r.errors)
        assertEquals(0, r.refLength)
        assertNull(r.rate)
    }

    @Test
    fun `chinese is scored per character`() {
        // 6 characters in the reference, one character substituted: 1/6, not a whole-string miss.
        val r = Wer.wer("今天天气很好", "今天天器很好")
        assertEquals(1, r.errors)
        assertEquals(6, r.refLength)
    }

    @Test
    fun `cjk and latin in one utterance split cjk per character and keep latin words whole`() {
        // SYNTHETIC mixed utterance: 我, 用, YazSes (one word), 听, 写 -> 5 tokens.
        assertEquals(listOf("我", "用", "yazses", "听", "写"), Wer.wordTokens(Wer.normalise("我用 YazSes 听写")))
    }

    @Test
    fun `korean is space-delimited, so its wer is word-level`() {
        val r = Wer.wer("안녕 하세요", "안녕 하세여")
        assertEquals(1, r.errors)
        assertEquals(2, r.refLength)
    }

    @Test
    fun `cer counts code points and ignores whitespace and punctuation`() {
        // SYNTHETIC: "Hello, 世界!" -> H e l l o 世 界 (7); one substitution.
        val r = Wer.cer("Hello, 世界!", "Hello 世届")
        assertEquals(1, r.errors)
        assertEquals(7, r.refLength)
    }

    @Test
    fun `corpus wer skips pairs with an empty reference like the desktop`() {
        val r = Wer.corpusWer(listOf("a b" to "a b", "" to "x y", "c d" to "c"))
        assertEquals(1, r.errors)
        assertEquals(4, r.refLength)
        assertEquals(0.25, r.rate)
    }

    @Test
    fun `an apostrophe is deleted, so a contraction matches its unpunctuated form`() {
        // SYNTHETIC: "don't" is one token in the reference, so the two spellings cost nothing.
        val r = Wer.wer("I don't know", "I dont know")
        assertEquals(0, r.errors)
        assertEquals(3, r.refLength)
    }

    @Test
    fun `a typographic apostrophe is deleted too`() {
        assertEquals(listOf("dont"), Wer.wordTokens(Wer.normalise("don\u2019t")))
    }

    @Test
    fun `a decimal point between digits keeps the number as one token`() {
        assertEquals(listOf("3.5"), Wer.wordTokens(Wer.normalise("3.5")))
        assertEquals(listOf("1,000"), Wer.wordTokens(Wer.normalise("1,000")))
        // a decimal must not score as the integer with the point dropped
        assertEquals(1, Wer.wer("it costs 3.5", "it costs 35").errors)
    }

    @Test
    fun `a hyphen between letters keeps the word as one token`() {
        assertEquals(listOf("email"), Wer.wordTokens(Wer.normalise("e-mail")))
    }

    @Test
    fun `initialisms with internal periods stay one token`() {
        assertEquals(listOf("us"), Wer.wordTokens(Wer.normalise("U.S.")))
    }

    @Test
    fun `a comma or hyphen followed by a space still separates words`() {
        assertEquals(listOf("hello", "world"), Wer.wordTokens(Wer.normalise("hello, world")))
        assertEquals(listOf("a", "b"), Wer.wordTokens(Wer.normalise("a - b")))
    }

    @Test
    fun `astral cjk ideographs in extensions C and G each count once`() {
        val ext_c = String(Character.toChars(0x2A700))
        val ext_g = String(Character.toChars(0x30000))
        assertEquals(listOf(ext_c, ext_g), Wer.wordTokens(Wer.normalise(ext_c + ext_g)))
    }

    @Test
    fun `a compatibility supplement ideograph is one token, scored as its canonical form`() {
        // U+2F800 canonically decomposes to U+4E3D under NFC, so it is scored as that character.
        val supplement = String(Character.toChars(0x2F800))
        assertEquals(listOf("\u4E3D"), Wer.wordTokens(Wer.normalise(supplement)))
    }

    @Test
    fun `rtf is wall over audio and not applicable without audio`() {
        assertEquals(0.5, Rtf.of(wallS = 2.0, audioS = 4.0))
        assertNull(Rtf.of(wallS = 1.0, audioS = 0.0))
        assertNull(Rtf.of(wallS = 0.0, audioS = 0.0))
    }
}
