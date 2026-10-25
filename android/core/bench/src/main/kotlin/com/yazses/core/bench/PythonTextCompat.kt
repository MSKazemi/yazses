// Python `re` / `str` semantics for the Whisper English normaliser port (see EnglishTextNormalizer.kt
// for the licence and attribution). These helpers exist because the oracle is Python 3 and its
// regular expressions and string methods are Unicode-aware in ways java.util.regex is not by default.
package com.yazses.core.bench

import java.text.Normalizer
import java.util.Locale

/** Python `str.isspace()`: the set `re` uses for `\s` and `str.split()` uses for whitespace. */
internal fun isPySpace(c: Char): Boolean = when (c.code) {
    in 0x09..0x0D, in 0x1C..0x20, 0x85, 0xA0, 0x1680, in 0x2000..0x200A,
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000 -> true
    else -> false
}

/** `\s` as Python matches it in a str pattern (Unicode whitespace, including U+001C..U+001F). */
internal const val PY_WS = "[\\t\\n\\u000B\\f\\r \\u001C-\\u001F\\u0085\\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000]"

/** `\w` as Python matches it: `str.isalnum()` or underscore. Letters (L*) plus numbers (N*). */
internal const val PY_WORD = "[\\p{L}\\p{Nd}\\p{Nl}\\p{No}_]"

/**
 * The body of a lookbehind that tests the character before a position as a word character.
 *
 * Java computes a lookbehind's length from the class, which is one char, so it only ever steps back
 * one UTF-16 unit. After a supplementary character that unit is a lone low surrogate, which is not a
 * letter, so an astral letter (a math alphanumeric, CJK Ext B) would count as a non-word character. The
 * dead branch `(?!)[\s\S][\s\S]` never matches, but it is two units long, so Java also tries the step
 * back of two units, where the class reads the whole code point.
 */
internal const val PY_WORD_BEHIND = "$PY_WORD|(?!)[\\s\\S][\\s\\S]"

/** `\b` as Python matches it. Java's own `\b` would use a different word definition. */
internal const val PY_B = "(?:(?<=$PY_WORD_BEHIND)(?!$PY_WORD)|(?<!$PY_WORD_BEHIND)(?=$PY_WORD))"

/** Python `$` without MULTILINE: end of string, or just before a newline that ends the string. */
internal const val PY_DOLLAR = "(?=\\n?\\z)"

/** Python `str.split()` with no argument: split on runs of whitespace, no empty pieces. */
internal fun pySplit(s: String): List<String> {
    val out = ArrayList<String>()
    var i = 0
    while (i < s.length) {
        while (i < s.length && isPySpace(s[i])) i++
        if (i >= s.length) break
        val start = i
        while (i < s.length && !isPySpace(s[i])) i++
        out += s.substring(start, i)
    }
    return out
}

/** Python `str.strip()` with no argument. */
internal fun pyStrip(s: String): String {
    var a = 0
    var b = s.length
    while (a < b && isPySpace(s[a])) a++
    while (b > a && isPySpace(s[b - 1])) b--
    return s.substring(a, b)
}

/**
 * Python `re.split(pattern, s)` for a pattern that cannot match the empty string and has no
 * capture groups. Unlike java.util.regex, empty leading and trailing pieces are kept.
 */
internal fun pyReSplit(pattern: Regex, s: String): List<String> {
    val out = ArrayList<String>()
    var last = 0
    for (m in pattern.findAll(s)) {
        out += s.substring(last, m.range.first)
        last = m.range.last + 1
    }
    out += s.substring(last)
    return out
}

/** `unicodedata.normalize('NFKD', s)` followed by the drop/replace rules of basic.py. */
internal val ADDITIONAL_DIACRITICS: Map<String, String> = mapOf(
    "œ" to "oe", "Œ" to "OE", "ø" to "o", "Ø" to "O", "æ" to "ae", "Æ" to "AE",
    "ß" to "ss", "ẞ" to "SS", "đ" to "d", "Đ" to "D", "ð" to "d", "Ð" to "D",
    "þ" to "th", "Þ" to "th", "ł" to "l", "Ł" to "L",
)

/**
 * basic.py `remove_symbols_and_diacritics`. Per code point of the NFKD string: a character in
 * [keep] is kept; a manual mapping applies; category Mn is dropped; categories M*, S* and P* become
 * one space; anything else is kept. Iterates code points so astral characters (emoji) are one unit.
 */
