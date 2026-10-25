package com.yazses.core.bench

import kotlin.test.Test
import kotlin.test.assertEquals

// The cleanup rules and the Unicode behaviour that the Python regular expressions give.
// Expected values are the oracle's own outputs (whisper-normalizer 0.1.15).
class EnglishTextNormalizerRulesTest {

    private fun assertNormalises(expected: String, input: String) =
        assertEquals(expected, EnglishTextNormalizer.normalize(input), "input=\"$input\"")

    @Test
    fun `brackets and parentheses are removed with their content`() {
        assertNormalises("hello world", "[inaudible] hello (laughs) world")
    }

    @Test
    fun `hesitation fillers are removed as whole words only`() {
        assertNormalises("yes no", "um yes, uh no")
        assertNormalises("", "hmm mm mhm mmm")
    }

    @Test
    fun `contractions expand`() {
        assertNormalises("i do not know", "I don't know")
        assertNormalises("we can not go", "we can't go")
        assertNormalises("will not", "won't")
        assertNormalises("it has been a while", "It's been a while")
        assertNormalises("she had gone", "she'd gone")
        assertNormalises("i am here you are late", "I'm here, you're late")
        assertNormalises("i would have", "I'd have")
        assertNormalises("madam", "Ma'am")
        assertNormalises("you all", "y'all")
        assertNormalises("want to go", "wanna go?")
        assertNormalises("that is all folks", "that's all folks!")
    }

    @Test
    fun `titles expand to words`() {
        assertNormalises("mister smith and doctor who", "Mr. Smith and Dr. Who")
    }

    @Test
    fun `a period between letters is removed and a period before a digit is kept`() {
        assertNormalises("end next", "end.Next")
        assertNormalises("e g apples", "e.g. apples")
        assertNormalises("u s economy", "U.S. economy")
        assertNormalises("it costs \$3.5", "it costs 3.5 dollars")
        assertNormalises("\$5.50 total", "\$5.50 total")
    }

    @Test
    fun `commas between digits are removed and other commas are dropped`() {
        assertNormalises("1000 people", "1,000 people")
    }

    @Test
    fun `a hyphen is a symbol and becomes a space`() {
        assertNormalises("co operate", "co-operate")
    }

    @Test
    fun `numbers inside a sentence are converted by the number rules`() {
        assertNormalises("21", "twenty-one")
        assertNormalises("\$105", "one hundred and five dollars")
        assertNormalises("50% off", "50% off")
    }

    @Test
    fun `whitespace is collapsed and the ends are trimmed`() {
        assertNormalises("hello world", "  Hello   World  ")
        assertNormalises("", "")
    }

    @Test
    fun `British spellings are changed by the spelling table`() {
        assertNormalises("color center", "Colour  centre")
    }

    @Test
    fun `symbols and diacritics are removed or spaced`() {
        assertEquals("cafe ss oe o L", removeSymbolsAndDiacritics("café ß œ ø Ł"))
        assertEquals("a b c", removeSymbolsAndDiacritics("a-b_c"))
        assertEquals("hi   there", removeSymbolsAndDiacritics("hi 😀 there"))
        assertEquals("price \$5 € 3 ¢ 9 % x.y", removeSymbolsAndDiacritics("price \$5 € 3 ¢ 9 % x.y", ".%\$¢€£"))
        assertEquals("ete", removeSymbolsAndDiacritics("été"))
        assertEquals("1 2 half 2", removeSymbolsAndDiacritics("½ half ²"))
    }

    @Test
    fun `a Python word character is a letter or number, not a combining mark`() {
        assertNormalises("naive cafe", "naïve café")
        assertNormalises("naive is", "naïve's")
        assertNormalises("ss and oeuvre", "ß and œuvre")
    }

    @Test
    fun `lower-casing is Unicode aware`() {
        assertNormalises("gg istanbul", "ĞĞ İstanbul")
    }

    @Test
    fun `a capital sigma is final only where the Final_Sigma rule says so`() {
        // Final sigma: a hyphen does not end the word, so the sigma before it is final (oracle: "οδος 3").
        assertNormalises("οδος 3", "ΟΔΟΣ-three")
        assertNormalises("οδος", "ΟΔΟΣ")
        // U+2019 is case-ignorable and a letter follows it, so the sigma is not final (oracle: "οδοσ x").
        assertNormalises("οδοσ x", "ΟΔΟΣ’x")
        assertNormalises("ας βς", "ΑΣ ΒΣ.")
    }

    @Test
    fun `an emoji is dropped like any other symbol`() {
        assertNormalises("it is a day", "it's a 😀 day")
    }

    @Test
    fun `Python whitespace includes the non-breaking space and the file separators`() {
        assertNormalises("a b c", "a b\u001Cc")
        assertNormalises("x 23", "x  two three")
        assertNormalises("2.5", "two and a half")
        assertNormalises("one 0", "1 000")
    }

    @Test
    fun `a hyphen U+2011 between words is a symbol here`() {
        assertNormalises("21", "twenty‑one")
    }

    @Test
    fun `a digit token of 4300 characters converts, as in CPython`() {
        // CPython raises AssertionError at 4301 digits (int() limit); the port does not refuse, so it
        // returns the text. 4300 digits is the oracle's own output.
        assertEquals("1".repeat(4300), EnglishTextNormalizer.normalize("1".repeat(4300)))
    }

    @Test
    fun `a digit token of 4301 characters is returned, where CPython raises`() {
        assertEquals("1".repeat(4301), EnglishTextNormalizer.normalize("1".repeat(4301)))
    }

    @Test
    fun `python split and strip use the Python whitespace set`() {
        assertEquals(listOf("a", "b", "c"), pySplit(" a b\u001Cc\t"))
        assertEquals("b", pyStrip("\u001C b  "))
        assertEquals(listOf("", " x ", ""), pyReSplit(Regex("y"), "y x y"))
    }
}
