package com.yazses.core.postprocess

/**
 * Script classes for unspaced CJK text (contract 7.1.0, #501).
 *
 * Port of the seam rule in `src/yazses/postprocess/cjk.py`. Everything here takes a
 * **code point**, never a `Char`: an extension-B ideograph such as U+20BB7 is two
 * UTF-16 chars, and a `Char`-based test calls it "not Chinese". The contract pins
 * that with an astral case.
 */

private val HAN = arrayOf(
    0x2E80..0x2FDF, // CJK radicals supplement, Kangxi radicals
    0x31C0..0x31EF, // CJK strokes
    0x3400..0x4DBF, // extension A
    0x4E00..0x9FFF, // unified ideographs
    0xF900..0xFAFF, // compatibility ideographs
    0x20000..0x2FA1F, // extensions B..F, I + compatibility supplement
    0x30000..0x323AF, // extensions G, H
)

private val UNSPACED_OTHER = arrayOf(
    0x3005..0x3007, // 々 〆 〇
    0x3021..0x3029, // Hangzhou numerals
    0x3031..0x3035, // kana repeat marks
    0x3038..0x303C,
    0x3040..0x309F, // hiragana
    0x30A0..0x30FF, // katakana
    0x3100..0x312F, // bopomofo
    0x31A0..0x31BF, // bopomofo extended
    0x31F0..0x31FF, // katakana phonetic extensions
    0xFF10..0xFF19, // full-width digits
    0xFF21..0xFF3A, // full-width Latin capitals
    0xFF41..0xFF5A, // full-width Latin small letters
    0xFF66..0xFF9F, // half-width katakana
)

private val CJK_PUNCT = arrayOf(
    0x3000..0x3004,
    0x3008..0x3020,
    0x3030..0x3030,
    0x303D..0x303F,
    0xFE10..0xFE1F,
    0xFE30..0xFE4F,
    0xFE50..0xFE6F,
    0xFF01..0xFF0F,
    0xFF1A..0xFF20,
    0xFF3B..0xFF40,
    0xFF5B..0xFF65,
)

private val GENERAL_PUNCT = 0x2010..0x205E

private const val ASCII_CLOSERS = ".,!?;:)]}%"

private fun Array<IntRange>.holds(cp: Int): Boolean = any { cp in it }

/** A letter of a script written without spaces between words (Han, kana, Bopomofo, …). */
internal fun isUnspacedLetter(cp: Int): Boolean = HAN.holds(cp) || UNSPACED_OTHER.holds(cp)

/** CJK / full-width punctuation, which carries its own spacing. */
internal fun isCjkPunct(cp: Int): Boolean = CJK_PUNCT.holds(cp)

/**
 * Whether one space belongs at a bare seam between code points [left] and [right].
 *
 * `true` whenever neither side is CJK — the answer a plain `" "` join always gave.
 * Withheld when either side is CJK punctuation, when both are unspaced letters, or
 * when an unspaced letter meets general punctuation (curly quotes, `…`) or an ASCII
 * closer follows one. A Han–Latin seam keeps its space.
 */
internal fun needsSpace(left: Int, right: Int): Boolean {
    if (left < 0 || right < 0) return false
    if (isCjkPunct(left) || isCjkPunct(right)) return false
    val leftLetter = isUnspacedLetter(left)
    val rightLetter = isUnspacedLetter(right)
    if (leftLetter && (
            rightLetter || right in GENERAL_PUNCT ||
                (right <= 0xFFFF && right.toChar() in ASCII_CLOSERS)
            )
    ) {
        return false
    }
    if (rightLetter && left in GENERAL_PUNCT) return false
    return true
}