internal fun removeSymbolsAndDiacritics(s: String, keep: String = ""): String {
    val nfkd = Normalizer.normalize(s, Normalizer.Form.NFKD)
    val sb = StringBuilder(nfkd.length)
    var i = 0
    while (i < nfkd.length) {
        val cp = nfkd.codePointAt(i)
        i += Character.charCount(cp)
        val c = String(Character.toChars(cp))
        val type = Character.getType(cp)
        when {
            keep.contains(c) -> sb.append(c)
            ADDITIONAL_DIACRITICS.containsKey(c) -> sb.append(ADDITIONAL_DIACRITICS.getValue(c))
            type == Character.NON_SPACING_MARK.toInt() -> Unit
            type in MSP_TYPES -> sb.append(' ')
            else -> sb.append(c)
        }
    }
    return sb.toString()
}

/** Character.getType values whose Unicode category starts with M, S or P (Mn is handled before this). */
private val MSP_TYPES: Set<Int> = setOf(
    Character.NON_SPACING_MARK.toInt(), Character.ENCLOSING_MARK.toInt(), Character.COMBINING_SPACING_MARK.toInt(),
    Character.MATH_SYMBOL.toInt(), Character.CURRENCY_SYMBOL.toInt(), Character.MODIFIER_SYMBOL.toInt(),
    Character.OTHER_SYMBOL.toInt(),
    Character.CONNECTOR_PUNCTUATION.toInt(), Character.DASH_PUNCTUATION.toInt(), Character.START_PUNCTUATION.toInt(),
    Character.END_PUNCTUATION.toInt(), Character.INITIAL_QUOTE_PUNCTUATION.toInt(),
    Character.FINAL_QUOTE_PUNCTUATION.toInt(), Character.OTHER_PUNCTUATION.toInt(),
)

/**
 * Python `str.lower()`. Java's `lowercase(Locale.ROOT)` agrees with it except for the capital sigma:
 * Java's final-sigma test does not match CPython's (for "ΟΔΟΣ-" Java keeps σ where Python writes ς).
 * So each U+03A3 is decided here with the Unicode Final_Sigma rule, as CPython does, and the rest is
 * left to Java.
 */
internal fun pyLower(s: String): String {
    if (s.indexOf('\u03A3') < 0) return s.lowercase(Locale.ROOT)
    val cps = s.codePoints().toArray()
    val sb = StringBuilder(s.length)
    for (i in cps.indices) {
        if (cps[i] == 0x3A3) sb.append(if (isFinalSigma(cps, i)) '\u03C2' else '\u03C3')
        else sb.appendCodePoint(cps[i])
    }
    return sb.toString().lowercase(Locale.ROOT)
}

/** Final_Sigma: preceded by a cased letter (skipping case-ignorable), not followed by one (skipping case-ignorable). */
private fun isFinalSigma(cps: IntArray, i: Int): Boolean {
    var j = i - 1
    while (j >= 0 && isCaseIgnorable(cps[j])) j--
    if (j < 0 || !isCased(cps[j])) return false
    var k = i + 1
    while (k < cps.size && isCaseIgnorable(cps[k])) k++
    return !(k < cps.size && isCased(cps[k]))
}

/** Unicode Cased: Lowercase, Uppercase or titlecase (Lt). */
private fun isCased(cp: Int): Boolean =
    Character.isLowerCase(cp) || Character.isUpperCase(cp) || Character.isTitleCase(cp)

/**
 * Unicode Case_Ignorable: categories Mn, Me, Cf, Lm, Sk, plus the Word_Break MidLetter, MidNumLet and
 * Single_Quote code points. Those 17 were read from the oracle's Python (Unicode 16) by probing
 * every code point, and are the only ones outside the categories.
 */
private fun isCaseIgnorable(cp: Int): Boolean =
    cp in CASE_IGNORABLE_WORD_BREAK || Character.getType(cp) in CASE_IGNORABLE_TYPES

private val CASE_IGNORABLE_WORD_BREAK: Set<Int> = setOf(
    0x27, 0x2E, 0x3A, 0xB7, 0x387, 0x55F, 0x5F4, 0x2018, 0x2019, 0x2024, 0x2027,
    0xFE13, 0xFE52, 0xFE55, 0xFF07, 0xFF0E, 0xFF1A,
)

private val CASE_IGNORABLE_TYPES: Set<Int> = setOf(
    Character.NON_SPACING_MARK.toInt(), Character.ENCLOSING_MARK.toInt(), Character.FORMAT.toInt(),
    Character.MODIFIER_LETTER.toInt(), Character.MODIFIER_SYMBOL.toInt(),
)
