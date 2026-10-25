package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertEquals

// Expected values are the oracle's own outputs (whisper-normalizer 0.1.15), not hand-derived.
// Where the oracle does something odd, the test keeps it and says so: the port must match, not improve.
class EnglishNumberNormalizerTest {

    private val n = EnglishNumberNormalizer()

    private fun assertNormalises(expected: String, input: String) =
        assertEquals(expected, n.normalize(input), "input=\"$input\"")

    @Test
    fun `compound cardinals become digits`() {
        assertNormalises("21", "twenty one")
        assertNormalises("99", "ninety nine")
        assertNormalises("11", "eleven")
        assertNormalises("123", "one hundred twenty three")
        assertNormalises("12345", "twelve thousand three hundred forty five")
    }

    @Test
    fun `hundreds thousands and millions combine`() {
        assertNormalises("105", "one hundred and five")
        assertNormalises("2005", "two thousand and five")
        assertNormalises("3000000", "three million")
        assertNormalises("3000", "3 thousand")
        assertNormalises("2500000", "two and a half million")
    }

    @Test
    fun `digit-by-digit speech becomes a nominal number`() {
        assertNormalises("101", "one oh one")
        assertNormalises("007", "double oh seven")
        assertNormalises("555", "triple five")
        assertNormalises("5551212", "five five five one two one two")
    }

    @Test
    fun `years spoken as pairs`() {
        assertNormalises("1984", "nineteen eighty four")
    }

    @Test
    fun `ordinals keep their suffix`() {
        assertNormalises("21st century", "twenty first century")
        assertNormalises("31st", "thirty first")
        assertNormalises("100th", "one hundredth")
    }

    @Test
    fun `currency and percent are written as symbols`() {
        assertNormalises("\$20000000", "\$20 million")
        assertNormalises("\$20.07", "twenty dollars and seven cents")
        assertNormalises("\$5.03", "\$5 and 3 cents")
        assertNormalises("¢50", "fifty cents")
        assertNormalises("¢5", "\$0.05")
        assertNormalises("£75", "seventy five pounds")
        assertNormalises("50%", "fifty percent")
        assertNormalises("20%", "twenty per cent")
    }

    @Test
    fun `signs and decimals`() {
        assertNormalises("-5 degrees", "minus five degrees")
        assertNormalises("-12", "negative twelve")
        assertNormalises("0.25", "zero point two five")
        assertNormalises("2.5", "two and a half")
    }

    @Test
    fun `a leading one becomes the word one`() {
        assertNormalises("one apple", "1 apple")
    }

    @Test
    fun `a bare multiplier is a number`() {
        assertNormalises("1000", "thousand")
        assertNormalises("100", "hundred")
        assertNormalises("a 1000", "a thousand")
    }

    @Test
    fun `words that are not numbers pass through`() {
        assertNormalises("forty-five", "forty-five")
        assertNormalises("2nd of may", "2nd of may")
        assertNormalises("ones", "ones")
        assertNormalises("minus", "minus")
        assertNormalises("1990s", "1990s")
    }

    @Test
    fun `quirks kept from the oracle`() {
        // "sixes" is the plural of six, written with an s; the oracle yields 6s, not six.
        assertNormalises("6s", "sixes")
        assertNormalises("6th", "sixth")
        assertNormalises("one.5", "one point five")
        assertNormalises("10 thousandths", "ten thousandths")
    }

    @Test
    fun `the empty string and the empty word list give nothing`() {
        assertNormalises("", "")
        assertEquals(emptyList(), n.processWords(emptyList()))
    }

    @Test
    fun `preprocess turns and-a-half into point five after a multiplier or decimal digit`() {
        // The oracle keeps the spaces around the split: "two " + "point five" + " million".
        assertEquals("two  point five  million", n.preprocess("two and a half million"))
        assertEquals("two  point five", n.preprocess("two and a half"))
    }

    @Test
    fun `preprocess splits letters from digits and rejoins a suffix`() {
        assertEquals("3rd", n.preprocess("3rd")) // the letter/digit space is put back by the suffix rule
        assertEquals("1st", n.preprocess("1 st"))
        assertEquals("5 apples", n.preprocess("5apples"))
    }
}
