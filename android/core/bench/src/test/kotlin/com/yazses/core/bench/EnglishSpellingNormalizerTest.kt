package com.yazses.core.bench

import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

// Expected values are the oracle's own outputs (EnglishSpellingNormalizer, whisper-normalizer 0.1.15).
class EnglishSpellingNormalizerTest {

    private val s = EnglishSpellingNormalizer()

    @Test
    fun `british spellings become american`() {
        assertEquals("color center theater favorite", s.normalize("colour centre theatre favourite"))
        assertEquals("realize organization analyze", s.normalize("realise organisation analyse"))
        assertEquals("gray defense traveling aluminum", s.normalize("grey defence travelling aluminium"))
        assertEquals("pediatrics", s.normalize("paediatrics"))
    }

    @Test
    fun `lookup is case sensitive and only whole words are replaced`() {
        assertEquals("Colour", s.normalize("Colour"))
        assertEquals("Cheque", s.normalize("Cheque"))
        assertEquals("not-a-word", s.normalize("not-a-word"))
    }

    @Test
    fun `whitespace is split and rejoined with single spaces`() {
        assertEquals("color center", s.normalize("  colour  centre "))
        assertEquals("", s.normalize("   "))
    }

    @Test
    fun `the table is loaded from the classpath and holds the oracle's 1739 entries`() {
        assertEquals(1739, SpellingTable.mapping.size)
        assertEquals("color", SpellingTable.mapping["colour"])
    }

    @Test
    fun `a well-formed table line parses`() {
        assertEquals(mapOf("colour" to "color", "grey" to "gray"), SpellingTable.parse(listOf("colour\tcolor", "grey\tgray")))
    }

    @Test
    fun `a later duplicate british key wins, as in the oracle's dict`() {
        assertEquals(mapOf("colour" to "colr"), SpellingTable.parse(listOf("colour\tcolor", "colour\tcolr")))
    }

    @Test
    fun `a malformed table line is an error that names the line`() {
        val noTab = assertFailsWith<IOException> { SpellingTable.parse(listOf("colour\tcolor", "grey gray")) }
        assertTrue(noTab.message!!.contains("line 2"), noTab.message)
        assertFailsWith<IOException> { SpellingTable.parse(listOf("a\tb\tc")) }
        assertFailsWith<IOException> { SpellingTable.parse(listOf("\tb")) }
        assertFailsWith<IOException> { SpellingTable.parse(listOf("a\t")) }
    }
}
